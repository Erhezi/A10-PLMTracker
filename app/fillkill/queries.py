"""Every Fill/Kill read (plan v2 §5.2). Returns plain dicts and lists.

Views are read with SQL (they are never mapped, see models/fillkill.py); the
workflow tables go through the models. The SQL here also runs on SQLite, where
the tests stand in tables with the views' names and columns.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from time import monotonic
from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, bindparam, func, or_, select, text, true

from .. import db
from ..models.fillkill import History, ItemInstruction, Sub, SubOrder, VendorItem
from . import rollup

log = logging.getLogger(__name__)

QTY = "[FillKill].[vw_MedlineFillKillQtyAgg]"
ITEMS = "[FillKill].[vw_MedlineFillKillItemCollection]"
LINES = "[FillKill].[vw_MedlineFillKill]"
LAST_LOAD = "[FillKill].[vw_FillKillLastLoad]"
CONTRACTS = "[FillKill].[vw_ContractLineSearch]"
VENDORS = "[FillKill].[vw_Vendor]"
UOM_ALIASES = "[FillKill].[vw_UomAlias]"

LIBRARY_LIMIT = 1000


@dataclass(frozen=True)
class Scope:
    """What the main table shows: order dates (inclusive) and Sold-To codes (empty = all)."""

    start: date
    end: date
    sites: tuple[str, ...] = field(default_factory=tuple)

    def where(self, date_column: str, site_column: str) -> tuple[str, dict, list]:
        """SQL condition, parameters, and the expanding bind for the site list."""
        sql = f"{date_column} BETWEEN :start AND :end"
        params = {"start": self.start, "end": self.end}
        binds = []
        if self.sites:
            sql += f" AND {site_column} IN :sites"
            params["sites"] = list(self.sites)
            binds.append(bindparam("sites", expanding=True))
        return sql, params, binds


def _rows(sql: str, params: dict | None = None, binds=()) -> list[dict]:
    statement = text(sql)
    if binds:
        statement = statement.bindparams(*binds)
    result = db.session.execute(statement, params or {})
    return [dict(row._mapping) for row in result]


def _is_mssql() -> bool:
    return db.engine.url.get_backend_name().startswith("mssql")


# --- the data's shape -------------------------------------------------------------

def date_bounds() -> tuple[date | None, date | None]:
    row = _rows(f"SELECT MIN([Order Date]) AS first, MAX([Order Date]) AS last FROM {QTY}")[0]
    return _as_date(row["first"]), _as_date(row["last"])


def sites() -> list[dict]:
    return _rows(
        f"SELECT DISTINCT [Sold-To] AS code, [Sold-To Name] AS name FROM {QTY} ORDER BY [Sold-To Name]"
    )


def last_load() -> dict:
    """last_success, last_line_update and, once 10 (2026-11-17) has run on O2, last_file: every
    column the view has, so the app doesn't wait on that script."""
    rows = _rows(f"SELECT * FROM {LAST_LOAD}")
    return rows[0] if rows else {"last_success": None, "last_line_update": None, "last_file": None}


def _as_date(value):
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


# --- the main table ------------------------------------------------------------------

def sync_pbo() -> int:
    """Add the subs Medline lists, each with its source, AutoSub and Customer Preferred ones approved
    (14_pbo_sync.sql). Never stops the page from loading."""
    if not _is_mssql():
        return 0
    try:
        added = db.session.execute(text("EXEC [FillKill].[usp_SyncPboSubs]")).scalar() or 0
        db.session.commit()
        return int(added)
    except Exception:  # no access, or the procedure is missing: show the page anyway
        db.session.rollback()
        log.exception("FillKill.usp_SyncPboSubs failed")
        return 0


def qty_rows(scope: Scope) -> list[dict]:
    """Quantities per Medline item, UOM and site (the site since 2026-10-27: each orders for itself)."""
    where, params, binds = scope.where("[Order Date]", "[Sold-To]")
    return _rows(
        f"""SELECT [Medline Item] AS medline_item, [UM] AS um, [Sold-To] AS site,
                   SUM([Total Ordered Qty]) AS ordered, SUM([Total Filled Qty]) AS filled,
                   SUM([Total Killed Qty]) AS killed, SUM([Total PO Line Count]) AS lines
            FROM {QTY} WHERE {where}
            GROUP BY [Medline Item], [UM], [Sold-To]""",
        params, binds,
    )


# --- the item view, kept in memory ----------------------------------------------------------------

# The item view is the slowest read (2026-10-21, O2: ~100 ms, up to 0.3 s when SQL Server compiles it,
# with 330 kill lines; it works over all of them, so it grows with Medline's data), and Main read it
# up to three times a load, the panel, the orders and the Subs page again. It changes only when the
# kill lines load (hourly) or Infor's item data does, so on SQL Server each process keeps all its
# rows and reads them again when the kill lines' "as of" moves, when they're ITEM_CACHE_SECONDS old,
# or when a Medline item asked for isn't among them (killed since). Not kept on SQLite: the tests and
# the dev server change the stand-in tables as they go.
ITEM_CACHE_SECONDS = 600
_item_cache: dict = {"rows": None, "items": frozenset(), "key": None, "at": 0.0}
_item_cache_lock = threading.Lock()


