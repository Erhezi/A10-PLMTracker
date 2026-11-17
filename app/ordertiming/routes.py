"""Order Timing (2026-10-30): a module beside Fill/Kill, for display.

Medline sends a feed of the EDI orders it received from us (A13 loads it hourly into SCSFileIngestor).
Main (2026-11-16) finds orders in it, by PO, item, site and status, to see whether Medline received
and confirmed them; the Dashboard is still empty. Nothing is entered here. Every Fill/Kill role can
view it (``access.MODULES[ORDERTIMING]`` has no roles of its own).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from flask import Blueprint, Response, jsonify, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from .. import db
from ..models import now_ny_naive
from ..utility import freshness
from ..utility.access import ORDERTIMING, is_admin, require_module
from . import queries

bp = Blueprint("ordertiming", __name__, url_prefix="/ordertiming")

DEFAULT_DAYS = 7  # Main opens on the last 7 days, today included
MAX_DAYS = 30  # and looks back no further than the last 30 (the user, 2026-11-16: volume, speed)
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


def default_dates(today: date) -> tuple[date, date]:
    return today - timedelta(days=DEFAULT_DAYS - 1), today


def earliest_day(today: date) -> date:
    """The first day Main and the export can reach: the last MAX_DAYS, today included."""
    return today - timedelta(days=MAX_DAYS - 1)


def _parse_date(value: str | None, default: date) -> date:
    try:
        return date.fromisoformat(value) if value else default
    except ValueError:
        raise BadRequest(f"Dates must look like 2026-11-16, not '{value}'.") from None


def filters_from_request() -> queries.Filters:
    """Days from ?start&end (default: the last DEFAULT_DAYS, today included), held to the last
    MAX_DAYS (an older bookmark gets the days it can); Sold-To codes from ?sites=a,b, the search from
    ?q and a line status from ?status."""
    today = now_ny_naive().date()
    first, last = default_dates(today)
    start = _parse_date(request.args.get("start"), first)
    end = _parse_date(request.args.get("end"), last)
    if start > end:
        start, end = end, start
    start = min(max(start, earliest_day(today)), today)
    end = min(max(end, start), today)
    raw = ",".join(request.args.getlist("sites"))
    sites = tuple(sorted({site.strip() for site in raw.split(",") if site.strip()}))
    status = (request.args.get("status") or "").strip()
    if status and status not in queries.STATUS_LABELS:
        raise BadRequest(f"There's no status '{status}'.")
    q = (request.args.get("q") or "").strip()[:Q_MAX]
    return queries.Filters(start, end, sites, q, status)


def page_from_request() -> int:
    value = (request.args.get("page") or "1").strip()
    if not value.isdigit() or int(value) < 1:
        raise BadRequest(f"A page is a number from 1, not '{value}'.")
    return int(value)


def data_as_of() -> dict:
    """When Medline's lines were last loaded, as Fill/Kill's Main says it (utility/freshness.py): A13's
    last good run, else the newest day's load; stale when more than 90 minutes old in the feed's hours."""
    load = queries.last_load()
    return freshness.data_as_of(load.get("last_success"), load.get("last_line_load"), now_ny_naive())


# --- pages ------------------------------------------------------------------------------

@bp.route("/")
@login_required
@require_module(ORDERTIMING, "view")
def index():
    today = now_ny_naive().date()
    start, end = default_dates(today)
    earliest = earliest_day(today)
    problem, sites, data = None, [], {"as_of": None}
    try:
        sites = queries.sites(earliest, today)
        data = data_as_of()
    except SQLAlchemyError as error:  # the views aren't there yet, or a grant is missing
        db.session.rollback()
        problem = unavailable(error)
    config = {
        "default": {"start": start, "end": end},
        "earliest": earliest,
        "today": today,
        "max_days": MAX_DAYS,
        "sites": sites,
        # Lists, not objects: the JSON encoder sorts object keys, and this order matters.
        "statuses": [[code, label] for code, label in queries.STATUSES],
        "per_page": queries.PAGE_SIZE,
        "data": data,
        "problem": problem,
        "api": {"orders": url_for("ordertiming.api_orders"), "export": url_for("ordertiming.export_lines")},
    }
    return render_template("ordertiming/index.html", config=plain(config))


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
    ("Shipped Qty", "shipped_qty"), ("Open Qty", "open_qty"), ("UM", "um"), ("Received", "received_at"),
    ("Order Created", "created_at"), ("Confirmed", "confirmed_at"), ("Mins to Confirm", "mins_to_confirm"),
    ("ASN Created", "asn_at"),
    ("Buyer", "buyer"), ("PO# as Sent", "po_raw"),
)


def _csv_cell(key: str, value) -> str:
    if key == "status":
        value = queries.STATUS_LABELS.get(value, value)
    if isinstance(value, datetime):
        value = f"{value:%Y-%m-%d %H:%M:%S}"
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
