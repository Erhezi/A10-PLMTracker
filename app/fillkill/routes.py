"""Fill/Kill Management: the Main page and its JSON API (plan v2 §5).

Every route needs a Fill/Kill role (``require_module``); actions need the
capability for that action, and services check the rules.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from flask import Blueprint, Response, current_app, jsonify, render_template, request, url_for
from flask_login import current_user, login_required

from ..models import now_ny_naive
from ..utility.access import DENIED_MESSAGES, FILLKILL, MODULES, can, deny, is_admin, require_module, roles_in
from . import dashboard, health, queries, rollup, services
from ..models.fillkill import INSTRUCTION_MAX, SUB_SOURCES, SUB_STATUSES
from .rules import INSTRUCTION_LABEL, MEDLINE_VENDOR_IDS, NO_VENDOR_ID, NO_VENDOR_LABEL, STATUS_LABELS, RuleError

bp = Blueprint("fillkill", __name__, url_prefix="/fillkill")

STALE_AFTER = timedelta(minutes=90)
DASHBOARD_DAYS = 30  # the Dashboard opens on the last 30 days of data
FEED_HOURS = (8, 23)  # the hourly feed runs 8am-11pm; outside that, old data is expected


# --- helpers ---------------------------------------------------------------------------

def plain(value):
    """JSON-ready: dates as ISO text, decimals as numbers."""
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def ok(payload, status=200):
    return jsonify(plain(payload)), status


@bp.errorhandler(RuleError)
def rule_error(error: RuleError):
    return jsonify({"error": "rule", "message": error.message}), error.status


def _parse_date(value, default):
    try:
        return date.fromisoformat(value) if value else default
    except ValueError:
        raise RuleError(f"Dates must look like 2026-10-13, not '{value}'.") from None


def default_dates(days: int = 1) -> tuple[date, date]:
    """The latest ``days`` order dates in the data, ending on the latest one (P4)."""
    first, last = queries.date_bounds()
    last = last or now_ny_naive().date()
    start = last - timedelta(days=days - 1)
    return (max(start, first) if first else start), last


def sites_from_request() -> tuple[str, ...]:
    """Sold-To codes from ?sites=a,b (or ?sites=a&sites=b); none means every site."""
    raw = ",".join(request.args.getlist("sites"))
    return tuple(sorted({site.strip() for site in raw.split(",") if site.strip()}))


def scope_from_request(days: int = 1) -> queries.Scope:
    """Dates from ?start&end (default: the latest ``days`` of data); sites from ?sites=a,b."""
    start, end = request.args.get("start"), request.args.get("end")
    # The defaults read the data's first and last dates: only when a date isn't given (2026-10-21).
    defaults = default_dates(days) if not (start and end) else (None, None)
    start = _parse_date(start, defaults[0])
    end = _parse_date(end, defaults[1])
    if start > end:
        start, end = end, start
    return queries.Scope(start, end, sites_from_request())


def data_as_of() -> dict:
    load = queries.last_load()
    as_of = load.get("last_success") or load.get("last_line_update")
    if isinstance(as_of, str):
        as_of = datetime.fromisoformat(as_of)
    now = now_ny_naive()
    stale = bool(as_of and now - as_of > STALE_AFTER and FEED_HOURS[0] <= now.hour < FEED_HOURS[1])
    return {
        "as_of": as_of,
        "source": "feed" if load.get("last_success") else "lines",
        "stale": stale,
    }


def body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise RuleError("Send the details as JSON.")
    return data


def capabilities(user) -> dict:
    return {cap: can(user, FILLKILL, cap) for cap in MODULES[FILLKILL].capabilities}


# --- pages ------------------------------------------------------------------------------

@bp.route("/")
@login_required
@require_module(FILLKILL, "view")
def index():
    first, last = queries.date_bounds()
    module = MODULES[FILLKILL]
    held = roles_in(current_user, FILLKILL)
    today = now_ny_naive().date()
    # The live server opens on today; locally, on the latest day with kill lines (FILLKILL_OPEN_ON).
    opening = today if current_app.config.get("FILLKILL_OPEN_ON") == "today" else last
    config = {
        "bounds": {"first": first, "last": last},
        "default": {"start": opening, "end": opening},
        "today": today,  # for "View today"
        "ordersDays": ORDERS_DAYS,
        "sites": queries.sites(),
        "can": capabilities(current_user),
        "me": current_user.email,
        # Lists, not objects: the JSON encoder sorts object keys, and these orders matter.
        "statuses": [[code, STATUS_LABELS[code]] for code in SUB_STATUSES],
        "needs": [[key, rollup.NEEDS_LABELS[key]] for key in rollup.NEEDS],
        # The vendor ID that says Infor has no such vendor (2026-10-19).
        "noVendor": {"id": NO_VENDOR_ID, "label": NO_VENDOR_LABEL},
        # A vendor item that is the Medline item itself from Medline isn't a sub (2026-10-20).
        "medlineVendorIds": list(MEDLINE_VENDOR_IDS),
        # A UOM typed another way, and Infor's for it (CS is CA): the forms change it as it's typed.
        "uomAliases": services.uom_aliases(),
        "instructionMax": INSTRUCTION_MAX,  # an MM Lead's instruction (2026-10-27)
        "instructionLabel": INSTRUCTION_LABEL,
        "api": {
            "main": url_for("fillkill.api_main"),
            "item": url_for("fillkill.api_item"),
            "history": url_for("fillkill.api_history", entity="ENTITY", entity_id=0),
            "orders": url_for("fillkill.api_orders"),
            "contractLines": url_for("fillkill.api_contract_lines"),
            "vendor": url_for("fillkill.api_vendor"),
            "vendors": url_for("fillkill.api_vendors"),
            "addSub": url_for("fillkill.api_add_sub"),
            "subAction": url_for("fillkill.api_sub_action", sub_id=0, action="ACTION"),
            "addVendorItem": url_for("fillkill.api_add_vendor_item", sub_id=0),
            "vendorItemAction": url_for("fillkill.api_vendor_item_action", vendor_item_id=0, action="ACTION"),
            "recordOrder": url_for("fillkill.api_record_order"),
            "orderAction": url_for("fillkill.api_order_action", order_id=0, action="ACTION"),
            "instructions": url_for("fillkill.api_instructions"),
        },
    }
    return render_template(
        "fillkill/index.html",
        roles=[label for code, label in module.roles if code in held],
        config=plain(config),
        instruction_label=INSTRUCTION_LABEL,
        # Admins see what the database is missing for this version (each item names its script).
        health=health.check() if is_admin(current_user) else [],
    )


@bp.cli.command("check-db")
def check_db():
    """flask fillkill check-db: what the database is missing for this version of the app."""
    found = health.check()
    for problem in found:
        print(f"- {problem['what']}" + (f"  -> run db/fillkill/{problem['script']}" if problem["script"] else ""))
    print("The database has everything this version needs." if not found else f"{len(found)} to fix.")


SOURCE_LABELS = {"manual": "Entered by hand", "medline_pbo": "Medline PBO", "llm": "AI finder"}


@bp.route("/subs")
@login_required
@require_module(FILLKILL, "view")
def subs_page():
    """Every sub on file, as a reference (2026-10-16; it was a tab on Main)."""
    config = {
        "statuses": [[code, STATUS_LABELS[code]] for code in SUB_STATUSES],
        "sources": [[code, SOURCE_LABELS.get(code, code)] for code in SUB_SOURCES],
        "limit": queries.LIBRARY_LIMIT,
        # The vendor ID that says Infor has no such vendor (2026-10-19).
        "noVendor": {"id": NO_VENDOR_ID, "label": NO_VENDOR_LABEL},
        "api": {"subs": url_for("fillkill.api_subs"), "export": url_for("fillkill.export_subs")},
        "mainPage": url_for("fillkill.index"),
    }
    return render_template("fillkill/subs.html", config=plain(config))


@bp.route("/dashboard")
@login_required
@require_module(FILLKILL, "view")
def dashboard_page():
    first, last = queries.date_bounds()
    start, end = default_dates(DASHBOARD_DAYS)
    config = {
        "bounds": {"first": first, "last": last},
        "default": {"start": start, "end": end},
        "today": now_ny_naive().date(),  # for "Today" (2026-10-21)
        "sites": queries.sites(),
        "statuses": [[code, STATUS_LABELS[code]] for code in SUB_STATUSES],
        "api": {"dashboard": url_for("fillkill.api_dashboard")},
        "mainPage": url_for("fillkill.index"),
    }
    return render_template("fillkill/dashboard.html", config=plain(config))


# --- reads --------------------------------------------------------------------------------

@bp.get("/api/main")
@login_required
@require_module(FILLKILL, "view")
def api_main():
    scope = scope_from_request()
    added = queries.sync_pbo()
    rows = rollup.build_main_rows(**queries.main_table_inputs(scope))
    return ok({
        "scope": {"start": scope.start, "end": scope.end, "sites": scope.sites},
        "rows": rows,
        "counts": rollup.needs_counts(rows),
        "data": data_as_of(),
        "pbo_added": added,
    })


@bp.get("/api/item")
@login_required
@require_module(FILLKILL, "view")
def api_item():
    medline_item = (request.args.get("item") or "").strip()
    if not medline_item:
        raise RuleError("Which item?")
    return ok(queries.item_panel(medline_item, scope_from_request()))


@bp.get("/api/history/<entity>/<int:entity_id>")
@login_required
@require_module(FILLKILL, "view")
def api_history(entity, entity_id):
    if entity not in ("sub", "vendoritem", "order"):
        raise RuleError("History is kept for subs, vendor items and orders.", 404)
    return ok({"entity": entity, "entity_id": entity_id, "history": queries.history(entity, entity_id)})


def _library_filters() -> dict:
    return {
        "status": request.args.get("status") or None,
        "source": request.args.get("source") or None,
        "q": request.args.get("q") or None,
        "needs_details": request.args.get("needs_details") == "1",
        "deleted": request.args.get("deleted") == "1",
    }


@bp.get("/api/subs")
@login_required
@require_module(FILLKILL, "view")
def api_subs():
    return ok({"subs": queries.subs_library(**_library_filters()), "limit": queries.LIBRARY_LIMIT})


# The Subs page's export: every sub the filters match, not just the first LIBRARY_LIMIT, one row per
# vendor item (a sub without one has a row of its own). The Medline item killed, the sub's Reference
# SKU, then its vendor item (2026-10-20: every column about what's ordered says "Sub"). Orders and
# Last Ordered are the sub's, all its vendor items together.
EXPORT_COLUMNS = (
    ("Sub ID", "sub_id"), ("Medline Item", "medline_item"), ("Medline Item's Infor Item", "medline_infor_item"),
    ("Reference SKU", "reference_sku"), ("Vendor Item ID", "vendor_item_id"),
    ("Sub Vendor Part", "vendor_part"), ("Sub Manufacturer Part", "manufacturer_part"), ("Sub Infor Item", "infor_item"),
    ("Sub Vendor ID", "vendor_id"), ("Sub Vendor Name", "vendor"), ("Sub Description", "description"),
    ("Sub UOM", "uom"), ("Sub QOE", "qoe"), ("Status", "status"),
    ("Picked", "is_picked"), ("Source", "source"), ("Entered By", "entered_by"), ("Entered", "create_dt"),
    ("Approved By", "approved_by"), ("Approved", "approved_at"),
    ("Vendor Item By", "vendor_item_by"), ("Vendor Item Added", "vendor_item_added"), ("Orders", "orders"),
    ("Last Ordered", "last_ordered"), ("Updated", "update_dt"), ("Latest Comment", "latest_comment"),
    ("Deleted By", "deleted_by"), ("Deleted", "deleted_at"), ("Delete Reason", "delete_reason"),
)
VENDOR_ITEM_COLUMNS = ("vendor_item_id", "vendor_part", "manufacturer_part", "infor_item", "vendor_id", "vendor",
                       "description", "uom", "qoe")


def _export_rows(subs):
    """One row per vendor item; a sub without one has a row with those columns empty."""
    for sub in subs:
        for item in sub["vendor_items"] or [{}]:
            yield {**sub, **{key: item.get(key) for key in VENDOR_ITEM_COLUMNS},
                   "vendor_item_by": item.get("entered_by"), "vendor_item_added": item.get("create_dt")}


def _csv_cell(key: str, value):
    if key == "status":
        return STATUS_LABELS.get(value, value)
    if key == "source":
        return SOURCE_LABELS.get(value, value)
    if key == "is_picked":
        return "Yes" if value else "No"
    if key == "latest_comment":
        value = value["comment"] if value else None
    if isinstance(value, datetime):
        value = f"{value:%Y-%m-%d %H:%M}"
    value = plain(value)
    text = "" if value is None else str(value)
    # A cell starting with = + - @ would run as a formula in Excel.
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


@bp.get("/subs/export")
@login_required
@require_module(FILLKILL, "view")
def export_subs():
    rows = queries.subs_library(**_library_filters(), limit=None)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([label for label, _ in EXPORT_COLUMNS])
    for row in _export_rows(rows):
        writer.writerow([_csv_cell(key, row.get(key)) for _, key in EXPORT_COLUMNS])
    name = f"fillkill-subs-{now_ny_naive():%Y%m%d}.csv"
    return Response("\ufeff" + out.getvalue(), mimetype="text/csv",  # the BOM: Excel reads it as UTF-8
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


ORDERS_DAYS = 30  # the orders section's default: the last 30 days, today included


@bp.get("/api/orders")
@login_required
@require_module(FILLKILL, "view")
def api_orders():
    """Orders by their own date, ?start&end (default: the last ORDERS_DAYS days); not the main
    table's dates. For ?sites, the main table's site filter (2026-10-27): a site's Materials Manager
    sees their site's orders."""
    end = _parse_date(request.args.get("end"), now_ny_naive().date())
    start = _parse_date(request.args.get("start"), end - timedelta(days=ORDERS_DAYS - 1))
    if start > end:
        start, end = end, start
    sites = sites_from_request()
    return ok({"orders": queries.orders_log(start, end, sites), "start": start, "end": end, "sites": sites})


