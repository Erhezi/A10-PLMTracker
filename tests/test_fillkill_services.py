"""Fill/Kill writes (app/fillkill/services.py) against the real tables on SQLite."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.fillkill.rules import RuleError
from conftest import CARDINAL, MEDLINE, OWENS, add_view_rows  # Infor vendor IDs

FINDER, APPROVER, OTHER_APPROVER, MANAGER, LEAD = (
    "finder@example.org", "approver@example.org", "approver2@example.org", "mm@example.org", "lead@example.org",
)
SITE, OTHER_SITE = "0001795146", "test site"  # Medline Sold-To codes: an order is for one (2026-10-27)


@pytest.fixture
def ctx(sqlite_app):
    add_view_rows(sqlite_app, "vw_MedlineFillKillQtyAgg", [
        {"Order Date": "2026-09-30", "Sold-To": SITE, "Sold-To Name": "WHITE PLAINS", "Medline Item": "MDS2585H",
         "UM": "BX", "Total Ordered Qty": 4, "Total Filled Qty": 0, "Total Killed Qty": 4, "Total PO Line Count": 1},
        {"Order Date": "2026-09-30", "Sold-To": OTHER_SITE, "Sold-To Name": "test site", "Medline Item": "MDS2585H",
         "UM": "BX", "Total Ordered Qty": 2, "Total Filled Qty": 0, "Total Killed Qty": 2, "Total PO Line Count": 1},
    ])
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
    base = {"medline_item": "MDS2585H", "reference_sku": "88885"}
    return services().add_sub({**base, **data}, FINDER)


def nurse_sub(**data):
    """A Reference SKU nursing enters (2026-10-15): approved on entry."""
    base = {"medline_item": "MDS2585H", "reference_sku": "88885"}
    return services().add_sub({**base, **data}, APPROVER, approve=True)


def vendor_item(sub, **data):
    """The Materials Manager's: a way to order the sub."""
    base = {"vendor_part": "88885", "vendor": "CARDINAL HEALTH", "vendor_id": CARDINAL, "uom": "BX", "qoe": "100"}
    return services().add_vendor_item(sub.sub_id, {**base, **data}, MANAGER)


def approved_with_vendor_item():
    """Nursing's sub for the item, approved on entry, with the Materials Manager's vendor item."""
    sub = nurse_sub()
    assert sub.status == "approved"
    return sub, vendor_item(sub)


def refused(call, *, status=400, says=""):
    with pytest.raises(RuleError) as caught:
        call()
    assert caught.value.status == status, caught.value.message
    assert says in caught.value.message
    return caught.value


# --- entering subs -------------------------------------------------------------------

def test_adding_a_sub_records_who_and_the_first_comment(ctx):
    sub = new_sub(comment="Same glove, other distributor")
    assert (sub.reference_sku, sub.status, sub.source, sub.entered_by) == ("88885", "pending_review", "manual", FINDER)
    assert history("sub", sub.sub_id) == [
        ("created", None, None, None, None, FINDER),
        ("comment", None, None, None, "Same glove, other distributor", FINDER),
    ]


def test_nursing_enters_a_reference_sku_approved_on_entry_and_others_wait_for_review(ctx):
    first = nurse_sub(reference_sku="A1", comment="From Owens' email: 200 in stock")
    assert first.status == "approved"
    assert history("sub", first.sub_id) == [
        ("created", None, None, None, None, APPROVER),
        ("comment", None, None, None, "From Owens' email: 200 in stock", APPROVER),
        ("status", "status", "pending_review", "approved", None, APPROVER),
    ]
    # Every approved sub can be ordered (2026-10-28): a second is approved just the same.
    assert nurse_sub(reference_sku="B1").status == "approved"
    # A Sub Finder's, Medline's PBO subs (and a future AI finder's) wait for a Sub Approver's review.
    assert new_sub(reference_sku="C1").status == "pending_review"
    pbo = services().add_sub({"medline_item": "MDS2585H", "reference_sku": "2329RH"}, "Medline", source="medline_pbo")
    assert pbo.status == "pending_review"
    assert services().set_status(pbo.sub_id, "approved", APPROVER).status == "approved"


def test_the_same_reference_sku_twice_is_refused_whatever_the_case(ctx):
    new_sub(reference_sku="ab-1")
    refused(lambda: nurse_sub(reference_sku="AB-1"), status=409, says="already a sub")
    new_sub(medline_item="OTHERITEM", reference_sku="ab-1")  # another item may have the same sub


