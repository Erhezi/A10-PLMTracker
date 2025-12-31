from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from typing import Callable, Mapping, Sequence

from .prep import (
    apply_inventory_recommended_bin_display,
    apply_setup_action_rules,
    prepare_inventory_setup_rows,
    prepare_par_setup_combined_rows,
    prepare_par_setup_original_rows,
    sort_export_rows,
)

Row = dict[str, object]
PipelineStep = Callable[[list[Row]], list[Row]]


def _inventory_setup_should_highlight(row: Row) -> bool:
    recommended_bin = row.get("recommended_preferred_bin_ri")
    if isinstance(recommended_bin, str) and recommended_bin.strip().upper() == "NEW ITEM":
        return False
    return True


def _par_setup_combined_should_highlight(row: Row) -> bool:
    item_set = row.get("item_set")
    if isinstance(item_set, str):
        return item_set.strip().lower() == "replacement"
    if item_set is None:
        return False
    return str(item_set).strip().lower() == "replacement"

INVENTORY_EXPORT_COLUMNS: list[tuple[str, str]] = [
    ("Stage", "stage"),
    ("Item Group", "item_group"),
    ("Group Type", "group_type"),
    ("Weekly Burn (G. & Loc.)", "weekly_burn_group_location"),
    ("Item", "item"),
    ("Location", "location"),
    ("Location Text", "location_text"),
    ("Company", "company"),
    ("Preferred Bin", "preferred_bin"),
    ("Auto-repl.", "auto_replenishment"),
    ("Active", "active"),
    ("Discon.", "discontinued"),
    ("Current Qty", "current_qty"),
    ("Weekly Burn", "weekly_burn"),
    ("Weeks on Hand", "weeks_on_hand"),
    ("Stock UOM", "stock_uom"),
    ("UOM Conversion", "uom_conversion"),
    ("Buy UOM", "buy_uom"),
    ("Buy UOM Multiplier", "buy_uom_multiplier"),
    ("Transaction UOM", "transaction_uom"),
    ("Transaction UOM Multiplier", "transaction_uom_multiplier"),
    ("Reorder Policy", "reorder_quantity_code"),
    ("Reorder Point", "reorder_point"),
    ("Min Order Qty", "min_order_qty"),
    ("Max Order Qty", "max_order_qty"),
    ("Manufacturer Number", "manufacturer_number"),
    ("90-day PO Qty", "po_90_qty"),
    ("Repl. Item", "replacement_item"),
    ("Location (RI)", "location_ri"),
    ("Location Text (RI)", "location_text_ri"),
    ("Company (RI)", "company_ri"),
    ("Preferred Bin (RI)", "preferred_bin_ri"),
    ("Preferred Bin (Recom.)", "recommended_preferred_bin_ri"),
    ("Auto-repl. (RI)", "auto_replenishment_ri"),
    ("Auto-repl. (Recom.)", "recommended_auto_replenishment_ri"),
    ("Active (RI)", "active_ri"),
    ("Discon. (RI)", "discontinued_ri"),
    ("Current Qty (RI)", "current_qty_ri"),
    ("Weekly Burn (RI)", "weekly_burn_ri"),
    ("Weeks on Hand (RI)", "weeks_on_hand_ri"),
    ("Stock UOM (RI)", "stock_uom_ri"),
    ("UOM Conversion (RI)", "uom_conversion_ri"),
    ("Buy UOM (RI)", "buy_uom_ri"),
    ("Buy UOM Multiplier (RI)", "buy_uom_multiplier_ri"),
    ("Transaction UOM (RI)", "transaction_uom_ri"),
    ("Transaction UOM (Recom.)", "recommended_transaction_uom_ri"),
    ("Transaction UOM Multiplier (RI)", "transaction_uom_multiplier_ri"),
    ("Transaction UOM Multiplier (Recom.)", "recommended_transaction_uom_multiplier_ri"),
    ("Reorder Policy (RI)", "reorder_quantity_code_ri"),
    ("Reorder Policy (Recom.)", "recommended_reorder_quantity_code_ri"),
    ("Reorder Point (RI)", "reorder_point_ri"),
    ("Reorder Point (Recom.)", "recommended_reorder_point_ri"),
    ("Min Order Qty (RI)", "min_order_qty_ri"),
    ("Min Order Qty (Recom.)", "recommended_min_order_qty_ri"),
    ("Max Order Qty (RI)", "max_order_qty_ri"),
    ("Max Order Qty (Recom.)", "recommended_max_order_qty_ri"),
    ("Manufacturer Number (RI)", "manufacturer_number_ri"),
    ("Item Description", "item_description"),
    ("Item Description (RI)", "item_description_ri"),
    ("Record Action", "action"),
    ("Setup Action", "setup_action"),
    ("Notes", "notes"),
]

