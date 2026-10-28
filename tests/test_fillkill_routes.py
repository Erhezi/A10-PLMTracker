"""The Fill/Kill Main page and its JSON API, through the real app on SQLite.

Stand-in tables hold the views' data (conftest.FILLKILL_VIEWS): two sites, like White Plains and
the test site, over 9/28-9/30.
"""

import csv
import io
import json
import os
import re
from datetime import date, datetime, timedelta

import pytest

from conftest import CARDINAL, MEDLINE, OWENS, add_view_rows, csrf_from, login, make_user

WP, TEST = "0001795146", "test site"


def qty(day, site, item, um, ordered, filled, lines):
    return {"Order Date": f"2026-09-{day}", "Sold-To": site, "Sold-To Name": "WHITE PLAINS" if site == WP else TEST,
            "Medline Item": item, "UM": um, "Customer Item #": "100339" if item == "DYND70294BH" else "108176",
            "Total Ordered Qty": ordered, "Total Filled Qty": filled, "Total Killed Qty": ordered - filled,
            "Total PO Line Count": lines}


def line(day, time, site, item, ordered, comment, reason, reason_date=None, so="1"):
    return {"Sold-To": site, "Sold-To Name": "WHITE PLAINS" if site == WP else TEST, "Ship-To Name": "4I",
            "Order Date": f"2026-09-{day}", "Order Time": time, "Sales Order #": so, "Order Line #": "10",
            "Item": item, "Order Qty": ordered, "UM": "EA", "Filled Qty": 0, "PO": "2600303592", "POLine": 8,
            "Internal Order Comments from SAP (Z106)": comment, "Reason": reason, "Reason Date": reason_date,
            "Is Test": int(site == TEST)}


@pytest.fixture
def app(sqlite_app):
    add_view_rows(sqlite_app, "vw_MedlineFillKillQtyAgg", [
        qty(28, WP, "DYND70294BH", "EA", 15, 0, 3),
        qty(30, WP, "DYND70294BH", "EA", 10, 0, 2),
        qty(30, TEST, "DYND70294BH", "EA", 5, 0, 1),
        qty(29, WP, "MDS2585H", "BX", 4, 1, 1),
        qty(29, WP, "MDS2585H", "CS", 2, 0, 1),
    ])
    add_view_rows(sqlite_app, "vw_MedlineFillKillItemCollection", [
        {"Medline Item": "DYND70294BH", "UM": "EA", "Customer Item #": "100339", "Item Description": "CUP,DENTURE",
         "Infor Item": "100339", "Infor Item Consistency": 1},
        {"Medline Item": "MDS2585H", "UM": "BX", "Customer Item #": "108176", "Item Description": "GLOVE",
         "Infor Item": "999999", "Infor Item Consistency": 0, "Item.Active": "Yes",
         "Item.Description": "GLOVE EXM MED LF", "Item.LongDescription": "GLOVE EXAM MEDIUM LATEX FREE",
         "CommodityCode": "4213-22-03", "CommodityCode.Description": "MEDICAL EXAM OR NON SURGICAL PROCEDURE GLOVES"},
    ])
    add_view_rows(sqlite_app, "vw_MedlineFillKill", [
        line(28, "09:00:00", WP, "DYND70294BH", 5, "MBO - ERD is 11/18/2026", "MBO", "2026-11-18", so="1"),
        line(30, "11:35:29", WP, "DYND70294BH", 5, "MBO - ERD is 11/30/2026", "MBO", "2026-11-30", so="2"),
        {**line(30, "10:00:00", TEST, "DYND70294BH", 5, "OUT OF STOCK - ETA is 10/02/2026", "OUT_OF_STOCK", "2026-10-02",
                so="TEST3"), "Test Purpose": "Sites: a real line copied under a second site."},
        line(29, "08:00:00", WP, "MDS2585H", 4, "Allocation limit has been reached", "ALLOCATION", so="4"),
    ])
    add_view_rows(sqlite_app, "vw_ContractLineSearch", [
        {"vendor_id": "1", "vendor_name": "CARDINAL HEALTH", "vendor_item": "88885", "vendor_item_stripped": "88885",
         "manufacturer_number": "N88", "manufacturer_number_stripped": "N88", "description": "GLOVE EXAM NITRILE",
         "uom": "BX", "qoe": 100, "infor_item": "200001", "item_type": "Itemmast", "contract": "C1", "is_mhs": "Yes"},
        {"vendor_id": "1", "vendor_name": "CARDINAL HEALTH", "vendor_item": "88885", "vendor_item_stripped": "88885",
         "manufacturer_number": "N88", "manufacturer_number_stripped": "N88", "description": "GLOVE EXAM NITRILE",
         "uom": "BX", "qoe": 100, "infor_item": "200001", "item_type": "Itemmast", "contract": "C2", "is_mhs": "No"},
        # A "Special" line: its item number isn't an Infor item number.
        {"vendor_id": "1000931", "vendor_name": "MEDLINE INDUSTRIES INC", "vendor_item": "DYNJAA04",
         "vendor_item_stripped": "DYNJAA04", "description": "LINE GAS SMPL", "uom": "CA", "qoe": 50,
         "infor_item": "1296-DYNJAA04", "item_type": "Special", "contract": "C3", "is_mhs": "No"},
    ])
    return sqlite_app


def client(app, email, **roles):
    make_user(app, email, **roles)
    c = app.test_client()
    login(c, email)
    return c


def get(c, path, **params):
    response = c.get(path, query_string=params, headers={"X-Requested-With": "fetch"})
    return response.status_code, response.get_json()


def post(c, path, payload):
    token = csrf_from(c.get("/auth/register/pending").get_data(as_text=True))
    response = c.post(path, json=payload, headers={"X-Requested-With": "fetch", "X-CSRFToken": token})
    return response.status_code, response.get_json()


@pytest.fixture
def viewer(app):
    return client(app, "viewer@example.org", plm=None, fillkill=("viewer",))


@pytest.fixture
def finder_approver(app):
    return client(app, "nurse@example.org", plm=None, fillkill=("sub_finder", "sub_approver"))


@pytest.fixture
def finder_manager(app):
    return client(app, "mm@example.org", plm=None, fillkill=("sub_finder", "materials_manager"))


# --- the page --------------------------------------------------------------------------

def test_the_page_opens_on_the_latest_date_with_the_users_abilities(app, viewer):
    page = viewer.get("/fillkill/").get_data(as_text=True)
    config = json.loads(re.search(r'<script id="fk-config" type="application/json">(.*?)</script>', page, re.S).group(1))
    assert config["default"] == {"start": "2026-09-30", "end": "2026-09-30"}  # P4
    assert config["bounds"] == {"first": "2026-09-28", "last": "2026-09-30"}
    assert [s["name"] for s in config["sites"]] == ["WHITE PLAINS", "test site"]
    assert config["can"] == {"view": True, "add_sub": False, "review": False, "pick": False, "details": False, "order": False,
                             "instruct": False}
    assert 'aria-current="page">Main</a>' in page


def test_only_admins_see_what_the_database_lacks(app, viewer, monkeypatch):
    from app.fillkill import health
    monkeypatch.setattr(health, "check", lambda: [{"what": "FillKill.vw_Vendor is missing", "script": "13_contract_search.sql"}])
    admin = client(app, "boss@example.org", role="admin", plm=None, fillkill=("viewer",))
    page = admin.get("/fillkill/").get_data(as_text=True)
    assert "The database needs an update" in page and "db/fillkill/13_contract_search.sql" in page
    assert "The database needs an update" not in viewer.get("/fillkill/").get_data(as_text=True)