# --- vendor items ----------------------------------------------------------------------

def test_a_reference_sku_has_a_vendor_item_for_each_way_to_order_it(ctx):
    # Nursing approved 930103, BD's part; Medline sells it as a case (B-D930103CS) and a box
    # (B-D930103CSZ): one sub, two vendor items (2026-10-20).
    sub = nurse_sub(medline_item="B-D930299Z", reference_sku="930103")
    case = vendor_item(sub, vendor_part="B-D930103CS", vendor="MEDLINE INDUSTRIES INC", vendor_id=MEDLINE, uom="ca",
                       qoe="400", manufacturer_part="930103", infor_item="100091", description="CHLORAPREP")
    box = vendor_item(sub, vendor_part="B-D930103CSZ", vendor="MEDLINE INDUSTRIES INC", vendor_id=MEDLINE, uom="BX", qoe="40")
    assert (case.sub_id, case.vendor_part, case.uom, case.qoe, case.manufacturer_part, case.infor_item, case.entered_by) == (
        sub.sub_id, "B-D930103CS", "CA", Decimal("400.0000"), "930103", "100091", MANAGER)
    assert box.vendor_item_id != case.vendor_item_id
    assert history("vendoritem", case.vendor_item_id) == [("created", None, None, None, None, MANAGER)]
    from app import db
    from app.models.fillkill import Sub
    assert db.session.get(Sub, sub.sub_id).reference_sku == "930103"  # what nursing entered stays
    # The same vendor ID, vendor part and UOM only once; another UOM or vendor is another way to order it.
    refused(lambda: vendor_item(sub, vendor_part="b-d930103cs", vendor="MEDLINE INDUSTRIES INC", vendor_id=MEDLINE, uom="CA"),
            status=409, says="already has vendor item B-D930103CS")
    vendor_item(sub, vendor_part="B-D930103CS", vendor="OWENS & MINOR", vendor_id=OWENS, uom="CA")


def test_a_vendor_item_needs_infors_vendor_id_or_0000000(ctx):
    sub = nurse_sub()
    refused(lambda: vendor_item(sub, vendor_id=""), says="Vendor ID (or 0000000: Vendor not available in system) is required")
    refused(lambda: vendor_item(sub, vendor_id="9999999"), says="isn't in Infor's vendor list")
    refused(lambda: vendor_item(sub, vendor_id="000000", vendor="LOCAL SUPPLY CO"),
            says="Vendor ID 000000 isn't in Infor's vendor list. Fix it, or use 0000000")  # six zeros: not the one
    refused(lambda: vendor_item(sub, uom=""), says="UOM is required")
    from app.models.fillkill import VendorItem
    assert VendorItem.query.count() == 0  # nothing saved
    item = vendor_item(sub, vendor_id="0000000", vendor="LOCAL SUPPLY CO")
    assert (item.vendor_id, item.vendor) == ("0000000", "LOCAL SUPPLY CO")


def test_correcting_and_deleting_a_vendor_item(ctx):
    sub, item = approved_with_vendor_item()
    item = services().edit_vendor_item(item.vendor_item_id, {"uom": "cs", "qoe": "1000", "vendor": "CARDINAL HEALTH"}, FINDER)
    assert (item.uom, item.qoe) == ("CS", Decimal("1000.0000"))
    assert [row[:4] + (row[5],) for row in history("vendoritem", item.vendor_item_id)][1:] == [
        ("edit", "uom", "BX", "CS", FINDER), ("edit", "qoe", "100", "1000", FINDER)]
    refused(lambda: services().edit_vendor_item(item.vendor_item_id, {"uom": "CS"}, FINDER), says="Nothing to change")
    refused(lambda: services().edit_vendor_item(item.vendor_item_id, {"vendor_id": "9999999"}, FINDER),
            says="isn't in Infor's vendor list")
    other = vendor_item(sub, uom="BX")
    refused(lambda: services().edit_vendor_item(other.vendor_item_id, {"uom": "CS"}, FINDER), status=409, says="already has")
    # Deleted with a reason, unless it has orders that aren't voided.
    order = services().record_order(item.vendor_item_id, {"site": SITE, "quantity": 2}, MANAGER)
    refused(lambda: services().delete_vendor_item(item.vendor_item_id, "no longer sold", FINDER), status=409, says="void it before")
    services().void_order(order.order_id, "entered twice", MANAGER)
    refused(lambda: services().delete_vendor_item(item.vendor_item_id, " ", FINDER), says="Reason is required")
    item = services().delete_vendor_item(item.vendor_item_id, "no longer sold", FINDER)
    assert (item.deleted_by, item.delete_reason) == (FINDER, "no longer sold")
    refused(lambda: services().edit_vendor_item(item.vendor_item_id, {"uom": "EA"}, FINDER), status=409, says="was deleted")
    from app.fillkill import queries
    [listed] = queries.subs_for_items(["MDS2585H"])
    assert [v["vendor_item_id"] for v in listed["vendor_items"]] == [other.vendor_item_id]
    # The sub's history shows its vendor items' too, each named.
    sub_history = queries.history("sub", sub.sub_id)
    assert (sub_history[0]["entity"], sub_history[0]["action"], sub_history[0]["label"]) == (
        "vendoritem", "delete", "88885 (CARDINAL HEALTH, CS)")