@bp.get("/api/instructions")
@login_required
@require_module(FILLKILL, "view")
def api_instructions():
    """Every MM Lead instruction for the main table's row of ?item=<Medline item>, newest first."""
    medline_item = (request.args.get("item") or "").strip()
    if not medline_item:
        raise RuleError("Which item?")
    return ok(queries.instruction_thread(medline_item))


@bp.get("/api/dashboard")
@login_required
@require_module(FILLKILL, "view")
def api_dashboard():
    return ok(dashboard.build(scope_from_request(DASHBOARD_DAYS)))


# The vendor details' lookups: theirs who fill the details in (Materials Managers, Sub Finders).

@bp.get("/api/contract-lines")
@login_required
@require_module(FILLKILL, "details")
def api_contract_lines():
    """Contract lines for the vendor details; ``more`` when there are more than shown."""
    q = (request.args.get("q") or "").strip()
    if len(q.replace(" ", "")) < 3:
        return ok({"lines": [], "message": "Type at least 3 characters."})
    lines = queries.contract_lines(q, limit=queries.CONTRACT_LIMIT + 1)
    return ok({"lines": lines[:queries.CONTRACT_LIMIT], "more": len(lines) > queries.CONTRACT_LIMIT})


@bp.get("/api/vendor")
@login_required
@require_module(FILLKILL, "details")
def api_vendor():
    """Infor's vendor for an ID, so the vendor details can check it and fill in the name."""
    vendor_id = (request.args.get("id") or "").strip()
    found = services.find_vendor(vendor_id) if vendor_id.isdigit() and vendor_id != NO_VENDOR_ID else None
    return ok({"vendor": found})