def test_a_user_without_a_fillkill_role_is_turned_away(app):
    plm_only = client(app, "plm@example.org")
    status, data = get(plm_only, "/fillkill/api/main")
    assert status == 403


# --- the main table ----------------------------------------------------------------------

def test_main_has_one_row_per_infor_item_summed_over_the_dates_and_sites(viewer):
    status, data = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-30")
    assert status == 200
    assert [r["infor_item"] for r in data["rows"]] == ["100339", "999999"]  # sorted by Infor item
    rows = {row["medline_items"][0]: row for row in data["rows"]}
    cup, glove = rows["DYND70294BH"], rows["MDS2585H"]
    [cup_pack] = cup["packagings"]
    assert cup_pack["quantities"] == [{"uom": "EA", "ordered": 30, "filled": 0, "killed": 30, "each": None}]
    assert cup["lines"] == 6
    assert cup["latest_reason"]["reason"] == "MBO"  # 11:35 at White Plains beats 10:00 at the test site
    [glove_pack] = glove["packagings"]
    assert [q["uom"] for q in glove_pack["quantities"]] == ["BX", "CS"]  # never added across UOMs
    assert glove["commodity_description"] == "MEDICAL EXAM OR NON SURGICAL PROCEDURE GLOVES"
    # Medline's customer item (108176) isn't the Infor item (999999): flagged beside the Medline item.
    assert (glove_pack["customer_item"], glove_pack["consistent"]) == ("108176", False)
    assert cup_pack["consistent"] is True
    assert data["counts"]["needs_subs"] == 2


def test_main_filters_by_site_and_defaults_to_the_latest_date(viewer):
    _, data = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-30", sites=TEST)
    assert [(r["medline_items"], r["lines"]) for r in data["rows"]] == [(["DYND70294BH"], 1)]
    assert data["rows"][0]["latest_reason"]["reason"] == "OUT_OF_STOCK"

    _, data = get(viewer, "/fillkill/api/main")
    assert data["scope"]["start"] == data["scope"]["end"] == "2026-09-30"
    assert [r["medline_items"] for r in data["rows"]] == [["DYND70294BH"]]


def test_bad_dates_are_refused(viewer):
    status, data = get(viewer, "/fillkill/api/main", start="09/28/2026")
    assert status == 400 and "2026-10-13" in data["message"]


# --- the whole flow, role by role ----------------------------------------------------------

CUP_ITEM = {"vendor_part": "88885", "vendor": "CARDINAL HEALTH", "vendor_id": CARDINAL, "description": "Denture cup",
            "uom": "bx", "qoe": "100"}


def test_nursing_enters_a_reference_sku_and_the_materials_manager_adds_a_vendor_item_and_orders(
        app, viewer, finder_approver, finder_manager):
    # Nursing (a Sub Approver) enters the Reference SKU and a note: approved, and picked as the
    # item's only approved sub (2026-10-15).
    status, data = post(finder_approver, "/fillkill/api/subs",
                        {"medline_item": "DYND70294BH", "reference_sku": "88885", "comment": "Same cup"})
    assert status == 201, data
    sub_id = data["sub"]["sub_id"]
    assert (data["sub"]["reference_sku"], data["sub"]["status"], data["sub"]["is_picked"], data["sub"]["vendor_items"]) == (
        "88885", "approved", True, [])

    _, main = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-30")
    row = next(r for r in main["rows"] if "DYND70294BH" in r["medline_items"])
    assert row["needs"] == ["needs_details", "needs_order"]  # nothing to order yet: the Materials Manager's
    assert main["counts"]["needs_details"] == 1

    # The Materials Manager adds a vendor item: a way to order it (2026-10-20).
    status, data = post(finder_manager, f"/fillkill/api/subs/{sub_id}/vendor-items", {"vendor_part": "88885", "uom": "BX"})
    assert status == 400 and "Vendor and Vendor ID (or 0000000: Vendor not available in system) are required" in data["message"]
    status, data = post(finder_manager, f"/fillkill/api/subs/{sub_id}/vendor-items", CUP_ITEM)
    assert status == 201, data
    item = data["vendor_item"]
    assert (item["sub_id"], item["vendor_part"], item["vendor_id"], item["uom"], item["qoe"]) == (sub_id, "88885", CARDINAL, "BX", 100)

    _, main = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-30")
    row = next(r for r in main["rows"] if "DYND70294BH" in r["medline_items"])
    assert row["needs"] == ["needs_order"]
    [pick] = row["picks"]
    assert (pick["reference_sku"], [v["vendor_part"] for v in pick["vendor_items"]]) == ("88885", ["88885"])
    # Its comments icon: how many, and the latest (2026-10-21).
    assert (pick["comments"], pick["latest_comment"]["comment"], pick["latest_comment"]["actor"]) == (
        1, "Same cup", "nurse@example.org")

    status, data = post(finder_manager, "/fillkill/api/orders", {"quantity": 30})
    assert status == 400 and "Which vendor item" in data["message"]
    status, data = post(finder_manager, "/fillkill/api/orders", {
        "vendor_item_id": item["vendor_item_id"], "site": WP, "quantity": 30, "ordered_dt": "2026-09-29T15:00",
        "expected_status": "approved",
        "uom": "CS",  # not the order's to say: the vendor item's
    })
    assert status == 201, data
    assert (data["order"]["vendor_part"], data["order"]["uom"], data["order"]["qoe"], data["order"]["vendor"],
            data["order"]["reference_sku"]) == ("88885", "BX", 100, "CARDINAL HEALTH", "88885")

    _, main = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-30")
    row = next(r for r in main["rows"] if "DYND70294BH" in r["medline_items"])
    assert (row["ordering_status"], row["needs"]) == ("ordered", ["ordered"])
    assert [(o["quantity"], o["uom"], o["ordered_dt"][:10]) for o in row["orders"]] == [(30, "BX", "2026-09-29")]
    # Killed 30 EA in these dates (an EA without Infor's QOE is 1); ordered 30 BX of 100 (2026-10-21).
    assert (row["killed_each"], row["sub_ordered_each"]) == (30.0, 3000.0)

    # Ordered on 9/29: it counts only for Fill/Kill dates that include 9/29 (S4, 2026-10-20; from
    # 10-15 it counted for any dates starting on or before it, so 9/28 alone said Ordered).
    _, main = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-29")
    row = next(r for r in main["rows"] if "DYND70294BH" in r["medline_items"])
    assert row["ordering_status"] == "ordered"
    for day in ("2026-09-28", "2026-09-30"):
        _, main = get(viewer, "/fillkill/api/main", start=day, end=day)
        row = next(r for r in main["rows"] if "DYND70294BH" in r["medline_items"])
        assert (row["ordering_status"], row["orders"], row["needs"]) == ("no order", [], ["needs_order"]), day

    _, panel = get(viewer, "/fillkill/api/item", item="DYND70294BH", start="2026-09-28", end="2026-09-30")
    assert panel["infor_item"] == "100339"
    assert [p["medline_item"] for p in panel["packagings"]] == ["DYND70294BH"]
    [sub] = [s for p in panel["packagings"] for s in p["subs"]]
    assert (sub["latest_comment"]["comment"], [v["vendor_part"] for v in sub["vendor_items"]]) == ("Same cup", ["88885"])
    # Sub History: the sub's steps, and its vendor items added (2026-10-20).
    assert [(h["entity"], h["action"], h["label"]) for h in panel["pick_history"]] == [
        ("vendoritem", "created", "88885: 88885 (CARDINAL HEALTH, BX)"), ("sub", "pick", "88885"),
        ("sub", "status", "88885"), ("sub", "created", "88885")]
    assert len(panel["orders"]) == 1 and len(panel["lines"]) == 3
    assert [l["test_purpose"] for l in panel["lines"] if l["is_test"]] == ["Sites: a real line copied under a second site."]
    assert panel["details"]["description"] == "CUP,DENTURE"

    _, history = get(viewer, f"/fillkill/api/history/sub/{sub_id}")
    assert [(h["entity"], h["action"]) for h in history["history"]] == [
        ("vendoritem", "created"), ("sub", "pick"), ("sub", "status"), ("sub", "comment"), ("sub", "created")]
    _, history = get(viewer, f"/fillkill/api/history/vendoritem/{item['vendor_item_id']}")
    assert [(h["action"], h["actor"]) for h in history["history"]] == [("created", "mm@example.org")]

    _, library = get(viewer, "/fillkill/api/subs", status="approved")
    assert [(s["reference_sku"], len(s["vendor_items"])) for s in library["subs"]] == [("88885", 1)]
    # The orders section on Main: by the order's own date, with dates of its own.
    _, orders = get(viewer, "/fillkill/api/orders", start="2026-09-29", end="2026-09-29")
    assert [o["quantity"] for o in orders["orders"]] == [30]
    # What the orders table shows and searches (2026-10-20): the Infor item, the vendor part ordered
    # and the sub's Reference SKU, the vendor ID the order was placed with.
    [order] = orders["orders"]
    assert (order["medline_infor_item"], order["vendor_part"], order["reference_sku"], order["vendor_id"], order["vendor"],
            order["qoe"], order["vendor_item_id"]) == ("100339", "88885", "88885", CARDINAL, "CARDINAL HEALTH", 100,
                                                       item["vendor_item_id"])
    _, orders = get(viewer, "/fillkill/api/orders", start="2026-09-30", end="2026-10-01")
    assert orders["orders"] == []
    _, orders = get(viewer, "/fillkill/api/orders")  # default: the last 30 days, today included
    assert date.fromisoformat(orders["end"]) - date.fromisoformat(orders["start"]) == timedelta(days=29)