def _read_item_view() -> list[dict]:
    return _rows(f"SELECT * FROM {ITEMS}")


def clear_item_cache() -> None:
    with _item_cache_lock:
        _item_cache.update(rows=None, items=frozenset(), key=None, at=0.0)


def item_view_rows(must_have=()) -> list[dict]:
    """Every row of vw_MedlineFillKillItemCollection (see ITEM_CACHE_SECONDS). ``must_have``: Medline
    items that should be in it; one that isn't has the rows read again. The rows are shared:
    callers must not change them."""
    if not _is_mssql():
        return _read_item_view()
    key = tuple(last_load().values())
    with _item_cache_lock:
        cache = _item_cache
        fresh = (cache["rows"] is not None and cache["key"] == key
                 and monotonic() - cache["at"] < ITEM_CACHE_SECONDS
                 and all(item in cache["items"] for item in must_have))
        if not fresh:
            rows = _read_item_view()
            cache.update(rows=rows, items=frozenset(row["Medline Item"] for row in rows), key=key, at=monotonic())
        return cache["rows"]


def latest_reasons(scope: Scope, items=None) -> dict[str, dict]:
    """Per Medline item, the latest Medline comment on a line inside the scope, with that line's
    date and time. ``items`` limits it to those Medline items."""
    where, params, binds = scope.where("[Order Date]", "[Sold-To]")
    if items is not None:
        where += " AND [Item] IN :items"
        params["items"] = sorted(set(items)) or [""]
        binds.append(bindparam("items", expanding=True))
    rows = _rows(
        f"""SELECT medline_item, comment, reason, reason_date, order_date, order_time FROM (
                SELECT [Item] AS medline_item, [Internal Order Comments from SAP (Z106)] AS comment,
                       [Reason] AS reason, [Reason Date] AS reason_date,
                       [Order Date] AS order_date, [Order Time] AS order_time,
                       ROW_NUMBER() OVER (PARTITION BY [Item]
                                          ORDER BY [Order Date] DESC, [Order Time] DESC,
                                                   [Sales Order #] DESC, [Order Line #] DESC) AS rk
                FROM {LINES} WHERE {where} AND [Reason] IS NOT NULL
            ) AS latest WHERE rk = 1""",
        params, binds,
    )
    return {row.pop("medline_item"): row for row in rows}


def vendor_item_dict(item: VendorItem) -> dict:
    """``sub_id`` None: one without a sub, for its Medline item itself (2026-11-02)."""
    return {
        "vendor_item_id": item.vendor_item_id, "sub_id": item.sub_id, "medline_item": item.item_for,
        "vendor_part": item.vendor_part,
        "vendor": item.vendor, "vendor_id": item.vendor_id, "uom": item.uom, "qoe": item.qoe,
        "manufacturer_part": item.manufacturer_part, "infor_item": item.infor_item, "description": item.description,
        "entered_by": item.entered_by, "create_dt": item.create_dt, "update_dt": item.update_dt,
    }


def sub_dict(sub: Sub, vendor_items=()) -> dict:
    """A sub, with its live vendor items (what can be ordered for it, 2026-10-20)."""
    return {
        "sub_id": sub.sub_id, "medline_item": sub.medline_item, "reference_sku": sub.reference_sku,
        "status": sub.status, "source": sub.source,
        "entered_by": sub.entered_by, "create_dt": sub.create_dt, "update_dt": sub.update_dt,
        "vendor_items": list(vendor_items),
    }


def vendor_items_of(sub_ids) -> dict[int, list[dict]]:
    """Per sub: its live vendor items, oldest first."""
    found: dict[int, list[dict]] = {}
    for chunk in _chunks(sorted(set(sub_ids))):
        for item in db.session.execute(
            select(VendorItem).where(VendorItem.sub_id.in_(chunk), VendorItem.deleted_at.is_(None))
            .order_by(VendorItem.create_dt, VendorItem.vendor_item_id)
        ).scalars():
            found.setdefault(item.sub_id, []).append(vendor_item_dict(item))
    return found


def _sub_dicts(subs) -> list[dict]:
    items = vendor_items_of(s.sub_id for s in subs)
    return [sub_dict(s, items.get(s.sub_id, [])) for s in subs]


def item_vendor_items(medline_items) -> dict[str, list[dict]]:
    """Per Medline item: its live vendor items without a sub (2026-11-02), oldest first: what SCM
    directs the sites to order when no sub nursing approved is available."""
    found: dict[str, list[dict]] = {}
    for chunk in _chunks(sorted(set(medline_items))):
        for item in db.session.execute(
            select(VendorItem).where(VendorItem.sub_id.is_(None), VendorItem.medline_item.in_(chunk),
                                     VendorItem.deleted_at.is_(None))
            .order_by(VendorItem.create_dt, VendorItem.vendor_item_id)
        ).scalars():
            found.setdefault(item.medline_item, []).append(vendor_item_dict(item))
    return found


def subs_for_items(items) -> list[dict]:
    subs = []
    for chunk in _chunks(sorted(set(items))):  # stay well under SQL Server's 2,100 parameters
        subs += db.session.execute(
            select(Sub).where(Sub.medline_item.in_(chunk), Sub.deleted_at.is_(None))
        ).scalars().all()
    return _sub_dicts(subs)