def item_vendor_item(medline_item="MDS2585H", **data):
    """SCM's (2026-11-02): a vendor item of the Medline item itself, with no sub."""
    base = {"vendor_part": "BD-345678", "vendor": "CARDINAL HEALTH", "vendor_id": CARDINAL, "uom": "BX", "qoe": "100"}
    return services().add_vendor_item(None, {**base, **data}, LEAD, medline_item=medline_item)


def test_a_vendor_item_without_a_sub_is_the_medline_items_and_is_ordered_as_it_is(ctx):
    # No sub nursing approved is available; SCM directs the sites to order the same item from
    # another vendor (2026-11-02, the user).
    item = item_vendor_item()
    assert (item.sub_id, item.medline_item, item.item_for, item.vendor_part, item.entered_by) == (
        None, "MDS2585H", "MDS2585H", "BD-345678", LEAD)
    from app.models.fillkill import History
    assert [(h.entity, h.medline_item, h.action) for h in History.query.all()] == [("vendoritem", "MDS2585H", "created")]
    order = services().record_order(item.vendor_item_id, {"site": SITE, "quantity": 3}, MANAGER, expected_status="approved")
    assert (order.sub_id, order.vendor_item_id, order.medline_item, order.vendor_part, order.quantity) == (
        None, item.vendor_item_id, "MDS2585H", "BD-345678", 3)
    from app.fillkill import queries
    assert queries.order_dict(order)["reference_sku"] is None
    assert [v["vendor_item_id"] for v in queries.item_vendor_items(["MDS2585H"])["MDS2585H"]] == [item.vendor_item_id]
    assert queries.subs_for_items(["MDS2585H"]) == []  # it isn't a sub
    # One per Medline item, vendor ID, vendor part and UOM; a sub's may have the same.
    refused(lambda: item_vendor_item(vendor_part="bd-345678"), status=409, says="MDS2585H (no sub) already has vendor item")
    item_vendor_item(medline_item="DYND70294BH")
    vendor_item(nurse_sub(), vendor_part="BD-345678")
    # Never the killed item itself from Medline, and it needs its Medline item.
    refused(lambda: item_vendor_item(vendor_part="MDS2585H", vendor="MEDLINE INDUSTRIES INC", vendor_id=MEDLINE),
            says="MDS2585H itself")
    refused(lambda: item_vendor_item(medline_item=" "), says="Medline item is required")


def test_correcting_and_deleting_a_vendor_item_without_a_sub(ctx):
    item = item_vendor_item()
    item = services().edit_vendor_item(item.vendor_item_id, {"uom": "CS"}, LEAD)
    assert item.uom == "CS"
    other = item_vendor_item(uom="BX")
    refused(lambda: services().edit_vendor_item(other.vendor_item_id, {"uom": "CS"}, LEAD), status=409, says="already has")
    order = services().record_order(item.vendor_item_id, {"site": SITE, "quantity": 2}, MANAGER)
    refused(lambda: services().delete_vendor_item(item.vendor_item_id, "BD has it again", LEAD), status=409, says="void it before")
    services().void_order(order.order_id, "entered twice", MANAGER)
    services().delete_vendor_item(item.vendor_item_id, "BD has it again", LEAD)
    assert [row[:2] for row in history("vendoritem", item.vendor_item_id)] == [
        ("created", None), ("edit", "uom"), ("delete", None)]
    from app.models.fillkill import History
    assert {h.medline_item for h in History.query.filter_by(entity="vendoritem")} == {"MDS2585H"}
    from app.fillkill import queries
    assert [v["vendor_item_id"] for v in queries.item_vendor_items(["MDS2585H"])["MDS2585H"]] == [other.vendor_item_id]


