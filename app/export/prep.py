from __future__ import annotations

import string
from decimal import Decimal, InvalidOperation
from typing import Callable, Iterable, Sequence

from app.utility.item_locations import compute_inventory_recommended_preferred_bin

Row = dict[str, object]
PipelineStep = Callable[[list[Row]], list[Row]]

MAX_PREFERRED_BIN_LENGTH = 10

INVENTORY_SETUP_COMPARISONS: tuple[tuple[str, str], ...] = (
    ("transaction_uom_ri", "recommended_transaction_uom_ri"),
    ("reorder_quantity_code_ri", "recommended_reorder_quantity_code_ri"),
    ("min_order_qty_ri", "recommended_min_order_qty_ri"),
    ("max_order_qty_ri", "recommended_max_order_qty_ri"),
    ("auto_replenishment_ri", "recommended_auto_replenishment_ri"),
)


def apply_pipeline(rows: list[Row], steps: Iterable[PipelineStep]) -> list[Row]:
    current = rows
    for step in steps:
        current = step(current)
    return current


def parse_column_selection(param: str | None) -> list[str]:
    if not param:
        return []
    seen: set[str] = set()
    results: list[str] = []
    for part in param.split(","):
        field = part.strip()
        if not field or field in seen:
            continue
        seen.add(field)
        results.append(field)
    return results


def filter_export_columns(
    column_defs: Sequence[tuple[str, str]],
    requested_fields: Sequence[str],
) -> list[tuple[str, str]]:
    if not requested_fields:
        return []
    lookup = {field_name: (header, field_name) for header, field_name in column_defs}
    filtered: list[tuple[str, str]] = []
    for field in requested_fields:
        column = lookup.get(field)
        if column and column not in filtered:
            filtered.append(column)
    return filtered


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _normalize_setup_compare_value(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value.normalize()
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value)).normalize()
        except (InvalidOperation, ValueError):
            return str(value).strip().lower()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        decimal_value = _to_decimal(text)
        if decimal_value is not None:
            return decimal_value.normalize()
        return text.lower()
    decimal_value = _to_decimal(value)
    if decimal_value is not None:
        return decimal_value.normalize()
    return str(value).strip().lower()


def setup_values_match(left, right) -> bool:
    return _normalize_setup_compare_value(left) == _normalize_setup_compare_value(right)