def _range_condition(column, scope: Scope):
    return and_(column >= scope.start, column < scope.end + timedelta(days=1))


def _orders(condition, items=None) -> list[dict]:
    query = select(SubOrder).where(SubOrder.voided_at.is_(None), condition)
    if items is not None:
        query = query.where(SubOrder.medline_item.in_(sorted(set(items)) or [""]))
    return [order_dict(order) for order in db.session.execute(query).scalars()]


def _site_condition(sites):
    """Orders for these sites (2026-10-27); every order, those without a site too, when none are
    chosen."""
    return SubOrder.site.in_(list(sites)) if sites else true()


def orders_in_range(scope: Scope, items=None) -> list[dict]:
    """Non-voided orders dated inside the scope's Fill/Kill dates, for its sites (2026-10-27): the
    main table's Ordering column (S4; 2026-10-20, back from "on or after the first day"), so Ordered
    and No order are about those dates and sites."""
    return _orders(and_(_range_condition(SubOrder.ordered_dt, scope), _site_condition(scope.sites)), items)


def orders_since_start(scope: Scope, items=None) -> list[dict]:
    """Non-voided orders dated on or after the scope's first day, for its sites (2026-10-27): what the
    Dashboard's kill-to-order times look for, the first order after each kill, whenever it came."""
    return _orders(and_(SubOrder.ordered_dt >= scope.start, _site_condition(scope.sites)), items)


FAMILY_COLUMNS = ("Medline Item", "UM", "Customer Item #", "Infor Item")


def family_rows(infor_items, rows=None) -> list[dict]:
    """Every Medline item (and UOM) Medline has killed under these Infor items: their packagings.
    From the item view (``rows``, or item_view_rows()), so only Medline items that have been killed,
    and matched to an Infor item there (by Medline vendor item). Medline's customer item isn't used:
    it isn't always an Infor item number."""
    wanted = {i for i in infor_items if i}
    found: dict[tuple, dict] = {}
    for row in item_view_rows() if rows is None else rows:
        if row.get("Infor Item") in wanted:
            picked = {column: row.get(column) for column in FAMILY_COLUMNS}
            found.setdefault(tuple(picked.values()), picked)
    return list(found.values())


def main_table_inputs(scope: Scope) -> dict:
    """Everything rollup.build_main_rows needs for the scope, including the subs of the Infor
    items' other packagings, for their "approved" signal."""
    qty = qty_rows(scope)
    items = {row["medline_item"] for row in qty}
    every = item_view_rows(must_have=items)
    details = [row for row in every if row["Medline Item"] in items]
    family = family_rows((row.get("Infor Item") for row in details), every)
    subs = subs_for_items(items | {row["Medline Item"] for row in family})
    # An approved sub's comments (a pick's until 2026-10-28): how many and the latest, for its
    # comments icon on Main (2026-10-21), the latest shown under it (2026-10-27).
    latest = _latest_comments("sub", [s["sub_id"] for s in subs if s["status"] == "approved"])
    for sub in subs:
        if sub["status"] == "approved":
            found = latest.get(sub["sub_id"])
            sub["comments"] = found["count"] if found else 0
            sub["latest_comment"] = found
    return {
        "qty_rows": qty,
        "item_rows": details,
        "subs": subs,
        "orders": orders_in_range(scope, items),
        "reasons": latest_reasons(scope),
        "family_rows": family,
        "instructions": instructions_for({row.get("Infor Item") for row in details}, items),
        "item_vendor_items": item_vendor_items(items),
    }


# --- SCM's instructions (2026-10-27) ----------------------------------------------------------

def instruction_dict(row: ItemInstruction) -> dict:
    return {
        "instruction_id": row.instruction_id, "infor_item": row.infor_item, "medline_item": row.medline_item,
        "instruction": row.instruction, "written_by": row.written_by, "written_at": row.written_at,
    }


def instructions_for(infor_items, medline_items) -> list[dict]:
    """Instructions for these Infor items, and those written for these Medline items while Infor had
    none for them, oldest first."""
    infor = sorted({i for i in infor_items if i})
    medline = sorted({i for i in medline_items if i})
    found: dict[int, ItemInstruction] = {}
    for chunk in _chunks(infor):
        for row in db.session.execute(select(ItemInstruction).where(ItemInstruction.infor_item.in_(chunk))).scalars():
            found[row.instruction_id] = row
    for chunk in _chunks(medline):
        for row in db.session.execute(select(ItemInstruction).where(
                ItemInstruction.infor_item.is_(None), ItemInstruction.medline_item.in_(chunk))).scalars():
            found[row.instruction_id] = row
    rows = sorted(found.values(), key=lambda row: (row.written_at, row.instruction_id))
    return [instruction_dict(row) for row in rows]


def instruction_thread(medline_item: str) -> dict:
    """Every instruction for the main table's row of ``medline_item``, newest first: its Infor item's
    (all its Medline items'), or its own when Infor has none."""
    infor = infor_items_of([medline_item]).get(medline_item)
    members = {medline_item} | {row["Medline Item"] for row in family_rows([infor] if infor else [])}
    instructions = instructions_for([infor], members)
    return {"infor_item": infor, "medline_item": medline_item, "instructions": instructions[::-1]}


