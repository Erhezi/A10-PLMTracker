from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import selectinload

from .. import db
from ..models import now_ny_naive
from ..models.relations import ItemLink, ItemLinkWrike
from ..utility.stage_transition import StageTransitionHelper


@dataclass(slots=True)
class BatchRowKey:
    item: str
    replace_item: Optional[str]

    @classmethod
    def from_payload(cls, payload: dict) -> "BatchRowKey":
        if not isinstance(payload, dict):
            raise ValueError("Each row payload must be an object")
        item = payload.get("item")
        if not item:
            raise ValueError("Row payload missing 'item'")
        replace_item = payload.get("replace_item")
        if isinstance(replace_item, str):
            text = replace_item.strip()
            if text.lower() in {"", "none", "null", "nan"}:
                replace_item = None
            else:
                replace_item = text
        elif replace_item is not None:
            replace_item = str(replace_item)
        return cls(item=str(item), replace_item=replace_item)


@dataclass(slots=True)
class BatchResult:
    item: str
    replace_item: Optional[str]
    success: bool
    message: Optional[str]
    record: Optional[dict]


def _build_row_filters(rows: Iterable[BatchRowKey]):
    clauses = []
    for row in rows:
        if row.replace_item is None:
            clauses.append(and_(ItemLink.item == row.item, ItemLink.replace_item.is_(None)))
        else:
            clauses.append(and_(ItemLink.item == row.item, ItemLink.replace_item == row.replace_item))
    if not clauses:
        return None
    return or_(*clauses)


def _serialize_item_link(record: ItemLink) -> dict:
    wrike = record.wrike or ItemLinkWrike.ensure_for_link(record)
    return {
        "item": record.item,
        "replace_item": record.replace_item,
        "item_group": record.item_group,
        "stage": record.stage,
        "expected_go_live_date": record.expected_go_live_date.isoformat() if record.expected_go_live_date else None,
        "wrike_id1": wrike.wrike_id1,
        "wrike_id2": wrike.wrike_id2,
        "wrike_id3": wrike.wrike_id3,
        "update_dt": record.update_dt.isoformat() if record.update_dt else None,
    }


def resolve_rows(
    payload_rows: Iterable[dict],
) -> tuple[
    list[BatchRowKey],
    dict[tuple[str, Optional[str]], ItemLink],
    dict[tuple[str, Optional[str]], BatchResult],
]:
    rows: List[BatchRowKey] = []
    for raw in payload_rows or []:
        rows.append(BatchRowKey.from_payload(raw))
    if not rows:
        raise ValueError("No rows supplied")

    clause = _build_row_filters(rows)
    if clause is None:
        raise ValueError("Unable to build row filter")

    records = (
        ItemLink.query
        .options(selectinload(ItemLink.wrike))
        .filter(clause)
        .all()
    )

    found_map = {(link.item, link.replace_item): link for link in records}
    missing: dict[tuple[str, Optional[str]], BatchResult] = {}

    for row in rows:
        key = (row.item, row.replace_item)
        if key not in found_map:
            missing[key] = BatchResult(row.item, row.replace_item, False, "Row not found", None)

    return rows, found_map, missing


def apply_stage(rows: Iterable[dict], requested_stage: str) -> list[BatchResult]:
    ordered_rows, record_map, missing = resolve_rows(rows)
    results_map: dict[tuple[str, Optional[str]], BatchResult] = missing.copy()

    if not StageTransitionHelper.is_valid_stage(requested_stage):
        raise ValueError("Invalid stage value")

    for key, record in record_map.items():
        decision = StageTransitionHelper.evaluate_transition(
            record.stage,
            requested_stage,
            replace_item=record.replace_item,
        )
        if not decision.allowed:
            results_map[key] = BatchResult(
                record.item,
                record.replace_item,
                False,
                decision.reason or "Transition blocked",
                _serialize_item_link(record),
            )
            continue

        record.stage = decision.final_stage
        record.update_dt = now_ny_naive()
        ItemLinkWrike.ensure_for_link(record).sync_from_item_link(record)
        results_map[key] = BatchResult(
            record.item,
            record.replace_item,
            True,
            decision.reason,
            _serialize_item_link(record),
        )

    db.session.commit()
    return [
        results_map.get((row.item, row.replace_item), BatchResult(row.item, row.replace_item, False, "Row not found", None))
        for row in ordered_rows
    ]


def _normalize_wrike_value(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if not (value.isdigit() and len(value) == 10):
        raise ValueError("Wrike ID must be exactly 10 digits")
    return value


def apply_wrike(rows: Iterable[dict], field: str, value: str | None) -> list[BatchResult]:
    if field not in {"wrike_id1", "wrike_id2", "wrike_id3"}:
        raise ValueError("Unsupported Wrike field")
    normalized = _normalize_wrike_value(value)
    ordered_rows, record_map, missing = resolve_rows(rows)
    results_map: dict[tuple[str, Optional[str]], BatchResult] = missing.copy()

    for key, record in record_map.items():
        wrike = ItemLinkWrike.ensure_for_link(record)
        setattr(wrike, field, normalized)
        wrike.sync_from_item_link(record)
        record.update_dt = now_ny_naive()
        results_map[key] = BatchResult(
            record.item,
            record.replace_item,
            True,
            None,
            _serialize_item_link(record),
        )

    db.session.commit()
    return [
        results_map.get((row.item, row.replace_item), BatchResult(row.item, row.replace_item, False, "Row not found", None))
        for row in ordered_rows
    ]


def _parse_date(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Invalid date format; use YYYY-MM-DD") from exc


def apply_go_live(rows: Iterable[dict], date_value: str | None) -> list[BatchResult]:
    ordered_rows, record_map, missing = resolve_rows(rows)
    results_map: dict[tuple[str, Optional[str]], BatchResult] = missing.copy()
    parsed_date = _parse_date(date_value)

    for key, record in record_map.items():
        record.expected_go_live_date = parsed_date.date() if parsed_date else None
        record.update_dt = now_ny_naive()
        ItemLinkWrike.ensure_for_link(record).sync_from_item_link(record)
        results_map[key] = BatchResult(
            record.item,
            record.replace_item,
            True,
            None,
            _serialize_item_link(record),
        )

    db.session.commit()
    return [
        results_map.get((row.item, row.replace_item), BatchResult(row.item, row.replace_item, False, "Row not found", None))
        for row in ordered_rows
    ]


def summarize_results(results: Iterable[BatchResult]) -> dict:
    results_list = list(results)
    successes = sum(1 for r in results_list if r.success)
    failures = len(results_list) - successes
    count_deleted = db.session.query(ItemLink).filter(ItemLink.stage == "Deleted").count()
    return {
        "status": "ok" if failures == 0 else "partial",
        "success": successes,
        "failed": failures,
        "count_deleted": count_deleted,
        "results": [
            {
                "item": r.item,
                "replace_item": r.replace_item,
                "success": r.success,
                "message": r.message,
                "record": r.record,
            }
            for r in results_list
        ],
    }