ITEM_PAYLOAD = {"vendor_part": "OM1", "vendor": "OWENS & MINOR", "vendor_id": OWENS, "uom": "CS"}


@pytest.mark.parametrize("who, path, payload, allowed", [
    ("viewer", "/fillkill/api/subs", {"medline_item": "DYND70294BH", "reference_sku": "P"}, False),
    ("finder_manager", "/fillkill/api/subs", {"medline_item": "DYND70294BH", "reference_sku": "P"}, True),
    ("finder_manager", "/fillkill/api/subs/{sub}/status", {"status": "approved"}, False),
    ("finder_manager", "/fillkill/api/subs/{sub}/comments", {"comment": "hi"}, False),
    ("finder_approver", "/fillkill/api/subs/{sub}/comments", {"comment": "hi"}, True),
    ("finder_approver", "/fillkill/api/subs/{sub}/edit", {"reference_sku": "OM2"}, True),
    ("viewer", "/fillkill/api/subs/{sub}/vendor-items", ITEM_PAYLOAD, False),
    ("finder_manager", "/fillkill/api/subs/{sub}/vendor-items", {**ITEM_PAYLOAD, "uom": "EA"}, True),
    ("viewer", "/fillkill/api/vendor-items/{item}/edit", {"uom": "EA"}, False),
    ("finder_manager", "/fillkill/api/vendor-items/{item}/edit", {"uom": "EA"}, True),
    ("finder_manager", "/fillkill/api/vendor-items/{item}/delete", {"reason": "no longer sold"}, True),
    ("finder_approver", "/fillkill/api/orders", {"vendor_item_id": "{item}", "site": WP, "quantity": 1}, False),
    ("viewer", "/fillkill/api/subs/{sub}/pick", {}, False),
    ("viewer", "/fillkill/api/subs/{sub}/delete", {"reason": "dup"}, False),
    ("finder_manager", "/fillkill/api/subs/{sub}/delete", {"reason": "dup"}, True),
])
def test_each_action_needs_its_role(app, request, finder_approver, who, path, payload, allowed):
    # A Sub Finder's sub: pending review (nursing's would be approved and picked), with a vendor item.
    manager = request.getfixturevalue("finder_manager")
    _, data = post(manager, "/fillkill/api/subs", {"medline_item": "MDS2585H", "reference_sku": "OM1"})
    sub_id = data["sub"]["sub_id"]
    _, data = post(manager, f"/fillkill/api/subs/{sub_id}/vendor-items", ITEM_PAYLOAD)
    ids = {"{sub}": sub_id, "{item}": data["vendor_item"]["vendor_item_id"]}
    actor = request.getfixturevalue(who)
    payload = {k: ids.get(v, v) if isinstance(v, str) else v for k, v in payload.items()}
    for key, value in ids.items():
        path = path.replace(key, str(value))
    status, data = post(actor, path, payload)
    if allowed:
        assert status in (200, 201), data
    else:
        assert status == 403, data
        assert data["error"] == "forbidden"


def test_materials_managers_pick_and_unpick_too(app):
    # Picking among the approved subs is the Sub Approver's and the Materials Manager's (2026-10-21);
    # the status and the subs' comments stay the Sub Approver's.
    nurse = client(app, "nurse4@example.org", plm=None, fillkill=("sub_approver",))
    manager = client(app, "mm4@example.org", plm=None, fillkill=("materials_manager",))
    finder = client(app, "finder4@example.org", plm=None, fillkill=("sub_finder",))
    _, data = post(nurse, "/fillkill/api/subs", {"medline_item": "MDS2585H", "reference_sku": "OM1"})
    first = data["sub"]["sub_id"]  # approved and picked: the only approved one
    _, data = post(nurse, "/fillkill/api/subs", {"medline_item": "MDS2585H", "reference_sku": "OM2"})
    second = data["sub"]["sub_id"]  # approved
    status, data = post(manager, f"/fillkill/api/subs/{first}/unpick", {"expected_status": "approved"})
    assert (status, data["sub"]["is_picked"]) == (200, False), data
    status, data = post(manager, f"/fillkill/api/subs/{second}/pick", {"expected_status": "approved"})
    assert (status, data["sub"]["is_picked"]) == (200, True), data
    _, data = get(manager, f"/fillkill/api/history/sub/{second}")
    assert (data["history"][0]["action"], data["history"][0]["actor"]) == ("pick", "mm4@example.org")
    status, data = post(manager, f"/fillkill/api/subs/{second}/status", {"status": "hold"})
    assert status == 403 and "Only Sub Approvers can review or comment on subs." in data["message"]
    assert post(manager, f"/fillkill/api/subs/{second}/comments", {"comment": "ok"})[0] == 403
    status, data = post(finder, f"/fillkill/api/subs/{first}/pick", {})
    assert status == 403 and "Only Sub Approvers, Materials Managers and MM Leads can pick" in data["message"]
    assert (page_config(manager)["can"]["pick"], page_config(manager)["can"]["review"]) == (True, False)


