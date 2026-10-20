"""Fill/Kill action rules (app/fillkill/rules.py), with no database."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.fillkill import rules
from app.fillkill.rules import RuleError

NOW = datetime(2026, 10, 13, 14, 0)


def sub(**kwargs):
    base = dict(status="pending_review", is_picked=False, reference_sku="930103")
    return SimpleNamespace(**{**base, **kwargs})


def vendor_item(**kwargs):
    base = dict(vendor_part="B-D930103CSZ", vendor="Medline", vendor_id="1000931", uom="BX", qoe=Decimal("40"),
                manufacturer_part=None, infor_item=None, description=None)
    return SimpleNamespace(**{**base, **kwargs})


def order(**kwargs):
    base = dict(quantity=10, vendor_part="P1", uom="BX", qoe=None, vendor="Medline", vendor_id="1000931",
                ordered_dt=NOW, voided_at=None)
    return SimpleNamespace(**{**base, **kwargs})


def refused(call, *, status=400, says=""):
    with pytest.raises(RuleError) as caught:
        call()
    assert caught.value.status == status
    assert says in caught.value.message
    return caught.value


# --- adding subs ---------------------------------------------------------------------

def test_a_new_sub_is_its_reference_sku_and_a_comment():
    # Nursing enters the Reference SKU alone (2026-10-20); vendor items are the Materials Manager's.
    clean = rules.check_new_sub({"medline_item": " MDS2585H ", "reference_sku": " 88885 ", "comment": "  same glove  ",
                                 "vendor": "ignored", "uom": "ignored"})
    assert clean == {"medline_item": "MDS2585H", "reference_sku": "88885", "comment": "same glove"}
    assert rules.check_new_sub({"medline_item": "M", "reference_sku": "P"})["comment"] is None
    refused(lambda: rules.check_new_sub({"medline_item": "M", "vendor_part": "P"}), says="Reference SKU is required")
    refused(lambda: rules.check_new_sub({"medline_item": "M", "reference_sku": "x" * 101}), says="longer than 100")
    refused(lambda: rules.check_new_sub({"medline_item": "M", "reference_sku": "P", "comment": "x" * 401}),
            says="longer than 400")


# --- vendor items --------------------------------------------------------------------

def test_a_vendor_item_needs_its_part_vendor_vendor_id_and_uom():
    clean = rules.check_new_vendor_item({
        "vendor_part": " B-D930103CSZ ", "vendor": "Medline", "vendor_id": " 1000931 ", "uom": "bx", "qoe": "40",
        "manufacturer_part": "930103", "infor_item": "", "description": "SWABSTICK", "status": "ignored",
    })
    assert clean == {"vendor_part": "B-D930103CSZ", "vendor": "Medline", "vendor_id": "1000931", "uom": "BX",
                     "qoe": Decimal("40.0000"), "manufacturer_part": "930103", "infor_item": None, "description": "SWABSTICK"}
    refused(lambda: rules.check_new_vendor_item({}),
            says="Vendor part, Vendor, Vendor ID (or 0000000: Vendor not available in system) and UOM are required.")
    refused(lambda: rules.check_new_vendor_item({"vendor_part": "P", "vendor": "V", "uom": "BX"}),
            says="Vendor ID (or 0000000: Vendor not available in system) is required.")
    # Infor's vendor ID is digits; 0000000 says Infor has no such vendor (2026-10-19).
    refused(lambda: rules.check_new_vendor_item({"vendor_part": "P", "vendor": "V", "vendor_id": "Cardinal", "uom": "BX"}),
            says="Infor's vendor ID (digits")
    assert rules.check_new_vendor_item({"vendor_part": "P", "vendor": "V", "vendor_id": "0000000", "uom": "BX"})["vendor_id"] == "0000000"


@pytest.mark.parametrize("field, value, says", [
    ("qoe", "0", "more than 0"),
    ("qoe", "abc", "must be a number"),
    ("uom", "TOOLONGUOMX", "longer than 10"),
    ("vendor_part", "x" * 101, "longer than 100"),
])
def test_a_vendor_item_refuses_bad_values(field, value, says):
    data = {"vendor_part": "P", "vendor": "V", "vendor_id": "1000931", "uom": "BX", field: value}
    refused(lambda: rules.check_new_vendor_item(data), says=says)


def test_vendor_item_changes_are_only_the_fields_that_differ():
    item = vendor_item()
    assert rules.check_vendor_item_changes(item, {"uom": "cs", "qoe": "40.0", "vendor": "Medline"}) == {"uom": "CS"}
    assert rules.check_vendor_item_changes(item, {"manufacturer_part": " 930103 ", "infor_item": "100091"}) == {
        "manufacturer_part": "930103", "infor_item": "100091"}
    refused(lambda: rules.check_vendor_item_changes(item, {"qoe": "40", "status": "x"}), says="Nothing to change")
    # What a vendor item needs can't be emptied.
    refused(lambda: rules.check_vendor_item_changes(item, {"uom": " "}), says="UOM is required")
    refused(lambda: rules.check_vendor_item_changes(item, {"vendor_id": ""}), says="Vendor ID (or 0000000")
    assert rules.check_vendor_item_changes(item, {"qoe": ""}) == {"qoe": None}  # QOE may be left out


# --- status and picks ----------------------------------------------------------------

@pytest.mark.parametrize("new", ["approved", "hold", "rejected"])
def test_an_approver_sets_approved_hold_or_rejected(new):
    assert rules.check_status_change(sub(), new) == new


def test_pending_review_is_only_where_a_sub_starts():
    refused(lambda: rules.check_status_change(sub(status="hold"), "pending_review"), says="Status must be one of")
    refused(lambda: rules.check_status_change(sub(status="hold"), "hold"), says="already Hold")


def test_only_an_approved_sub_can_be_picked():
    refused(lambda: rules.check_pick(sub(status="hold")), says="Only an approved sub")
    refused(lambda: rules.check_pick(sub(status="approved", is_picked=True)), status=409)
    rules.check_pick(sub(status="approved"))
    refused(lambda: rules.check_unpick(sub(status="approved")), status=409)


# --- orders --------------------------------------------------------------------------

def test_an_order_needs_a_picked_sub():
    refused(lambda: rules.check_new_order(sub(status="approved"), vendor_item(), {"quantity": 5}, now=NOW),
            status=409, says="isn't picked")


def test_an_order_takes_what_it_is_placed_with_from_the_vendor_item():
    picked = sub(status="approved", is_picked=True)
    clean = rules.check_new_order(picked, vendor_item(), {"quantity": "15", "uom": "EA", "vendor": "Owens"}, now=NOW)
    assert (clean["quantity"], clean["vendor_part"], clean["uom"], clean["qoe"], clean["vendor"], clean["vendor_id"]) == (
        15, "B-D930103CSZ", "BX", Decimal("40"), "Medline", "1000931")
    assert clean["ordered_dt"] is None  # "now", set when saved
    assert rules.check_new_order(picked, vendor_item(qoe=None), {"quantity": 1}, now=NOW)["qoe"] is None


@pytest.mark.parametrize("quantity", [0, -3, "2.5", "", None])
def test_quantity_is_a_whole_number_above_zero(quantity):
    refused(lambda: rules.check_new_order(sub(status="approved", is_picked=True), vendor_item(),
                                          {"quantity": quantity}, now=NOW))


def test_ordered_date_can_be_earlier_but_not_in_the_future():
    picked = sub(status="approved", is_picked=True)
    clean = rules.check_new_order(picked, vendor_item(), {"quantity": 1, "ordered_dt": "2026-10-12T09:15"}, now=NOW)
    assert clean["ordered_dt"] == datetime(2026, 10, 12, 9, 15)
    refused(lambda: rules.check_new_order(picked, vendor_item(), {"quantity": 1, "ordered_dt": "2026-10-14"}, now=NOW),
            says="future")
    refused(lambda: rules.check_new_order(picked, vendor_item(), {"quantity": 1, "ordered_dt": "10/12/2026"}, now=NOW),
            says="must look like")


def test_order_corrections_list_only_what_changed():
    assert rules.check_order_edit(order(), {"quantity": "12", "uom": "BX"}, now=NOW) == {"quantity": 12}
    assert rules.check_order_edit(order(), {"vendor_part": "P2", "qoe": "1"}, now=NOW) == {"vendor_part": "P2", "qoe": Decimal("1.0000")}
    refused(lambda: rules.check_order_edit(order(voided_at=NOW), {"quantity": 1}, now=NOW), status=409)
    refused(lambda: rules.check_order_edit(order(), {"ordered_dt": ""}, now=NOW), says="Ordered date is required")
    refused(lambda: rules.check_order_edit(order(), {"vendor_part": ""}, now=NOW), says="Vendor part is required")
    refused(lambda: rules.check_order_edit(order(), {"vendor_id": " "}, now=NOW),
            says="Vendor ID (or 0000000: Vendor not available in system) is required")


def test_voiding_needs_a_reason_once():
    assert rules.check_void(order(), " entered twice ") == "entered twice"
    refused(lambda: rules.check_void(order(), "  "), says="Reason is required")
    refused(lambda: rules.check_void(order(voided_at=NOW), "again"), status=409)


def test_history_values_are_written_plainly():
    assert rules.display(Decimal("100.0000")) == "100"
    assert rules.display(Decimal("0.5000")) == "0.5"
    assert rules.display(datetime(2026, 10, 13, 9, 5, 30)) == "2026-10-13 09:05"
    assert rules.display(None) is None
    assert rules.clean_vendor_id(" 0000000 ") == "0000000"
