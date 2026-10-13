"""Fill/Kill action rules (app/fillkill/rules.py), with no database."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.fillkill import rules
from app.fillkill.rules import RuleError

NOW = datetime(2026, 10, 13, 14, 0)


def sub(**kwargs):
    base = dict(status="pending_review", is_picked=False, vendor="Medline", vendor_part="P1",
                description=None, uom=None, qoe=None)
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

def test_new_sub_needs_vendor_and_part_and_cleans_the_rest():
    clean = rules.check_new_sub({
        "medline_item": " MDS2585H ", "vendor": "Cardinal", "vendor_part": "88885",
        "uom": "bx", "qoe": "100", "comment": "  same glove  ",
    })
    assert clean == {
        "medline_item": "MDS2585H", "vendor": "Cardinal", "vendor_part": "88885", "description": None,
        "uom": "BX", "qoe": Decimal("100.0000"), "comment": "same glove",
    }
    refused(lambda: rules.check_new_sub({"medline_item": "M", "vendor_part": "P"}), says="Vendor is required")
    refused(lambda: rules.check_new_sub({"medline_item": "M", "vendor": "V"}), says="Vendor part is required")


@pytest.mark.parametrize("field, value, says", [
    ("qoe", "0", "more than 0"),
    ("qoe", "abc", "must be a number"),
    ("uom", "TOOLONGUOMX", "longer than 10"),
    ("comment", "x" * 401, "longer than 400"),
])
def test_new_sub_refuses_bad_values(field, value, says):
    data = {"medline_item": "M", "vendor": "V", "vendor_part": "P", field: value}
    refused(lambda: rules.check_new_sub(data), says=says)


def test_vendor_and_part_can_be_fixed_only_before_the_first_review():
    assert rules.check_sub_edit(sub(), {"vendor_part": "P2"}) == {"vendor_part": "P2"}
    refused(lambda: rules.check_sub_edit(sub(status="approved"), {"vendor": "Other"}),
            says="can't change after the sub has been reviewed")
    assert rules.check_sub_edit(sub(status="hold"), {"description": "Glove"}) == {"description": "Glove"}


def test_an_edit_that_changes_nothing_is_refused():
    refused(lambda: rules.check_sub_edit(sub(qoe=Decimal("100")), {"qoe": "100.0"}), says="Nothing to change")


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
    picked = sub(status="approved", is_picked=True, uom="CS", qoe=Decimal("4"))
    clean = rules.check_new_order(picked, {"quantity": "15"}, now=NOW)
    assert (clean["quantity"], clean["uom"], clean["qoe"], clean["vendor"]) == (15, "CS", Decimal("4"), "Medline")
    assert clean["ordered_dt"] is None  # "now", set when saved

    clean = rules.check_new_order(picked, {"quantity": 2, "uom": "ea", "qoe": "", "vendor": "Owens"}, now=NOW)
    assert (clean["uom"], clean["qoe"], clean["vendor"]) == ("EA", None, "Owens")


def test_an_order_needs_a_uom_from_somewhere():
    refused(lambda: rules.check_new_order(sub(status="approved", is_picked=True), {"quantity": 1}, now=NOW),
            says="UOM is required")


@pytest.mark.parametrize("quantity", [0, -3, "2.5", "", None])
def test_quantity_is_a_whole_number_above_zero(quantity):
    refused(lambda: rules.check_new_order(sub(status="approved", is_picked=True, uom="BX"),
                                          {"quantity": quantity}, now=NOW))


def test_ordered_date_can_be_earlier_but_not_in_the_future():
    picked = sub(status="approved", is_picked=True, uom="BX")
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