def test_rule_errors_and_conflicts_come_back_as_messages(app, finder_approver, finder_manager):
    status, data = post(finder_approver, "/fillkill/api/subs", {"medline_item": "NOT-KILLED", "reference_sku": "P"})
    assert status == 404 and "isn't a Medline item" in data["message"]

    _, data = post(finder_manager, "/fillkill/api/subs", {"medline_item": "MDS2585H", "reference_sku": "P"})
    sub_id = data["sub"]["sub_id"]  # a Sub Finder's: pending review
    status, data = post(finder_approver, f"/fillkill/api/subs/{sub_id}/pick", {})
    assert status == 400 and "Only an approved sub" in data["message"]

    post(finder_approver, f"/fillkill/api/subs/{sub_id}/status", {"status": "rejected"})
    status, data = post(finder_approver, f"/fillkill/api/subs/{sub_id}/status",
                        {"status": "approved", "expected_status": "pending_review"})
    assert status == 409 and "nurse@example.org" in data["message"]

    _, data = post(finder_manager, f"/fillkill/api/subs/{sub_id}/vendor-items", ITEM_PAYLOAD)
    status, data = post(finder_manager, "/fillkill/api/orders", {"vendor_item_id": data["vendor_item"]["vendor_item_id"], "site": WP,
                                                       "quantity": 1})
    assert status == 409 and "isn't picked" in data["message"]
    status, data = post(finder_manager, "/fillkill/api/vendor-items/999/edit", {"uom": "EA"})
    assert status == 404 and "That vendor item no longer exists" in data["message"]
    assert post(finder_manager, "/fillkill/api/vendor-items/1/move", {})[0] == 404
    assert post(finder_manager, f"/fillkill/api/subs/{sub_id}/details", {"vendor": "Owens"})[0] == 404  # gone: vendor items


def test_actions_need_the_csrf_token(app, finder_approver):
    response = finder_approver.post("/fillkill/api/subs", json={"medline_item": "MDS2585H", "reference_sku": "P"},
                                    headers={"X-Requested-With": "fetch"})
    assert response.status_code == 401
    assert response.get_json()["error"] == "login_expired"


# --- contract search ------------------------------------------------------------------------

def test_contract_search_for_whoever_fills_in_the_vendor_details(app, viewer, finder_approver):
    assert get(viewer, "/fillkill/api/contract-lines", q="88885")[0] == 403
    # The vendor details are the Materials Manager's and the Sub Finder's (2026-10-15): theirs
    # are the lookups, not nursing's (2026-10-19).
    manager = client(app, "mm4@example.org", plm=None, fillkill=("materials_manager",))
    nurse = client(app, "nurse4@example.org", plm=None, fillkill=("sub_approver",))
    for path, params in (("/fillkill/api/contract-lines", {"q": "88885"}), ("/fillkill/api/vendor", {"id": CARDINAL}),
                         ("/fillkill/api/vendors", {"q": "cardinal"})):
        assert get(manager, path, **params)[0] == 200, path
        assert get(nurse, path, **params)[0] == 403, path
    _, data = get(finder_approver, "/fillkill/api/contract-lines", q="88")
    assert data["lines"] == [] and "at least 3" in data["message"]
    _, data = get(finder_approver, "/fillkill/api/contract-lines", q="888-85")
    assert [(r["vendor_name"], r["vendor_item"], r["contracts"]) for r in data["lines"]] == [("CARDINAL HEALTH", "88885", 2)]
    # Vendor ID, Infor item, and MHS when any of its contracts is MHS's (C1 is, C2 isn't).
    [glove] = data["lines"]
    assert (glove["vendor_id"], glove["infor_item"], glove["is_mhs"], glove["mhs_contracts"]) == ("1", "200001", "Yes", 1)
    _, data = get(finder_approver, "/fillkill/api/contract-lines", q="DYNJAA04")
    [special] = data["lines"]
    assert (special["vendor_id"], special["infor_item"], special["is_mhs"]) == ("1000931", None, "No")
    _, data = get(finder_approver, "/fillkill/api/contract-lines", q="nitrile glove")
    assert [r["vendor_item"] for r in data["lines"]] == ["88885"]
    _, data = get(finder_approver, "/fillkill/api/contract-lines", q="glove 7.5%")
    assert data["lines"] == []
    assert data["more"] is False


def test_contract_search_by_several_words_and_by_infor_item(app, finder_approver):
    lines = lambda q: [(r["vendor_name"], r["vendor_item"]) for r in get(finder_approver, "/fillkill/api/contract-lines", q=q)[1]["lines"]]
    # Every word somewhere in the line: its part number, description or vendor (2026-10-19).
    assert lines("88885 nitrile") == lines("NITRILE 888-85") == lines("cardinal 88885") == [("CARDINAL HEALTH", "88885")]
    assert lines("88885 owens") == []
    assert lines("88885 bx") == [("CARDINAL HEALTH", "88885")] and lines("88885 cs") == []  # a word can be the UOM
    assert lines("DYNJ AA04") == [("MEDLINE INDUSTRIES INC", "DYNJAA04")]  # read as one part number
    # The Infor item number finds its lines.
    assert lines("200001") == [("CARDINAL HEALTH", "88885")]


def test_vendor_search_finds_the_vendor_id_from_a_name(app, viewer, finder_approver):
    assert get(viewer, "/fillkill/api/vendors", q="cardinal")[0] == 403
    found = lambda q: [v["vendor_id"] for v in get(finder_approver, "/fillkill/api/vendors", q=q)[1]["vendors"]]
    assert found("c") == []  # two characters at least
    assert found("cardinal") == found("CARD HEALTH") == [CARDINAL]
    # Infor's legal name and search name count too, and * stands for anything inside a word.
    assert found("distribution") == found("owens and") == [OWENS]
    assert found("card*prod") == [CARDINAL]
    # A number also finds vendor IDs starting with it; active vendors first.
    assert found("1000") == [CARDINAL, MEDLINE, OWENS, "1000099"]
    [old] = get(finder_approver, "/fillkill/api/vendors", q="old supply")[1]["vendors"]
    assert (old["vendor_name"], old["legal_name"], old["vendor_status"]) == ("OLD SUPPLY CO", "OLD SUPPLY COMPANY", "Inactive")


def test_a_vendor_item_without_an_infor_vendor_uses_0000000(app, viewer, finder_approver, finder_manager):
    _, data = post(finder_approver, "/fillkill/api/subs", {"medline_item": "DYND70294BH", "reference_sku": "LS-1"})
    sub_id = data["sub"]["sub_id"]
    _, main = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-30")
    row = next(r for r in main["rows"] if "DYND70294BH" in r["medline_items"])
    assert row["needs"] == ["needs_details", "needs_order"]
    assert [s["reference_sku"] for s in get(viewer, "/fillkill/api/subs", needs_details="1")[1]["subs"]] == ["LS-1"]
    # Infor has no such vendor: 0000000 says so, on purpose; Infor isn't asked about it.
    assert get(finder_approver, "/fillkill/api/vendor", id="0000000")[1]["vendor"] is None
    status, data = post(finder_manager, f"/fillkill/api/subs/{sub_id}/vendor-items",
                        {"vendor_part": "LS-1", "vendor": "Local Supply", "vendor_id": "0000000", "uom": "EA"})
    assert (status, data["vendor_item"]["vendor_id"]) == (201, "0000000"), data
    _, main = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-30")
    row = next(r for r in main["rows"] if "DYND70294BH" in r["medline_items"])
    assert row["needs"] == ["needs_order"]
    assert get(viewer, "/fillkill/api/subs", needs_details="1")[1]["subs"] == []
    page = viewer.get("/fillkill/").get_data(as_text=True)
    assert '"noVendor": {"id": "0000000", "label": "Vendor not available in system"}' in page


def page_config(c) -> dict:
    page = c.get("/fillkill/").get_data(as_text=True)
    return json.loads(re.search(r'<script id="fk-config" type="application/json">(.*?)</script>', page, re.S).group(1))


