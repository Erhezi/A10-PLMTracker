from app.utility.item_locations import _annotate_replacement_setups


def test_one_to_one_inventory_simple():
    rows = [
        {
            "item_group": 101,
            "group_location": "LOC-INV",
            "item": "ITEM-A",
            "replacement_item": "ITEM-B",
            "location_type": "Inventory Location",
            "reorder_point": 30,
            "min_order_qty": 5,
            "max_order_qty": 18,
            "uom_conversion": 4,
            "uom_conversion_ri": 3,
            "buy_uom_multiplier": 10,
            "buy_uom_multiplier_ri": 8,
            "transaction_uom_multiplier_ri": 6,
            "reorder_quantity_code": "STD",
        }
    ]

    _annotate_replacement_setups(rows, br_calc_type="simple")

    row = rows[0]
    assert row["item_replace_relation"] == "1-1"
    assert row["BRCalcType"] == "simple"
    assert row["recommended_setup_source"] == "simple-1-1-inventory"
    assert row["recommended_reorder_point_ri"] == 40
    assert row["recommended_min_order_qty_ri"] == 8
    assert row["recommended_max_order_qty_ri"] == 72
    assert row["recommended_reorder_quantity_code_ri"] == "STD"


def test_one_to_one_par_simple():
    rows = [
        {
            "item_group": 202,
            "group_location": "LOC-PAR",
            "item": "ITEM-P",
            "replacement_item": "ITEM-Q",
            "location_type": "Par Location",
            "reorder_point": 15,
            "min_order_qty": 12,
            "max_order_qty": 12,
            "uom_conversion": 4,
            "uom_conversion_ri": 3,
            "buy_uom_multiplier": 10,
            "buy_uom_multiplier_ri": 5,
            "transaction_uom_multiplier_ri": 6,
            "reorder_quantity_code": "PAR",
        }
    ]

    _annotate_replacement_setups(rows, br_calc_type="simple")

    row = rows[0]
    assert row["item_replace_relation"] == "1-1"
    assert row["recommended_setup_source"] == "simple-1-1-par"
    assert row["recommended_reorder_point_ri"] == 20
    assert row["recommended_min_order_qty_ri"] == 12
    assert row["recommended_max_order_qty_ri"] == 8


def test_many_to_one_inventory_simple():
    rows = [
        {
            "item_group": 404,
            "group_location": "LOC-M1",
            "item": "SRC-1",
            "replacement_item": "REPL",
            "location_type": "Inventory Location",
            "reorder_point": 10,
            "min_order_qty": 2,
            "max_order_qty": 5,
            "uom_conversion": 8,
            "uom_conversion_ri": 5,
            "buy_uom_multiplier_ri": 6,
            "transaction_uom_multiplier_ri": 4,
            "reorder_quantity_code": "STD",
            "reorder_quantity_code_ri": "RI-STD",
        },
        {
            "item_group": 404,
            "group_location": "LOC-M1",
            "item": "SRC-2",
            "replacement_item": "REPL",
            "location_type": "Inventory Location",
            "reorder_point": 15,
            "min_order_qty": 4,
            "max_order_qty": 4,
            "uom_conversion": 8,
            "uom_conversion_ri": 5,
            "buy_uom_multiplier_ri": 6,
            "transaction_uom_multiplier_ri": 4,
            "reorder_quantity_code": "STD",
            "reorder_quantity_code_ri": "RI-STD",
        },
    ]

    _annotate_replacement_setups(rows, br_calc_type="simple")

    for row in rows:
        assert row["item_replace_relation"] == "many-1"
        assert row["recommended_setup_source"] == "simple-many-1-inventory"
        assert row["recommended_reorder_point_ri"] == 40
        assert row["recommended_min_order_qty_ri"] == 6
        assert row["recommended_max_order_qty_ri"] == 72
        assert row["recommended_reorder_quantity_code_ri"] == "RI-STD"


