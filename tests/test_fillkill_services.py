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
    """A sub proposed for review (a Sub Finder; Medline's PBO subs work the same): pending."""
    base = {"medline_item": "MDS2585H", "vendor_part": "88885"}
    return services().add_sub({**base, **data}, FINDER)


def nurse_sub(**data):
    """A vendor part nursing enters (2026-10-15): approved on entry."""
    base = {"medline_item": "MDS2585H", "vendor_part": "88885"}
    return services().add_sub({**base, **data}, APPROVER, approve=True)


def approved_and_picked():
    """Nursing's only sub for the item, with the Materials Manager's details."""
    sub = nurse_sub(vendor="Cardinal", uom="BX", qoe="100")
    assert sub.is_picked
    return sub


def refused(call, *, status=400, says=""):
    with pytest.raises(RuleError) as caught:
        call()
    assert caught.value.status == status, caught.value.message
    assert says in caught.value.message
    return caught.value


# --- entering subs -------------------------------------------------------------------

def test_adding_a_sub_records_who_and_the_first_comment(ctx):
    sub = new_sub(comment="Same glove, other distributor")
    assert (sub.status, sub.is_picked, sub.source, sub.entered_by) == ("pending_review", False, "manual", FINDER)
    assert history("sub", sub.sub_id) == [
        ("created", None, None, None, None, FINDER),
        ("comment", None, None, None, "Same glove, other distributor", FINDER),
    ]


def test_nursing_enters_a_vendor_part_approved_and_picked_when_its_the_only_approved_one(ctx):
    first = nurse_sub(vendor_part="A1", comment="From Owens' email: 200 in stock")
    assert (first.status, first.is_picked, first.vendor, first.uom) == ("approved", True, None, None)
    assert history("sub", first.sub_id) == [
        ("created", None, None, None, None, APPROVER),
        ("comment", None, None, None, "From Owens' email: 200 in stock", APPROVER),
        ("status", "status", "pending_review", "approved", None, APPROVER),
        ("pick", None, None, None, "Picked automatically: the only approved sub.", APPROVER),
    ]
    second = nurse_sub(vendor_part="B1")  # another approved one: the Sub Approver picks
    assert (second.status, second.is_picked) == ("approved", False)
    # Medline's PBO subs (and a future AI finder's) wait for review; approving one picks it when
    # it's the item's only approved sub.
    pbo = services().add_sub({"medline_item": "MDS2585H", "vendor_part": "2329RH"}, "Medline", source="medline_pbo")
    assert (pbo.status, pbo.is_picked) == ("pending_review", False)
    assert services().set_status(pbo.sub_id, "approved", APPROVER).is_picked is False  # A1 and B1 are approved
    other_item = new_sub(medline_item="OTHERITEM")
    assert services().set_status(other_item.sub_id, "approved", APPROVER).is_picked is True


def test_the_same_vendor_part_twice_is_refused_whatever_the_case_or_vendor(ctx):
    new_sub(vendor_part="ab-1")
    refused(lambda: nurse_sub(vendor_part="AB-1"), status=409, says="already a sub")
    refused(lambda: new_sub(vendor="Owens", vendor_part="ab-1"), status=409, says="already a sub")
    new_sub(medline_item="OTHERITEM", vendor_part="ab-1")  # another item may have the same sub


def test_the_vendor_details_are_the_materials_managers(ctx):
    sub = nurse_sub()
    sub = services().set_details(sub.sub_id, {"vendor": "CARDINAL HEALTH", "vendor_id": CARDINAL, "description": "Glove",
                                              "uom": "bx", "qoe": "100", "vendor_part": "ignored"}, MANAGER)
    assert (sub.vendor, sub.vendor_id, sub.description, sub.uom, sub.qoe, sub.vendor_part) == (
        "CARDINAL HEALTH", CARDINAL, "Glove", "BX", Decimal("100.0000"), "88885")
    assert [row[1:4] + (row[5],) for row in history("sub", sub.sub_id) if row[0] == "edit"] == [
        ("vendor", None, "CARDINAL HEALTH", MANAGER), ("vendor_id", None, CARDINAL, MANAGER),
        ("description", None, "Glove", MANAGER), ("uom", None, "BX", MANAGER), ("qoe", None, "100", MANAGER),
    ]
    refused(lambda: services().set_details(sub.sub_id, {"vendor_id": "9999999"}, MANAGER), says="isn't in Infor's vendor list")
    refused(lambda: services().set_details(sub.sub_id, {"vendor_id": "Cardinal"}, MANAGER), says="digits")
    refused(lambda: services().set_details(sub.sub_id, {"uom": "BX"}, MANAGER), says="Nothing to change")
    services().set_status(sub.sub_id, "hold", APPROVER)  # whatever the status
    assert services().set_details(sub.sub_id, {"vendor_id": "", "vendor": "OWENS & MINOR"}, MANAGER).vendor_id is None