def test_the_live_server_opens_on_today(app, viewer, monkeypatch):
    # FILLKILL_OPEN_ON: "today" on the server (ProductionConfig), the latest day with lines locally.
    from app.config import DevelopmentConfig, ProductionConfig
    from app.fillkill import routes
    if "FILLKILL_OPEN_ON" not in os.environ:
        assert (DevelopmentConfig.FILLKILL_OPEN_ON, ProductionConfig.FILLKILL_OPEN_ON) == ("latest", "today")
    monkeypatch.setattr(routes, "now_ny_naive", lambda: datetime(2026, 10, 20, 9, 0))
    assert page_config(viewer)["default"] == {"start": "2026-09-30", "end": "2026-09-30"}
    app.config["FILLKILL_OPEN_ON"] = "today"
    config = page_config(viewer)
    assert config["default"] == {"start": "2026-10-20", "end": "2026-10-20"} and config["today"] == "2026-10-20"


def test_the_medline_item_itself_from_medline_is_refused_as_a_vendor_item(app, finder_approver):
    _, data = post(finder_approver, "/fillkill/api/subs", {"medline_item": "DYND70294BH", "reference_sku": "DYND70294"})
    sub_id = data["sub"]["sub_id"]
    itself = {"vendor_part": " dynd70294bh ", "vendor": "MEDLINE INDUSTRIES INC", "vendor_id": MEDLINE, "uom": "EA"}
    status, data = post(finder_approver, f"/fillkill/api/subs/{sub_id}/vendor-items", itself)
    assert status == 400 and "dynd70294bh from Medline (vendor ID 1000931) is DYND70294BH itself" in data["message"]
    # Another of Medline's parts is a sub, and it can't be corrected into the item itself.
    status, data = post(finder_approver, f"/fillkill/api/subs/{sub_id}/vendor-items", {**itself, "vendor_part": "DYND70294"})
    assert status == 201, data
    status, data = post(finder_approver, f"/fillkill/api/vendor-items/{data['vendor_item']['vendor_item_id']}/edit",
                        {"vendor_part": "DYND70294BH"})
    assert status == 400 and "itself" in data["message"]
    # From a vendor that isn't Medline, the same number is someone else's part.
    status, data = post(finder_approver, f"/fillkill/api/subs/{sub_id}/vendor-items", {**itself, "vendor": "Cardinal", "vendor_id": CARDINAL})
    assert (status, data["vendor_item"]["vendor_part"]) == (201, "dynd70294bh"), data


def test_a_uom_typed_another_way_is_saved_as_infors_and_spaces_go(app, finder_approver, finder_manager):
    add_view_rows(app, "vw_UomAlias", [
        {"external_value": "CS", "lawson_value": "CA"}, {"external_value": "VL", "lawson_value": "VI"},
        # Listed with two Infor UOMs: left as typed.
        {"external_value": "ZZ", "lawson_value": "EA"}, {"external_value": "ZZ", "lawson_value": "BX"},
    ])
    config = page_config(finder_manager)
    assert config["uomAliases"] == {"CS": "CA", "VL": "VI"}
    assert config["medlineVendorIds"] == ["1000931", "1017968", "1017969", "1037888"]
    _, data = post(finder_approver, "/fillkill/api/subs", {"medline_item": "MDS2585H", "reference_sku": "  OM1 "})
    assert data["sub"]["reference_sku"] == "OM1"
    sub_id = data["sub"]["sub_id"]
    item = {"vendor_part": "  OM-1-CS ", "vendor": " OWENS & MINOR ", "vendor_id": f" {OWENS} ", "uom": " cs ", "qoe": " 100 "}
    status, data = post(finder_manager, f"/fillkill/api/subs/{sub_id}/vendor-items", item)
    saved = data["vendor_item"]
    assert (status, saved["vendor_part"], saved["vendor"], saved["vendor_id"], saved["uom"], saved["qoe"]) == (
        201, "OM-1-CS", "OWENS & MINOR", OWENS, "CA", 100)
    # The same vendor item with its UOM typed Infor's way is the same one.
    status, data = post(finder_manager, f"/fillkill/api/subs/{sub_id}/vendor-items", {**item, "uom": "CA"})
    assert status == 409, data
    url = f"/fillkill/api/vendor-items/{saved['vendor_item_id']}/edit"
    assert post(finder_manager, url, {"uom": "vl"})[1]["vendor_item"]["uom"] == "VI"
    assert post(finder_manager, url, {"uom": "zz"})[1]["vendor_item"]["uom"] == "ZZ"


def test_without_the_uom_view_uoms_stay_as_typed(app, finder_approver):
    # As on O2 before 13_contract_search.sql adds FillKill.vw_UomAlias: nothing is refused for it.
    from app import db
    with app.app_context():
        with db.engine.begin() as conn:
            conn.exec_driver_sql('DROP TABLE "FillKill"."vw_UomAlias"')
    assert page_config(finder_approver)["uomAliases"] == {}
    _, data = post(finder_approver, "/fillkill/api/subs", {"medline_item": "MDS2585H", "reference_sku": "OM1"})
    status, data = post(finder_approver, f"/fillkill/api/subs/{data['sub']['sub_id']}/vendor-items",
                        {"vendor_part": "OM-1", "vendor": "Owens", "vendor_id": OWENS, "uom": "cs"})
    assert (status, data["vendor_item"]["uom"]) == (201, "CS")


def test_the_vendor_name_follows_the_vendor_id(app, finder_approver):
    # The ID leads (2026-10-21): an Infor vendor ID is saved with Infor's name for it, whatever was typed.
    _, data = post(finder_approver, "/fillkill/api/subs", {"medline_item": "MDS2585H", "reference_sku": "OM1"})
    status, data = post(finder_approver, f"/fillkill/api/subs/{data['sub']['sub_id']}/vendor-items",
                        {"vendor_part": "OM-1", "vendor": "Owens", "vendor_id": OWENS, "uom": "BX"})
    assert (status, data["vendor_item"]["vendor"]) == (201, "OWENS & MINOR"), data
    url = f"/fillkill/api/vendor-items/{data['vendor_item']['vendor_item_id']}/edit"
    # A corrected ID brings its own name, even with the old one sent along.
    status, data = post(finder_approver, url, {"vendor_id": CARDINAL, "vendor": "OWENS & MINOR"})
    assert (status, data["vendor_item"]["vendor"], data["vendor_item"]["vendor_id"]) == (200, "CARDINAL HEALTH", CARDINAL), data
    # A name alone can't move it to another vendor: the ID is what to change.
    status, data = post(finder_approver, url, {"vendor": "Owens"})
    assert status == 400 and "Infor calls 1000001 CARDINAL HEALTH" in data["message"]
    # With 0000000, Infor has no name for it: theirs, as typed.
    status, data = post(finder_approver, url, {"vendor_id": "0000000", "vendor": "Local Supply"})
    assert (status, data["vendor_item"]["vendor"]) == (200, "Local Supply"), data
    _, data = get(finder_approver, url.replace("/vendor-items/", "/history/vendoritem/").replace("/edit", ""))
    assert sorted((h["field"], h["from_value"], h["to_value"]) for h in data["history"] if h["action"] == "edit") == [
        ("vendor", "CARDINAL HEALTH", "Local Supply"), ("vendor", "OWENS & MINOR", "CARDINAL HEALTH"),
        ("vendor_id", CARDINAL, "0000000"), ("vendor_id", OWENS, CARDINAL)]