# --- the item panel --------------------------------------------------------------------

def _chunks(values, size: int = 1000):
    """``values`` in lists of ``size``: SQL Server takes at most 2,100 parameters a statement."""
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _latest_comments(entity: str, ids) -> dict[int, dict]:
    """Per sub or order: its newest comment and how many it has."""
    rows = []
    for chunk in _chunks(ids):
        rows += db.session.execute(
            select(History).where(History.entity == entity, History.entity_id.in_(chunk), History.action == "comment")
            .order_by(History.acted_at, History.history_id)
        ).scalars().all()
    rows.sort(key=lambda row: (row.acted_at, row.history_id))
    found: dict[int, dict] = {}
    for row in rows:
        entry = found.setdefault(row.entity_id, {"count": 0})
        entry.update(count=entry["count"] + 1, comment=row.comment, actor=row.actor, acted_at=row.acted_at)
    return found


def order_dict(order: SubOrder) -> dict:
    """An order as placed: its vendor part, vendor, vendor ID, UOM and QOE are its own. The sub's
    Reference SKU and the vendor item's other numbers are there to find it by (2026-10-20)."""
    sub, item = order.sub, order.vendor_item
    return {
        "order_id": order.order_id, "sub_id": order.sub_id, "vendor_item_id": order.vendor_item_id,
        "medline_item": order.medline_item, "reference_sku": sub.reference_sku if sub else None,
        "site": order.site, "po_number": order.po_number,
        "vendor_part": order.vendor_part,
        "manufacturer_part": item.manufacturer_part if item else None,
        "infor_item": item.infor_item if item else None,
        "quantity": order.quantity, "uom": order.uom, "qoe": order.qoe, "vendor": order.vendor,
        "vendor_id": order.vendor_id,
        "ordered_by": order.ordered_by, "ordered_dt": order.ordered_dt,
        "voided_by": order.voided_by, "voided_at": order.voided_at, "void_reason": order.void_reason,
    }


def _history_dict(row: History, labels: dict[tuple, str]) -> dict:
    """``labels``: what to call each sub or vendor item, by (entity, entity_id)."""
    return {
        "history_id": row.history_id, "entity": row.entity, "entity_id": row.entity_id,
        "medline_item": row.medline_item,
        "label": labels.get((row.entity, row.entity_id)), "action": row.action, "field": row.field,
        "from_value": row.from_value, "to_value": row.to_value, "comment": row.comment,
        "actor": row.actor, "acted_at": row.acted_at,
    }


def _vendor_item_labels(items, *, with_sub: bool = True) -> dict[tuple, str]:
    """A vendor item's History rows are labelled with it, after its sub's Reference SKU when they
    may be read beside other subs' (or "No sub" for one without, 2026-11-02)."""
    return {("vendoritem", i.vendor_item_id): f"{i.sub.reference_sku if i.sub else 'No sub'}: {i.label()}"
            if with_sub else i.label() for i in items}