PAR_EXPORT_COLUMNS: list[tuple[str, str]] = [
    ("Stage", "stage"),
    ("Item Group", "item_group"),
    ("Group Type", "group_type"),
    ("Weekly Burn (G. & Loc.)", "weekly_burn_group_location"),
    ("Item", "item"),
    ("Location", "location"),
    ("Location Text", "location_text"),
    ("Company", "company"),
    ("Preferred Bin", "preferred_bin"),
    ("Auto-repl.", "auto_replenishment"),
    ("Active", "active"),
    ("Discon.", "discontinued"),
    ("Reorder Point", "reorder_point"),
    ("Weekly Demand", "weekly_burn"),
    ("Weeks Reorder", "weeks_reorder"),
    ("Stock UOM", "stock_uom"),
    ("UOM Conversion", "uom_conversion"),
    ("Buy UOM", "buy_uom"),
    ("Buy UOM Multiplier", "buy_uom_multiplier"),
    ("Transaction UOM", "transaction_uom"),
    ("Transaction UOM Multiplier", "transaction_uom_multiplier"),
    ("Reorder Policy", "reorder_quantity_code"),
    ("Min Order Qty", "min_order_qty"),
    ("Max Order Qty", "max_order_qty"),
    ("Manufacturer Number", "manufacturer_number"),
    ("90-day Req Qty", "req_qty_ea"),
    ("Repl. Item", "replacement_item"),
    ("Location (RI)", "location_ri"),
    ("Location Text (RI)", "location_text_ri"),
    ("Company (RI)", "company_ri"),
    ("Preferred Bin (RI)", "preferred_bin_ri"),
    ("Preferred Bin (Recom.)", "recommended_preferred_bin_ri"),
    ("Auto-repl. (RI)", "auto_replenishment_ri"),
    ("Auto-repl. (Recom.)", "recommended_auto_replenishment_ri"),
    ("Active (RI)", "active_ri"),
    ("Discon. (RI)", "discontinued_ri"),
    ("Reorder Point (RI)", "reorder_point_ri"),
    ("Reorder Point (Recom.)", "recommended_reorder_point_ri"),
    ("Weekly Demand (RI)", "weekly_burn_ri"),
    ("Weeks Reorder (RI)", "weeks_reorder_ri"),
    ("Stock UOM (RI)", "stock_uom_ri"),
    ("UOM Conversion (RI)", "uom_conversion_ri"),
    ("Buy UOM (RI)", "buy_uom_ri"),
    ("Buy UOM Multiplier (RI)", "buy_uom_multiplier_ri"),
    ("Transaction UOM (RI)", "transaction_uom_ri"),
    ("Transaction UOM (Recom.)", "recommended_transaction_uom_ri"),
    ("Transaction UOM Multiplier (RI)", "transaction_uom_multiplier_ri"),
    ("Transaction UOM Multiplier (Recom.)", "recommended_transaction_uom_multiplier_ri"),
    ("Reorder Policy (RI)", "reorder_quantity_code_ri"),
    ("Reorder Policy (Recom.)", "recommended_reorder_quantity_code_ri"),
    ("Min Order Qty (RI)", "min_order_qty_ri"),
    ("Min Order Qty (Recom.)", "recommended_min_order_qty_ri"),
    ("Max Order Qty (RI)", "max_order_qty_ri"),
    ("Max Order Qty (Recom.)", "recommended_max_order_qty_ri"),
    ("Manufacturer Number (RI)", "manufacturer_number_ri"),
    ("Item Description", "item_description"),
    ("Item Description (RI)", "item_description_ri"),
    ("Record Action", "action"),
    ("Setup Action", "setup_action"),
    ("Notes", "notes"),
]

