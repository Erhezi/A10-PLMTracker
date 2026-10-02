import copy
import io

import pytest
from flask import Flask
from openpyxl import load_workbook
from werkzeug.exceptions import BadRequest

from app.dashboard import routes
from app.export.prep import (
    derive_item_description_update,
    prepare_inventory_item_description_update_original_rows,
)


INVENTORY_ROWS = [
    {
        "stage": "Tracking - Item Transition",
        "item_group": 177,
        "item": "ORIG-1",
        "replacement_item": "REPL-1",
        "manufacturer_number_ri": "MFG-1",
        "location": "LOC1",
        "group_location": "LOC1",
        "location_type": "Inventory Location",
        "action": "Update",
    },
    {
        "stage": "Tracking - Discontinued",
        "item_group": 186,
        "item": "ORIG-2",
        "replacement_item": None,
        "manufacturer_number_ri": None,
        "location": "LOC2",
        "group_location": "LOC2",
        "location_type": "Inventory Location",
        "action": "Update",
    },
]


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            {"stage": "Tracking - Item Transition", "replacement_item": "R1", "manufacturer_number_ri": "M1"},
            ("SEE ITEM NO R1 MFG NO M1", "DISCONTINUED SEE ITEM NO R1 MFG NO M1"),
        ),
        (
            {"stage": "Pending Clinical Readiness", "replacement_item": "R2", "manufacturer_number_ri": None},
            ("SEE ITEM NO R2 MFG NO", "DISCONTINUED SEE ITEM NO R2 MFG NO"),
        ),
        (
            {"stage": "Tracking - Discontinued", "replacement_item": "R3", "manufacturer_number_ri": "M3"},
            ("DISCONTINUED", "DISCONTINUED"),
        ),
        (
            {"stage": "Tracking - Item Transition", "replacement_item": "  ", "manufacturer_number_ri": "M4"},
            ("DISCONTINUED", "DISCONTINUED"),
        ),
        (
            {"stage": "Something Else", "replacement_item": "R5", "manufacturer_number_ri": "M5"},
            ("", ""),
        ),
    ],
)
def test_derive_item_description_update(row, expected):
    assert derive_item_description_update(row) == expected


def test_description_update_preset_matches_table_values():
    preset_rows = prepare_inventory_item_description_update_original_rows(copy.deepcopy(INVENTORY_ROWS))
    for source, exported in zip(INVENTORY_ROWS, preset_rows):
        assert (exported["reference2"], exported["description2"]) == derive_item_description_update(source)


def test_filtered_inventory_rows_include_reference2_and_description2(monkeypatch):
    monkeypatch.setattr(routes, "build_location_pairs", lambda **kwargs: copy.deepcopy(INVENTORY_ROWS))
    app = Flask(__name__)

    with app.test_request_context("/dashboard/api/inventory"):
        rows = routes._filtered_inventory_rows({}, apply_filters=False)

    assert rows[0]["reference2"] == "SEE ITEM NO REPL-1 MFG NO MFG-1"
    assert rows[0]["description2"] == "DISCONTINUED SEE ITEM NO REPL-1 MFG NO MFG-1"
    assert rows[1]["reference2"] == "DISCONTINUED"
    assert rows[1]["description2"] == "DISCONTINUED"


def _export(monkeypatch, table_key, query):
    monkeypatch.setattr(
        routes,
        "_filtered_inventory_rows",
        lambda args, *, apply_filters=True: [
            {**copy.deepcopy(row), "reference2": "REF", "description2": "DESC"} for row in INVENTORY_ROWS
        ],
    )
    monkeypatch.setattr(
        routes,
        "_filtered_par_rows",
        lambda args, *, apply_filters=True: copy.deepcopy(INVENTORY_ROWS),
    )
    app = Flask(__name__)
    with app.test_request_context(f"/dashboard/export/{table_key}?{query}"):
        response = routes.export_table(table_key)
        response.direct_passthrough = False
        workbook = load_workbook(io.BytesIO(response.get_data()))
    sheet = workbook.active
    return [cell.value for cell in sheet[1]]


def test_custom_inventory_export_accepts_item_group_reference2_description2(monkeypatch):
    headers = _export(
        monkeypatch,
        "inventory",
        "row_scope=all&column_mode=custom&columns=item_group,item,reference2,description2",
    )
    assert headers == ["Item Group", "Item", "Reference2", "Description2"]


def test_custom_par_export_accepts_item_group(monkeypatch):
    headers = _export(monkeypatch, "par", "row_scope=all&column_mode=custom&columns=item_group,item")
    assert headers == ["Item Group", "Item"]


@pytest.mark.parametrize(
    ("table_key", "field"),
    [
        ("inventory", "item_set"),
        ("inventory", "recommended_auto_replenishment"),
        ("inventory", "item_group_export"),
        ("par", "item_set"),
    ],
)
def test_custom_export_rejects_preset_only_columns(monkeypatch, table_key, field):
    with pytest.raises(BadRequest):
        _export(monkeypatch, table_key, f"row_scope=all&column_mode=custom&columns=item,{field}")
