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
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from sqlalchemy import and_, case, column, func, literal_column, or_, select, table

from .. import db

# Each line's status, as the view works it out ([Line Status]), in the order of Main's tabs (the
# user, 2026-11-17) and each PO's chips; the labels are the app's. A status the view adds needs a
# label here.
STATUSES = (
    ("rejected", "Rejected"),
    ("asn", "ASN sent"),
    ("confirmed", "Confirmed"),
    ("not_confirmed", "Not confirmed"),
)
STATUS_LABELS = dict(STATUSES)
# Short shipped (2026-11-17) isn't a status but the view's [Short Qty]: a line with an ASN can be
# short too (the user: ASN sent wins in the status, short shipped is tallied on its own). Main's
# last tab picks such lines, as ?status=short, like a status's tab.
SHORT = "short"
SHORT_LABEL = "Short shipped"
TABS = (*STATUSES, (SHORT, SHORT_LABEL))
TAB_LABELS = dict(TABS)

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
    "short_qty": "Short Qty",  # NULL unless short shipped (2026-11-17)
}
# The values that belong to the order (the same on each of its lines); the rest are the line's.
ORDER_KEYS = ("order_no", "po", "po_raw", "po_type", "report_date", "site", "site_name", "ship_to", "ship_to_name",
              "buyer")

# Short Ships' lines (vw_ShortShipLine, 2026-11-17): the short-shipped lines with Main's columns, then
# what the view adds: the PO's total lines, and the line in Medline's Fill/Kill feed, which the view
# joins on Medline's order and line.
SHORT_COLUMNS = {
    **LINE_COLUMNS,
    "po_lines": "PO Total Lines",
    "in_fillkill": "In Fill/Kill",
    "kill_reason": "Fill/Kill Reason",
    "kill_reason_date": "Est Avail Date",
}

LINES = table("vw_MedlineOrderLine", *(column(name) for name in LINE_COLUMNS.values()), schema="OrderTiming")
SHORT_LINES = table("vw_ShortShipLine", *(column(name) for name in SHORT_COLUMNS.values()), schema="OrderTiming")
# Fill/Kill's kill lines per Medline item, Sold-To (as this feed writes it) and day, for Short Ships'
# kill counts.
KILL_DAYS = table("vw_ItemKillDay", column("Medline Item #"), column("Sold-To #"), column("Order Date"),
                  column("Kill Lines"), schema="OrderTiming")
LAST_LOAD = table("vw_OrderTimingLastLoad", column("last_success"), column("last_line_load"), schema="OrderTiming")

# What the search box looks in; the item numbers also without dashes, spaces, dots and slashes
# ("dls5529" finds DLS-5529), as Fill/Kill's sub search does.
SEARCHED = ("po_raw", "order_no", "medline_item", "cust_item", "item_on_po", "mfr_item", "description",
            "manufacturer", "ship_to", "ship_to_name", "buyer")
COMPACTED = ("medline_item", "cust_item", "item_on_po", "mfr_item")
PUNCTUATION = ("-", " ", ".", "/")


def col(key: str, source=LINES):
    """A line's column by the app's name, in Main's view or (``source``) Short Ships'."""
    return source.c[SHORT_COLUMNS[key]]


@dataclass(frozen=True)
class Filters:
    """What Main shows: Medline's order days (Report Date, inclusive), Sold-To codes (empty = all),
    the search text and a line status (empty = any)."""

    start: date
    end: date
    sites: tuple[str, ...] = field(default_factory=tuple)
    q: str = ""
    status: str = ""  # a status, or SHORT for short-shipped lines (TABS)

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
    """last_success, last_line_load and last_file (2026-11-17; the file loaded, for "Data as of"):
    every column the view has, so a view without last_file still works."""
    rows = _rows(select(literal_column("*")).select_from(LAST_LOAD))
    return rows[0] if rows else {"last_success": None, "last_line_load": None, "last_file": None}


# --- the search --------------------------------------------------------------------------

def search_terms(q: str | None) -> list[str]:
    """The words of the search: spaces, commas and semicolons part them (pasted lists too)."""
    return [word for word in re.split(r"[\s,;]+", (q or "").strip().lower()) if word]


def _compact(text: str) -> str:
    for ch in PUNCTUATION:
        text = text.replace(ch, "")
    return text


def _compact_column(key: str, source=LINES):
    expression = func.lower(col(key, source))
    for ch in PUNCTUATION:
        expression = func.replace(expression, ch, "")
    return expression


def _word_condition(word: str, source=LINES):
    """A line where the word is in any column searched."""
    conditions = [func.lower(col(key, source)).contains(word, autoescape=True) for key in SEARCHED]
    bare = _compact(word)
    if bare:  # the item numbers, both without punctuation: "bd930103" finds B-D930103, and "b-d930103" BD930103
        conditions += [_compact_column(key, source).contains(bare, autoescape=True) for key in COMPACTED]
    return or_(*conditions)