# --- correcting and reviewing subs ----------------------------------------------------------

def test_nursing_corrects_the_reference_sku_until_the_sub_has_an_order(ctx):
    sub, item = approved_with_vendor_item()
    services().edit_sub(sub.sub_id, {"reference_sku": "88886", "vendor_part": "ignored"}, APPROVER)
    assert [row[:4] for row in history("sub", sub.sub_id) if row[0] == "edit"] == [("edit", "reference_sku", "88885", "88886")]
    refused(lambda: services().edit_sub(sub.sub_id, {"reference_sku": "88886"}, APPROVER), says="Nothing to change")
    from app import db
    from app.models.fillkill import VendorItem
    assert db.session.get(VendorItem, item.vendor_item_id).vendor_part == "88885"  # the Materials Manager's stays
    services().record_order(item.vendor_item_id, {"site": SITE, "quantity": 1}, MANAGER)
    refused(lambda: services().edit_sub(sub.sub_id, {"reference_sku": "88887"}, APPROVER), status=409, says="has an order")
    nurse_sub(reference_sku="OTHER")
    other = nurse_sub(reference_sku="OTHER-2")
    refused(lambda: services().edit_sub(other.sub_id, {"reference_sku": "other"}, APPROVER), status=409, says="already a sub")


def test_hold_or_reject_with_an_optional_reason_kept_as_a_comment(ctx):
    sub, _ = approved_with_vendor_item()
    sub = services().set_status(sub.sub_id, "hold", APPROVER, expected_status="approved", reason="  Recalled by the maker  ")
    assert sub.status == "hold"
    assert [row[:5] for row in history("sub", sub.sub_id)][-2:] == [
        ("status", "status", "approved", "hold", None),
        ("comment", None, None, None, "Hold: Recalled by the maker"),
    ]
    # Without a reason, the status alone.
    services().set_status(sub.sub_id, "approved", APPROVER)
    sub = services().set_status(sub.sub_id, "rejected", APPROVER, reason=" ")
    assert history("sub", sub.sub_id)[-1][:5] == ("status", "status", "approved", "rejected", None)
    before = history()
    refused(lambda: services().set_status(sub.sub_id, "hold", APPROVER, reason="x" * 381), says="Reason is longer than 380")
    assert history() == before


def test_a_stale_status_is_refused_and_names_who_changed_it(ctx):
    sub = new_sub()
    services().set_status(sub.sub_id, "rejected", OTHER_APPROVER)
    error = refused(lambda: services().set_status(sub.sub_id, "approved", APPROVER, expected_status="pending_review"),
                    status=409, says=OTHER_APPROVER)
    assert "now Rejected" in error.message


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


def test_a_missing_sub_or_vendor_item(ctx):
    refused(lambda: services().set_status(999, "approved", APPROVER), status=404, says="That sub")
    refused(lambda: services().edit_vendor_item(999, {"uom": "BX"}, MANAGER), status=404, says="That vendor item")
    refused(lambda: services().record_order(999, {"site": SITE, "quantity": 1}, MANAGER), status=404, says="That vendor item")


# --- orders -------------------------------------------------------------------------

def test_an_order_is_recorded_for_a_vendor_item_of_an_approved_sub(ctx):
    sub, item = approved_with_vendor_item()
    order = services().record_order(item.vendor_item_id, {"site": SITE, "quantity": 15, "comment": "covers 4E and ICU"}, MANAGER,
                                    expected_status="approved")
    assert (order.sub_id, order.vendor_item_id, order.medline_item, order.quantity, order.vendor_part, order.uom,
            order.qoe, order.vendor, order.vendor_id, order.ordered_by) == (
        sub.sub_id, item.vendor_item_id, "MDS2585H", 15, "88885", "BX", Decimal("100.0000"), "CARDINAL HEALTH", CARDINAL, MANAGER,
    )
    assert isinstance(order.ordered_dt, datetime)
    assert history("order", order.order_id) == [
        ("created", None, None, None, None, MANAGER),
        ("comment", None, None, None, "covers 4E and ICU", MANAGER),
    ]