@bp.get("/api/vendors")
@login_required
@require_module(FILLKILL, "details")
def api_vendors():
    """Infor's vendors matching a typed name (2026-10-19), to find the vendor ID."""
    q = (request.args.get("q") or "").strip()
    if len(q.replace(" ", "").replace("*", "")) < 2:
        return ok({"vendors": [], "more": False})
    found = services.search_vendors(q)
    return ok({"vendors": found, "more": len(found) >= queries.VENDOR_LIMIT})


# --- actions --------------------------------------------------------------------------------

def _sub_payload(sub):
    # picked_instead: the sub that became the pick when this one stopped being approved.
    return {"sub": queries.sub_dict(sub), "picked_instead": getattr(sub, "picked_instead", None)}


@bp.post("/api/subs")
@login_required
@require_module(FILLKILL, "add_sub")
def api_add_sub():
    data = body()
    item = (data.get("medline_item") or "").strip()
    if item and not queries.item_exists(item):
        raise RuleError(f"{item} isn't a Medline item in the fill/kill data.", 404)
    # A Sub Approver's entry (nursing's) is approved on entry; a Sub Finder's waits for review.
    sub = services.add_sub(data, current_user.email, approve=can(current_user, FILLKILL, "review"))
    return ok(_sub_payload(sub), 201)