def infer_setup_table(row: dict, explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    if not isinstance(row, dict):
        return None
    if "recommended_transaction_uom_ri" in row or "transaction_uom_ri" in row:
        return "inventory"
    if "recommended_reorder_point_ri" in row:
        return "par"
    return None


def _normalize_boolean_flag(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if not s:
        return None
    if s in {"yes", "y", "true", "t", "1", "active"}:
        return True
    if s in {"no", "n", "false", "f", "0", "inactive"}:
        return False
    return None


def _boolean_values_match(left, right) -> bool:
    l_bool, r_bool = _normalize_boolean_flag(left), _normalize_boolean_flag(right)
    if l_bool is not None and r_bool is not None:
        return l_bool == r_bool
    return setup_values_match(left, right)


def should_mark_update_as_no_action(row: dict, *, table: str | None = None, action_source: str | None = None) -> bool:
    if not isinstance(row, dict):
        return False
    action_raw = action_source if action_source is not None else row.get("action")
    action_key = str(action_raw or "").strip().lower()
    if action_key != "update":
        return False
    context = infer_setup_table(row, explicit=table)
    if context == "inventory":
        comparisons = list(INVENTORY_SETUP_COMPARISONS)
    elif context == "par":
        comparisons = [
            ("reorder_point_ri", "recommended_reorder_point_ri"),
            ("auto_replenishment_ri", "recommended_auto_replenishment_ri"),
        ]
    else:
        return False
    for current_field, recommended_field in comparisons:
        val_cur = row.get(current_field)
        val_rec = row.get(recommended_field)
        if current_field == "auto_replenishment_ri":
            if not _boolean_values_match(val_cur, val_rec):
                return False
        elif not setup_values_match(val_cur, val_rec):
            return False
    return True


def derive_setup_action(row: dict, *, table: str | None = None, action_source: str | None = None) -> str | None:
    if not isinstance(row, dict):
        return None
    raw_action = action_source if action_source is not None else row.get("action")
    if raw_action is None:
        return None
    text = str(raw_action).strip()
    if not text:
        return None
    normalized = text.lower().replace("-", " ").replace("_", " ").strip()
    if normalized == "update" and should_mark_update_as_no_action(row, table=table, action_source=raw_action):
        return "No Action (U)"
    friendly_labels = {
        "update": "Replace",
        "create": "Add",
    }
    friendly = friendly_labels.get(normalized)
    if friendly:
        return friendly
    return text


def assign_setup_action(row: dict, *, table: str | None = None, action_source: str | None = None) -> None:
    if not isinstance(row, dict):
        return
    row["setup_action"] = derive_setup_action(row, table=table, action_source=action_source or row.get("action"))


def apply_setup_action_rules(
    rows: list[Row],
    *,
    table: str | None = None,
    forced_setup_action: str | None = None,
    forced_item_set: str | None = None,
) -> list[Row]:
    if not rows:
        return []

    normalized: list[Row] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        action_raw = row.get("action")
        action_text = str(action_raw or "").strip()
        action_key = action_text.lower().replace("-", " ")
        if action_key in {"mute", "ri only"}:
            continue

        updated = dict(row)
        updated["action"] = action_raw
        updated["setup_action"] = derive_setup_action(updated, table=table, action_source=action_raw)

        if forced_setup_action is not None:
            updated["setup_action"] = forced_setup_action
        if forced_item_set is not None:
            updated["item_set"] = forced_item_set

        normalized.append(updated)

    return normalized


def apply_inventory_replacement_setup_action(rows: list[Row]) -> list[Row]:
    if not rows:
        return []

    processed: list[Row] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        updated = dict(row)
        no_action = True
        for current_field, recommended_field in INVENTORY_SETUP_COMPARISONS:
            val_cur = updated.get(current_field)
            val_rec = updated.get(recommended_field)
            if current_field == "auto_replenishment_ri":
                if not _boolean_values_match(val_cur, val_rec):
                    no_action = False
                    break
            elif not setup_values_match(val_cur, val_rec):
                no_action = False
                break
        discontinued_flag = _normalize_boolean_flag(updated.get("discontinued_ri"))
        
        updated["setup_action"] = "No Action (U)" if (no_action is True and discontinued_flag is False) else "Replace"
        updated["discontinued_ri"] = "No"
        processed.append(updated)

    return processed


def apply_inventory_original_setup_action(rows: list[Row]) -> list[Row]:
    if not rows:
        return []

    processed: list[Row] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        updated = dict(row)
        auto_flag = _normalize_boolean_flag(updated.get("auto_replenishment"))
        discontinued_flag = _normalize_boolean_flag(updated.get("discontinued"))
        updated["setup_action"] = "No Action (U)" if (auto_flag is False and discontinued_flag is True) else "Replace"
        updated["discontinued"] = "Yes"
        updated["notes"] = ""
        processed.append(updated)

    return processed


def apply_inventory_recommended_bin_display(rows: list[Row]) -> list[Row]:
    if not rows:
        return []

    for row in rows:
        if not isinstance(row, dict):
            continue
        current_value = row.get("recommended_preferred_bin_ri")
        if isinstance(current_value, str) and current_value.strip().lower() in {"n.a.", "n.a", "n/a"}:
            continue
        row["recommended_preferred_bin_ri"] = compute_inventory_recommended_preferred_bin(row)
    return rows


def _letter_suffix(index: int) -> str:
    if index < 0:
        return ""
    alphabet = string.ascii_lowercase
    base = len(alphabet)
    result = ""
    idx = index
    while True:
        idx, remainder = divmod(idx, base)
        result = alphabet[remainder] + result
        if idx == 0:
            break
        idx -= 1
    return result or alphabet[0]


def _format_par_original_preferred_bin(row: dict, counters: dict[tuple[str, str], int]) -> str:
    replacement_raw = row.get("replacement_item")
    replacement = str(replacement_raw or "").strip()
    if not replacement:
        return "Now"

    relation = (row.get("item_replace_relation") or "").strip().lower()
    if relation == "many-1":
        key = (
            replacement.lower(),
            str(row.get("group_location") or row.get("location") or "").lower(),
        )
        index = counters.get(key, 0)
        suffix = _letter_suffix(index)
        counters[key] = index + 1
        prefix = "Now"
        sanitized_replacement = replacement.replace(" ", "")
        available = MAX_PREFERRED_BIN_LENGTH - len(prefix) - len(suffix)
        truncated = sanitized_replacement[:available] if available > 0 else ""
        candidate = f"{prefix}{truncated}{suffix}".rstrip()
    else:
        prefix = "Now "
        available = MAX_PREFERRED_BIN_LENGTH - len(prefix)
        truncated = replacement[:available] if available > 0 else ""
        candidate = f"{prefix}{truncated}".rstrip()

    return candidate or "Now"


def prepare_par_setup_original_rows(rows: list[Row]) -> list[Row]:
    if not rows:
        return []

    letter_counters: dict[tuple[str, str], int] = {}
    prepared: list[Row] = []
    for row in rows:
        updated = dict(row)

        action_raw = row.get("action")
        updated["action"] = action_raw
        updated["setup_action"] = derive_setup_action(updated, table="par", action_source=action_raw)

        item_display = str(row.get("item") or "").strip() or "N/A"
        original_bin = str(row.get("preferred_bin") or "").strip() or "N/A"
        updated["notes"] = f"{item_display} currently is in bin {original_bin}"

        updated["preferred_bin"] = _format_par_original_preferred_bin(row, letter_counters)
        prepared.append(updated)

    return prepared


def _sort_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip().lower()
    return str(value)


def sort_export_rows(rows: list[Row], column_mode: str) -> list[Row]:
    if not rows:
        return []

    if column_mode == "inventory_setup":
        key_fields = ("company", "location_ri", "recommended_preferred_bin_ri")
    elif column_mode == "inventory_setup_original":
        key_fields = ("company", "location", "preferred_bin")
    elif column_mode == "par_setup_replacement":
        key_fields = ("company", "location_ri", "recommended_preferred_bin_ri")
    elif column_mode == "par_setup_original":
        key_fields = ("company", "location", "preferred_bin")
    else:
        return rows

    def sort_key(row: dict) -> tuple[str, ...]:
        return tuple(_sort_value(row.get(field)) for field in key_fields)

    return sorted(rows, key=sort_key)


def prepare_inventory_setup_rows(rows: list[Row]) -> list[Row]:
    if not rows:
        return []

    prepared: list[Row] = []
    for row in rows:
        updated = dict(row)
        raw_value = updated.get("recommended_auto_replenishment_ri")
        normalized = str(raw_value).strip().lower() if raw_value is not None else ""
        if normalized == "yes":
            updated["recommended_auto_replenishment_ri"] = "True"
        elif normalized == "no":
            updated["recommended_auto_replenishment_ri"] = "False"
        elif normalized in {"true", "false"}:
            updated["recommended_auto_replenishment_ri"] = normalized.capitalize()
        elif normalized == "tbd":
            updated["recommended_auto_replenishment_ri"] = "TBD"
        else:
            updated["recommended_auto_replenishment_ri"] = "TBD"
        updated["recommended_auto_replenishment"] = "False"
        prepared.append(updated)

    return prepared


def prepare_inventory_setup_combined_rows(rows: list[Row]) -> list[Row]:
    if not rows:
        return []

    normalized_rows = prepare_inventory_setup_rows(rows)

    replacement_rows = apply_inventory_replacement_setup_action(
        apply_setup_action_rules(
            normalized_rows,
            table="inventory",
            forced_item_set="Replacement",
        )
    )
    original_rows = apply_inventory_original_setup_action(
        apply_setup_action_rules(
            normalized_rows,
            table="inventory",
            forced_item_set="Original",
        )
    )

    combined: list[Row] = []

    for row in sort_export_rows(replacement_rows, "inventory_setup"):
        combined.append({
            "company": row.get("company"),
            "location_ri": row.get("location_ri"),
            "replacement_item": row.get("replacement_item"),
            "recommended_transaction_uom_ri": row.get("recommended_transaction_uom_ri"),
            "recommended_preferred_bin_ri": row.get("recommended_preferred_bin_ri"),
            "recommended_min_order_qty_ri": row.get("recommended_min_order_qty_ri"),
            "recommended_max_order_qty_ri": row.get("recommended_max_order_qty_ri"),
            "recommended_reorder_point_ri": row.get("recommended_reorder_point_ri"),
            "recommended_auto_replenishment_ri": row.get("recommended_auto_replenishment_ri"),
            "discontinued_ri": row.get("discontinued_ri"),
            "manufacturer_number_ri": row.get("manufacturer_number_ri"),
            "setup_action": row.get("setup_action"),
            "notes": row.get("notes"),
            "preferred_bin_ri": row.get("preferred_bin_ri"),
            "min_order_qty_ri": row.get("min_order_qty_ri"),
            "max_order_qty_ri": row.get("max_order_qty_ri"),
            "reorder_point_ri": row.get("reorder_point_ri"),
            "auto_replenishment_ri": row.get("auto_replenishment_ri"),
            "item_set": row.get("item_set") or "Replacement",
        })

    for row in sort_export_rows(original_rows, "inventory_setup_original"):
        combined.append({
            "company": row.get("company"),
            "location_ri": row.get("location"),
            "replacement_item": row.get("item"),
            "recommended_transaction_uom_ri": row.get("transaction_uom"),
            "recommended_preferred_bin_ri": row.get("preferred_bin"),
            "recommended_min_order_qty_ri": row.get("min_order_qty"),
            "recommended_max_order_qty_ri": row.get("max_order_qty"),
            "recommended_reorder_point_ri": row.get("reorder_point"),
            "recommended_auto_replenishment_ri": row.get("recommended_auto_replenishment"),
            "discontinued_ri": row.get("discontinued"),
            "manufacturer_number_ri": row.get("manufacturer_number"),
            "setup_action": row.get("setup_action"),
            "notes": row.get("notes"),
            "preferred_bin_ri": row.get("preferred_bin_ri"),
            "min_order_qty_ri": row.get("min_order_qty_ri"),
            "max_order_qty_ri": row.get("max_order_qty_ri"),
            "reorder_point_ri": row.get("reorder_point_ri"),
            "auto_replenishment_ri": row.get("auto_replenishment"),
            "item_set": row.get("item_set") or "Original",
        })

    def _combined_sort_key(entry: dict) -> tuple[str, str, str]:
        return (
            _sort_value(entry.get("company")),
            _sort_value(entry.get("location_ri")),
            _sort_value(entry.get("recommended_preferred_bin_ri")),
        )

    combined.sort(key=_combined_sort_key)
    return combined


def _format_item_reference(replacement_item: object, manufacturer_number: object) -> str:
    replacement_text = str(replacement_item or "").strip()
    manufacturer_text = str(manufacturer_number or "").strip()
    return f"SEE ITEM NO {replacement_text} MFG NO {manufacturer_text}".strip()


def prepare_inventory_item_description_update_original_rows(rows: list[Row]) -> list[Row]:
    if not rows:
        return []

    prepared: list[Row] = []
    seen_items: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue

        item_value = row.get("item")
        item_key = str(item_value or "").strip().casefold()
        if item_key in seen_items:
            continue
        seen_items.add(item_key)

        stage_raw = row.get("stage")
        stage = str(stage_raw or "").strip().lower()
        replacement_text = str(row.get("replacement_item") or "").strip()
        manufacturer_text = str(row.get("manufacturer_number_ri") or "").strip()
        reference_text = _format_item_reference(replacement_text, manufacturer_text)
        reference2 = ""
        description2 = ""

        is_discontinued = "discontinued" in stage or not replacement_text
        if is_discontinued:
            reference2 = 'DISCONTINUED'
            description2 = 'DISCONTINUED'
        elif stage in {"tracking - item transition", "pending clinical readiness"}:
            if replacement_text or manufacturer_text:
                reference2 = reference_text
                description2 = f"DISCONTINUED {reference_text}".strip()

        prepared.append({
            "item_group_export": 1,
            "replacement_item": row.get("item"),
            "stock_uom": row.get("stock_uom"),
            "reference2": reference2,
            "description2": description2,
        })

    return prepared


def prepare_par_setup_combined_rows(rows: list[Row]) -> list[Row]:
    if not rows:
        return []

    replacement_rows = apply_setup_action_rules(rows, table="par")
    original_prepared = prepare_par_setup_original_rows(rows)
    original_rows = apply_setup_action_rules(
        original_prepared,
        table="par",
        forced_setup_action="Replace",
    )

    combined: list[Row] = []

    for row in sort_export_rows(replacement_rows, "par_setup_replacement"):
        combined.append({
            "company": row.get("company"),
            "location_ri": row.get("location_ri"),
            "location_text": row.get("location_text"),
            "replacement_item": row.get("replacement_item"),
            "manufacturer_number_ri": row.get("manufacturer_number_ri"),
            "item_description_ri": row.get("item_description_ri"),
            "recommended_min_order_qty_ri": row.get("recommended_min_order_qty_ri"),
            "recommended_max_order_qty_ri": row.get("recommended_max_order_qty_ri"),
            "recommended_reorder_point_ri": row.get("recommended_reorder_point_ri"),
            "stock_uom_ri": row.get("stock_uom_ri"),
            "recommended_preferred_bin_ri": row.get("recommended_preferred_bin_ri"),
            "action": row.get("action"),
            "setup_action": row.get("setup_action") or derive_setup_action(row, table="par"),
            "notes": row.get("notes"),
            "preferred_bin_ri": row.get("preferred_bin_ri"),
            "reorder_point_ri": row.get("reorder_point_ri"),
            "item_set": "Replacement",
        })

    for row in sort_export_rows(original_rows, "par_setup_original"):
        combined.append({
            "company": row.get("company"),
            "location_ri": row.get("location"),
            "location_text": row.get("location_text"),
            "replacement_item": row.get("item"),
            "manufacturer_number_ri": row.get("manufacturer_number"),
            "item_description_ri": row.get("item_description"),
            "recommended_min_order_qty_ri": row.get("min_order_qty"),
            "recommended_max_order_qty_ri": row.get("max_order_qty"),
            "recommended_reorder_point_ri": row.get("reorder_point"),
            "stock_uom_ri": row.get("stock_uom"),
            "recommended_preferred_bin_ri": row.get("preferred_bin"),
            "action": row.get("action"),
            "setup_action": row.get("setup_action") or derive_setup_action(row, table="par"),
            "notes": row.get("notes"),
            "preferred_bin_ri": row.get("preferred_bin_ri"),
            "reorder_point_ri": row.get("reorder_point_ri"),
            "item_set": "Original",
        })

    def _combined_sort_key(entry: dict) -> tuple[str, str, str]:
        return (
            _sort_value(entry.get("company")),
            _sort_value(entry.get("location_ri")),
            _sort_value(entry.get("recommended_preferred_bin_ri")),
        )

    combined.sort(key=_combined_sort_key)
    return combined


__all__ = [
    "MAX_PREFERRED_BIN_LENGTH",
    "apply_inventory_original_setup_action",
    "apply_inventory_replacement_setup_action",
    "apply_inventory_recommended_bin_display",
    "apply_pipeline",
    "apply_setup_action_rules",
    "assign_setup_action",
    "derive_setup_action",
    "filter_export_columns",
    "parse_column_selection",
    "prepare_inventory_setup_rows",
    "prepare_inventory_setup_combined_rows",
    "prepare_inventory_item_description_update_original_rows",
    "prepare_par_setup_combined_rows",
    "prepare_par_setup_original_rows",
    "setup_values_match",
    "should_mark_update_as_no_action",
    "sort_export_rows",
]