def item_panel(medline_item: str, scope: Scope) -> dict:
    """The Infor item ``medline_item`` belongs to: every packaging (Medline item) Medline has killed
    under it, with their subs, kill lines in the scope, sub history and orders. A Medline item
    Infor can't place is shown on its own."""
    every = item_view_rows(must_have={medline_item})
    own = [row for row in every if row["Medline Item"] == medline_item]
    infor_items = {row.get("Infor Item") for row in own if row.get("Infor Item")}
    infor = next(iter(infor_items)) if len(infor_items) == 1 else None
    uoms: dict[str, list] = {medline_item: [row.get("UM") or "" for row in own]}
    for row in family_rows([infor] if infor else [], every):
        uoms.setdefault(row["Medline Item"], []).append(row.get("UM") or "")
    uom_lists = {item: sorted(set(u)) for item, u in uoms.items()}
    uoms = {item: "/".join(u) for item, u in uom_lists.items()}
    members = sorted(uoms)

    member_rows = [row for row in every if row["Medline Item"] in uoms]
    details = rollup.merge_item_details(member_rows)
    factors = rollup.each_factors(member_rows)

    every_sub = db.session.execute(
        select(Sub).where(Sub.medline_item.in_(members)).order_by(Sub.create_dt, Sub.sub_id)
    ).scalars().all()
    every_item = db.session.execute(
        select(VendorItem).where(or_(VendorItem.sub_id.in_([s.sub_id for s in every_sub] or [0]),
                                     and_(VendorItem.sub_id.is_(None), VendorItem.medline_item.in_(members))))
    ).scalars().all()
    no_sub = item_vendor_items(members)
    # Deleted ones too, for the history.
    labels = {("sub", s.sub_id): s.label() for s in every_sub} | _vendor_item_labels(every_item)
    subs = [s for s in every_sub if s.deleted_at is None]
    comments = _latest_comments("sub", [s.sub_id for s in subs])
    approvals = _latest_approvals([s.sub_id for s in subs])
    all_subs = [{**d, "latest_comment": comments.get(d["sub_id"]), **approvals.get(d["sub_id"], {})}
                for d in _sub_dicts(subs)]

    where, params, binds = scope.where("[Order Date]", "[Sold-To]")
    params["members"] = members
    binds.append(bindparam("members", expanding=True))
    lines = _rows(
        f"""SELECT [Item] AS medline_item, [Order Date] AS order_date, [Order Time] AS order_time,
                   [Sold-To Name] AS site, [Ship-To Name] AS department, [Ship-To Code] AS ship_to_code,
                   [PO] AS po, [POLine] AS po_line,
                   [Order Qty] AS ordered, [Filled Qty] AS filled, [UM] AS um,
                   [Internal Order Comments from SAP (Z106)] AS comment, [Reason] AS reason,
                   [Reason Date] AS reason_date
            FROM {LINES} WHERE [Item] IN :members AND {where}
            ORDER BY [Order Date] DESC, [Order Time] DESC""",
        params, binds,
    )
    for line in lines:
        line["killed"] = (line["ordered"] or 0) - (line["filled"] or 0)
    # Killed in the range by the main table's own source, the quantity view.
    q_where, q_params, q_binds = scope.where("[Order Date]", "[Sold-To]")
    q_params["members"] = members
    q_binds.append(bindparam("members", expanding=True))
    killed = {row["item"] for row in _rows(
        f"SELECT DISTINCT [Medline Item] AS item FROM {QTY} WHERE [Medline Item] IN :members AND {q_where}",
        q_params, q_binds,
    )}

    packagings = []
    for item in members:
        info = details.get(item, {})
        here = [s for s in all_subs if s["medline_item"] == item]
        others = [s for s in all_subs if s["medline_item"] != item]
        annotated, other_subs = rollup.sibling_signals(here, others, uoms)
        packagings.append({
            "medline_item": item,
            "um": uoms[item],
            "qoe": info.get("item_qoe"),  # eaches per UOM, from Infor's conversion for the Infor item
            # Each UOM with its QOE, for the forms' "for B-D930299Z (BX/25)" (2026-10-21); qoe None if Infor has none.
            "uom_qoes": [{"uom": u, "qoe": factors.get((item, u))} for u in uom_lists[item] if u],
            "customer_item": info.get("customer_item"),
            "consistent": bool(infor) and info.get("customer_item") == infor,
            "description": info.get("description"),
            "killed_in_range": item in killed,
            "subs": annotated,
            "other_subs": other_subs,
            "vendor_items": no_sub.get(item, []),  # without a sub, as SCM directs (2026-11-02)
        })
    # Killed in the range first, then the Infor item's other packagings.
    packagings.sort(key=lambda p: (not p["killed_in_range"], p["medline_item"]))

    # Subs added, reviewed and deleted, and vendor items added and deleted.
    sub_history = db.session.execute(
        select(History).where(
            History.medline_item.in_(members), History.action.in_(("created", "status", "delete")),
            History.entity.in_(("sub", "vendoritem")),
            or_(History.entity == "sub", History.action.in_(("created", "delete"))),
        ).order_by(History.acted_at.desc(), History.history_id.desc())
    ).scalars().all()
    orders = db.session.execute(
        select(SubOrder).where(SubOrder.medline_item.in_(members))
        .order_by(SubOrder.ordered_dt.desc(), SubOrder.order_id.desc())
    ).scalars().all()
    order_comments = _latest_comments("order", [o.order_id for o in orders])

    first = details.get(medline_item) or next(iter(details.values()), {})
    return {
        "infor_item": infor,
        "medline_item": medline_item,
        "instruction": rollup.instruction_summary(instructions_for([infor], members)),
        "details": {
            "infor_item": infor,
            **{field: (first.get(field) if infor else None) for field in rollup.INFOR_FIELDS},
            "manufacturer": first.get("manufacturer"), "mfr_item": first.get("mfr_item"),
            "description": first.get("description"),
        },
        "packagings": packagings,
        "lines": lines,
        "sub_history": [_history_dict(row, labels) for row in sub_history],
        "orders": [{**order_dict(o), "latest_comment": order_comments.get(o.order_id)} for o in orders],
        "latest_reason": rollup.latest_of(latest_reasons(scope, members).values()),
    }


def _latest_approvals(sub_ids) -> dict[int, dict]:
    """Per sub: who last approved it and when."""
    rows = []
    for chunk in _chunks(sub_ids):
        rows += db.session.execute(
            select(History).where(History.entity == "sub", History.entity_id.in_(chunk),
                                  History.action == "status", History.to_value == "approved")
        ).scalars().all()
    rows.sort(key=lambda row: (row.acted_at, row.history_id))
    return {row.entity_id: {"approved_by": row.actor, "approved_at": row.acted_at} for row in rows}


def history(entity: str, entity_id: int) -> list[dict]:
    """One sub's, vendor item's or order's timeline, newest first. A sub's includes its vendor items'
    (2026-10-20), each labelled with the vendor item."""
    condition = and_(History.entity == entity, History.entity_id == entity_id)
    labels = {}
    if entity in ("sub", "vendoritem"):
        items = db.session.execute(select(VendorItem).where(
            VendorItem.sub_id == entity_id if entity == "sub" else VendorItem.vendor_item_id == entity_id
        )).scalars().all()
        labels = _vendor_item_labels(items, with_sub=False)
        if entity == "sub" and items:
            condition = or_(condition, and_(History.entity == "vendoritem",
                                            History.entity_id.in_([i.vendor_item_id for i in items])))
    rows = db.session.execute(
        select(History).where(condition).order_by(History.acted_at.desc(), History.history_id.desc())
    ).scalars().all()
    return [_history_dict(row, labels) for row in rows]


