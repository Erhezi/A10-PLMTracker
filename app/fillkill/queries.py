"""Every Fill/Kill read (plan v2 §5.2). Returns plain dicts and lists.

Views are read with SQL (they are never mapped, see models/fillkill.py); the
workflow tables go through the models. The SQL here also runs on SQLite, where
the tests stand in tables with the views' names and columns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import and_, bindparam, func, or_, select, text

from .. import db
from ..models.fillkill import History, Sub, SubOrder

log = logging.getLogger(__name__)

QTY = "[FillKill].[vw_MedlineFillKillQtyAgg]"
ITEMS = "[FillKill].[vw_MedlineFillKillItemCollection]"
LINES = "[FillKill].[vw_MedlineFillKill]"
LAST_LOAD = "[FillKill].[vw_FillKillLastLoad]"
CONTRACTS = "[FillKill].[vw_ContractLineSearch]"

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
    rows = _rows(f"SELECT last_success, last_line_update FROM {LAST_LOAD}")
    return rows[0] if rows else {"last_success": None, "last_line_update": None}


def _as_date(value):
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


# --- the main table ------------------------------------------------------------------

def sync_pbo() -> int:
    """Add Medline PBO subs (14_pbo_sync.sql). Never stops the page from loading."""
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
    where, params, binds = scope.where("[Order Date]", "[Sold-To]")
    return _rows(
        f"""SELECT [Medline Item] AS medline_item, [UM] AS um,
                   SUM([Total Ordered Qty]) AS ordered, SUM([Total Filled Qty]) AS filled,
                   SUM([Total Killed Qty]) AS killed, SUM([Total PO Line Count]) AS lines
            FROM {QTY} WHERE {where}
            GROUP BY [Medline Item], [UM]""",
        params, binds,
    )


def _items_in_scope(scope: Scope) -> tuple[str, dict, list]:
    where, params, binds = scope.where("[Order Date]", "[Sold-To]")
    return f"SELECT DISTINCT [Medline Item] FROM {QTY} WHERE {where}", params, binds


def item_rows(scope: Scope) -> list[dict]:
    items_sql, params, binds = _items_in_scope(scope)
    return _rows(f"SELECT * FROM {ITEMS} WHERE [Medline Item] IN ({items_sql})", params, binds)


def latest_reasons(scope: Scope, medline_item: str | None = None) -> dict[str, dict]:
    """Per item, the latest Medline comment on a line inside the scope."""
    where, params, binds = scope.where("[Order Date]", "[Sold-To]")
    if medline_item is not None:
        where += " AND [Item] = :item"
        params["item"] = medline_item
    rows = _rows(
        f"""SELECT medline_item, comment, reason, reason_date FROM (
                SELECT [Item] AS medline_item, [Internal Order Comments from SAP (Z106)] AS comment,
                       [Reason] AS reason, [Reason Date] AS reason_date,
                       ROW_NUMBER() OVER (PARTITION BY [Item]
                                          ORDER BY [Order Date] DESC, [Order Time] DESC,
                                                   [Sales Order #] DESC, [Order Line #] DESC) AS rk
                FROM {LINES} WHERE {where} AND [Reason] IS NOT NULL
            ) AS latest WHERE rk = 1""",
        params, binds,
    )
    return {row.pop("medline_item"): row for row in rows}


def sub_dict(sub: Sub) -> dict:
    return {
        "sub_id": sub.sub_id, "medline_item": sub.medline_item, "vendor": sub.vendor,
        "vendor_part": sub.vendor_part, "description": sub.description, "uom": sub.uom, "qoe": sub.qoe,
        "status": sub.status, "is_picked": bool(sub.is_picked), "source": sub.source,
        "entered_by": sub.entered_by, "create_dt": sub.create_dt, "update_dt": sub.update_dt,
    }


def subs_for_items(items) -> list[dict]:
    items = sorted(set(items))
    if not items:
        return []
    subs = []
    for start in range(0, len(items), 1000):  # stay well under SQL Server's 2,100 parameters
        chunk = items[start:start + 1000]
        subs += db.session.execute(select(Sub).where(Sub.medline_item.in_(chunk))).scalars().all()
    return [sub_dict(sub) for sub in subs]


def _range_condition(column, scope: Scope):
    return and_(column >= scope.start, column < scope.end + timedelta(days=1))


def orders_in_range(scope: Scope, items=None) -> list[dict]:
    """Non-voided orders with an ordered date inside the scope's dates (Ordering Status, S4)."""
    query = select(SubOrder).where(SubOrder.voided_at.is_(None), _range_condition(SubOrder.ordered_dt, scope))
    if items is not None:
        query = query.where(SubOrder.medline_item.in_(sorted(set(items)) or [""]))
    return [order_dict(order) for order in db.session.execute(query).scalars()]


def main_table_inputs(scope: Scope) -> dict:
    """Everything rollup.build_main_rows needs for the scope."""
    qty = qty_rows(scope)
    items = {row["medline_item"] for row in qty}
    return {
        "qty_rows": qty,
        "item_rows": item_rows(scope),
        "subs": subs_for_items(items),
        "orders": orders_in_range(scope, items),
        "reasons": latest_reasons(scope),
    }


# --- the item panel --------------------------------------------------------------------

def _latest_comments(entity: str, ids) -> dict[int, dict]:
    """Per sub or order: its newest comment and how many it has."""
    ids = list(ids)
    if not ids:
        return {}
    rows = db.session.execute(
        select(History).where(History.entity == entity, History.entity_id.in_(ids), History.action == "comment")
        .order_by(History.acted_at, History.history_id)
    ).scalars().all()
    found: dict[int, dict] = {}
    for row in rows:
        entry = found.setdefault(row.entity_id, {"count": 0})
        entry.update(count=entry["count"] + 1, comment=row.comment, actor=row.actor, acted_at=row.acted_at)
    return found


def order_dict(order: SubOrder) -> dict:
    sub = order.sub
    return {
        "order_id": order.order_id, "sub_id": order.sub_id, "medline_item": order.medline_item,
        "sub_label": sub.vendor_part if sub else None,  # the order has its own vendor
        "sub_vendor": sub.vendor if sub else None,
        "quantity": order.quantity, "uom": order.uom, "qoe": order.qoe, "vendor": order.vendor,
        "ordered_by": order.ordered_by, "ordered_dt": order.ordered_dt,
        "voided_by": order.voided_by, "voided_at": order.voided_at, "void_reason": order.void_reason,
    }


def _history_dict(row: History, labels: dict[int, str]) -> dict:
    return {
        "history_id": row.history_id, "entity": row.entity, "entity_id": row.entity_id,
        "label": labels.get(row.entity_id), "action": row.action, "field": row.field,
        "from_value": row.from_value, "to_value": row.to_value, "comment": row.comment,
        "actor": row.actor, "acted_at": row.acted_at,
    }


def item_panel(medline_item: str, scope: Scope) -> dict:
    """Subs, the kill lines in scope, the pick history and the order history of one item."""
    subs = db.session.execute(
        select(Sub).where(Sub.medline_item == medline_item).order_by(Sub.create_dt, Sub.sub_id)
    ).scalars().all()
    comments = _latest_comments("sub", [s.sub_id for s in subs])
    sub_list = [{**sub_dict(s), "latest_comment": comments.get(s.sub_id)} for s in subs]
    sub_labels = {s.sub_id: s.label() for s in subs}

    picks = db.session.execute(
        select(History).where(
            History.medline_item == medline_item, History.entity == "sub",
            History.action.in_(("created", "status", "pick", "unpick")),
        ).order_by(History.acted_at.desc(), History.history_id.desc())
    ).scalars().all()

    orders = db.session.execute(
        select(SubOrder).where(SubOrder.medline_item == medline_item)
        .order_by(SubOrder.ordered_dt.desc(), SubOrder.order_id.desc())
    ).scalars().all()
    order_comments = _latest_comments("order", [o.order_id for o in orders])

    where, params, binds = scope.where("[Order Date]", "[Sold-To]")
    params["item"] = medline_item
    lines = _rows(
        f"""SELECT [Order Date] AS order_date, [Order Time] AS order_time, [Sold-To Name] AS site,
                   [Ship-To Name] AS department, [PO] AS po, [POLine] AS po_line,
                   [Order Qty] AS ordered, [Filled Qty] AS filled, [UM] AS um,
                   [Internal Order Comments from SAP (Z106)] AS comment, [Reason] AS reason,
                   [Reason Date] AS reason_date, [Is Test] AS is_test
            FROM {LINES} WHERE [Item] = :item AND {where}
            ORDER BY [Order Date] DESC, [Order Time] DESC""",
        params, binds,
    )
    for line in lines:
        line["killed"] = (line["ordered"] or 0) - (line["filled"] or 0)

    items_sql = f"SELECT * FROM {ITEMS} WHERE [Medline Item] = :item"
    return {
        "medline_item": medline_item,
        "item_rows": _rows(items_sql, {"item": medline_item}),
        "subs": sub_list,
        "lines": lines,
        "pick_history": [_history_dict(row, sub_labels) for row in picks],
        "orders": [{**order_dict(o), "latest_comment": order_comments.get(o.order_id)} for o in orders],
    }


def history(entity: str, entity_id: int) -> list[dict]:
    """One sub's or order's timeline, newest first."""
    rows = db.session.execute(
        select(History).where(History.entity == entity, History.entity_id == entity_id)
        .order_by(History.acted_at.desc(), History.history_id.desc())
    ).scalars().all()
    return [_history_dict(row, {}) for row in rows]


# --- the tables under the main table -----------------------------------------------------

def subs_library(*, status: str | None = None, source: str | None = None, q: str | None = None) -> list[dict]:
    """Every sub across all items (the reference library), newest change first."""
    query = select(Sub)
    if status:
        query = query.where(Sub.status == status)
    if source:
        query = query.where(Sub.source == source)
    if q:
        like = f"%{q.strip().lower()}%"
        query = query.where(or_(
            func.lower(Sub.medline_item).like(like), func.lower(Sub.vendor).like(like),
            func.lower(Sub.vendor_part).like(like), func.lower(func.coalesce(Sub.description, "")).like(like),
        ))
    subs = db.session.execute(
        query.order_by(Sub.update_dt.desc(), Sub.sub_id.desc()).limit(LIBRARY_LIMIT)
    ).scalars().all()
    comments = _latest_comments("sub", [s.sub_id for s in subs])
    return [{**sub_dict(s), "latest_comment": comments.get(s.sub_id)} for s in subs]


def orders_log(scope: Scope) -> list[dict]:
    """Orders with an ordered date inside the scope's dates, voided ones included."""
    orders = db.session.execute(
        select(SubOrder).where(_range_condition(SubOrder.ordered_dt, scope))
        .order_by(SubOrder.ordered_dt.desc(), SubOrder.order_id.desc())
    ).scalars().all()
    comments = _latest_comments("order", [o.order_id for o in orders])
    return [{**order_dict(o), "latest_comment": comments.get(o.order_id)} for o in orders]


CONTRACT_LIMIT = 15


def _search_terms(q: str) -> list[str]:
    """Words of the search, without LIKE wildcards (they would match anything)."""
    cleaned = "".join(ch for ch in q if ch not in "%_[]")
    return [word for word in cleaned.split() if word]


def _contract_rows(where: str, params: dict) -> list[dict]:
    """Contract lines grouped per vendor item and UOM: the same item on several contracts shows once."""
    return _rows(
        f"""SELECT vendor_id, vendor_name, vendor_item, uom, qoe,
                   MAX(manufacturer_number) AS manufacturer_number, MAX(description) AS description,
                   MAX(infor_item) AS infor_item, COUNT(*) AS contracts
            FROM {CONTRACTS} WHERE {where}
            GROUP BY vendor_id, vendor_name, vendor_item, uom, qoe
            ORDER BY CASE WHEN vendor_item = CAST(:raw AS VARCHAR(120)) THEN 0 ELSE 1 END,
                     vendor_name, vendor_item, uom""",
        params,
    )


def contract_lines(q: str, limit: int = CONTRACT_LIMIT) -> list[dict]:
    """Active contract lines for "Add sub" (13_contract_search.sql).

    First by part number: the search without spaces or dashes, inside the stripped vendor item or
    manufacturer number (exact vendor item first). If that finds fewer than ``limit`` and a word has
    no digits, then by description: every word must appear. Two simple searches are much faster
    than one with OR. Parameters are cast to VARCHAR: as NVARCHAR, SQL Server would convert every
    row's VARCHAR column before comparing (about 1 s instead of 0.2 s on 632k lines).
    """
    words = _search_terms(q)
    if not words:
        return []
    raw = " ".join(words)
    compact = "".join(words).replace("-", "").upper()
    like = "CAST(:like AS VARCHAR(120))"
    found = _contract_rows(
        f"[vendor_item_stripped] LIKE {like} OR [manufacturer_number_stripped] LIKE {like}",
        {"raw": raw, "like": f"%{compact}%"},
    )[:limit]
    if len(found) < limit and any(not any(ch.isdigit() for ch in word) for word in words):
        params = {"raw": raw, **{f"w{i}": f"%{word.upper()}%" for i, word in enumerate(words)}}
        where = " AND ".join(f"UPPER([description]) LIKE CAST(:w{i} AS VARCHAR(120))" for i in range(len(words)))
        seen = {(r["vendor_id"], r["vendor_item"], r["uom"], r["qoe"]) for r in found}
        for row in _contract_rows(where, params):
            if len(found) >= limit:
                break
            if (row["vendor_id"], row["vendor_item"], row["uom"], row["qoe"]) not in seen:
                found.append(row)
    return found


def item_exists(medline_item: str) -> bool:
    """Whether Medline has killed this item at least once (subs are only added to such items)."""
    row = _rows(
        f"SELECT CASE WHEN EXISTS (SELECT 1 FROM {QTY} WHERE [Medline Item] = :item) THEN 1 ELSE 0 END AS found",
        {"item": medline_item},
    )[0]
    return bool(row["found"])


# --- the Dashboard ---------------------------------------------------------------------------

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
    return [sub_dict(s) for s in db.session.execute(select(Sub)).scalars()]


def sub_history(actions) -> list[dict]:
    """Every History row about subs with one of these actions, oldest first."""
    rows = db.session.execute(
        select(History).where(History.entity == "sub", History.action.in_(tuple(actions)))
        .order_by(History.acted_at, History.history_id)
    ).scalars().all()
    return [_history_dict(row, {}) for row in rows]
