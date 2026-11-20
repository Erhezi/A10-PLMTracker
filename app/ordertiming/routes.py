"""Order Timing (2026-10-30): a module beside Fill/Kill, for display.

Medline sends a feed of the EDI orders it received from us (A13 loads it hourly into SCSFileIngestor).
Main (2026-11-16) finds orders in it, by PO, item, site and status, to see whether Medline received
and confirmed them. Short Ships (2026-11-17) lists the items Medline short shipped, with how often
Fill/Kill's feed killed each one. The Dashboard is still empty. Nothing is entered here. Every
Fill/Kill role can view it (``access.MODULES[ORDERTIMING]`` has no roles of its own).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from flask import Blueprint, Response, current_app, jsonify, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from .. import db
from ..fillkill import queries as fillkill_queries
from ..models import now_ny_naive
from ..utility import freshness
from ..utility.access import ORDERTIMING, is_admin, require_module
from . import queries

bp = Blueprint("ordertiming", __name__, url_prefix="/ordertiming")

MAIN_DAYS = 1  # Main opens on today (the user, 2026-11-17; the last 7 days before)
SHORT_SHIPS_DAYS = 1  # Short Ships too (the user, 2026-11-18; the last 7 days before)
MAX_DAYS = 30  # and both look back no further than the last 30 (the user, 2026-11-16: volume, speed),
# nor before ORDERTIMING_FIRST_DAY (config.py: Medline's LUM go-live, 2026-11-16)
Q_MAX = 500  # characters of search text taken (a pasted list of POs fits)
SCRIPT = "db/ordertiming/01_views.sql"


class BadRequest(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@bp.errorhandler(BadRequest)
def bad_request(error: BadRequest):
    return jsonify({"error": "request", "message": error.message}), 400


@bp.errorhandler(SQLAlchemyError)
def database_error(error: SQLAlchemyError):
    db.session.rollback()
    return jsonify({"error": "database", "message": unavailable(error)}), 503


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


def unavailable(error: Exception) -> str:
    """What to say when the views can't be read: the cause and the fix for admins, a pointer for others."""
    if is_admin(current_user):
        cause = str(getattr(error, "orig", error)).splitlines()[0][:300]
        return (f"Order Timing can't read Medline's order lines ({cause}). Run {SCRIPT} on O2, and grant the "
                "app's account SELECT on SCSFileIngestor.MedlineOrderTiming.MedlineOrderTiming.")
    return "Medline's order data can't be read right now. Ask an admin to look at it."


def first_day() -> date | None:
    """ORDERTIMING_FIRST_DAY (a date, or ISO text; empty: none)."""
    value = current_app.config.get("ORDERTIMING_FIRST_DAY")
    if not value:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value).strip())


def earliest_day(today: date) -> date:
    """The first day the pages and their exports can reach: the last MAX_DAYS, today included, and
    not before ORDERTIMING_FIRST_DAY (nor after today)."""
    earliest = today - timedelta(days=MAX_DAYS - 1)
    go_live = first_day()
    return min(max(earliest, go_live), today) if go_live else earliest


def default_dates(today: date, days: int) -> tuple[date, date]:
    """A page's opening days: the last ``days``, today included, from the earliest day it can reach."""
    return max(today - timedelta(days=days - 1), earliest_day(today)), today


def _parse_date(value: str | None, default: date) -> date:
    try:
        return date.fromisoformat(value) if value else default
    except ValueError:
        raise BadRequest(f"Dates must look like 2026-11-16, not '{value}'.") from None


def filters_from_request(days: int = MAIN_DAYS) -> queries.Filters:
    """Days from ?start&end (default: the page's opening days), held to the days the pages reach
    (earliest_day: an older bookmark gets the days it can); Sold-To codes from ?sites=a,b, the search
    from ?q, and a line status or short-shipped lines (``short``) from ?status (Main's tabs)."""
    today = now_ny_naive().date()
    first, last = default_dates(today, days)
    start = _parse_date(request.args.get("start"), first)
    end = _parse_date(request.args.get("end"), last)
    if start > end:
        start, end = end, start
    start = min(max(start, earliest_day(today)), today)
    end = min(max(end, start), today)
    raw = ",".join(request.args.getlist("sites"))
    sites = tuple(sorted({site.strip() for site in raw.split(",") if site.strip()}))
    status = (request.args.get("status") or "").strip()
    if status and status not in queries.TAB_LABELS:
        raise BadRequest(f"There's no status '{status}'.")
    q = (request.args.get("q") or "").strip()[:Q_MAX]
    return queries.Filters(start, end, sites, q, status)


def page_from_request() -> int:
    value = (request.args.get("page") or "1").strip()
    if not value.isdigit() or int(value) < 1:
        raise BadRequest(f"A page is a number from 1, not '{value}'.")
    return int(value)


