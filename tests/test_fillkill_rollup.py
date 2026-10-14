"""Main-table assembly (app/fillkill/rollup.py): sums, details, statuses and the Needs filter."""

import pytest

from app.fillkill import rollup


def qty(item, um, ordered, filled, lines=1):
    return {"medline_item": item, "um": um, "ordered": ordered, "filled": filled,
            "killed": ordered - filled, "lines": lines}


def sub(sub_id, item, status, picked=False):
    return {"sub_id": sub_id, "medline_item": item, "vendor": "V", "vendor_part": f"P{sub_id}",
            "status": status, "is_picked": picked, "uom": None, "qoe": None}


def test_quantities_add_up_across_dates_and_sites_but_never_across_uoms():
    rows = [
        qty("A", "BX", 10, 0, lines=2),   # White Plains, 9/28
        qty("A", "BX", 5, 1, lines=1),    # test site, 9/28
        qty("A", "CS", 2, 0, lines=1),    # same item, another UOM
        qty("B", "EA", 3, 3, lines=1),
    ]
    summed = rollup.sum_quantities(rows)
    assert summed["A"] == {
        "by_uom": [
            {"uom": "BX", "ordered": 15, "filled": 1, "killed": 14},
            {"uom": "CS", "ordered": 2, "filled": 0, "killed": 2},
        ],
        "lines": 4,
    }
    assert summed["B"]["lines"] == 1


def test_item_details_merge_and_say_when_rows_disagree():
    details = rollup.merge_item_details([
        {"Medline Item": "A", "Item Description": "GLOVE", "Customer Item #": "108176",
         "Infor Item": "108176", "Infor Item Consistency": 1},
        {"Medline Item": "A", "Item Description": "GLOVE", "Customer Item #": "108176",
         "Infor Item": "999999", "Infor Item Consistency": 0},
        {"Medline Item": "B", "Item Description": "CUP", "Customer Item #": "100339",
         "Infor Item": None, "Infor Item Consistency": 0},
    ])
    assert details["A"]["description"] == "GLOVE"
    assert details["A"]["infor_item"] == "108176 / 999999"
    assert details["A"]["varies"] == ["infor_item"]
    assert details["A"]["infor_consistent"] is False
    assert details["B"]["infor_consistent"] is False
    assert details["B"]["infor_item"] is None


@pytest.mark.parametrize("counts, has_pick, ordered, expected", [
    ({}, False, False, ["needs_subs"]),
    ({"rejected": 2}, False, False, ["needs_subs"]),
    ({"hold": 1}, False, False, []),
    ({"pending_review": 1}, False, False, ["needs_review"]),
    ({"approved": 1}, False, False, ["needs_pick"]),
    ({"approved": 1}, True, False, ["needs_order"]),
    ({"approved": 1, "pending_review": 1}, True, False, ["needs_review", "needs_order"]),
    ({"approved": 1}, True, True, ["ordered"]),
    ({"rejected": 1}, False, True, ["needs_subs", "ordered"]),  # ordered from a pick since rejected
])
def test_needs_flags(counts, has_pick, ordered, expected):
    assert rollup.needs_flags(counts, has_pick=has_pick, ordered=ordered) == expected


def test_main_rows():
    rows = rollup.build_main_rows(
        qty_rows=[qty("A", "BX", 10, 0, lines=3), qty("B", "EA", 4, 0, lines=1), qty("C", "EA", 1, 0, lines=3)],
        item_rows=[{"Medline Item": "A", "Item Description": "GLOVE", "Infor Item Consistency": 1}],
        subs=[sub(1, "A", "approved", picked=True), sub(2, "A", "rejected"), sub(3, "B", "pending_review"),
              sub(4, "Z", "approved")],  # Z isn't killed in the range: not shown
        orders=[{"medline_item": "A", "order_id": 9}],
        reasons={"A": {"comment": "MBO - ERD is 11/30/2026", "reason": "MBO", "reason_date": "2026-11-30"}},
    )
    assert [row["medline_item"] for row in rows] == ["A", "B", "C"]  # no customer items: by Medline item
    a, b, c = rows
    assert a["description"] == "GLOVE" and a["infor_consistent"] is True
    assert a["subs_status"] == {"approved": 1, "hold": 0, "pending_review": 0, "rejected": 1}
    assert [p["sub_id"] for p in a["picks"]] == [1]
    assert (a["ordering_status"], a["orders_in_range"], a["needs"]) == ("ordered", 1, ["ordered"])
    assert a["latest_reason"]["reason"] == "MBO"
    assert (b["ordering_status"], b["needs"]) == ("no order", ["needs_review"])
    assert (c["description"], c["needs"], c["latest_reason"]) == (None, ["needs_subs"], None)
    assert rollup.needs_counts(rows) == {
        "all": 3, "needs_subs": 1, "needs_review": 1, "needs_pick": 0, "needs_order": 0, "ordered": 1,
    }
    assert [r["medline_item"] for r in rollup.most_killed(rows, 2)] == ["A", "C"]  # 3 lines each; A killed more