def test_without_the_vendor_view_a_vendor_id_is_refused_with_a_message_not_a_server_error(app, finder_approver):
    # As on O2 before 13_contract_search.sql adds FillKill.vw_Vendor.
    from app import db
    with app.app_context():
        with db.engine.begin() as conn:
            conn.exec_driver_sql('DROP TABLE "FillKill"."vw_Vendor"')
    status, data = get(finder_approver, "/fillkill/api/vendor", id=CARDINAL)
    assert status == 503 and "can't be read right now" in data["message"]
    status, data = get(finder_approver, "/fillkill/api/vendors", q="cardinal")
    assert status == 503 and "can't be read right now" in data["message"]
    # Subs are added as usual; a vendor item with Infor's vendor ID waits, one with 0000000 doesn't.
    status, data = post(finder_approver, "/fillkill/api/subs", {"medline_item": "MDS2585H", "reference_sku": "88885"})
    assert status == 201
    sub_id = data["sub"]["sub_id"]
    item = {"vendor_part": "88885", "vendor": "CARDINAL HEALTH", "vendor_id": CARDINAL, "uom": "BX"}
    status, data = post(finder_approver, f"/fillkill/api/subs/{sub_id}/vendor-items", item)
    assert status == 503 and "Try again later" in data["message"]
    status, data = post(finder_approver, f"/fillkill/api/subs/{sub_id}/vendor-items", {**item, "vendor_id": "0000000"})
    assert status == 201


def test_vendor_lookup_and_the_library_finds_subs_by_their_vendor_items(app, viewer, finder_approver):
    assert get(viewer, "/fillkill/api/vendor", id=CARDINAL)[0] == 403
    _, data = get(finder_approver, "/fillkill/api/vendor", id=CARDINAL)
    assert data["vendor"] == {"vendor_id": CARDINAL, "vendor_name": "CARDINAL HEALTH", "vendor_status": "Active"}
    assert get(finder_approver, "/fillkill/api/vendor", id="9999999")[1]["vendor"] is None
    assert get(finder_approver, "/fillkill/api/vendor", id="Cardinal")[1]["vendor"] is None  # not an ID
    # The library finds a sub by its vendor items' vendor ID, vendor, part, manufacturer part.
    _, data = post(finder_approver, "/fillkill/api/subs", {"medline_item": "MDS2585H", "reference_sku": "N88"})
    post(finder_approver, f"/fillkill/api/subs/{data['sub']['sub_id']}/vendor-items",
         {"vendor_part": "88885", "vendor": "CARDINAL HEALTH", "vendor_id": CARDINAL, "uom": "BX", "manufacturer_part": "N-88"})
    _, other = post(finder_approver, "/fillkill/api/subs", {"medline_item": "MDS2585H", "reference_sku": "OM1"})
    for q in (CARDINAL, "cardinal", "888-85", "n88", "N88"):
        assert [s["reference_sku"] for s in get(viewer, "/fillkill/api/subs", q=q)[1]["subs"]] == ["N88"], q
    status, data = post(finder_approver, f"/fillkill/api/subs/{other['sub']['sub_id']}/vendor-items",
                        {"vendor_part": "X", "vendor": "X", "vendor_id": "9999999", "uom": "EA"})
    assert status == 400 and "isn't in Infor's vendor list" in data["message"]


def test_library_search_ignores_dashes_spaces_dots_and_slashes(app, viewer, finder_approver):
    post(finder_approver, "/fillkill/api/subs", {"medline_item": "MDS2585H", "reference_sku": "OM-12.5/A"})
    for q in ("om125a", "OM-12.5", "om 12", "mds2585"):
        _, data = get(viewer, "/fillkill/api/subs", q=q)
        assert [s["reference_sku"] for s in data["subs"]] == ["OM-12.5/A"], q
    _, data = get(viewer, "/fillkill/api/subs", q="om13")
    assert data["subs"] == []


def test_packagings_of_one_infor_item_share_a_row_and_see_each_others_subs(app, viewer, finder_approver):
    # MDS2585HX (case) and MDS2585HZ: other Medline items of Infor item 999999, like MDS2585H.
    # MDS2585HZ was killed only on 9/20, outside the dates below.
    add_view_rows(app, "vw_MedlineFillKillItemCollection", [
        {"Medline Item": "MDS2585HX", "UM": "CS", "Customer Item #": "108176", "Infor Item": "999999",
         "Item Description": "GLOVE CASE", "Item.UOMConversion": 1000},
        {"Medline Item": "MDS2585HZ", "UM": "EA", "Customer Item #": "999999", "Infor Item": "999999",
         "Item Description": "GLOVE EACH", "Item.UOMConversion": 1},
    ])
    add_view_rows(app, "vw_MedlineFillKillQtyAgg", [qty(29, WP, "MDS2585HX", "CS", 1, 0, 1),
                                                    qty(20, WP, "MDS2585HZ", "EA", 9, 0, 1)])

    # Nursing's entries: approved on entry.
    post(finder_approver, "/fillkill/api/subs", {"medline_item": "MDS2585H", "reference_sku": "88885"})
    post(finder_approver, "/fillkill/api/subs", {"medline_item": "MDS2585HZ", "reference_sku": "OM-9"})

    _, main = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-30")
    glove = next(r for r in main["rows"] if r["infor_item"] == "999999")
    assert glove["medline_items"] == ["MDS2585H", "MDS2585HX"]  # killed in the range; HZ isn't
    assert glove["subs_status"]["approved"] == 1  # the one on MDS2585H
    # Approved on MDS2585HZ, a packaging not killed in these dates: signalled.
    assert [(a["medline_item"], a["reference_sku"]) for a in glove["approved_other_packagings"]] == [("MDS2585HZ", "OM-9")]

    _, panel = get(viewer, "/fillkill/api/item", item="MDS2585HX", start="2026-09-28", end="2026-09-30")
    assert panel["infor_item"] == "999999"
    packs = {p["medline_item"]: p for p in panel["packagings"]}
    assert [p["medline_item"] for p in panel["packagings"]] == ["MDS2585H", "MDS2585HX", "MDS2585HZ"]  # killed first
    assert (packs["MDS2585HZ"]["killed_in_range"], packs["MDS2585HX"]["killed_in_range"]) == (False, True)
    # Each UOM with Infor's QOE, for the forms' "for MDS2585HX (CS/1000)" (2026-10-21); none known for MDS2585H's BX.
    assert [(p["medline_item"], p["uom_qoes"]) for p in panel["packagings"]] == [
        ("MDS2585H", [{"uom": "BX", "qoe": None}]), ("MDS2585HX", [{"uom": "CS", "qoe": 1000}]),
        ("MDS2585HZ", [{"uom": "EA", "qoe": 1}])]
    assert [(o["reference_sku"], o["status"], o["approved_by"]) for o in packs["MDS2585HX"]["other_subs"]] == [
        ("88885", "approved", "nurse@example.org"), ("OM-9", "approved", "nurse@example.org"),
    ]

    # Added for MDS2585HX too (approved: nursing's), flagged as approved on MDS2585H as well.
    post(finder_approver, "/fillkill/api/subs", {"medline_item": "MDS2585HX", "reference_sku": "88885"})
    _, panel = get(viewer, "/fillkill/api/item", item="MDS2585H", start="2026-09-28", end="2026-09-30")
    packs = {p["medline_item"]: p for p in panel["packagings"]}
    [here] = packs["MDS2585HX"]["subs"]
    assert (here["status"], here["is_picked"]) == ("approved", True)
    assert [o["medline_item"] for o in here["approved_elsewhere"]] == ["MDS2585H"]
    assert [o["reference_sku"] for o in packs["MDS2585HX"]["other_subs"]] == ["OM-9"]


