"""Fill/Kill writes (app/fillkill/services.py) against the real tables on SQLite."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.fillkill.rules import RuleError
from conftest import CARDINAL, OWENS  # Infor vendor IDs

FINDER, APPROVER, OTHER_APPROVER, MANAGER = (
    "finder@example.org", "approver@example.org", "approver2@example.org", "mm@example.org",
)


@pytest.fixture
def ctx(sqlite_app):
    with sqlite_app.app_context():
        yield


def services():
    from app.fillkill import services as s
    return s


def history(entity=None, entity_id=None):
    from app.models.fillkill import History
    query = History.query.order_by(History.history_id)
    if entity:
        query = query.filter_by(entity=entity, entity_id=entity_id)
    return [(h.action, h.field, h.from_value, h.to_value, h.comment, h.actor) for h in query]


def new_sub(**data):
    base = {"medline_item": "MDS2585H", "vendor": "Cardinal", "vendor_part": "88885"}
    return services().add_sub({**base, **data}, FINDER)


def approved_and_picked():
    sub = new_sub(uom="BX", qoe="100")
    services().set_status(sub.sub_id, "approved", APPROVER)
    return services().pick(sub.sub_id, APPROVER)


def refused(call, *, status=400, says=""):
    with pytest.raises(RuleError) as caught:
        call()
    assert caught.value.status == status, caught.value.message
    assert says in caught.value.message
    return caught.value


# --- subs --------------------------------------------------------------------------

def test_adding_a_sub_records_who_and_the_first_comment(ctx):
    sub = new_sub(comment="Same glove, other distributor")
    assert (sub.status, sub.is_picked, sub.source, sub.entered_by) == ("pending_review", False, "manual", FINDER)
    assert history("sub", sub.sub_id) == [
        ("created", None, None, None, None, FINDER),
        ("comment", None, None, None, "Same glove, other distributor", FINDER),
    ]


def test_the_same_vendor_part_twice_is_refused_whatever_the_case(ctx):
    new_sub(vendor_part="ab-1")
    refused(lambda: new_sub(vendor_part="AB-1"), status=409, says="already a sub")
    new_sub(medline_item="OTHERITEM", vendor_part="ab-1")  # another item may have the same sub
    new_sub(vendor="Owens", vendor_part="ab-1")  # and another vendor the same part number


def test_the_vendor_id_is_optional_and_must_be_infors_when_given(ctx):
    sub = new_sub()
    assert (sub.vendor, sub.vendor_id, sub.label()) == ("Cardinal", None, "88885 (Cardinal)")
    sub = new_sub(vendor="CARDINAL HEALTH", vendor_id=CARDINAL, vendor_part="X1")  # as picked from a contract line
    assert (sub.vendor, sub.vendor_id) == ("CARDINAL HEALTH", CARDINAL)
    refused(lambda: new_sub(vendor_id="9999999", vendor_part="X2"), says="isn't in Infor's vendor list")
    refused(lambda: new_sub(vendor_id="Cardinal", vendor_part="X2"), says="digits")
    # Before the first review the ID can be added or changed, and the history keeps it.
    sub = services().edit_sub(sub.sub_id, {"vendor_id": OWENS, "vendor": "OWENS & MINOR"}, FINDER)
    assert (sub.vendor, sub.vendor_id) == ("OWENS & MINOR", OWENS)
    assert [row[:4] for row in history("sub", sub.sub_id) if row[0] == "edit"] == [
        ("edit", "vendor", "CARDINAL HEALTH", "OWENS & MINOR"), ("edit", "vendor_id", CARDINAL, OWENS),
    ]
    refused(lambda: services().edit_sub(sub.sub_id, {"vendor_id": "9999999"}, FINDER), says="isn't in Infor's vendor list")
    assert services().edit_sub(sub.sub_id, {"vendor_id": ""}, FINDER).vendor_id is None  # can be emptied


def test_corrections_are_logged_field_by_field(ctx):
    sub = new_sub()
    services().edit_sub(sub.sub_id, {"vendor_part": "88886", "description": "Glove"}, FINDER)
    edits = [row for row in history("sub", sub.sub_id) if row[0] == "edit"]
    assert edits == [
        ("edit", "vendor_part", "88885", "88886", None, FINDER),
        ("edit", "description", None, "Glove", None, FINDER),
    ]
    services().set_status(sub.sub_id, "hold", APPROVER)
    refused(lambda: services().edit_sub(sub.sub_id, {"vendor": "Owens"}, FINDER), says="after the sub has been reviewed")
    refused(lambda: services().edit_sub(sub.sub_id, {"vendor_id": OWENS}, FINDER), says="after the sub has been reviewed")


def test_status_changes_and_leaving_approved_unpicks(ctx):
    sub = approved_and_picked()
    assert sub.is_picked
    sub = services().set_status(sub.sub_id, "hold", APPROVER, expected_status="approved")
    assert (sub.status, sub.is_picked) == ("hold", False)
    assert [row[:4] for row in history("sub", sub.sub_id)][-2:] == [
        ("status", "status", "approved", "hold"),
        ("unpick", None, None, None),
    ]


def test_a_stale_status_is_refused_and_names_who_changed_it(ctx):
    sub = new_sub()
    services().set_status(sub.sub_id, "rejected", OTHER_APPROVER)
    error = refused(lambda: services().set_status(sub.sub_id, "approved", APPROVER, expected_status="pending_review"),
                    status=409, says=OTHER_APPROVER)
    assert "now Rejected" in error.message


def test_picks(ctx):
    sub = new_sub()
    refused(lambda: services().pick(sub.sub_id, APPROVER), says="Only an approved sub")
    services().set_status(sub.sub_id, "approved", APPROVER)
    services().pick(sub.sub_id, APPROVER)
    refused(lambda: services().pick(sub.sub_id, APPROVER), status=409)
    sub = services().unpick(sub.sub_id, APPROVER)
    assert not sub.is_picked


def test_comments_on_subs_append(ctx):
    sub = new_sub()
    services().comment_on_sub(sub.sub_id, "Checked with 4E", APPROVER)
    services().comment_on_sub(sub.sub_id, "Still fine", APPROVER)
    comments = [row[4] for row in history("sub", sub.sub_id) if row[0] == "comment"]
    assert comments == ["Checked with 4E", "Still fine"]
    refused(lambda: services().comment_on_sub(sub.sub_id, "   ", APPROVER), says="Comment is required")


def test_a_refused_action_writes_nothing(ctx):
    sub = new_sub()
    before = history()
    refused(lambda: services().set_status(sub.sub_id, "pending_review", APPROVER))
    refused(lambda: services().comment_on_sub(sub.sub_id, "x" * 401, APPROVER))
    assert history() == before


def test_a_missing_sub(ctx):
    refused(lambda: services().pick(999, APPROVER), status=404)


# --- orders -------------------------------------------------------------------------

def test_an_order_is_recorded_against_a_pick_with_the_sub_defaults(ctx):
    sub = approved_and_picked()
    order = services().record_order(sub.sub_id, {"quantity": 15, "comment": "covers 4E and ICU"}, MANAGER,
                                    expected_status="approved")
    assert (order.medline_item, order.quantity, order.uom, order.qoe, order.vendor, order.ordered_by) == (
        "MDS2585H", 15, "BX", Decimal("100.0000"), "Cardinal", MANAGER,
    )
    assert isinstance(order.ordered_dt, datetime)
    assert history("order", order.order_id) == [
        ("created", None, None, None, None, MANAGER),
        ("comment", None, None, None, "covers 4E and ICU", MANAGER),
    ]


def test_no_order_without_a_pick(ctx):
    sub = new_sub()
    services().set_status(sub.sub_id, "approved", APPROVER)
    refused(lambda: services().record_order(sub.sub_id, {"quantity": 1, "uom": "BX"}, MANAGER),
            status=409, says="isn't picked")


def test_two_orders_for_one_item(ctx):
    first = approved_and_picked()
    second = new_sub(vendor="Owens", vendor_part="OM-1", uom="CS")
    services().set_status(second.sub_id, "approved", APPROVER)
    services().pick(second.sub_id, APPROVER)
    services().record_order(first.sub_id, {"quantity": 10}, MANAGER)
    services().record_order(second.sub_id, {"quantity": 5}, MANAGER)
    from app.models.fillkill import SubOrder
    assert sorted((o.vendor, o.quantity) for o in SubOrder.query.all()) == [("Cardinal", 10), ("Owens", 5)]


def test_order_corrections_void_and_comments(ctx):
    order = services().record_order(approved_and_picked().sub_id, {"quantity": 10}, MANAGER)
    services().edit_order(order.order_id, {"quantity": "12"}, MANAGER)
    order = services().void_order(order.order_id, "entered twice", MANAGER)
    assert (order.voided_by, order.void_reason, order.is_voided) == (MANAGER, "entered twice", True)
    refused(lambda: services().edit_order(order.order_id, {"quantity": 3}, MANAGER), status=409)
    refused(lambda: services().void_order(order.order_id, "again", MANAGER), status=409)
    services().comment_on_order(order.order_id, "re-ordered under PO 123", MANAGER)  # still allowed
    assert [row[:4] for row in history("order", order.order_id)] == [
        ("created", None, None, None),
        ("edit", "quantity", "10", "12"),
        ("void", None, None, None),
        ("comment", None, None, None),
    ]


def test_an_order_survives_its_sub_being_unpicked(ctx):
    sub = approved_and_picked()
    order = services().record_order(sub.sub_id, {"quantity": 3}, MANAGER)
    services().set_status(sub.sub_id, "rejected", APPROVER)
    from app import db
    from app.models.fillkill import SubOrder
    assert db.session.get(SubOrder, order.order_id).voided_at is None