PAR_SETUP_COMBINED_EXPORT_COLUMNS: list[tuple[str, str]] = [
    ("Company", "company"),
    ("Inventory Location", "location_ri"),
    ("Inventory Location Name", "location_text"),
    ("Item", "replacement_item"),
    ("Item Manufacturer Number", "manufacturer_number_ri"),
    ("Item.Description", "item_description_ri"),
    ("Min", "recommended_min_order_qty_ri"),
    ("Max", "recommended_max_order_qty_ri"),
    ("ReorderPoint", "recommended_reorder_point_ri"),
    ("UOM Unit Of Measure", "stock_uom_ri"),
    ("BIN Location                        (All New Sequence)", "recommended_preferred_bin_ri"),
    ("Requested update/Action", "setup_action"),
    ("Notes", "notes"),
    ("Current Bin (Repl. Item)", "preferred_bin_ri"),
    ("Current Reorder (Repl. Item)", "reorder_point_ri"),
    ("Item Set", "item_set"),
]

PAR_SETUP_REPLACEMENT_EXPORT_COLUMNS: tuple[tuple[str, str], ...] = tuple(list(PAR_EXPORT_COLUMNS) + [("Item Set", "item_set")])
PAR_SETUP_ORIGINAL_EXPORT_COLUMNS: tuple[tuple[str, str], ...] = tuple(list(PAR_EXPORT_COLUMNS) + [("Item Set", "item_set")])

INVENTORY_SETUP_HEADER_OVERRIDES: dict[str, str] = {
    "company": "Company",
    "location_ri": "InventoryLocation",
    "group_type": "Group Type",
    "replacement_item": "Item",
    "item": " Original Item",
    "recommended_transaction_uom_ri": "DefaultTransactionUOM-Issue UOM",
    "recommended_preferred_bin_ri": "PreferredBin",
    "recommended_min_order_qty_ri": "MinimumOrderQuantity",
    "recommended_max_order_qty_ri": "MaximumOrderQuantity",
    "recommended_reorder_point_ri": "ReorderPoint",
    "recommended_auto_replenishment_ri": "AutomaticPurchaseOrder (True/False)",
    "manufacturer_number_ri": "Item Manufacturer Number",
    "setup_action": "Requested update/Action",
    "notes": "Notes",
    "preferred_bin_ri": "Current PreferredBin (Repl. Item)",
    "min_order_qty_ri": "Current Min (Repl. Item)",
    "max_order_qty_ri": "Current Max (Repl. Item)",
    "reorder_point_ri": "Current Reorder (Repl. Item)",
    "auto_replenishment_ri": "Current Auto-repl. (Repl. Item)",
}

PAR_SETUP_REPLACEMENT_HEADER_OVERRIDES: dict[str, str] = {
    "company": "Company",
    "location_ri": "Inventory Location",
    "location_text": "Inventory Location Name",
    "group_type": "Group Type",
    "replacement_item": "Item",
    "item": " Original Item",
    "manufacturer_number_ri": "Item Manufacturer Number",
    "item_description_ri": "Item.Description",
    "recommended_min_order_qty_ri": "Min",
    "recommended_max_order_qty_ri": "Max",
    "recommended_reorder_point_ri": "ReorderPoint",
    "stock_uom_ri": "UOM Unit Of Measure",
    "recommended_preferred_bin_ri": "BIN Location                        (All New Sequence)",
    "setup_action": "Requested update/Action",
    "notes": "Notes",
    "preferred_bin_ri": "Current Bin (Repl. Item)",
    "reorder_point_ri": "Current Reorder (Repl. Item)",
    "item_set": "Item Set",
}