def test_nursing_and_the_materials_manager_each_do_their_part(app):
    nurse = client(app, "nurse2@example.org", plm=None, fillkill=("sub_approver",))
    manager = client(app, "mm2@example.org", plm=None, fillkill=("materials_manager",))
    status, data = post(manager, "/fillkill/api/subs", {"medline_item": "MDS2585H", "reference_sku": "OM1"})
    assert status == 403
    status, data = post(nurse, "/fillkill/api/subs", {"medline_item": "MDS2585H", "reference_sku": "OM1"})
    assert (status, data["sub"]["status"]) == (201, "approved")
    sub_id = data["sub"]["sub_id"]
    item = {"vendor_part": "OM-1-CS", "vendor": "OWENS & MINOR", "uom": "bx"}
    status, data = post(nurse, f"/fillkill/api/subs/{sub_id}/vendor-items", {**item, "vendor_id": OWENS})
    assert status == 403 and "vendor items" in data["message"]
    status, data = post(manager, f"/fillkill/api/subs/{sub_id}/vendor-items", item)
    assert status == 400 and "Vendor ID (or 0000000" in data["message"]  # 2026-10-19
    status, data = post(manager, f"/fillkill/api/subs/{sub_id}/vendor-items", {**item, "vendor_id": OWENS})
    assert (status, data["vendor_item"]["vendor"], data["vendor_item"]["vendor_id"], data["vendor_item"]["uom"]) == (
        201, "OWENS & MINOR", OWENS, "BX")
    vendor_item_id = data["vendor_item"]["vendor_item_id"]
    assert post(manager, f"/fillkill/api/subs/{sub_id}/edit", {"reference_sku": "OM-1"})[0] == 403
    status, data = post(nurse, f"/fillkill/api/subs/{sub_id}/edit", {"reference_sku": "OM-1"})
    assert (status, data["sub"]["reference_sku"]) == (200, "OM-1")
    # The vendor item is the Materials Manager's to correct or delete.
    assert post(nurse, f"/fillkill/api/vendor-items/{vendor_item_id}/edit", {"uom": "CS"})[0] == 403
    status, data = post(manager, f"/fillkill/api/vendor-items/{vendor_item_id}/edit", {"uom": "cs"})
    assert (status, data["vendor_item"]["uom"]) == (200, "CS")
    status, data = post(manager, f"/fillkill/api/vendor-items/{vendor_item_id}/delete", {"reason": "Owens stopped it"})
    assert status == 200
    _, data = get(manager, f"/fillkill/api/history/sub/{sub_id}")
    assert [(h["entity"], h["action"], h["field"]) for h in data["history"]][:4] == [
        ("vendoritem", "delete", None), ("vendoritem", "edit", "uom"), ("sub", "edit", "reference_sku"),
        ("vendoritem", "created", None)]


def test_deleting_a_sub_hides_it_and_shows_in_sub_history(app, viewer, finder_approver):
    manager = client(app, "mm3@example.org", plm=None, fillkill=("materials_manager",))
    _, data = post(finder_approver, "/fillkill/api/subs", {"medline_item": "MDS2585H", "reference_sku": "OM1"})
    sub_id = data["sub"]["sub_id"]
    post(finder_approver, f"/fillkill/api/subs/{sub_id}/unpick", {})  # entered approved and picked
    status, data = post(manager, f"/fillkill/api/subs/{sub_id}/delete", {"reason": "dup"})
    assert status == 403 and "delete" in data["message"]
    status, data = post(finder_approver, f"/fillkill/api/subs/{sub_id}/delete", {"reason": ""})
    assert status == 400 and "Reason is required" in data["message"]
    status, data = post(finder_approver, f"/fillkill/api/subs/{sub_id}/delete",
                        {"reason": "Owens doesn't carry it any more", "expected_status": "approved"})
    assert status == 200 and data["sub"]["sub_id"] == sub_id

    _, panel = get(viewer, "/fillkill/api/item", item="MDS2585H", start="2026-09-28", end="2026-09-30")
    assert [s for p in panel["packagings"] for s in p["subs"]] == []
    assert [(h["action"], h["label"], h["comment"]) for h in panel["pick_history"]][0] == (
        "delete", "OM1", "Owens doesn't carry it any more")
    _, library = get(viewer, "/fillkill/api/subs")
    assert library["subs"] == []
    _, main = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-30")
    glove = next(r for r in main["rows"] if "MDS2585H" in r["medline_items"])
    assert sum(glove["subs_status"].values()) == 0 and "needs_subs" in glove["needs"]


# --- the Subs page ------------------------------------------------------------------------------

def test_the_subs_page_is_a_reference_with_filters_and_an_export(app, viewer, finder_approver, finder_manager):
    page = viewer.get("/fillkill/subs").get_data(as_text=True)
    assert 'id="fk-subs-rows"' in page and ">Subs</a>" in page  # its own page, in the module's menu
    assert 'id="fk-lib-rows"' not in viewer.get("/fillkill/").get_data(as_text=True)  # no longer a tab on Main

    # Nursing's sub with two vendor items, one ordered; a Sub Finder's, still without one; a deleted one.
    _, data = post(finder_approver, "/fillkill/api/subs",
                   {"medline_item": "DYND70294BH", "reference_sku": "88885", "comment": "=SUM(A1)"})
    cup_id = data["sub"]["sub_id"]
    _, data = post(finder_manager, f"/fillkill/api/subs/{cup_id}/vendor-items",
                   {"vendor_part": "88885", "vendor": "CARDINAL HEALTH", "vendor_id": CARDINAL, "uom": "BX", "qoe": "100"})
    post(finder_manager, "/fillkill/api/orders", {"vendor_item_id": data["vendor_item"]["vendor_item_id"], "site": WP, "quantity": 2,
                                                  "ordered_dt": "2026-09-29T10:00"})
    post(finder_manager, f"/fillkill/api/subs/{cup_id}/vendor-items",
         {"vendor_part": "88885-CS", "vendor": "OWENS & MINOR", "vendor_id": OWENS, "uom": "CS", "manufacturer_part": "N88"})
    post(finder_manager, "/fillkill/api/subs", {"medline_item": "MDS2585H", "reference_sku": "OM1"})
    _, data = post(finder_manager, "/fillkill/api/subs", {"medline_item": "MDS2585H", "reference_sku": "GONE"})
    post(finder_manager, f"/fillkill/api/subs/{data['sub']['sub_id']}/delete", {"reason": "duplicate"})

    _, library = get(viewer, "/fillkill/api/subs")
    rows = {s["reference_sku"]: s for s in library["subs"]}
    assert sorted(rows) == ["88885", "OM1"]
    cup, glove = rows["88885"], rows["OM1"]
    assert (cup["medline_infor_item"], cup["approved_by"], cup["orders"], cup["last_ordered"][:10]) == (
        "100339", "nurse@example.org", 1, "2026-09-29")
    assert [(v["vendor_part"], v["uom"]) for v in cup["vendor_items"]] == [("88885", "BX"), ("88885-CS", "CS")]
    assert (glove["medline_infor_item"], glove["status"], glove["approved_by"], glove["orders"], glove["vendor_items"]) == (
        "999999", "pending_review", None, 0, [])
    _, library = get(viewer, "/fillkill/api/subs", needs_details="1")
    assert [s["reference_sku"] for s in library["subs"]] == ["OM1"]
    _, library = get(viewer, "/fillkill/api/subs", deleted="1")
    assert [(s["reference_sku"], s["deleted_by"], s["delete_reason"]) for s in library["subs"]] == [
        ("GONE", "mm@example.org", "duplicate")]

    # The export: what the filters match, all of it, one row per vendor item, readable by Excel.
    response = viewer.get("/fillkill/subs/export", query_string={"status": "approved"})
    assert response.mimetype == "text/csv" and "attachment" in response.headers["Content-Disposition"]
    text = response.get_data(as_text=True)
    assert text.startswith("﻿Sub ID,Medline Item,Medline Item's Infor Item,Reference SKU,Vendor Item ID,Sub Vendor Part,"
                           "Sub Manufacturer Part,Sub Infor Item,Sub Vendor ID,Sub Vendor Name,Sub Description,Sub UOM,Sub QOE,")
    header, *lines = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    box, case = [dict(zip(header, line)) for line in lines]
    assert (box["Medline Item"], box["Medline Item's Infor Item"], box["Reference SKU"], box["Sub Vendor Name"], box["Status"],
            box["Picked"], box["Orders"]) == ("DYND70294BH", "100339", "88885", "CARDINAL HEALTH", "Approved", "Yes", "1")
    assert (box["Sub Vendor Part"], box["Sub Vendor ID"], box["Sub UOM"], box["Sub QOE"], box["Vendor Item By"]) == (
        "88885", CARDINAL, "BX", "100.0", "mm@example.org")
    assert (case["Sub Vendor Part"], case["Sub Manufacturer Part"], case["Sub Vendor ID"], case["Sub UOM"], case["Sub ID"]) == (
        "88885-CS", "N88", OWENS, "CS", box["Sub ID"])
    assert box["Last Ordered"] == "2026-09-29 10:00"
    assert box["Latest Comment"] == "'=SUM(A1)"  # kept as text: Excel won't run it
    # A sub without a vendor item has a row of its own.
    response = viewer.get("/fillkill/subs/export", query_string={"status": "pending_review"})
    header, *lines = list(csv.reader(io.StringIO(response.get_data(as_text=True).lstrip("﻿"))))
    [line] = [dict(zip(header, line)) for line in lines]
    assert (line["Reference SKU"], line["Vendor Item ID"], line["Sub Vendor Part"]) == ("OM1", "", "")


