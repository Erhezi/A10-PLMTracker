from app.utility.item_locations import _annotate_replacement_setups


def test_annotate_replacement_setups_one_to_one_same_uom():
    rows = [
        {
            "item_group": 101,
            "group_location": "LOC-1",
            "item": "ITEM-A",
            "replacement_item": "ITEM-B",
            "reorder_point": 30,
            "min_order_qty": 5,
            "max_order_qty": 60,
            "buy_uom_multiplier": 10,
            "buy_uom_multiplier_ri": 10,
        }
    ]

    _annotate_replacement_setups(rows)

    assert rows[0]["item_replace_relation"] == "1-1"
    assert rows[0]["recommended_reorder_point_ri"] == 30
    assert rows[0]["recommended_min_order_qty_ri"] == 10
    assert rows[0]["recommended_max_order_qty_ri"] == 60
    assert rows[0]["recommended_setup_source"] == "uom-match"


def test_annotate_replacement_setups_one_to_one_adjusted_uom():
    rows = [
        {
            "item_group": 202,
            "group_location": "LOC-2",
            "item": "ITEM-X",
            "replacement_item": "ITEM-Y",
            "reorder_point": 30,
            "min_order_qty": 10,
            "max_order_qty": 60,
            "buy_uom_multiplier": 10,
            "buy_uom_multiplier_ri": 8,
        }
    ]

    _annotate_replacement_setups(rows)

    assert rows[0]["item_replace_relation"] == "1-1"
    assert rows[0]["recommended_reorder_point_ri"] == 32
    assert rows[0]["recommended_min_order_qty_ri"] == 8
    assert rows[0]["recommended_max_order_qty_ri"] == 64
    assert rows[0]["recommended_setup_source"] == "uom-adjust"


def test_annotate_replacement_setups_missing_replacement_multiplier():
    rows = [
        {
            "item_group": 303,
            "group_location": "LOC-3",
            "item": "ITEM-M",
            "replacement_item": "ITEM-N",
            "reorder_point": 15,
            "min_order_qty": 12,
            "max_order_qty": 45,
            "buy_uom_multiplier": 10,
            "buy_uom_multiplier_ri": None,
        }
    ]

    _annotate_replacement_setups(rows)

    assert rows[0]["item_replace_relation"] == "1-1"
    assert rows[0]["recommended_reorder_point_ri"] == 15
    assert rows[0]["recommended_min_order_qty_ri"] == 12
    assert rows[0]["recommended_max_order_qty_ri"] == 45
    assert rows[0]["recommended_setup_source"] == "copy"


def test_annotate_replacement_setups_many_to_one_aggregates_recommendations():
    rows = [
        {
            "item_group": 404,
            "group_location": "LOC-4",
            "item": "ITEM-1",
            "replacement_item": "ITEM-Z",
            "reorder_point": 10,
            "min_order_qty": 2,
            "max_order_qty": 20,
            "buy_uom_multiplier": 1,
            "buy_uom_multiplier_ri": 4,
            "min_order_qty_ri": 4,
            "max_order_qty_ri": 80,
            "reorder_quantity_code": "STD",
        },
        {
            "item_group": 404,
            "group_location": "LOC-4",
            "item": "ITEM-2",
            "replacement_item": "ITEM-Z",
            "reorder_point": 15,
            "min_order_qty": 5,
            "max_order_qty": 50,
            "buy_uom_multiplier": 1,
            "buy_uom_multiplier_ri": 4,
            "min_order_qty_ri": 4,
            "max_order_qty_ri": 80,
            "reorder_quantity_code": "STD",
        },
    ]

    _annotate_replacement_setups(rows)

    assert rows[0]["item_replace_relation"] == "many-1"
    assert rows[1]["item_replace_relation"] == "many-1"
    assert rows[0]["recommended_reorder_point_ri"] == 24
    assert rows[0]["recommended_min_order_qty_ri"] == 4
    assert rows[0]["recommended_max_order_qty_ri"] == 72
    assert rows[0]["recommended_setup_source"] == "aggregate-many-1"
    assert rows[1]["recommended_reorder_point_ri"] == 24
    assert rows[1]["recommended_min_order_qty_ri"] == 4
    assert rows[1]["recommended_max_order_qty_ri"] == 72
    assert rows[1]["recommended_setup_source"] == "aggregate-many-1"