PAR_SETUP_ORIGINAL_HEADER_OVERRIDES: dict[str, str] = {
    "company": "Company",
    "location": "Inventory Location",
    "location_text": "Inventory Location Name",
    "group_type": "Group Type",
    "item": "Item",
    "manufacturer_number": "Item Manufacturer Number",
    "item_description": "Item.Description",
    "min_order_qty": "Min",
    "max_order_qty": "Max",
    "reorder_point": "ReorderPoint",
    "stock_uom": "UOM Unit Of Measure",
    "preferred_bin": "BIN Location                        (All New Sequence)",
    "setup_action": "Requested update/Action",
    "notes": "Notes",
    "preferred_bin_ri": "Current Bin (Repl. Item)",
    "reorder_point_ri": "Current Reorder (Repl. Item)",
    "replacement_item": "Replacement Item",
    "item_set": "Item Set",
}


@dataclass(frozen=True)
class TableConfig:
    key: str
    sheet_name: str
    columns: Sequence[tuple[str, str]]
    base_pipeline: tuple[PipelineStep, ...] = field(default_factory=tuple)
    highlight_notes: bool = False
    highlight_row_predicate: Callable[[Row], bool] | None = None


@dataclass(frozen=True)
class ColumnMode:
    key: str
    columns: Sequence[tuple[str, str]] | None = None
    header_overrides: Mapping[str, str] = field(default_factory=dict)
    pipeline: tuple[PipelineStep, ...] = field(default_factory=tuple)
    highlight_notes: bool = False
    highlight_row_predicate: Callable[[Row], bool] | None = None


TABLE_CONFIGS: dict[str, TableConfig] = {
    "inventory": TableConfig(
        key="inventory",
        sheet_name="Inventory",
        columns=INVENTORY_EXPORT_COLUMNS,
        base_pipeline=(apply_inventory_recommended_bin_display,),
    ),
    "par": TableConfig(
        key="par",
        sheet_name="Par Locations",
        columns=PAR_EXPORT_COLUMNS,
    ),
}

COLUMN_MODE_REGISTRY: dict[str, ColumnMode] = {
    "inventory_setup": ColumnMode(
        key="inventory_setup",
        header_overrides=INVENTORY_SETUP_HEADER_OVERRIDES,
        pipeline=(
            prepare_inventory_setup_rows,
            partial(apply_setup_action_rules, table="inventory"),
            partial(sort_export_rows, column_mode="inventory_setup"),
        ),
        highlight_notes=True,
        highlight_row_predicate=_inventory_setup_should_highlight,
    ),
    "par_setup_replacement": ColumnMode(
        key="par_setup_replacement",
        columns=PAR_SETUP_REPLACEMENT_EXPORT_COLUMNS,
        header_overrides=PAR_SETUP_REPLACEMENT_HEADER_OVERRIDES,
        pipeline=(
            partial(apply_setup_action_rules, table="par", forced_item_set="Replacement"),
            partial(sort_export_rows, column_mode="par_setup_replacement"),
        ),
        highlight_notes=True,
    ),
    "par_setup_original": ColumnMode(
        key="par_setup_original",
        columns=PAR_SETUP_ORIGINAL_EXPORT_COLUMNS,
        header_overrides=PAR_SETUP_ORIGINAL_HEADER_OVERRIDES,
        pipeline=(
            prepare_par_setup_original_rows,
            partial(
                apply_setup_action_rules,
                table="par",
                forced_setup_action="Replace",
                forced_item_set="Original",
            ),
            partial(sort_export_rows, column_mode="par_setup_original"),
        ),
    ),
    "par_setup_combined": ColumnMode(
        key="par_setup_combined",
        columns=PAR_SETUP_COMBINED_EXPORT_COLUMNS,
        pipeline=(prepare_par_setup_combined_rows,),
        highlight_notes=True,
        highlight_row_predicate=_par_setup_combined_should_highlight,
    ),
}

CUSTOM_EXPORT_MODES: set[str] = {"custom"} | set(COLUMN_MODE_REGISTRY.keys())


__all__ = [
    "COLUMN_MODE_REGISTRY",
    "CUSTOM_EXPORT_MODES",
    "INVENTORY_EXPORT_COLUMNS",
    "PAR_EXPORT_COLUMNS",
    "PAR_SETUP_COMBINED_EXPORT_COLUMNS",
    "TABLE_CONFIGS",
]