# --- the coordination hub (2026-10-27) -----------------------------------------------------------

@pytest.fixture
def lead(app):
    return client(app, "lead@example.org", plm=None, fillkill=("mm_lead",))


def test_the_mm_lead_writes_the_instruction_the_sites_read_on_main(app, viewer, lead, finder_manager):
    assert page_config(lead)["can"] == {"view": True, "add_sub": False, "review": False, "pick": True, "details": True,
                                       "order": False, "instruct": True}
    # Called Will's Comments on the page for now (the user, 2026-10-27), before Vendor Item Detail.
    assert page_config(lead)["instructionLabel"] == "Will's Comments"
    page = lead.get("/fillkill/").get_data(as_text=True)
    assert page.index("Nursing's Pick</th>") < page.index("Will&#39;s Comments</th>") < page.index(">Vendor Item Detail</th>")
    status, data = post(viewer, "/fillkill/api/instructions", {"medline_item": "MDS2585H", "instruction": "x"})
    assert status == 403 and "Only MM Leads" in data["message"]
    assert post(finder_manager, "/fillkill/api/instructions", {"medline_item": "MDS2585H", "instruction": "x"})[0] == 403
    assert post(lead, "/fillkill/api/instructions", {"medline_item": "NOT-KILLED", "instruction": "x"})[0] == 404
    status, data = post(lead, "/fillkill/api/instructions", {"medline_item": "MDS2585H", "instruction": " "})
    assert status == 400 and "Instruction is required" in data["message"]
    for text in ("Hold until Friday", "White Plains: 2 BX of OM1. Test site: use stock."):
        status, data = post(lead, "/fillkill/api/instructions", {"medline_item": "MDS2585H", "instruction": text})
        assert status == 201, data
    assert (data["instruction"]["infor_item"], data["instruction"]["written_by"]) == ("999999", "lead@example.org")

    # On Main, the latest is in force; it isn't tied to the Fill/Kill dates.
    _, main = get(viewer, "/fillkill/api/main", start="2026-09-29", end="2026-09-29")
    [glove] = main["rows"]
    assert (glove["instruction"]["count"], glove["instruction"]["latest"]["instruction"]) == (
        2, "White Plains: 2 BX of OM1. Test site: use stock.")
    _, main = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-30")
    assert next(r for r in main["rows"] if r["infor_item"] == "100339")["instruction"] is None
    _, thread = get(viewer, "/fillkill/api/instructions", item="MDS2585H")
    assert [i["instruction"] for i in thread["instructions"]] == [
        "White Plains: 2 BX of OM1. Test site: use stock.", "Hold until Friday"]  # newest first
    assert get(viewer, "/fillkill/api/instructions")[0] == 400
    _, panel = get(viewer, "/fillkill/api/item", item="MDS2585H", start="2026-09-28", end="2026-09-30")
    assert panel["instruction"]["latest"]["written_by"] == "lead@example.org"
    # The MM Lead doesn't record orders.
    status, data = post(lead, "/fillkill/api/orders", {"vendor_item_id": 1, "site": WP, "quantity": 1})
    assert status == 403 and "Only Materials Managers" in data["message"]


def test_orders_are_for_a_site_and_the_site_filter_applies_to_them(app, viewer, finder_approver, finder_manager):
    _, data = post(finder_approver, "/fillkill/api/subs", {"medline_item": "DYND70294BH", "reference_sku": "88885"})
    _, data = post(finder_manager, f"/fillkill/api/subs/{data['sub']['sub_id']}/vendor-items", CUP_ITEM)  # BX of 100
    order = {"vendor_item_id": data["vendor_item"]["vendor_item_id"], "quantity": 1, "expected_status": "approved",
             "ordered_dt": "2026-09-30T12:00"}
    status, data = post(finder_manager, "/fillkill/api/orders", order)
    assert status == 400 and "Choose the site" in data["message"]
    status, data = post(finder_manager, "/fillkill/api/orders", {**order, "site": "MOSES"})
    assert status == 400 and "isn't one of the sites" in data["message"]
    status, data = post(finder_manager, "/fillkill/api/orders", {**order, "site": TEST, "po_number": "3000564756"})
    assert status == 201, data
    assert (data["order"]["site"], data["order"]["po_number"]) == (TEST, "3000564756")

    # Every site: each one's kills (White Plains 25 EA over 9/28-9/30, the test site 5) and orders.
    _, main = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-30")
    cup = next(r for r in main["rows"] if r["infor_item"] == "100339")
    assert [(s["site"], s["killed_each"], s["sub_ordered_each"]) for s in cup["sites"]] == [(WP, 25.0, 0.0), (TEST, 5.0, 100.0)]
    assert cup["ordering_status"] == "ordered"
    # White Plains alone: the test site's order doesn't count for it.
    _, main = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-30", sites=WP)
    cup = next(r for r in main["rows"] if r["infor_item"] == "100339")
    assert (cup["ordering_status"], cup["sub_ordered_each"], cup["needs"]) == ("no order", 0.0, ["needs_order"])
    # The orders under the table follow the site filter.
    for sites, expected in ((WP, []), (TEST, ["3000564756"]), (None, ["3000564756"])):
        params = {"start": "2026-09-30", "end": "2026-09-30", **({"sites": sites} if sites else {})}
        _, orders = get(viewer, "/fillkill/api/orders", **params)
        assert [o["po_number"] for o in orders["orders"]] == expected, sites
    # So do the Dashboard's (the user, 2026-10-27: a site's figures through the filter, the totals for
    # every site): the cup is ordered for the test site, and short at White Plains, unordered.
    for sites, ordered, short in ((WP, 0, 0), (TEST, 1, 0), (None, 1, 0)):
        params = {"start": "2026-09-28", "end": "2026-09-30", **({"sites": sites} if sites else {})}
        _, dash = get(viewer, "/fillkill/api/dashboard", **params)
        assert (dash["headline"]["items_ordered"], dash["headline"]["items_ordered_short"]) == (ordered, short), sites
        assert dash["flow"]["items_ordered"] == ordered, sites
