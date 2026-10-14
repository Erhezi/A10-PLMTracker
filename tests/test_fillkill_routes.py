"""The Fill/Kill Main page and its JSON API, through the real app on SQLite.

Stand-in tables hold the views' data (conftest.FILLKILL_VIEWS): two sites, like White Plains and
the test site, over 9/28-9/30.
"""

import json
import re

import pytest

from conftest import add_view_rows, csrf_from, login, make_user

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
        line(30, "10:00:00", TEST, "DYND70294BH", 5, "OUT OF STOCK - ETA is 10/02/2026", "OUT_OF_STOCK", "2026-10-02", so="TEST3"),
        line(29, "08:00:00", WP, "MDS2585H", 4, "Allocation limit has been reached", "ALLOCATION", so="4"),
    ])
    add_view_rows(sqlite_app, "vw_ContractLineSearch", [
        {"vendor_id": "1", "vendor_name": "CARDINAL HEALTH", "vendor_item": "88885", "vendor_item_stripped": "88885",
         "manufacturer_number": "N88", "manufacturer_number_stripped": "N88", "description": "GLOVE EXAM NITRILE",
         "uom": "BX", "qoe": 100, "infor_item": "200001", "contract": "C1"},
        {"vendor_id": "1", "vendor_name": "CARDINAL HEALTH", "vendor_item": "88885", "vendor_item_stripped": "88885",
         "manufacturer_number": "N88", "manufacturer_number_stripped": "N88", "description": "GLOVE EXAM NITRILE",
         "uom": "BX", "qoe": 100, "infor_item": "200001", "contract": "C2"},
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
    assert config["can"] == {"view": True, "add_sub": False, "review": False, "order": False}
    assert 'aria-current="page">Main</a>' in page


def test_a_user_without_a_fillkill_role_is_turned_away(app):
    plm_only = client(app, "plm@example.org")
    status, data = get(plm_only, "/fillkill/api/main")
    assert status == 403


# --- the main table ----------------------------------------------------------------------

def test_main_sums_per_item_and_uom_over_the_dates_and_sites(viewer):
    status, data = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-30")
    assert status == 200
    rows = {row["medline_item"]: row for row in data["rows"]}
    assert rows["DYND70294BH"]["quantities"] == [{"uom": "EA", "ordered": 30, "filled": 0, "killed": 30}]
    assert rows["DYND70294BH"]["lines"] == 6
    assert rows["DYND70294BH"]["latest_reason"]["reason"] == "MBO"  # 11:35 at White Plains beats 10:00 at the test site
    assert [q["uom"] for q in rows["MDS2585H"]["quantities"]] == ["BX", "CS"]  # never added across UOMs
    assert rows["MDS2585H"]["commodity_description"] == "MEDICAL EXAM OR NON SURGICAL PROCEDURE GLOVES"
    assert [r["customer_item"] for r in data["rows"]] == ["100339", "108176"]  # sorted by customer item
    assert rows["MDS2585H"]["infor_consistent"] is False
    assert data["counts"]["needs_subs"] == 2


def test_main_filters_by_site_and_defaults_to_the_latest_date(viewer):
    _, data = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-30", sites=TEST)
    assert [(r["medline_item"], r["lines"]) for r in data["rows"]] == [("DYND70294BH", 1)]
    assert data["rows"][0]["latest_reason"]["reason"] == "OUT_OF_STOCK"

    _, data = get(viewer, "/fillkill/api/main")
    assert data["scope"]["start"] == data["scope"]["end"] == "2026-09-30"
    assert [r["medline_item"] for r in data["rows"]] == ["DYND70294BH"]


def test_bad_dates_are_refused(viewer):
    status, data = get(viewer, "/fillkill/api/main", start="09/28/2026")
    assert status == 400 and "2026-10-13" in data["message"]


# --- the whole flow, role by role ----------------------------------------------------------

def test_finder_adds_approver_reviews_and_picks_manager_orders(app, viewer, finder_approver, finder_manager):
    status, data = post(finder_approver, "/fillkill/api/subs", {
        "medline_item": "DYND70294BH", "vendor": "Cardinal Health", "vendor_part": "88885", "uom": "bx",
        "qoe": "100", "comment": "Same cup",
    })
    assert status == 201, data
    sub_id = data["sub"]["sub_id"]
    assert data["sub"]["status"] == "pending_review"

    _, main = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-30")
    row = next(r for r in main["rows"] if r["medline_item"] == "DYND70294BH")
    assert row["needs"] == ["needs_review"]

    assert post(finder_approver, f"/fillkill/api/subs/{sub_id}/status",
                {"status": "approved", "expected_status": "pending_review"})[0] == 200
    assert post(finder_approver, f"/fillkill/api/subs/{sub_id}/pick", {"expected_status": "approved"})[0] == 200

    status, data = post(finder_manager, "/fillkill/api/orders", {
        "sub_id": sub_id, "quantity": 30, "ordered_dt": "2026-09-30T15:00", "expected_status": "approved",
    })
    assert status == 201, data
    assert (data["order"]["uom"], data["order"]["qoe"], data["order"]["vendor"]) == ("BX", 100, "Cardinal Health")

    _, main = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-30")
    row = next(r for r in main["rows"] if r["medline_item"] == "DYND70294BH")
    assert (row["ordering_status"], row["needs"]) == ("ordered", ["ordered"])
    assert [p["vendor_part"] for p in row["picks"]] == ["88885"]

    _, main = get(viewer, "/fillkill/api/main", start="2026-09-28", end="2026-09-29")
    row = next(r for r in main["rows"] if r["medline_item"] == "DYND70294BH")
    assert row["ordering_status"] == "no order"  # ordered on 9/30, outside these dates (S4)

    _, panel = get(viewer, "/fillkill/api/item", item="DYND70294BH", start="2026-09-28", end="2026-09-30")
    assert [s["latest_comment"]["comment"] for s in panel["subs"]] == ["Same cup"]
    assert [h["action"] for h in panel["pick_history"]] == ["pick", "status", "created"]
    assert len(panel["orders"]) == 1 and len(panel["lines"]) == 3
    assert panel["details"]["description"] == "CUP,DENTURE"

    _, history = get(viewer, f"/fillkill/api/history/sub/{sub_id}")
    assert [h["action"] for h in history["history"]] == ["pick", "status", "comment", "created"]

    _, library = get(viewer, "/fillkill/api/subs", status="approved")
    assert [s["vendor_part"] for s in library["subs"]] == ["88885"]
    _, orders = get(viewer, "/fillkill/api/orders", start="2026-09-30", end="2026-09-30")
    assert [o["quantity"] for o in orders["orders"]] == [30]


@pytest.mark.parametrize("who, path, payload, allowed", [
    ("viewer", "/fillkill/api/subs", {"medline_item": "DYND70294BH", "vendor": "V", "vendor_part": "P"}, False),
    ("finder_manager", "/fillkill/api/subs", {"medline_item": "DYND70294BH", "vendor": "V", "vendor_part": "P"}, True),
    ("finder_manager", "/fillkill/api/subs/{sub}/status", {"status": "approved"}, False),
    ("finder_manager", "/fillkill/api/subs/{sub}/comments", {"comment": "hi"}, False),
    ("finder_approver", "/fillkill/api/subs/{sub}/comments", {"comment": "hi"}, True),
    ("finder_approver", "/fillkill/api/subs/{sub}/edit", {"description": "x"}, True),
    ("finder_approver", "/fillkill/api/orders", {"sub_id": "{sub}", "quantity": 1, "uom": "EA"}, False),
    ("viewer", "/fillkill/api/subs/{sub}/pick", {}, False),
])
def test_each_action_needs_its_role(app, request, finder_approver, who, path, payload, allowed):
    _, data = post(finder_approver, "/fillkill/api/subs",
                   {"medline_item": "MDS2585H", "vendor": "Owens", "vendor_part": "OM1"})
    sub_id = data["sub"]["sub_id"]
    actor = request.getfixturevalue(who)
    payload = {k: (sub_id if v == "{sub}" else v) for k, v in payload.items()}
    status, data = post(actor, path.replace("{sub}", str(sub_id)), payload)
    if allowed:
        assert status in (200, 201), data
    else:
        assert status == 403, data
        assert data["error"] == "forbidden"


def test_rule_errors_and_conflicts_come_back_as_messages(app, finder_approver, finder_manager):
    status, data = post(finder_approver, "/fillkill/api/subs", {"medline_item": "NOT-KILLED", "vendor": "V", "vendor_part": "P"})
    assert status == 404 and "isn't a Medline item" in data["message"]

    _, data = post(finder_approver, "/fillkill/api/subs", {"medline_item": "MDS2585H", "vendor": "V", "vendor_part": "P"})
    sub_id = data["sub"]["sub_id"]
    status, data = post(finder_approver, f"/fillkill/api/subs/{sub_id}/pick", {})
    assert status == 400 and "Only an approved sub" in data["message"]

    post(finder_approver, f"/fillkill/api/subs/{sub_id}/status", {"status": "rejected"})
    status, data = post(finder_approver, f"/fillkill/api/subs/{sub_id}/status",
                        {"status": "approved", "expected_status": "pending_review"})
    assert status == 409 and "nurse@example.org" in data["message"]

    status, data = post(finder_manager, "/fillkill/api/orders", {"sub_id": sub_id, "quantity": 1, "uom": "EA"})
    assert status == 409 and "isn't picked" in data["message"]


def test_actions_need_the_csrf_token(app, finder_approver):
    response = finder_approver.post("/fillkill/api/subs", json={"medline_item": "MDS2585H", "vendor": "V", "vendor_part": "P"},
                                    headers={"X-Requested-With": "fetch"})
    assert response.status_code == 401
    assert response.get_json()["error"] == "login_expired"


# --- contract search ------------------------------------------------------------------------

def test_contract_search_for_sub_finders(app, viewer, finder_approver):
    assert get(viewer, "/fillkill/api/contract-lines", q="88885")[0] == 403
    _, data = get(finder_approver, "/fillkill/api/contract-lines", q="88")
    assert data["lines"] == [] and "at least 3" in data["message"]
    _, data = get(finder_approver, "/fillkill/api/contract-lines", q="888-85")
    assert [(r["vendor_name"], r["vendor_item"], r["contracts"]) for r in data["lines"]] == [("CARDINAL HEALTH", "88885", 2)]
    _, data = get(finder_approver, "/fillkill/api/contract-lines", q="nitrile glove")
    assert [r["vendor_item"] for r in data["lines"]] == ["88885"]
    _, data = get(finder_approver, "/fillkill/api/contract-lines", q="glove 7.5%")
    assert data["lines"] == []


def test_library_search_ignores_dashes_spaces_dots_and_slashes(app, viewer, finder_approver):
    post(finder_approver, "/fillkill/api/subs", {"medline_item": "MDS2585H", "vendor": "Owens", "vendor_part": "OM-12.5/A"})
    for q in ("om125a", "OM-12.5", "om 12", "mds2585"):
        _, data = get(viewer, "/fillkill/api/subs", q=q)
        assert [s["vendor_part"] for s in data["subs"]] == ["OM-12.5/A"], q
    _, data = get(viewer, "/fillkill/api/subs", q="om13")
    assert data["subs"] == []