def test_many_to_one_par_simple():
    rows = [
        {
            "item_group": 505,
            "group_location": "LOC-M2",
            "item": "SRC-1",
            "replacement_item": "REPL",
            "location_type": "Par Location",
            "reorder_point": 8,
            "min_order_qty": 5,
            "max_order_qty": 25,
            "uom_conversion": 3,
            "uom_conversion_ri": 2,
            "buy_uom_multiplier_ri": 6,
            "transaction_uom_multiplier_ri": 10,
        },
        {
            "item_group": 505,
            "group_location": "LOC-M2",
            "item": "SRC-2",
            "replacement_item": "REPL",
            "location_type": "Par Location",
            "reorder_point": 12,
            "min_order_qty": 3,
            "max_order_qty": 15,
            "uom_conversion": 2,
            "uom_conversion_ri": 2,
            "buy_uom_multiplier_ri": 6,
            "transaction_uom_multiplier_ri": 10,
        },
    ]

    _annotate_replacement_setups(rows, br_calc_type="simple")

    for row in rows:
        assert row["item_replace_relation"] == "many-1"
        assert row["recommended_setup_source"] == "simple-many-1-par"
        assert row["recommended_reorder_point_ri"] == 24
        assert row["recommended_min_order_qty_ri"] == 5
        assert row["recommended_max_order_qty_ri"] == 11


def test_one_to_many_inventory_simple():
    rows = [
        {
            "item_group": 606,
            "group_location": "LOC-1M",
            "item": "SRC",
            "replacement_item": "REPL-1",
            "location_type": "Inventory Location",
            "reorder_point": 20,
            "min_order_qty": 10,
            "max_order_qty": 16,
            "uom_conversion": 6,
            "uom_conversion_ri": 4,
            "buy_uom_multiplier_ri": 6,
            "transaction_uom_multiplier_ri": 5,
            "reorder_quantity_code": "STD",
        },
        {
            "item_group": 606,
            "group_location": "LOC-1M",
            "item": "SRC",
            "replacement_item": "REPL-2",
            "location_type": "Inventory Location",
            "reorder_point": 20,
            "min_order_qty": 10,
            "max_order_qty": 16,
            "uom_conversion": 6,
            "uom_conversion_ri": 3,
            "buy_uom_multiplier_ri": 9,
            "transaction_uom_multiplier_ri": 5,
            "reorder_quantity_code": "STD",
        },
    ]

    _annotate_replacement_setups(rows, br_calc_type="simple")

    first, second = rows
    assert first["item_replace_relation"] == "1-many"
    assert first["recommended_setup_source"] == "simple-1-many-inventory"
    assert first["recommended_reorder_point_ri"] == 15
    assert first["recommended_min_order_qty_ri"] == 6
    assert first["recommended_max_order_qty_ri"] == 48

    assert second["recommended_setup_source"] == "simple-1-many-inventory"
    assert second["recommended_reorder_point_ri"] == 20
    assert second["recommended_min_order_qty_ri"] == 9
    assert second["recommended_max_order_qty_ri"] == 45


def test_one_to_many_par_simple():
    rows = [
        {
            "item_group": 707,
            "group_location": "LOC-1P",
            "item": "SRC",
            "replacement_item": "REPL-1",
            "location_type": "Par Location",
            "reorder_point": 25,
            "min_order_qty": 12,
            "max_order_qty": 24,
            "uom_conversion": 8,
            "uom_conversion_ri": 5,
            "buy_uom_multiplier_ri": 6,
            "transaction_uom_multiplier_ri": 9,
            "reorder_quantity_code": "PAR",
        },
        {
            "item_group": 707,
            "group_location": "LOC-1P",
            "item": "SRC",
            "replacement_item": "REPL-2",
            "location_type": "Par Location",
            "reorder_point": 25,
            "min_order_qty": 12,
            "max_order_qty": 24,
            "uom_conversion": 8,
            "uom_conversion_ri": 4,
            "buy_uom_multiplier_ri": 8,
            "transaction_uom_multiplier_ri": 11,
            "reorder_quantity_code": "PAR",
        },
    ]

    _annotate_replacement_setups(rows, br_calc_type="simple")

    first, second = rows
    assert first["item_replace_relation"] == "1-many"
    assert first["recommended_setup_source"] == "simple-1-many-par"
    assert first["recommended_reorder_point_ri"] == 20
    assert first["recommended_min_order_qty_ri"] == 12
    assert first["recommended_max_order_qty_ri"] == 11

    assert second["recommended_setup_source"] == "simple-1-many-par"
    assert second["recommended_reorder_point_ri"] == 25
    assert second["recommended_min_order_qty_ri"] == 12
    assert second["recommended_max_order_qty_ri"] == 9