# Sub actions: which capability each needs, and the service that does it.
SUB_ACTIONS = {
    "edit": "add_sub",
    "status": "review",
    "pick": "pick",  # Sub Approvers and Materials Managers (2026-10-21)
    "unpick": "pick",
    "comments": "review",
    "delete": "add_sub",
}


@bp.post("/api/subs/<int:sub_id>/<action>")
@login_required
@require_module(FILLKILL, "view")
def api_sub_action(sub_id, action):
    capability = SUB_ACTIONS.get(action)
    if capability is None:
        raise RuleError("Unknown action.", 404)
    if not can(current_user, FILLKILL, capability):
        return deny(DENIED_MESSAGES[(FILLKILL, capability)])
    data = body()
    me = current_user.email
    expected = data.get("expected_status")
    if action == "edit":
        sub = services.edit_sub(sub_id, data, me)
    elif action == "status":
        sub = services.set_status(sub_id, data.get("status"), me, expected_status=expected)
    elif action == "pick":
        sub = services.pick(sub_id, me, expected_status=expected)
    elif action == "unpick":
        sub = services.unpick(sub_id, me, expected_status=expected)
    elif action == "delete":
        sub = services.delete_sub(sub_id, data.get("reason"), me, expected_status=expected)
    else:
        sub = services.comment_on_sub(sub_id, data.get("comment"), me)
    return ok(_sub_payload(sub))


