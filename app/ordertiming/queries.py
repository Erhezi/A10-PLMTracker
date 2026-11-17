"""Every Order Timing read (2026-11-16): Medline's order lines, through the views of
db/ordertiming/01_views.sql. Read-only; returns plain dicts and lists.

The views are read with SQLAlchemy Core (``table``/``column``), so the same queries run on SQL Server
and on SQLite, where the tests stand in tables with the views' names and columns (tests/conftest.py).

An order is Medline's sales order, which carries one of our POs; its lines are the PO's lines. The
search and the status filter pick lines; an order shows when any of its lines is picked, with all
its lines, the picked ones marked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import and_, column, func, or_, select, table

from .. import db

# Each line's status, as the view works it out ([Line Status]), in the order they happen; the labels
# are the app's. A status the view adds needs a label here.
STATUSES = (
    ("not_confirmed", "Not confirmed"),
    ("rejected", "Rejected"),
    ("confirmed", "Confirmed"),
    ("asn", "ASN sent"),
)
STATUS_LABELS = dict(STATUSES)

PAGE_SIZE = 20  # orders (POs) a page of Main shows, newest first; the export has them all
EXPORT_LIMIT = 100_000  # lines in one export, a guard

# A line's values, by the name the app gives them -> the view's column.
LINE_COLUMNS = {
    "report_date": "Report Date",
    "order_no": "Order #",
    "order_line": "Order Line",
    "po_raw": "PO#",
    "po": "PO",
    "po_line": "POLine",
    "po_type": "PO Type",
    "site": "Sold-To #",
    "site_name": "Sold-To Name",
    "ship_to": "Ship-To #",
    "ship_to_name": "Ship-To Name",
    "buyer": "Buyer Name",
    "medline_item": "Medline Item #",
    "cust_item": "Cust Item #",
    "item_on_po": "Item # on PO",
    "mfr_item": "Mfr Item #",
    "manufacturer": "Manufacturer",
    "description": "Item Description",
    "qty": "Order Qty",
    "open_qty": "Open Qty",
    "shipped_qty": "Shipped Qty",
    "um": "UM",
    "line_type": "Line Type",
    "bad_line": "Bad Line",
    "rej_code": "Rej Code",
    "received_at": "Received At",
    "created_at": "Order Created At",
    "confirmed_at": "Confirmed At",
    "mins_to_create": "Mins  to Order Create",  # Medline's double space
    "mins_to_confirm": "Mins to Confirm",
    "asn_at": "ASN Created At",
    "status": "Line Status",
}
# The values that belong to the order (the same on each of its lines); the rest are the line's.
ORDER_KEYS = ("order_no", "po", "po_raw", "po_type", "report_date", "site", "site_name", "ship_to", "ship_to_name",
              "buyer")

LINES = table("vw_MedlineOrderLine", *(column(name) for name in LINE_COLUMNS.values()), schema="OrderTiming")
LAST_LOAD = table("vw_OrderTimingLastLoad", column("last_success"), column("last_line_load"), schema="OrderTiming")

# What the search box looks in; the item numbers also without dashes, spaces, dots and slashes
# ("dls5529" finds DLS-5529), as Fill/Kill's sub search does.
SEARCHED = ("po_raw", "order_no", "medline_item", "cust_item", "item_on_po", "mfr_item", "description",
            "manufacturer", "ship_to", "ship_to_name", "buyer")
COMPACTED = ("medline_item", "cust_item", "item_on_po", "mfr_item")
PUNCTUATION = ("-", " ", ".", "/")


def col(key: str):
    return LINES.c[LINE_COLUMNS[key]]


@dataclass(frozen=True)
class Filters:
    """What Main shows: Medline's order days (Report Date, inclusive), Sold-To codes (empty = all),
    the search text and a line status (empty = any)."""

    start: date
    end: date
    sites: tuple[str, ...] = field(default_factory=tuple)
    q: str = ""
    status: str = ""

    @property
    def picks_lines(self) -> bool:
        """Whether the search or the status pick some lines of an order and not others."""
        return bool(search_terms(self.q) or self.status)


def _rows(statement) -> list[dict]:
    return [dict(row._mapping) for row in db.session.execute(statement)]


# --- the data's shape --------------------------------------------------------------------

def sites(start: date, end: date) -> list[dict]:
    """Every Sold-To with an order in those days, by name (only the days Main can show: a range seek
    on the source table's key, not a scan of every day)."""
    statement = (select(col("site").label("code"), func.max(col("site_name")).label("name"))
                 .where(col("report_date").between(start, end))
                 .group_by(col("site")).order_by(func.max(col("site_name")), col("site")))
    return _rows(statement)


def last_load() -> dict:
    rows = _rows(select(LAST_LOAD.c.last_success, LAST_LOAD.c.last_line_load))
    return rows[0] if rows else {"last_success": None, "last_line_load": None}


# --- the search --------------------------------------------------------------------------

def search_terms(q: str | None) -> list[str]:
    """The words of the search: spaces, commas and semicolons part them (pasted lists too)."""
    return [word for word in re.split(r"[\s,;]+", (q or "").strip().lower()) if word]


def _compact(text: str) -> str:
    for ch in PUNCTUATION:
        text = text.replace(ch, "")
    return text


def _compact_column(key: str):
    expression = func.lower(col(key))
    for ch in PUNCTUATION:
        expression = func.replace(expression, ch, "")
    return expression


def _word_condition(word: str):
    """A line where the word is in any column searched."""
    conditions = [func.lower(col(key)).contains(word, autoescape=True) for key in SEARCHED]
    bare = _compact(word)
    if bare:  # the item numbers, both without punctuation: "bd930103" finds B-D930103, and "b-d930103" BD930103
        conditions += [_compact_column(key).contains(bare, autoescape=True) for key in COMPACTED]
    return or_(*conditions)


def search_condition(q: str | None):
    """Lines with every word of the search; but when every word is a number (POs, Medline order
    numbers, items pasted as a list), lines with any of them: one line can't be on two POs."""
    words = search_terms(q)
    if not words:
        return None
    each = [_word_condition(word) for word in words]
    if len(words) > 1 and all(word.isdigit() for word in words):
        return or_(*each)
    return and_(*each)


def _conditions(filters: Filters, *, scope_only: bool = False) -> list:
    """The SQL conditions for the days and sites, and (unless ``scope_only``) the search and status."""
    found = [col("report_date").between(filters.start, filters.end)]
    if filters.sites:
        found.append(col("site").in_(list(filters.sites)))
    if scope_only:
        return found
    searched = search_condition(filters.q)
    if searched is not None:
        found.append(searched)
    if filters.status:
        found.append(col("status") == filters.status)
    return found


def _selected(keys=None):
    return [col(key).label(key) for key in (keys or LINE_COLUMNS)]


# --- Main ---------------------------------------------------------------------------------

def find_orders(filters: Filters, page: int = 1, per_page: int = PAGE_SIZE) -> dict:
    """One page of the orders with a line the filters pick, newest first, each with all its lines.
    ``total`` counts every order picked and ``pages`` the pages; a page past the last is the last."""
    picked = _conditions(filters)
    total = db.session.execute(select(func.count(func.distinct(col("order_no")))).where(*picked)).scalar() or 0
    pages = max(1, -(-total // per_page))
    page = min(max(page, 1), pages)
    found = {"orders": [], "total": total, "page": page, "pages": pages, "per_page": per_page}
    if not total:
        return found
    newest = (select(col("order_no").label("order_no"))
              .where(*picked)
              .group_by(col("order_no"))
              .order_by(func.max(col("report_date")).desc(), func.max(col("received_at")).desc(), col("order_no").desc())
              .offset((page - 1) * per_page)
              .limit(per_page))
    order_nos = [row["order_no"] for row in _rows(newest)]
    if not order_nos:
        return found

    # All their lines (an order's lines share its day and site, so the scope keeps them all).
    scope = _conditions(filters, scope_only=True)
    lines = _rows(select(*_selected()).where(col("order_no").in_(order_nos), *scope))
    matched = None
    if filters.picks_lines:
        rows = _rows(select(col("order_no").label("o"), col("order_line").label("l"))
                     .where(col("order_no").in_(order_nos), *picked))
        matched = {(row["o"], row["l"]) for row in rows}
    by_order: dict[str, list[dict]] = {}
    for line in lines:
        line["matched"] = matched is None or (line["order_no"], line["order_line"]) in matched
        by_order.setdefault(line["order_no"], []).append(line)
    found["orders"] = [build_order(by_order[no]) for no in order_nos if no in by_order]
    return found


def _line_sort(line: dict):
    text = str(line.get("order_line") or "")
    return (0, int(text), "") if text.isdigit() else (1, 0, text)


def _latest_of_each_line(lines: list[dict]) -> list[dict]:
    """Each order line once, as of its latest day. Medline's reports cover one order day each, but if
    a line ever shows up in two (A13's open question 1), the PO's line count still counts it once."""
    latest: dict = {}
    for line in lines:
        kept = latest.get(line["order_line"])
        if kept is None or str(line["report_date"]) > str(kept["report_date"]):
            latest[line["order_line"]] = line
    return list(latest.values())


def build_order(lines: list[dict]) -> dict:
    """An order from its lines: what they share, when Medline received and confirmed it, how many
    lines it has (``line_count``, the PO's total) and in each status, and the lines."""
    lines = sorted(_latest_of_each_line(lines), key=_line_sort)
    first = lines[0]
    counts = {code: 0 for code, _ in STATUSES}
    for line in lines:
        counts[line["status"]] = counts.get(line["status"], 0) + 1
    confirmed = [line["confirmed_at"] for line in lines if line["confirmed_at"]]
    received = [line["received_at"] for line in lines if line["received_at"]]
    created = [line["created_at"] for line in lines if line["created_at"]]
    # Medline confirms an order as a whole (855): confirmed when every line has it.
    is_confirmed = len(confirmed) == len(lines)
    minutes = [line["mins_to_confirm"] for line in lines if line["mins_to_confirm"] is not None]
    return {
        **{key: first[key] for key in ORDER_KEYS},
        "received_at": min(received) if received else None,
        "created_at": min(created) if created else None,
        "confirmed_at": max(confirmed) if is_confirmed else None,
        "mins_to_confirm": max(minutes) if is_confirmed and minutes else None,
        "status": "confirmed" if is_confirmed else "not_confirmed",
        "counts": counts,
        "line_count": len(lines),
        "matched": sum(1 for line in lines if line["matched"]),
        "lines": [{key: value for key, value in line.items() if key not in ORDER_KEYS} for line in lines],
    }


def export_lines(filters: Filters, limit: int = EXPORT_LIMIT) -> list[dict]:
    """Every line the filters pick (not just the first orders'), newest first, for the CSV."""
    statement = (select(*_selected()).where(*_conditions(filters))
                 .order_by(col("report_date").desc(), col("received_at").desc(), col("order_no").desc(),
                           col("order_line"))
                 .limit(limit))
    return _rows(statement)