# --- the tables under the main table -----------------------------------------------------

PUNCTUATION = ("-", " ", ".", "/")


def _compact(text: str) -> str:
    text = (text or "").strip().lower()
    for ch in PUNCTUATION:
        text = text.replace(ch, "")
    return text


def _compact_column(column):
    expression = func.lower(column)
    for ch in PUNCTUATION:
        expression = func.replace(expression, ch, "")
    return expression


def infor_items_of(medline_items) -> dict[str, str]:
    """Medline item -> Infor item, from the item view (Medline items Infor can't place are left out)."""
    wanted = {item for item in medline_items if item}
    found: dict[str, str] = {}
    for row in item_view_rows():
        if row["Medline Item"] in wanted and row.get("Infor Item"):
            found.setdefault(row["Medline Item"], row["Infor Item"])
    return found


def _order_stats(sub_ids) -> dict[int, dict]:
    """Per sub: how many orders that aren't voided, and the latest one's date."""
    found = {}
    for chunk in _chunks(sub_ids):
        rows = db.session.execute(
            select(SubOrder.sub_id, func.count(), func.max(SubOrder.ordered_dt))
            .where(SubOrder.sub_id.in_(chunk), SubOrder.voided_at.is_(None)).group_by(SubOrder.sub_id)
        ).all()
        found.update({sub_id: {"orders": count, "last_ordered": last} for sub_id, count, last in rows})
    return found


def subs_library(*, status: str | None = None, source: str | None = None, q: str | None = None,
                 needs_details: bool = False, deleted: bool = False, limit: int | None = LIBRARY_LIMIT) -> list[dict]:
    """Every sub across all items (the Subs page), newest change first, with its vendor items, its
    Infor item, who approved it, and its orders. ``deleted`` shows the deleted ones instead (who,
    when, why); ``needs_details`` keeps those without a vendor item yet; ``limit`` None means all."""
    query = select(Sub).where(Sub.deleted_at.is_not(None) if deleted else Sub.deleted_at.is_(None))
    live_items = select(VendorItem.vendor_item_id).where(VendorItem.sub_id == Sub.sub_id, VendorItem.deleted_at.is_(None))
    if needs_details:
        query = query.where(~live_items.exists())
    if status:
        query = query.where(Sub.status == status)
    if source:
        query = query.where(Sub.source == source)
    if q:
        like = f"%{q.strip().lower()}%"
        conditions = [func.lower(Sub.medline_item).like(like), func.lower(Sub.reference_sku).like(like)]
        item_conditions = [
            func.lower(VendorItem.vendor).like(like), VendorItem.vendor_id.like(like),
            func.coalesce(VendorItem.infor_item, "").like(like), func.lower(VendorItem.vendor_part).like(like),
            func.lower(func.coalesce(VendorItem.description, "")).like(like),
        ]
        bare = _compact(q)
        if bare:  # item numbers also match without dashes, spaces, dots and slashes ("bd930")
            conditions += [_compact_column(column).like(f"%{bare}%") for column in (Sub.medline_item, Sub.reference_sku)]
            item_conditions += [_compact_column(column).like(f"%{bare}%")
                                for column in (VendorItem.vendor_part, VendorItem.manufacturer_part)]
        conditions.append(live_items.where(or_(*item_conditions)).exists())
        query = query.where(or_(*conditions))
    query = query.order_by(Sub.update_dt.desc(), Sub.sub_id.desc())
    subs = db.session.execute(query.limit(limit) if limit else query).scalars().all()
    ids = [s.sub_id for s in subs]
    comments, approvals, orders = _latest_comments("sub", ids), _latest_approvals(ids), _order_stats(ids)
    infor = infor_items_of(s.medline_item for s in subs)
    return [{
        # medline_infor_item: the killed Medline item's Infor item (a vendor item's infor_item is its own)
        **d, "medline_infor_item": infor.get(s.medline_item), "latest_comment": comments.get(s.sub_id),
        "approved_by": None, "approved_at": None, **approvals.get(s.sub_id, {}),
        "orders": 0, "last_ordered": None, **orders.get(s.sub_id, {}),
        "deleted_at": s.deleted_at, "deleted_by": s.deleted_by, "delete_reason": s.delete_reason,
    } for s, d in zip(subs, _sub_dicts(subs))]


def orders_log(start: date, end: date, sites=()) -> list[dict]:
    """Orders dated from ``start`` to ``end``, voided ones included: the orders section on Main,
    whose dates are its own (2026-10-19), so past orders can be looked up there. For ``sites``, the
    table's site filter, when given (2026-10-27)."""
    orders = db.session.execute(
        select(SubOrder).where(SubOrder.ordered_dt >= start, SubOrder.ordered_dt < end + timedelta(days=1),
                               _site_condition(sites))
        .order_by(SubOrder.ordered_dt.desc(), SubOrder.order_id.desc())
    ).scalars().all()
    comments = _latest_comments("order", [o.order_id for o in orders])
    infor = infor_items_of(o.medline_item for o in orders)
    return [{**order_dict(o), "medline_infor_item": infor.get(o.medline_item), "latest_comment": comments.get(o.order_id)}
            for o in orders]