def test_rows_sort_by_customer_item_then_medline_item_then_description():
    rows = rollup.build_main_rows(
        qty_rows=[qty("M3", "EA", 1, 0, lines=9), qty("M1", "EA", 1, 0), qty("M2", "EA", 1, 0), qty("M0", "EA", 1, 0)],
        item_rows=[
            {"Medline Item": "M1", "Customer Item #": "200000", "Item Description": "B"},
            {"Medline Item": "M2", "Customer Item #": "100000", "Item Description": "Z"},
            {"Medline Item": "M3", "Customer Item #": "100000", "Item Description": "A"},
            # M0 has no customer item: last
        ],
        subs=[], orders=[], reasons={},
    )
    assert [(r["customer_item"], r["medline_item"]) for r in rows] == [
        ("100000", "M2"), ("100000", "M3"), ("200000", "M1"), (None, "M0"),
    ]


def test_infor_details_are_carried_for_the_panel_and_search():
    details = rollup.merge_item_details([{
        "Medline Item": "MDS2585H", "Item.Description": "GLOVE EXM MED", "Item.LongDescription": "GLOVE EXAM MEDIUM",
        "Item.Active": "Yes", "CommodityCode": "4213-22-03", "CommodityCode.Description": "MEDICAL EXAM GLOVES",
    }])["MDS2585H"]
    assert (details["long_description"], details["infor_active"],
            details["commodity_code"], details["commodity_description"]) == (
        "GLOVE EXAM MEDIUM", "Yes", "4213-22-03", "MEDICAL EXAM GLOVES",
    )
    assert "infor_description" not in details  # Infor's short description isn't used


# --- one Infor item, several Medline items (other packagings) --------------------------------

FAMILY = [
    {"Medline Item": "JLC-EA", "UM": "EA", "Customer Item #": "111848"},
    {"Medline Item": "JLC-BX", "UM": "BX", "Customer Item #": "111848"},
    {"Medline Item": "OTHER", "UM": "EA", "Customer Item #": "999999"},
]
ITEM_ROWS = [
    {"Medline Item": "JLC-EA", "UM": "EA", "Customer Item #": "111848", "Item.UOMConversion": 1},
    {"Medline Item": "JLC-BX", "UM": "BX", "Customer Item #": "111848", "Item.UOMConversion": 20},
    {"Medline Item": "OTHER", "UM": "EA", "Customer Item #": "999999"},  # no Infor conversion
]


def family_sub(sub_id, item, status, part="CARD-1", vendor="Cardinal"):
    return {**sub(sub_id, item, status), "vendor": vendor, "vendor_part": part}


def test_infor_item_groups_add_packagings_up_in_eaches():
    rows = rollup.build_main_rows(
        qty_rows=[qty("JLC-EA", "EA", 186, 0, lines=9), qty("JLC-BX", "BX", 15, 0, lines=3), qty("OTHER", "EA", 4, 0)],
        item_rows=ITEM_ROWS, subs=[], orders=[{"medline_item": "JLC-BX"}], reasons={}, family_rows=FAMILY,
    )
    assert [(r["medline_item"], r["quantities"][0]["each"]) for r in rows] == [
        ("JLC-BX", 20.0), ("JLC-EA", 1.0), ("OTHER", None),
    ]
    groups = rollup.infor_groups(rows)
    assert groups["111848"] == {
        "customer_item": "111848", "medline_items": ["JLC-BX", "JLC-EA"], "lines": 12, "complete": True,
        "ordered_each": 486.0, "killed_each": 486.0, "filled_each": 0.0, "ordered": True,
    }
    assert groups["999999"]["complete"] is False  # no conversion: eaches leave it out


def test_a_sub_approved_on_another_packaging_is_signalled():
    rows = rollup.build_main_rows(
        qty_rows=[qty("JLC-BX", "BX", 15, 0)],  # only the BX packaging is killed in the range
        item_rows=ITEM_ROWS,
        subs=[family_sub(1, "JLC-EA", "approved"),                    # approved on the EA packaging
              family_sub(2, "JLC-EA", "rejected", part="CARD-2"),     # rejected there: no signal
              family_sub(3, "JLC-BX", "pending_review", part="card-1", vendor="CARDINAL")],  # same sub, here
        orders=[], reasons={}, family_rows=FAMILY,
    )
    [row] = rows
    assert row["approved_other_packagings"] == [
        {"medline_item": "JLC-EA", "um": "EA", "vendor": "Cardinal", "vendor_part": "CARD-1", "sub_id": 1},
    ]
    assert row["needs"] == ["needs_review"]  # still needs its own review here

    rows = rollup.build_main_rows(
        qty_rows=[qty("JLC-BX", "BX", 15, 0)], item_rows=ITEM_ROWS,
        subs=[family_sub(1, "JLC-EA", "approved"), family_sub(3, "JLC-BX", "approved")],
        orders=[], reasons={}, family_rows=FAMILY,
    )
    assert rows[0]["approved_other_packagings"] == []  # approved here too: nothing to flag


def test_panel_signals_for_this_items_subs_and_the_other_packagings_subs():
    here = [family_sub(3, "JLC-BX", "pending_review"), family_sub(4, "JLC-BX", "approved", part="OWN-1")]
    siblings = [family_sub(1, "JLC-EA", "approved"), family_sub(2, "JLC-EA", "hold", part="CARD-2"),
                family_sub(5, "JLC-EA", "approved", part="CARD-3")]
    annotated, others = rollup.sibling_signals(here, siblings, {"JLC-EA": "EA"})
    assert [(s["sub_id"], [o["sub_id"] for o in s["approved_elsewhere"]]) for s in annotated] == [(3, [1]), (4, [])]
    assert [(o["sub_id"], o["status"], o["um"]) for o in others] == [(5, "approved", "EA"), (2, "hold", "EA")]