def test_one_to_zero_marks_not_applicable():
    rows = [
        {
            "item_group": 808,
            "group_location": "LOC-DISC",
            "item": "DISC-ITEM",
            "replacement_item": None,
            "reorder_quantity_code": "STD",
        }
    ]

    _annotate_replacement_setups(rows, br_calc_type="simple")

    row = rows[0]
    assert row["item_replace_relation"] == "1-0"
    assert row["group_type"] == "1-0"
    assert row["recommended_preferred_bin_ri"] == "N.A."
    assert row["recommended_auto_replenishment_ri"] == "N.A."
    assert row["recommended_reorder_quantity_code_ri"] == "N.A."
    assert row["recommended_transaction_uom_ri"] == "N.A."


def test_relation_rules_preferred_bin_uses_source_bin():
    rows = [
        {
            "item_group": 909,
            "group_location": "LOC-A",
            "item": "SRC-ITEM",
            "replacement_item": "REPL-ITEM",
            "preferred_bin": " SRC-BIN ",
            "location_type": "Inventory Location",
        }
    ]

    _annotate_replacement_setups(rows, br_calc_type="simple")

    assert rows[0]["item_replace_relation"] == "1-1"
    assert rows[0]["recommended_preferred_bin_ri"] == "SRC-BIN"


def test_relation_rules_many_to_one_marks_tbd():
    rows = [
        {
            "item_group": 910,
            "group_location": "LOC-B",
            "item": "SRC-1",
            "replacement_item": "REPL",
            "preferred_bin": "BIN-1",
            "location_type": "Inventory Location",
        },
        {
            "item_group": 910,
            "group_location": "LOC-B",
            "item": "SRC-2",
            "replacement_item": "REPL",
            "preferred_bin": "BIN-2",
            "location_type": "Inventory Location",
        },
    ]

    _annotate_replacement_setups(rows, br_calc_type="simple")

    for row in rows:
        assert row["item_replace_relation"] == "many-1"
        assert row["recommended_preferred_bin_ri"] == "TBD"


def test_action_update_overrides_with_current_preferred_bin_ri():
    rows = [
        {
            "item_group": 911,
            "group_location": "LOC-C",
            "item": "SRC",
            "replacement_item": "REPL",
            "preferred_bin": "SRC-BIN",
            "preferred_bin_ri": "RI-BIN",
            "action": "Update",
            "location_type": "Inventory Location",
        }
    ]

    _annotate_replacement_setups(rows, br_calc_type="simple")

    assert rows[0]["recommended_preferred_bin_ri"] == "RI-BIN"


def test_action_create_behaviour_differs_by_location_type():
    rows = [
        {
            "item_group": 912,
            "group_location": "LOC-D",
            "item": "SRC-INV",
            "replacement_item": "REPL-INV",
            "preferred_bin": "INV-BIN",
            "action": "Create",
            "location_type": "Inventory Location",
        },
        {
            "item_group": 913,
            "group_location": "LOC-E",
            "item": "SRC-PAR",
            "replacement_item": "REPL-PAR",
            "preferred_bin": "PAR-BIN",
            "action": "Create",
            "location_type": "Par Location",
        },
    ]

    _annotate_replacement_setups(rows, br_calc_type="simple")

    assert rows[0]["recommended_preferred_bin_ri"] == "NEW ITEM"
    assert rows[1]["recommended_preferred_bin_ri"] == "PAR-BIN"


def test_blank_preferred_bin_defaults_to_tbd_after_rules():
    rows = [
        {
            "item_group": 914,
            "group_location": "LOC-F",
            "item": "SRC",
            "replacement_item": "REPL",
            "preferred_bin": "   ",
            "location_type": "Inventory Location",
        }
    ]

    _annotate_replacement_setups(rows, br_calc_type="simple")

    assert rows[0]["recommended_preferred_bin_ri"] == "TBD"
