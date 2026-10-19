"""Fill/Kill action rules (app/fillkill/rules.py), with no database."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.fillkill import rules
from app.fillkill.rules import RuleError

NOW = datetime(2026, 10, 13, 14, 0)


def sub(**kwargs):
    base = dict(status="pending_review", is_picked=False, vendor="Medline", vendor_id=None,
                vendor_part="P1", manufacturer_part=None, infor_item=None, description=None, uom=None, qoe=None)
    return SimpleNamespace(**{**base, **kwargs})


def order(**kwargs):
    base = dict(quantity=10, uom="BX", qoe=None, vendor="Medline", ordered_dt=NOW, voided_at=None)
    return SimpleNamespace(**{**base, **kwargs})


def refused(call, *, status=400, says=""):
    with pytest.raises(RuleError) as caught:
        call()
    assert caught.value.status == status
    assert says in caught.value.message
    return caught.value


# --- adding and editing subs --------------------------------------------------------

def test_a_new_sub_needs_only_its_vendor_part_and_cleans_the_rest():
    clean = rules.check_new_sub({
        "medline_item": " MDS2585H ", "vendor": "Cardinal", "vendor_id": " 1000001 ", "vendor_part": "88885",
        "uom": "bx", "qoe": "100", "comment": "  same glove  ",
    })
    assert clean == {
        "medline_item": "MDS2585H", "vendor": "Cardinal", "vendor_id": "1000001", "vendor_part": "88885",
        "manufacturer_part": None, "infor_item": None, "description": None,
        "uom": "BX", "qoe": Decimal("100.0000"), "comment": "same glove",
    }
    # Nursing enters the vendor part alone; the Materials Manager fills in the rest (2026-10-15).
    assert rules.check_new_sub({"medline_item": "M", "vendor_part": "P"}) == {
        "medline_item": "M", "vendor": None, "vendor_id": None, "vendor_part": "P", "manufacturer_part": None,
        "infor_item": None, "description": None, "uom": None, "qoe": None, "comment": None,
    }
    refused(lambda: rules.check_new_sub({"medline_item": "M", "vendor": "V"}), says="Vendor part is required")
    # The vendor ID is optional; when given, it's Infor's (digits), not a name.
    assert rules.check_new_sub({"medline_item": "M", "vendor": "V", "vendor_id": " ", "vendor_part": "P"})["vendor_id"] is None
    refused(lambda: rules.check_new_sub({"medline_item": "M", "vendor": "V", "vendor_id": "Cardinal", "vendor_part": "P"}),
            says="Infor's vendor ID (digits")


@pytest.mark.parametrize("field, value, says", [
    ("qoe", "0", "more than 0"),
    ("qoe", "abc", "must be a number"),
    ("uom", "TOOLONGUOMX", "longer than 10"),
    ("comment", "x" * 401, "longer than 400"),
])
def test_new_sub_refuses_bad_values(field, value, says):
    data = {"medline_item": "M", "vendor": "V", "vendor_part": "P", field: value}
    refused(lambda: rules.check_new_sub(data), says=says)


def test_changes_are_only_the_fields_asked_for_that_differ():
    details = rules.SUB_DETAIL_FIELDS
    # The vendor part is among the Materials Manager's details: the one ordered (2026-10-19).
    assert rules.check_sub_changes(sub(status="approved"), {"vendor": "Other", "vendor_part": "X"}, details) == {
        "vendor": "Other", "vendor_part": "X"}
    assert rules.check_sub_changes(sub(), {"manufacturer_part": " 930103 ", "infor_item": "100091"}, details) == {
        "manufacturer_part": "930103", "infor_item": "100091"}
    assert rules.check_sub_changes(sub(), {"vendor_part": "P2"}, ("vendor_part",)) == {"vendor_part": "P2"}
    assert rules.check_sub_changes(sub(), {"uom": "bx", "vendor_id": ""}, details) == {"uom": "BX"}
    refused(lambda: rules.check_sub_changes(sub(), {"vendor_part": " "}, ("vendor_part",)), says="Vendor part is required")


def test_an_edit_that_changes_nothing_is_refused_unless_it_comes_with_an_order():
    unchanged = {"qoe": "100.0", "vendor": "Medline"}
    refused(lambda: rules.check_sub_changes(sub(qoe=Decimal("100")), unchanged, rules.SUB_DETAIL_FIELDS),
            says="Nothing to change")
    assert rules.check_sub_changes(sub(qoe=Decimal("100")), unchanged, rules.SUB_DETAIL_FIELDS, required=False) == {}


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
    refused(lambda: rules.check_new_order(sub(status="approved"), {"quantity": 5, "uom": "BX"}, now=NOW),
            status=409, says="isn't picked")


def test_an_order_takes_uom_qoe_and_vendor_from_the_sub_unless_given():
    picked = sub(status="approved", is_picked=True, vendor_id="1000931", uom="CS", qoe=Decimal("4"))
    clean = rules.check_new_order(picked, {"quantity": "15"}, now=NOW)
    assert (clean["quantity"], clean["uom"], clean["qoe"], clean["vendor"]) == (15, "CS", Decimal("4"), "Medline")
    assert clean["ordered_dt"] is None  # "now", set when saved

    clean = rules.check_new_order(picked, {"quantity": 2, "uom": "ea", "qoe": "", "vendor": "Owens"}, now=NOW)
    assert (clean["uom"], clean["qoe"], clean["vendor"]) == ("EA", None, "Owens")


def test_an_order_needs_the_vendor_id_and_a_uom():
    refused(lambda: rules.check_new_order(sub(status="approved", is_picked=True, vendor_id="1000931"), {"quantity": 1},
                                          now=NOW), says="UOM is required")
    # The vendor ID is needed too (2026-10-19), unless Infor has no such vendor: 000000, on purpose.
    refused(lambda: rules.check_new_order(sub(status="approved", is_picked=True, uom="BX"), {"quantity": 1}, now=NOW),
            says="Vendor ID (or 000000: Vendor not available in system) is required")
    no_vendor = sub(status="approved", is_picked=True, uom="BX", vendor_id=rules.NO_VENDOR_ID)
    assert rules.check_new_order(no_vendor, {"quantity": 1}, now=NOW)["vendor"] == "Medline"


def test_complete_vendor_details_have_the_vendor_its_id_and_the_uom():
    assert rules.details_missing({"vendor": None, "vendor_id": None, "uom": None}) == ["Vendor", "Vendor ID", "UOM"]
    assert rules.details_missing(sub(vendor="Owens", vendor_id="000000", uom="CS")) == []
    refused(lambda: rules.check_details_complete(sub(vendor="Owens", uom="CS")),
            says="Vendor ID (or 000000: Vendor not available in system) is required")
    refused(lambda: rules.check_details_complete(sub(vendor=None)),
            says="Vendor, Vendor ID (or 000000: Vendor not available in system) and UOM are required")
    assert rules.clean_vendor_id(" 000000 ") == "000000"


@pytest.mark.parametrize("quantity", [0, -3, "2.5", "", None])
def test_quantity_is_a_whole_number_above_zero(quantity):
    refused(lambda: rules.check_new_order(sub(status="approved", is_picked=True, vendor_id="1000931", uom="BX"),
                                          {"quantity": quantity}, now=NOW))


def test_ordered_date_can_be_earlier_but_not_in_the_future():
    picked = sub(status="approved", is_picked=True, vendor_id="1000931", uom="BX")
    clean = rules.check_new_order(picked, {"quantity": 1, "ordered_dt": "2026-10-12T09:15"}, now=NOW)
    assert clean["ordered_dt"] == datetime(2026, 10, 12, 9, 15)
    refused(lambda: rules.check_new_order(picked, {"quantity": 1, "ordered_dt": "2026-10-14"}, now=NOW),
            says="future")
    refused(lambda: rules.check_new_order(picked, {"quantity": 1, "ordered_dt": "10/12/2026"}, now=NOW),
            says="must look like")


def test_order_corrections_list_only_what_changed():
    assert rules.check_order_edit(order(), {"quantity": "12", "uom": "BX"}, now=NOW) == {"quantity": 12}
    refused(lambda: rules.check_order_edit(order(voided_at=NOW), {"quantity": 1}, now=NOW), status=409)
    refused(lambda: rules.check_order_edit(order(), {"ordered_dt": ""}, now=NOW), says="Ordered date is required")


def test_voiding_needs_a_reason_once():
    assert rules.check_void(order(), " entered twice ") == "entered twice"
    refused(lambda: rules.check_void(order(), "  "), says="Reason is required")
    refused(lambda: rules.check_void(order(voided_at=NOW), "again"), status=409)


def test_history_values_are_written_plainly():
    assert rules.display(Decimal("100.0000")) == "100"
    assert rules.display(Decimal("0.5000")) == "0.5"
    assert rules.display(datetime(2026, 10, 13, 9, 5, 30)) == "2026-10-13 09:05"
    assert rules.display(None) is None