def test_every_approved_sub_can_be_ordered(ctx):
    # Picking among them is gone (2026-10-28): two approved subs, an order for each.
    _, first = approved_with_vendor_item()
    second = vendor_item(nurse_sub(reference_sku="B1"), vendor_part="B1")
    services().record_order(first.vendor_item_id, {"site": SITE, "quantity": 1}, MANAGER)
    services().record_order(second.vendor_item_id, {"site": SITE, "quantity": 1}, MANAGER)
    from app.models.fillkill import SubOrder
    assert SubOrder.query.count() == 2


def test_no_order_for_a_sub_that_isnt_approved(ctx):
    pending = new_sub(reference_sku="B1")  # a Sub Finder's: pending review
    item = vendor_item(pending, vendor_part="B1")
    refused(lambda: services().record_order(item.vendor_item_id, {"site": SITE, "quantity": 1}, MANAGER),
            status=409, says="Only an approved sub can be ordered, and B1 is pending review")
    services().set_status(pending.sub_id, "approved", APPROVER)
    services().record_order(item.vendor_item_id, {"site": SITE, "quantity": 1}, MANAGER)
    # Nursing doesn't want it ordered any more: on hold, it can't be.
    services().set_status(pending.sub_id, "hold", OTHER_APPROVER)
    refused(lambda: services().record_order(item.vendor_item_id, {"site": SITE, "quantity": 1}, MANAGER),
            status=409, says="B1 is on hold")
    refused(lambda: services().record_order(item.vendor_item_id, {"site": SITE, "quantity": 1}, MANAGER, expected_status="approved"),
            status=409, says="now Hold")


def test_orders_for_two_vendor_items_of_one_sub(ctx):
    sub, box = approved_with_vendor_item()
    case = vendor_item(sub, vendor_part="88885-CS", vendor="OWENS & MINOR", vendor_id=OWENS, uom="CS", qoe="1000")
    services().record_order(box.vendor_item_id, {"site": SITE, "quantity": 10}, MANAGER)
    services().record_order(case.vendor_item_id, {"site": SITE, "quantity": 5}, MANAGER)
    from app.models.fillkill import SubOrder
    assert sorted((o.vendor, o.vendor_part, o.uom, o.quantity) for o in SubOrder.query.all()) == [
        ("CARDINAL HEALTH", "88885", "BX", 10), ("OWENS & MINOR", "88885-CS", "CS", 5)]


def test_order_corrections_void_and_comments(ctx):
    order = services().record_order(approved_with_vendor_item()[1].vendor_item_id, {"site": SITE, "quantity": 10}, MANAGER)
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


def test_an_order_survives_its_sub_being_rejected(ctx):
    sub, item = approved_with_vendor_item()
    order = services().record_order(item.vendor_item_id, {"site": SITE, "quantity": 3}, MANAGER)
    services().set_status(sub.sub_id, "rejected", APPROVER)
    from app import db
    from app.models.fillkill import SubOrder
    assert db.session.get(SubOrder, order.order_id).voided_at is None


def test_an_order_keeps_what_it_was_placed_with(ctx):
    _, item = approved_with_vendor_item()  # Cardinal
    order = services().record_order(item.vendor_item_id, {"site": SITE, "quantity": 3}, MANAGER)
    # The vendor item is corrected later; the order keeps its own until corrected.
    services().edit_vendor_item(item.vendor_item_id, {"vendor": "OWENS & MINOR", "vendor_id": OWENS, "vendor_part": "OM-1"}, MANAGER)
    from app import db
    from app.models.fillkill import SubOrder
    kept = db.session.get(SubOrder, order.order_id)
    assert (kept.vendor, kept.vendor_id, kept.vendor_part) == ("CARDINAL HEALTH", CARDINAL, "88885")
    refused(lambda: services().edit_order(order.order_id, {"vendor_id": "9999999"}, MANAGER), says="isn't in Infor's vendor list")
    refused(lambda: services().edit_order(order.order_id, {"vendor_id": " "}, MANAGER),
            says="Vendor ID (or 0000000: Vendor not available in system) is required")
    order = services().edit_order(order.order_id, {"vendor": "OWENS & MINOR", "vendor_id": OWENS, "vendor_part": "OM-1"}, MANAGER)
    assert (order.vendor, order.vendor_id, order.vendor_part) == ("OWENS & MINOR", OWENS, "OM-1")
    assert [row[1:4] for row in history("order", order.order_id) if row[0] == "edit"] == [
        ("vendor_part", "88885", "OM-1"), ("vendor", "CARDINAL HEALTH", "OWENS & MINOR"), ("vendor_id", CARDINAL, OWENS)]
    assert services().edit_order(order.order_id, {"vendor_id": "0000000"}, MANAGER).vendor_id == "0000000"