def search_condition(q: str | None, source=LINES):
    """Lines with every word of the search; but when every word is a number (POs, Medline order
    numbers, items pasted as a list), lines with any of them: one line can't be on two POs."""
    words = search_terms(q)
    if not words:
        return None
    each = [_word_condition(word, source) for word in words]
    if len(words) > 1 and all(word.isdigit() for word in words):
        return or_(*each)
    return and_(*each)


def _conditions(filters: Filters, *, scope_only: bool = False, source=LINES) -> list:
    """The SQL conditions for the days and sites, and (unless ``scope_only``) the search and status,
    on Main's view or (``source``) Short Ships'."""
    found = [col("report_date", source).between(filters.start, filters.end)]
    if filters.sites:
        found.append(col("site", source).in_(list(filters.sites)))
    if scope_only:
        return found
    searched = search_condition(filters.q, source)
    if searched is not None:
        found.append(searched)
    if filters.status == SHORT:
        found.append(col("short_qty", source) > 0)
    elif filters.status:
        found.append(col("status", source) == filters.status)
    return found


def _selected(keys=None, source=LINES):
    return [col(key, source).label(key) for key in (keys or LINE_COLUMNS)]


# --- Main ---------------------------------------------------------------------------------

def status_counts(filters: Filters) -> dict:
    """For Main's tabs (2026-11-17): how many orders the days, sites and search find (``all``), how
    many of them have a line in each status, and how many a short-shipped line (``short``). The tab
    chosen doesn't count, so each tab says what clicking it would show. An order with lines in two
    statuses counts under both. One pass over the lines, in the same days as the search."""
    order = col("order_no")
    statement = select(
        func.count(func.distinct(order)).label("all"),
        *(func.count(func.distinct(case((col("status") == code, order)))).label(code) for code, _ in STATUSES),
        func.count(func.distinct(case((col("short_qty") > 0, order)))).label(SHORT),
    ).where(*_conditions(replace(filters, status="")))
    rows = _rows(statement)
    return {key: int(value or 0) for key, value in rows[0].items()} if rows else {}


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
    lines it has (``line_count``, the PO's total), in each status and short shipped (``short_lines``,
    whatever their status), and the lines."""
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
        "short_lines": sum(1 for line in lines if (line.get("short_qty") or 0) > 0),
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


# --- Short Ships (2026-11-17) ---------------------------------------------------------------
# The user: the short-shipped lines, one row per Medline item, with how often Fill/Kill has killed
# that item today, in the last 7 days and in the last 30, so items killed again and again stand out.
# A short-shipped line is one with a Short Qty (the view's rule), whatever its status. The joins to
# Fill/Kill are the views' (vw_ShortShipLine, vw_ItemKillDay; the user, 2026-11-17: the logic in the
# query, not the code); here they're filtered, grouped per item and paged.

ITEMS_PAGE_SIZE = 20  # items a page of Short Ships shows
KILL_KEYS = ("kills_today", "kills_7", "kills_30")
NO_KILLS = {key: 0 for key in KILL_KEYS}
# What Short Ships can sort on (a header click); it opens on the items most killed in 30 days.
ITEM_SORTS = ("medline_item", "short_lines", "pos", "sites", "short_qty", "last_short", *KILL_KEYS)
DEFAULT_ITEM_SORT = ("kills_30", "desc")


def scol(key: str):
    """A column of Short Ships' view (vw_ShortShipLine)."""
    return col(key, SHORT_LINES)


def _short_conditions(filters: Filters) -> list:
    """The days, sites and search, on Short Ships' view: every line in it is short shipped."""
    return _conditions(replace(filters, status=""), source=SHORT_LINES)


def kill_counts(today: date, sites=()) -> dict[str, dict]:
    """How many lines Medline's Fill/Kill feed killed for each Medline item: today, in the last 7
    days and in the last 30 (today included, by Fill/Kill's Order Date), at the Sold-Tos given (all
    when none). Each kill line counts once; an item killed on three orders today was killed 3 times.
    vw_ItemKillDay counts them per day and writes Fill/Kill's Sold-Tos as this feed does."""
    k = KILL_DAYS.c
    day, kills = k["Order Date"], k["Kill Lines"]
    statement = (select(k["Medline Item #"].label("item"),
                        func.sum(case((day == today, kills), else_=0)).label("kills_today"),
                        func.sum(case((day >= today - timedelta(days=6), kills), else_=0)).label("kills_7"),
                        func.sum(kills).label("kills_30"))
                 .where(day.between(today - timedelta(days=29), today))
                 .group_by(k["Medline Item #"]))
    if sites:
        statement = statement.where(k["Sold-To #"].in_(list(sites)))
    return {row["item"]: {key: int(row[key] or 0) for key in KILL_KEYS} for row in _rows(statement)}