# Vendor items: what can be ordered for a sub (2026-10-20), the Materials Manager's and the Sub Finder's.

@bp.post("/api/subs/<int:sub_id>/vendor-items")
@login_required
@require_module(FILLKILL, "details")
def api_add_vendor_item(sub_id):
    item = services.add_vendor_item(sub_id, body(), current_user.email)
    return ok({"vendor_item": queries.vendor_item_dict(item)}, 201)


VENDOR_ITEM_ACTIONS = ("edit", "delete")


@bp.post("/api/vendor-items/<int:vendor_item_id>/<action>")
@login_required
@require_module(FILLKILL, "details")
def api_vendor_item_action(vendor_item_id, action):
    if action not in VENDOR_ITEM_ACTIONS:
        raise RuleError("Unknown action.", 404)
    data = body()
    if action == "edit":
        item = services.edit_vendor_item(vendor_item_id, data, current_user.email)
    else:
        item = services.delete_vendor_item(vendor_item_id, data.get("reason"), current_user.email)
    return ok({"vendor_item": queries.vendor_item_dict(item)})


@bp.post("/api/orders")
@login_required
@require_module(FILLKILL, "order")
def api_record_order():
    data = body()
    try:
        vendor_item_id = int(data.get("vendor_item_id"))
    except (TypeError, ValueError):
        raise RuleError("Which vendor item is this order for?") from None
    order = services.record_order(vendor_item_id, data, current_user.email, expected_status=data.get("expected_status"))
    return ok({"order": queries.order_dict(order)}, 201)


ORDER_ACTIONS = ("edit", "void", "comments")


@bp.post("/api/orders/<int:order_id>/<action>")
@login_required
@require_module(FILLKILL, "order")
def api_order_action(order_id, action):
    if action not in ORDER_ACTIONS:
        raise RuleError("Unknown action.", 404)
    data = body()
    me = current_user.email
    if action == "edit":
        order = services.edit_order(order_id, data, me)
    elif action == "void":
        order = services.void_order(order_id, data.get("reason"), me)
    else:
        order = services.comment_on_order(order_id, data.get("comment"), me)
    return ok({"order": queries.order_dict(order)})


# The MM Lead's instructions to the sites (2026-10-27).

@bp.post("/api/instructions")
@login_required
@require_module(FILLKILL, "instruct")
def api_add_instruction():
    data = body()
    medline_item = (data.get("medline_item") or "").strip()
    if not medline_item:
        raise RuleError("Which item is this instruction for?")
    if not queries.item_exists(medline_item):
        raise RuleError(f"{medline_item} isn't a Medline item in the fill/kill data.", 404)
    row = services.add_instruction(medline_item, data.get("instruction"), current_user.email)
    return ok({"instruction": queries.instruction_dict(row)}, 201)