def kill_windows(today: date) -> dict:
    """The days Short Ships' kill counts cover, today included: today, the last 7 and the last 30."""
    return {"today": today, "week": today - timedelta(days=6), "month": today - timedelta(days=29)}


def fillkill_as_of() -> dict | None:
    """How fresh Fill/Kill's kill lines are (Fill/Kill's own "Data as of" and "Last loaded"), for
    Short Ships: a line shorted since then isn't in Fill/Kill yet. None when it can't be read."""
    try:
        load = fillkill_queries.last_load()
    except SQLAlchemyError:
        db.session.rollback()
        return None
    return freshness.data_as_of(load.get("last_success"), load.get("last_line_update"), now_ny_naive(),
                                load.get("last_file"))


def data_as_of() -> dict:
    """How fresh Medline's lines are, as Fill/Kill's Main says it (utility/freshness.py): when Medline
    made the file loaded, and when it was loaded (A13's last good run, else the newest day's load);
    stale when the load is more than 90 minutes old in the feed's hours."""
    load = queries.last_load()
    return freshness.data_as_of(load.get("last_success"), load.get("last_line_load"), now_ny_naive(),
                                load.get("last_file"))


# --- pages ------------------------------------------------------------------------------

def page_config(today: date, days: int) -> dict:
    """What Main and Short Ships both start from: the days (opening on the last ``days``), the sites
    in them, the statuses and the data's freshness, or the problem reading it (the views aren't there
    yet, or a grant is missing)."""
    start, end = default_dates(today, days)
    earliest = earliest_day(today)
    problem, sites, data = None, [], {"loaded_at": None}
    try:
        sites = queries.sites(earliest, today)
        data = data_as_of()
    except SQLAlchemyError as error:
        db.session.rollback()
        problem = unavailable(error)
    return {
        "default": {"start": start, "end": end},
        "earliest": earliest,
        "today": today,
        "max_days": MAX_DAYS,
        "sites": sites,
        # Lists, not objects: the JSON encoder sorts object keys, and this order matters.
        "statuses": [[code, label] for code, label in queries.STATUSES],
        "short_tab": [queries.SHORT, queries.SHORT_LABEL],
        "data": data,
        "problem": problem,
    }


@bp.route("/")
@login_required
@require_module(ORDERTIMING, "view")
def index():
    config = {
        **page_config(now_ny_naive().date(), MAIN_DAYS),
        "per_page": queries.PAGE_SIZE,
        "api": {"orders": url_for("ordertiming.api_orders"), "export": url_for("ordertiming.export_lines")},
    }
    return render_template("ordertiming/index.html", config=plain(config))


@bp.route("/shortships")
@login_required
@require_module(ORDERTIMING, "view")
def shortships_page():
    """Short Ships (2026-11-17): the items Medline short shipped, one row each, with how often
    Fill/Kill's feed killed it; drawn by static/js/ordertiming/shortships.js."""
    today = now_ny_naive().date()
    config = {
        **page_config(today, SHORT_SHIPS_DAYS),
        "per_page": queries.ITEMS_PAGE_SIZE,
        "sort": list(queries.DEFAULT_ITEM_SORT),
        "kill_windows": kill_windows(today),
        "api": {"items": url_for("ordertiming.api_shortships"), "export": url_for("ordertiming.export_shortships"),
                "fillkill": url_for("fillkill.index")},
    }
    return render_template("ordertiming/shortships.html", config=plain(config))


@bp.route("/dashboard")
@login_required
@require_module(ORDERTIMING, "view")
def dashboard_page():
    return render_template("ordertiming/dashboard.html")


# --- reads --------------------------------------------------------------------------------

@bp.get("/api/orders")
@login_required
@require_module(ORDERTIMING, "view")
def api_orders():
    filters = filters_from_request()
    found = queries.find_orders(filters, page_from_request())
    return jsonify(plain({
        # The days as held to the last MAX_DAYS, which the page shows.
        "filters": {"start": filters.start, "end": filters.end, "sites": filters.sites, "q": filters.q,
                    "status": filters.status, "picks_lines": filters.picks_lines},
        **found,  # orders, total, page (a page past the last is the last), pages, per_page
        # The tabs: orders in these days, sites and search, in all, with a line in each status and
        # with a short-shipped line.
        "status_counts": queries.status_counts(filters),
        "data": data_as_of(),
    }))


