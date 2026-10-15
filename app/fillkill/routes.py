"""Fill/Kill Management: the Main page and its JSON API (plan v2 §5).

Every route needs a Fill/Kill role (``require_module``); actions need the
capability for that action, and services check the rules.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from flask import Blueprint, jsonify, render_template, request, url_for
from flask_login import current_user, login_required

from ..models import now_ny_naive
from ..utility.access import DENIED_MESSAGES, FILLKILL, MODULES, can, deny, require_module, roles_in
from . import dashboard, queries, rollup, services
from ..models.fillkill import SUB_STATUSES
from .rules import STATUS_LABELS, RuleError

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


def scope_from_request(days: int = 1) -> queries.Scope:
    """Dates from ?start&end (default: the latest ``days`` of data); sites from ?sites=a,b."""
    default_start, default_end = default_dates(days)
    start = _parse_date(request.args.get("start"), default_start)
    end = _parse_date(request.args.get("end"), default_end)
    if start > end:
        start, end = end, start
    raw = ",".join(request.args.getlist("sites"))
    sites = tuple(sorted({site.strip() for site in raw.split(",") if site.strip()}))
    return queries.Scope(start, end, sites)


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
    config = {
        "bounds": {"first": first, "last": last},
        "default": {"start": last, "end": last},
        "sites": queries.sites(),
        "can": capabilities(current_user),
        "me": current_user.email,
        # Lists, not objects: the JSON encoder sorts object keys, and these orders matter.
        "statuses": [[code, STATUS_LABELS[code]] for code in SUB_STATUSES],
        "needs": [[key, rollup.NEEDS_LABELS[key]] for key in rollup.NEEDS],
        "api": {
            "main": url_for("fillkill.api_main"),
            "item": url_for("fillkill.api_item"),
            "history": url_for("fillkill.api_history", entity="ENTITY", entity_id=0),
            "subs": url_for("fillkill.api_subs"),
            "orders": url_for("fillkill.api_orders"),
            "contractLines": url_for("fillkill.api_contract_lines"),
            "vendor": url_for("fillkill.api_vendor"),
            "addSub": url_for("fillkill.api_add_sub"),
            "subAction": url_for("fillkill.api_sub_action", sub_id=0, action="ACTION"),
            "recordOrder": url_for("fillkill.api_record_order"),
            "orderAction": url_for("fillkill.api_order_action", order_id=0, action="ACTION"),
        },
    }
    return render_template(
        "fillkill/index.html",
        roles=[label for code, label in module.roles if code in held],
        config=plain(config),
    )


@bp.route("/dashboard")
@login_required
@require_module(FILLKILL, "view")
def dashboard_page():
    first, last = queries.date_bounds()
    start, end = default_dates(DASHBOARD_DAYS)
    config = {
        "bounds": {"first": first, "last": last},
        "default": {"start": start, "end": end},
        "sites": queries.sites(),
        "statuses": [[code, STATUS_LABELS[code]] for code in SUB_STATUSES],
        "api": {"dashboard": url_for("fillkill.api_dashboard"), "main": url_for("fillkill.index")},
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
    if entity not in ("sub", "order"):
        raise RuleError("History is kept for subs and orders.", 404)
    return ok({"entity": entity, "entity_id": entity_id, "history": queries.history(entity, entity_id)})


@bp.get("/api/subs")
@login_required
@require_module(FILLKILL, "view")
def api_subs():
    subs = queries.subs_library(
        status=request.args.get("status") or None,
        source=request.args.get("source") or None,
        q=request.args.get("q") or None,
    )
    return ok({"subs": subs, "limit": queries.LIBRARY_LIMIT})


@bp.get("/api/orders")
@login_required
@require_module(FILLKILL, "view")
def api_orders():
    scope = scope_from_request()
    return ok({"orders": queries.orders_log(scope)})


@bp.get("/api/dashboard")
@login_required
@require_module(FILLKILL, "view")
def api_dashboard():
    return ok(dashboard.build(scope_from_request(DASHBOARD_DAYS)))


@bp.get("/api/contract-lines")
@login_required
@require_module(FILLKILL, "add_sub")
def api_contract_lines():
    q = (request.args.get("q") or "").strip()
    if len(q.replace(" ", "")) < 3:
        return ok({"lines": [], "message": "Type at least 3 characters."})
    return ok({"lines": queries.contract_lines(q)})


@bp.get("/api/vendor")
@login_required
@require_module(FILLKILL, "add_sub")
def api_vendor():
    """Infor's vendor for an ID, so the add-sub form can check it and fill in the name."""
    vendor_id = (request.args.get("id") or "").strip()
    found = queries.vendor(vendor_id) if vendor_id.isdigit() else None
    return ok({"vendor": found})


# --- actions --------------------------------------------------------------------------------

def _sub_payload(sub):
    return {"sub": queries.sub_dict(sub)}


@bp.post("/api/subs")
@login_required
@require_module(FILLKILL, "add_sub")
def api_add_sub():
    data = body()
    item = (data.get("medline_item") or "").strip()
    if item and not queries.item_exists(item):
        raise RuleError(f"{item} isn't a Medline item in the fill/kill data.", 404)
    sub = services.add_sub(data, current_user.email)
    return ok(_sub_payload(sub), 201)


# Sub actions: which capability each needs, and the service that does it.
SUB_ACTIONS = {
    "edit": "add_sub",
    "status": "review",
    "pick": "review",
    "unpick": "review",
    "comments": "review",
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
    else:
        sub = services.comment_on_sub(sub_id, data.get("comment"), me)
    return ok(_sub_payload(sub))


@bp.post("/api/orders")
@login_required
@require_module(FILLKILL, "order")
def api_record_order():
    data = body()
    try:
        sub_id = int(data.get("sub_id"))
    except (TypeError, ValueError):
        raise RuleError("Which pick is this order for?") from None
    order = services.record_order(sub_id, data, current_user.email, expected_status=data.get("expected_status"))
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