CONTRACT_LIMIT = 15


def _search_terms(q: str) -> list[str]:
    """Words of the search, without LIKE wildcards (they would match anything)."""
    cleaned = "".join(ch for ch in q if ch not in "%_[]")
    return [word for word in cleaned.split() if word]


def _contract_rows(where: str, params: dict) -> list[dict]:
    """Contract lines grouped per vendor item and UOM: the same item on several contracts shows once.

    ``infor_item`` is the 6-digit Infor item number, from item-master lines only ("Special" lines
    have numbers like 1296-DYNJAA04). ``is_mhs`` is "Yes" when any of the contracts is MHS's, and
    ``mhs_contracts`` says how many are.
    """
    rows = _rows(
        f"""SELECT vendor_id, vendor_name, vendor_item, uom, qoe,
                   MAX(manufacturer_number) AS manufacturer_number, MAX(description) AS description,
                   MAX(CASE WHEN item_type = 'Itemmast' THEN infor_item END) AS infor_item,
                   COUNT(*) AS contracts, SUM(CASE WHEN is_mhs = 'Yes' THEN 1 ELSE 0 END) AS mhs_contracts
            FROM {CONTRACTS} WHERE {where}
            GROUP BY vendor_id, vendor_name, vendor_item, uom, qoe
            ORDER BY CASE WHEN vendor_item = CAST(:raw AS VARCHAR(120)) THEN 0 ELSE 1 END,
                     vendor_name, vendor_item, uom""",
        params,
    )
    for row in rows:
        row["is_mhs"] = "Yes" if row["mhs_contracts"] else "No"
    return rows


def _contract_key(row: dict) -> tuple:
    return (row["vendor_id"], row["vendor_item"], row["uom"], row["qoe"])


def contract_lines(q: str, limit: int = CONTRACT_LIMIT) -> list[dict]:
    """Active contract lines for the vendor details (13_contract_search.sql), at most ``limit``.

    Several words, e.g. "930103 chloraprep" (2026-10-19): every word must be in the line's vendor
    item or manufacturer number (without dashes), its Infor item number, its description or its
    vendor's name, or be its UOM ("930103 bx"). Descriptions often run words together
    ("APPLICATORCHLORAPREP10.5ML"), so a word matches anywhere in them. If no line has them all, the words are read as one part number.

    One word: by part number, the word without dashes inside the stripped vendor item or
    manufacturer number, or the Infor item number (exact vendor item first); and if that finds fewer
    than ``limit`` and the word has no digits, by description.

    Parameters are cast to VARCHAR: as NVARCHAR, SQL Server would convert every row's VARCHAR
    column before comparing (about 1 s instead of 0.2 s on 632k lines). Measured 2026-10-19 on
    632k lines: one word 0.2-0.3 s, two words 0.4 s.
    """
    words = _search_terms(q)
    if not words:
        return []
    raw = " ".join(words)
    like = "CAST(:{} AS VARCHAR(120))"
    if len(words) > 1:
        params = {"raw": raw}
        where = []
        for i, word in enumerate(words):
            params[f"p{i}"] = f"%{word.replace('-', '').upper()}%"
            params[f"w{i}"] = f"%{word.upper()}%"
            params[f"i{i}"] = word
            params[f"u{i}"] = word.upper()
            p, w = like.format(f"p{i}"), like.format(f"w{i}")
            where.append(f"([vendor_item_stripped] LIKE {p} OR [manufacturer_number_stripped] LIKE {p}"
                         f" OR UPPER([description]) LIKE {w} OR UPPER([vendor_name]) LIKE {w}"
                         f" OR [infor_item] = {like.format(f'i{i}')} OR UPPER([uom]) = {like.format(f'u{i}')})")
        found = _contract_rows(" AND ".join(where), params)[:limit]
        if found:
            return found
    compact = "".join(words).replace("-", "").upper()
    part = like.format("like")
    found = _contract_rows(
        f"[vendor_item_stripped] LIKE {part} OR [manufacturer_number_stripped] LIKE {part}"
        f" OR [infor_item] = {like.format('raw')}",
        {"raw": raw, "like": f"%{compact}%"},
    )[:limit]
    if len(found) < limit and len(words) == 1 and not any(ch.isdigit() for ch in words[0]):
        seen = {_contract_key(r) for r in found}
        for row in _contract_rows(f"UPPER([description]) LIKE {like.format('w')}",
                                  {"raw": raw, "w": f"%{words[0].upper()}%"}):
            if len(found) >= limit:
                break
            if _contract_key(row) not in seen:
                found.append(row)
    return found