def _short_lines(filters: Filters, *extra, limit: int | None = None) -> list[dict]:
    """The short-shipped lines the filters pick, newest first, each with its PO's total lines
    (``po_lines``) and its Fill/Kill line (``in_fillkill``, ``kill_reason``, ``kill_reason_date``),
    as vw_ShortShipLine gives them."""
    statement = (select(*_selected(SHORT_COLUMNS, SHORT_LINES))
                 .where(*_short_conditions(filters), *extra)
                 .order_by(scol("report_date").desc(), scol("created_at").desc(), scol("order_no").desc(),
                           scol("order_line")))
    if limit:
        statement = statement.limit(limit)
    lines = _rows(statement)
    for line in lines:
        line["in_fillkill"] = bool(line["in_fillkill"])  # SQL Server's BIT; 1 or 0 on SQLite
    return lines


def _sort_items(items: list[dict], sort: str, direction: str) -> None:
    """In place: by the sort chosen (empty values last either way), then the most killed in 30 days,
    the most short lines and the item number."""
    items.sort(key=lambda item: item["medline_item"] or "")
    items.sort(key=lambda item: item["short_lines"], reverse=True)
    items.sort(key=lambda item: item["kills_30"], reverse=True)
    present = [item for item in items if item[sort] is not None]
    present.sort(key=lambda item: item[sort], reverse=direction == "desc")
    items[:] = present + [item for item in items if item[sort] is None]


def short_items(filters: Filters, today: date, sort: str = "", direction: str = "", page: int = 1,
                per_page: int = ITEMS_PAGE_SIZE) -> dict:
    """One page of Short Ships: each Medline item with a short-shipped line the days, sites and search
    pick (``short_lines``, on ``pos`` POs at ``sites`` Sold-Tos, ``short_qty`` in its UM, the latest
    PO created ``last_short``), how often Fill/Kill killed it (kill_counts, at the same sites), and its
    short lines, newest first. ``total`` counts every item picked."""
    if sort not in ITEM_SORTS:
        sort, direction = DEFAULT_ITEM_SORT
    direction = "asc" if direction == "asc" else "desc"
    picked = _short_conditions(filters)
    items = _rows(select(scol("medline_item").label("medline_item"),
                         func.count().label("short_lines"),
                         func.count(func.distinct(scol("order_no"))).label("pos"),
                         func.count(func.distinct(scol("site"))).label("sites"),
                         func.sum(scol("short_qty")).label("short_qty"),
                         func.min(scol("um")).label("um"), func.max(scol("um")).label("um_last"),
                         func.max(scol("description")).label("description"),
                         func.max(scol("cust_item")).label("cust_item"),
                         func.max(scol("manufacturer")).label("manufacturer"),
                         func.max(scol("mfr_item")).label("mfr_item"),
                         func.max(scol("created_at")).label("last_short"))
                  .where(*picked).group_by(scol("medline_item")))
    names: dict = {}
    for row in _rows(select(scol("medline_item").label("i"), scol("site_name").label("n"), scol("site").label("s"))
                     .where(*picked).distinct()):
        names.setdefault(row["i"], set()).add(row["n"] or row["s"])
    kills = kill_counts(today, filters.sites)
    for item in items:
        if item.pop("um_last") != item["um"]:  # in more than one UM: no one total
            item["um"], item["short_qty"] = None, None
        item["site_names"] = sorted(names.get(item["medline_item"], ()))
        item.update(kills.get(item["medline_item"], NO_KILLS))
    _sort_items(items, sort, direction)

    total = len(items)
    pages = max(1, -(-total // per_page))
    page = min(max(page, 1), pages)
    shown = items[(page - 1) * per_page:page * per_page]
    by_item: dict = {}
    if shown:
        for line in _short_lines(filters, scol("medline_item").in_([item["medline_item"] for item in shown])):
            by_item.setdefault(line["medline_item"], []).append(line)
    for item in shown:
        item["lines"] = by_item.get(item["medline_item"], [])
    return {"items": shown, "total": total, "page": page, "pages": pages, "per_page": per_page,
            "sort": sort, "dir": direction}


def export_short_lines(filters: Filters, today: date, limit: int = EXPORT_LIMIT) -> list[dict]:
    """Every short-shipped line the filters pick, newest first, each with its PO's total lines, its
    Fill/Kill reason and its item's kill counts, for Short Ships' CSV."""
    lines = _short_lines(filters, limit=limit)
    kills = kill_counts(today, filters.sites)
    for line in lines:
        line.update(kills.get(line["medline_item"], NO_KILLS))
    return lines