# The export: every line the filters pick, newest first. Order-level values repeat on each line.
EXPORT_COLUMNS = (
    ("Report Date", "report_date"), ("Sold-To #", "site"), ("Sold-To Name", "site_name"), ("Ship-To #", "ship_to"),
    ("Ship-To Name", "ship_to_name"), ("PO", "po"), ("PO Type", "po_type"), ("PO Line", "po_line"),
    ("Medline Order #", "order_no"), ("Order Line", "order_line"), ("Line Type", "line_type"), ("Status", "status"),
    ("Bad Line", "bad_line"), ("Rej Code", "rej_code"), ("Medline Item #", "medline_item"),
    ("Cust Item #", "cust_item"), ("Item # on PO", "item_on_po"), ("Mfr Item #", "mfr_item"),
    ("Manufacturer", "manufacturer"), ("Item Description", "description"), ("Order Qty", "qty"),
    ("Shipped Qty", "shipped_qty"), ("Open Qty", "open_qty"), ("Short Qty", "short_qty"), ("UM", "um"),
    ("Received", "received_at"), ("Order Created", "created_at"), ("Confirmed", "confirmed_at"),
    ("Mins to Confirm", "mins_to_confirm"), ("ASN Created", "asn_at"),
    ("Buyer", "buyer"), ("PO# as Sent", "po_raw"),
)


def _csv_cell(key: str, value) -> str:
    if key == "status":
        value = queries.STATUS_LABELS.get(value, value)
    if isinstance(value, datetime):
        value = f"{value:%Y-%m-%d %H:%M:%S}"
    if isinstance(value, Decimal):  # SQL Server's 12.0000 (an Infor QOE, eaches from it) as 12
        value = format(value.normalize(), "f")
    value = plain(value)
    text = "" if value is None else str(value)
    # A cell starting with = + - @ would run as a formula in Excel.
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


@bp.get("/export")
@login_required
@require_module(ORDERTIMING, "view")
def export_lines():
    rows = queries.export_lines(filters_from_request())
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([label for label, _ in EXPORT_COLUMNS])
    for row in rows:
        writer.writerow([_csv_cell(key, row.get(key)) for _, key in EXPORT_COLUMNS])
    name = f"order-timing-{now_ny_naive():%Y%m%d}.csv"
    return Response("﻿" + out.getvalue(), mimetype="text/csv",  # the BOM: Excel reads it as UTF-8
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# --- Short Ships (2026-11-17) -------------------------------------------------------------------

@bp.get("/api/shortships")
@login_required
@require_module(ORDERTIMING, "view")
def api_shortships():
    """One page of Short Ships' items (queries.short_items), with each item's short lines."""
    filters = filters_from_request(SHORT_SHIPS_DAYS)
    today = now_ny_naive().date()
    found = queries.short_items(filters, today, (request.args.get("sort") or "").strip(),
                                (request.args.get("dir") or "").strip(), page_from_request())
    return jsonify(plain({
        "filters": {"start": filters.start, "end": filters.end, "sites": filters.sites, "q": filters.q},
        **found,  # items, total, page, pages, per_page, sort, dir (as the server took them)
        "kill_windows": kill_windows(today),
        "data": data_as_of(),
        "fillkill_data": fillkill_as_of(),
    }))


# Short Ships' export: every short-shipped line, each with its item's kill counts.
SHORT_EXPORT_COLUMNS = (
    ("Report Date", "report_date"), ("Sold-To #", "site"), ("Sold-To Name", "site_name"), ("Ship-To #", "ship_to"),
    ("Ship-To Name", "ship_to_name"), ("PO", "po"), ("PO Created", "created_at"), ("PO Total Lines", "po_lines"),
    ("PO Line", "po_line"), ("Medline Order #", "order_no"), ("Order Line", "order_line"), ("Line Type", "line_type"),
    ("Medline Item #", "medline_item"), ("Cust Item #", "cust_item"), ("Mfr Item #", "mfr_item"),
    ("Manufacturer", "manufacturer"), ("Item Description", "description"), ("Order Qty", "qty"),
    ("Shipped Qty", "shipped_qty"), ("Open Qty", "open_qty"), ("Short Qty", "short_qty"), ("UM", "um"),
    ("QOE", "qoe"), ("Order Qty EA", "qty_each"), ("Short Qty EA", "short_qty_each"),
    ("ASN Created", "asn_at"), ("In Fill/Kill", "in_fillkill"), ("Fill/Kill Reason", "kill_reason"),
    ("Est Avail Date", "kill_reason_date"), ("Item Killed Today", "kills_today"),
    ("Item Killed 7 Days", "kills_7"), ("Item Killed 30 Days", "kills_30"), ("Buyer", "buyer"),
)


@bp.get("/shortships/export")
@login_required
@require_module(ORDERTIMING, "view")
def export_shortships():
    rows = queries.export_short_lines(filters_from_request(SHORT_SHIPS_DAYS), now_ny_naive().date())
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([label for label, _ in SHORT_EXPORT_COLUMNS])
    for row in rows:
        values = {**row, "in_fillkill": "Yes" if row.get("in_fillkill") else "No"}
        writer.writerow([_csv_cell(key, values.get(key)) for _, key in SHORT_EXPORT_COLUMNS])
    name = f"short-ships-{now_ny_naive():%Y%m%d}.csv"
    return Response("﻿" + out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