# --- deleting a sub ----------------------------------------------------------------------

def test_a_deleted_sub_keeps_its_row_and_history_and_leaves_every_list(ctx):
    from app.fillkill import queries
    sub = new_sub()
    item = vendor_item(sub)
    refused(lambda: services().delete_sub(sub.sub_id, "  ", FINDER), says="Reason is required")
    sub = services().delete_sub(sub.sub_id, "Wrong item: a sterile glove", FINDER, expected_status="pending_review")
    assert (sub.deleted_by, sub.delete_reason, sub.deleted_at is not None) == (FINDER, "Wrong item: a sterile glove", True)
    assert history("sub", sub.sub_id)[-1] == ("delete", None, None, None, "Wrong item: a sterile glove", FINDER)
    assert queries.subs_for_items(["MDS2585H"]) == []
    assert queries.subs_library() == [] and queries.all_subs() == []
    # Nothing more can happen to it or its vendor items, and the same Reference SKU can be added again.
    refused(lambda: services().set_status(sub.sub_id, "approved", APPROVER), status=409, says="was deleted")
    refused(lambda: services().delete_sub(sub.sub_id, "again", FINDER), status=409, says="was deleted")
    refused(lambda: services().edit_vendor_item(item.vendor_item_id, {"uom": "CS"}, MANAGER), status=409, says="was deleted")
    again = new_sub()
    assert again.sub_id != sub.sub_id and [s["sub_id"] for s in queries.subs_for_items(["MDS2585H"])] == [again.sub_id]
    assert queries.subs_for_items(["MDS2585H"])[0]["vendor_items"] == []


def test_a_sub_with_orders_cant_be_deleted(ctx):
    sub, item = approved_with_vendor_item()
    order = services().record_order(item.vendor_item_id, {"site": SITE, "quantity": 3}, MANAGER)
    refused(lambda: services().delete_sub(sub.sub_id, "not needed", FINDER), status=409, says="void it before")
    services().void_order(order.order_id, "entered twice", MANAGER)
    assert services().delete_sub(sub.sub_id, "not needed", FINDER).deleted_by == FINDER


# --- sites, PO numbers and instructions (2026-10-27) -------------------------------------------

def test_an_order_is_for_a_site_and_keeps_its_po_number(ctx):
    _, item = approved_with_vendor_item()
    refused(lambda: services().record_order(item.vendor_item_id, {"quantity": 2}, MANAGER), says="Choose the site")
    order = services().record_order(item.vendor_item_id, {"site": OTHER_SITE, "quantity": 2, "po_number": "3000564756"},
                                    MANAGER)
    assert (order.site, order.po_number) == (OTHER_SITE, "3000564756")
    order = services().edit_order(order.order_id, {"site": SITE, "po_number": ""}, MANAGER)
    assert (order.site, order.po_number) == (SITE, None)
    assert [row[:4] for row in history("order", order.order_id)][-2:] == [
        ("edit", "site", OTHER_SITE, SITE), ("edit", "po_number", "3000564756", None)]


def test_an_instruction_belongs_to_the_infor_item_of_its_medline_item(ctx, sqlite_app):
    add_view_rows(sqlite_app, "vw_MedlineFillKillItemCollection", [
        {"Medline Item": "MDS2585H", "UM": "BX", "Infor Item": "999999"}])
    first = services().add_instruction("MDS2585H", "  Both sites: 2 BX of 88885  ", LEAD)
    assert (first.infor_item, first.medline_item, first.instruction, first.written_by) == (
        "999999", "MDS2585H", "Both sites: 2 BX of 88885", LEAD)
    assert services().add_instruction("NOT-IN-INFOR", "Use stock", LEAD).infor_item is None
    refused(lambda: services().add_instruction("MDS2585H", "", LEAD), says="Instruction is required")