def test_nursing_corrects_the_vendor_part_until_the_sub_has_an_order(ctx):
    sub = approved_and_picked()
    services().edit_sub(sub.sub_id, {"vendor_part": "88886", "vendor": "ignored"}, APPROVER)
    assert [row[:4] for row in history("sub", sub.sub_id) if row[0] == "edit"] == [("edit", "vendor_part", "88885", "88886")]
    refused(lambda: services().edit_sub(sub.sub_id, {"vendor_part": "88886"}, APPROVER), says="Nothing to change")
    services().record_order(sub.sub_id, {"quantity": 1}, MANAGER)
    refused(lambda: services().edit_sub(sub.sub_id, {"vendor_part": "88887"}, APPROVER), status=409, says="has an order")


def test_status_changes_and_leaving_approved_unpicks(ctx):
    sub = approved_and_picked()
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
    assert services().set_status(sub.sub_id, "approved", APPROVER).is_picked  # the only approved one
    refused(lambda: services().pick(sub.sub_id, APPROVER), status=409)
    assert not services().unpick(sub.sub_id, APPROVER).is_picked
    assert services().pick(sub.sub_id, APPROVER).is_picked


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


def test_the_materials_manager_fills_in_the_vendor_details_with_the_order(ctx):
    sub = nurse_sub()  # just the vendor part
    refused(lambda: services().record_order(sub.sub_id, {"quantity": 2, "uom": "CS"}, MANAGER), says="Vendor is required")
    details = {"vendor": "OWENS & MINOR", "vendor_id": OWENS, "uom": "cs", "qoe": "12"}
    refused(lambda: services().record_order(sub.sub_id, {**details, "quantity": 0}, MANAGER), says="more than 0")
    from app import db
    from app.models.fillkill import Sub
    assert db.session.get(Sub, sub.sub_id).vendor is None  # a refused order saves no details either
    order = services().record_order(sub.sub_id, {**details, "quantity": 2}, MANAGER)
    assert (order.vendor, order.uom, order.qoe) == ("OWENS & MINOR", "CS", Decimal("12.0000"))
    sub = db.session.get(Sub, sub.sub_id)
    assert (sub.vendor, sub.vendor_id, sub.uom) == ("OWENS & MINOR", OWENS, "CS")
    assert [row[1] for row in history("sub", sub.sub_id) if row[0] == "edit" and row[5] == MANAGER] == [
        "vendor", "vendor_id", "uom", "qoe"]


def test_no_order_without_a_pick(ctx):
    approved_and_picked()
    second = nurse_sub(vendor_part="B1", vendor="V", uom="EA")  # approved, but not the pick
    refused(lambda: services().record_order(second.sub_id, {"quantity": 1}, MANAGER),
            status=409, says="isn't picked")


def test_two_orders_for_one_item(ctx):
    first = approved_and_picked()
    second = nurse_sub(vendor="Owens", vendor_part="OM-1", uom="CS")
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


# --- deleting a sub ----------------------------------------------------------------------

def test_a_deleted_sub_keeps_its_row_and_history_and_leaves_every_list(ctx):
    from app.fillkill import queries
    sub = new_sub()
    refused(lambda: services().delete_sub(sub.sub_id, "  ", FINDER), says="Reason is required")
    sub = services().delete_sub(sub.sub_id, "Wrong item: a sterile glove", FINDER, expected_status="pending_review")
    assert (sub.deleted_by, sub.delete_reason, sub.deleted_at is not None) == (FINDER, "Wrong item: a sterile glove", True)
    assert history("sub", sub.sub_id)[-1] == ("delete", None, None, None, "Wrong item: a sterile glove", FINDER)
    assert queries.subs_for_items(["MDS2585H"]) == []
    assert queries.subs_library() == [] and queries.all_subs() == []
    # Nothing more can happen to it, and the same vendor part can be added again as a new sub.
    refused(lambda: services().set_status(sub.sub_id, "approved", APPROVER), status=409, says="was deleted")
    refused(lambda: services().delete_sub(sub.sub_id, "again", FINDER), status=409, says="was deleted")
    again = new_sub()
    assert again.sub_id != sub.sub_id and [s["sub_id"] for s in queries.subs_for_items(["MDS2585H"])] == [again.sub_id]


def test_the_approvers_pick_and_a_sub_with_orders_cant_be_deleted(ctx):
    sub = approved_and_picked()
    refused(lambda: services().delete_sub(sub.sub_id, "not needed", FINDER), status=409, says="unpicked before")
    order = services().record_order(sub.sub_id, {"quantity": 3}, MANAGER)
    services().unpick(sub.sub_id, APPROVER)
    refused(lambda: services().delete_sub(sub.sub_id, "not needed", FINDER), status=409, says="void it before")
    services().void_order(order.order_id, "entered twice", MANAGER)
    assert services().delete_sub(sub.sub_id, "not needed", FINDER).deleted_by == FINDER