def vendor(vendor_id: str) -> dict | None:
    """An Infor vendor by ID (13_contract_search.sql, vw_Vendor): vendor_id, vendor_name,
    vendor_status. None if Infor has no such vendor."""
    rows = _rows(
        f"""SELECT vendor_id, vendor_name, vendor_status FROM {VENDORS}
            WHERE vendor_id = CAST(:id AS VARCHAR(20))""",
        {"id": vendor_id},
    )
    return rows[0] if rows else None


def uom_aliases() -> dict[str, str]:
    """Infor's UOM for each one typed another way (vw_UomAlias, 13_contract_search.sql; 2026-10-20):
    {"CS": "CA", "VL": "VI", ...}. An external value listed with two Infor UOMs is left out, so it
    stays as typed."""
    found: dict[str, set] = defaultdict(set)
    for row in _rows(f"SELECT external_value, lawson_value FROM {UOM_ALIASES}"):
        external = str(row["external_value"] or "").strip().upper()
        lawson = str(row["lawson_value"] or "").strip().upper()
        if external and lawson and external != lawson:
            found[external].add(lawson)
    return {external: lawson.pop() for external, lawson in found.items() if len(lawson) == 1}


VENDOR_LIMIT = 20


def search_vendors(q: str, limit: int = VENDOR_LIMIT) -> list[dict]:
    """Infor's vendors for a name typed in the vendor details (2026-10-19), at most ``limit``:
    every word must be in the vendor's name, legal name or search name (``*`` inside a word
    stands for anything, e.g. "card*med"); digits alone also find the vendor IDs starting with
    them. Active vendors first, then names starting with the first word."""
    words = [word.upper() for word in _search_terms(q)]
    words = [word for word in words if word.strip("*")]
    if not words:
        return []
    like = "CAST(:{} AS VARCHAR(255))"
    params = {"first": words[0].replace("*", "%") + "%"}
    where = []
    for i, word in enumerate(words):
        params[f"w{i}"] = f"%{word.replace('*', '%')}%"
        w = like.format(f"w{i}")
        where.append(f"(UPPER(vendor_name) LIKE {w} OR UPPER(legal_name) LIKE {w} OR UPPER(search_name) LIKE {w})")
    condition = " AND ".join(where)
    if len(words) == 1 and words[0].isdigit():
        params["id"] = words[0] + "%"
        condition = f"({condition}) OR vendor_id LIKE {like.format('id')}"
    top, tail = (f"TOP ({int(limit)}) ", "") if _is_mssql() else ("", f" LIMIT {int(limit)}")
    return _rows(
        f"""SELECT {top}vendor_id, vendor_name, legal_name, search_name, vendor_status FROM {VENDORS}
            WHERE {condition}
            ORDER BY CASE WHEN vendor_status = 'Active' THEN 0 ELSE 1 END,
                     CASE WHEN UPPER(vendor_name) LIKE {like.format('first')} THEN 0 ELSE 1 END,
                     vendor_name, vendor_id{tail}""",
        params,
    )


def item_exists(medline_item: str) -> bool:
    """Whether Medline has killed this item at least once (subs are only added to such items)."""
    row = _rows(
        f"SELECT CASE WHEN EXISTS (SELECT 1 FROM {QTY} WHERE [Medline Item] = :item) THEN 1 ELSE 0 END AS found",
        {"item": medline_item},
    )[0]
    return bool(row["found"])


# --- the Dashboard ---------------------------------------------------------------------------

def first_kills(scope: Scope) -> dict[str, datetime]:
    """Per Medline item killed in the scope: when its first kill line in the scope was ordered."""
    where, params, binds = scope.where("[Order Date]", "[Sold-To]")
    rows = _rows(
        f"""SELECT [Item] AS item, [Order Date] AS day, MIN([Order Time]) AS at FROM {LINES}
            WHERE {where} GROUP BY [Item], [Order Date]""",
        params, binds,
    )
    found: dict[str, datetime] = {}
    for row in rows:
        day = _as_date(row["day"])
        at = row["at"]
        if isinstance(at, str):
            at = time.fromisoformat(at[:8])
        moment = datetime.combine(day, at or time())
        if row["item"] not in found or moment < found[row["item"]]:
            found[row["item"]] = moment
    return found


def lines_by_day(scope: Scope, by: str) -> list[dict]:
    """Kill lines per order date and reason (by='reason') or site (by='site')."""
    column = {"reason": "[Reason]", "site": "[Sold-To Name]"}[by]
    where, params, binds = scope.where("[Order Date]", "[Sold-To]")
    return _rows(
        f"""SELECT [Order Date] AS day, {column} AS series, COUNT(*) AS lines
            FROM {LINES} WHERE {where}
            GROUP BY [Order Date], {column} ORDER BY [Order Date]""",
        params, binds,
    )


def all_subs() -> list[dict]:
    """Every sub that isn't deleted, with its vendor items (the Dashboard)."""
    return _sub_dicts(db.session.execute(select(Sub).where(Sub.deleted_at.is_(None))).scalars().all())


def sub_history(actions) -> list[dict]:
    """Every History row about subs with one of these actions, oldest first."""
    rows = db.session.execute(
        select(History).where(History.entity == "sub", History.action.in_(tuple(actions)))
        .order_by(History.acted_at, History.history_id)
    ).scalars().all()
    return [_history_dict(row, {}) for row in rows]
