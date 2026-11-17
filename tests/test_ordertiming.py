"""Order Timing (2026-10-30): a module beside Fill/Kill with its own Main and Dashboard, for display.
Every Fill/Kill role can view it; it has no roles of its own.

Main (2026-11-16) finds our orders in Medline's feed (OrderTiming.vw_MedlineOrderLine, stood in on
SQLite by tests/conftest.py) by PO, item, site, day and line status, to see whether Medline received
and confirmed them. The Dashboard is still empty."""

import csv
import io
from datetime import timedelta

import pytest

from app.models import now_ny_naive
from app.ordertiming import queries
from app.utility import access
from app.utility.access import ORDERTIMING
from conftest import add_view_rows, login, make_user
from test_fillkill_access import fake_user

FILLKILL_ROLES = ["viewer", "sub_finder", "sub_approver", "materials_manager", "scm"]
SITE_A, SITE_B = ("0001041251", "MONTEFIORE HOSPITAL AND MEDICAL CTR"), ("0002522116", "MONTEFIORE WAKEFIELD LAB")
SITE_C = ("0003000000", "MONTEFIORE OLD SITE")  # only on an order past the last 30 days


def logged_in(app, email, **kwargs):
    make_user(app, email, **kwargs)
    client = app.test_client()
    login(client, email)
    return client


# --- access ---------------------------------------------------------------------------------

@pytest.mark.parametrize("role", FILLKILL_ROLES)
def test_every_fillkill_role_can_view_it(role):
    assert access.can(fake_user(fillkill=(role,)), ORDERTIMING, "view")


def test_nobody_else_can_view_it():
    assert not access.can(fake_user(plm="editor"), ORDERTIMING, "view")
    assert not access.can(fake_user(admin=True), ORDERTIMING, "view")  # admin grants nothing in a module
    assert not access.can(fake_user(fillkill=("viewer",), authenticated=False), ORDERTIMING, "view")


@pytest.mark.parametrize("role", FILLKILL_ROLES)
def test_its_pages_for_every_fillkill_role(sqlite_app, role):
    client = logged_in(sqlite_app, f"{role}@example.org", plm=None, fillkill=(role,))
    main = client.get("/ordertiming/").get_data(as_text=True)
    assert 'aria-current="page">Order Timing</a>' in main  # the module row
    assert 'aria-current="page">Main</a>' in main and 'id="ot-rows"' in main and 'id="ot-q"' in main
    assert "js/ordertiming/main.js" in main
    dash = client.get("/ordertiming/dashboard").get_data(as_text=True)
    assert 'aria-current="page">Dashboard</a>' in dash and 'id="ot-dash-empty"' in dash
    assert 'href="/doc/ordertiming">Docs</a>' in dash


@pytest.mark.parametrize("path", ["/ordertiming/", "/ordertiming/dashboard", "/ordertiming/api/orders",
                                  "/ordertiming/export"])
def test_users_without_a_fillkill_role_are_turned_away(sqlite_app, path):
    client = logged_in(sqlite_app, "plm@example.org")  # PLM editor, no Fill/Kill
    response = client.get(path)
    assert response.status_code in (302, 403)
    if response.status_code == 302:
        page = client.get(response.headers["Location"], follow_redirects=True).get_data(as_text=True)
        assert "You don&#39;t have access to Order Timing" in page


def test_page_and_module_rows(sqlite_app):
    with sqlite_app.test_request_context("/ordertiming/dashboard"):
        nav = access.build_nav(fake_user(fillkill=("materials_manager",)))
    assert nav["active"] == ORDERTIMING
    assert [m["label"] for m in nav["modules"]] == ["Fill/Kill Management", "Order Timing"]
    assert [(p["label"], p["active"]) for p in nav["pages"]] == [("Main", False), ("Dashboard", True)]


def test_fillkill_users_still_land_on_fillkill(sqlite_app):
    client = logged_in(sqlite_app, "nurse@example.org", plm=None, fillkill=("sub_approver",))
    assert client.get("/").headers["Location"].endswith("/fillkill/")


def test_no_roles_to_give_or_ask_for(sqlite_app):
    assert ORDERTIMING not in access.ROLE_MODULES
    assert access.INCLUDED_MODULES == {"plm": [], "fillkill": ["Order Timing"]}
    page = sqlite_app.test_client().get("/auth/register").get_data(as_text=True)
    assert 'value="ordertiming"' not in page
    assert "Fill/Kill Management <span class=\"text-muted\">(includes Order Timing)</span>" in page


def test_its_docs_are_public(sqlite_app):
    page = sqlite_app.test_client().get("/doc/ordertiming").get_data(as_text=True)
    assert "Order Timing Docs" in page
    assert 'aria-current="page">Order Timing</a>' in page  # the docs page row
    assert "ask an admin for a Fill/Kill role" in page
    assert "Not confirmed" in page and "ASN sent" in page  # the statuses explained


# --- Medline's order lines ------------------------------------------------------------------------

def day(n: int) -> str:
    return (now_ny_naive().date() - timedelta(days=n)).isoformat()


def line(order: int, order_line: str, ago: int, site=SITE_A, **values) -> dict:
    """An order line as the view gives it: confirmed, not shipped, unless ``values`` say otherwise."""
    d = day(ago)
    row = {
        "Report Date": d, "Order #": f"10000000{order:02d}", "Order Line": order_line,
        "PO#": f"30000000{order:02d}-STPO", "PO": f"30000000{order:02d}", "POLine": str(int(order_line) // 10),
        "PO Type": "EDI", "Sold-To #": site[0], "Sold-To Name": site[1], "Ship-To #": "0002464430",
        "Ship-To Name": "4 WEST", "Buyer Name": "Vata, Fanda", "Medline Item #": "DYND70294BH",
        "Cust Item #": "100339", "Item # on PO": "DYND70294BH", "Mfr Item #": "D70294", "Manufacturer": "MEDLINE",
        "Item Description": "CUP,DENTURE,8OZ", "Order Qty": 10, "Open Qty": 10, "Shipped Qty": 0, "UM": "CS",
        "Line Type": "STD", "Bad Line": None, "Rej Code": None, "Received At": f"{d} 09:00:00",
        "Order Created At": f"{d} 09:03:00", "Confirmed At": f"{d} 09:04:00", "Mins  to Order Create": 3,
        "Mins to Confirm": 4, "ASN Created At": None, "Line Status": "confirmed",
    }
    row.update(values)
    return row


def lines() -> list[dict]:
    return [
        # 1: today, three lines: confirmed, rejected (a bad line), shipped (ASN)
        line(1, "000010", 0, **{"Received At": f"{day(0)} 11:55:41", "Item Description": "GLOVE,EXAM,NITRILE,M",
                                "Medline Item #": "MDS2585H", "Cust Item #": "999999", "Item # on PO": "MDS2585H"}),
        line(1, "000020", 0, **{"Received At": f"{day(0)} 11:55:41", "Medline Item #": "INVALID PART",
                                "Line Status": "rejected", "Bad Line": "YES", "Rej Code": "E1", "Open Qty": None}),
        line(1, "000030", 0, **{"Received At": f"{day(0)} 11:55:41", "Line Status": "asn", "Shipped Qty": 10,
                                "Open Qty": None, "ASN Created At": f"{day(0)} 12:17:50"}),
        # 2: today, another site, not confirmed yet
        line(2, "000010", 0, site=SITE_B, **{"Received At": f"{day(0)} 08:00:00", "Confirmed At": None,
                                             "Mins to Confirm": None, "Line Status": "not_confirmed"}),
        # 3: three days ago: confirmed and open, and shipped one short
        line(3, "000010", 3, **{"Medline Item #": "B-D930103", "Item Description": "CHLORAPREP APPLICATOR"}),
        line(3, "000020", 3, **{"Order Qty": 3, "Shipped Qty": 2, "Open Qty": None, "Line Status": "asn",
                                "ASN Created At": f"{day(3)} 13:00:00"}),
        # 4: ten days ago, past the default week; a description Excel would run as a formula
        line(4, "000010", 10, **{"Item Description": "=SUM(A1)"}),
        # 5: forty days ago, past the 30 days Main and the export reach, at a site with nothing newer
        line(5, "000010", 40, site=SITE_C),
    ]


@pytest.fixture
def ot_app(sqlite_app):
    add_view_rows(sqlite_app, "vw_MedlineOrderLine", lines())
    add_view_rows(sqlite_app, "vw_OrderTimingLastLoad",
                  [{"last_success": f"{day(0)} 12:00:00", "last_line_load": f"{day(0)} 12:30:00"}])
    return sqlite_app


@pytest.fixture
def client(ot_app):
    return logged_in(ot_app, "mm@example.org", plm=None, fillkill=("materials_manager",))


def get_orders(client, **params):
    response = client.get("/ordertiming/api/orders", query_string=params)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def numbers(data):
    return [o["order_no"][-1] for o in data["orders"]]


def test_main_page_settings(client):
    page = client.get("/ordertiming/").get_data(as_text=True)
    today = now_ny_naive().date()
    assert f'"start": "{(today - timedelta(days=6)).isoformat()}"' in page and f'"end": "{today.isoformat()}"' in page
    assert f'"earliest": "{day(29)}"' in page and '"max_days": 30' in page  # the last 30 days, today included
    assert '"per_page": 20' in page
    assert '"name": "MONTEFIORE WAKEFIELD LAB"' in page  # the sites in those days
    assert SITE_C[1] not in page  # not a site with only older orders
    assert '["not_confirmed", "Not confirmed"]' in page
    assert '"problem": null' in page


def test_the_last_week_newest_first_each_order_with_its_lines(client):
    data = get_orders(client)
    assert numbers(data) == ["1", "2", "3"] and data["total"] == 3  # order 4 is ten days old
    first = data["orders"][0]
    assert (first["po"], first["po_raw"], first["site"], first["ship_to_name"]) == (
        "3000000001", "3000000001-STPO", SITE_A[0], "4 WEST")
    assert first["status"] == "confirmed" and first["confirmed_at"].endswith("09:04:00")
    assert first["received_at"].endswith("11:55:41") and first["mins_to_confirm"] == 4
    assert first["line_count"] == 3 and first["po_type"] == "EDI"
    assert first["counts"] == {"not_confirmed": 0, "rejected": 1, "confirmed": 1, "asn": 1}
    assert [(ln["order_line"], ln["status"], ln["matched"]) for ln in first["lines"]] == [
        ("000010", "confirmed", True), ("000020", "rejected", True), ("000030", "asn", True)]
    rejected = first["lines"][1]
    assert (rejected["line_type"], rejected["bad_line"], rejected["rej_code"]) == ("STD", "YES", "E1")
    assert first["lines"][0]["bad_line"] is None and first["lines"][0]["rej_code"] is None
    assert "site" not in rejected and "po_type" not in rejected  # order values on the order
    assert not any(key.startswith("delivery") for key in rejected)  # SAP's delivery isn't shown
    assert data["filters"]["picks_lines"] is False
    # As Fill/Kill's Main: A13's last good run ("Data as of"), with whether it's stale.
    assert data["data"]["as_of"].endswith("12:00:00") and data["data"]["source"] == "feed"
    assert isinstance(data["data"]["stale"], bool)


def test_an_order_without_its_855_is_not_confirmed(client):
    second = get_orders(client)["orders"][1]
    assert second["status"] == "not_confirmed" and second["confirmed_at"] is None
    assert second["mins_to_confirm"] is None


def test_confirmed_only_when_every_line_has_its_855():
    built = queries.build_order([
        {**{key: "x" for key in queries.ORDER_KEYS}, "order_line": "000020", "status": "confirmed",
         "confirmed_at": "2026-11-16 09:04:00", "received_at": "2026-11-16 09:00:00", "created_at": None,
         "mins_to_confirm": 4, "matched": True},
        {**{key: "x" for key in queries.ORDER_KEYS}, "order_line": "000010", "status": "not_confirmed",
         "confirmed_at": None, "received_at": "2026-11-16 08:59:00", "created_at": None,
         "mins_to_confirm": None, "matched": False},
    ])
    assert built["status"] == "not_confirmed" and built["confirmed_at"] is None
    assert [ln["order_line"] for ln in built["lines"]] == ["000010", "000020"]
    assert built["received_at"] == "2026-11-16 08:59:00" and built["matched"] == 1


def test_a_line_in_two_days_reports_counts_once_as_of_its_latest_day():
    def reported(day_, status):
        return {**{key: "x" for key in queries.ORDER_KEYS}, "report_date": day_, "order_line": "000010",
                "status": status, "confirmed_at": "2026-11-16 23:58:00", "received_at": "2026-11-16 23:55:00",
                "created_at": None, "mins_to_confirm": 3, "matched": True}

    built = queries.build_order([reported("2026-11-17", "asn"), reported("2026-11-16", "confirmed")])
    assert built["line_count"] == 1 and [ln["status"] for ln in built["lines"]] == ["asn"]
    assert built["counts"]["asn"] == 1 and built["counts"]["confirmed"] == 0


def test_find_a_po(client):
    data = get_orders(client, q="3000000001")
    assert numbers(data) == ["1"] and data["orders"][0]["matched"] == 3  # every line is on the PO
    assert data["filters"]["picks_lines"] is True


def test_several_pos_pasted_find_them_all(client):
    assert numbers(get_orders(client, q="3000000001, 3000000003\n3000000099")) == ["1", "3"]


def test_an_item_finds_its_lines_and_marks_them(client):
    data = get_orders(client, q="invalid")
    assert numbers(data) == ["1"]
    assert [ln["matched"] for ln in data["orders"][0]["lines"]] == [False, True, False]
    assert data["orders"][0]["matched"] == 1 and data["orders"][0]["line_count"] == 3


def test_item_numbers_match_without_punctuation(client):
    assert numbers(get_orders(client, q="bd930103")) == ["3"]
    assert numbers(get_orders(client, q="B-D930103")) == ["3"]


def test_every_word_must_match_unless_all_are_numbers(client):
    assert numbers(get_orders(client, q="nitrile glove")) == ["1"]
    assert numbers(get_orders(client, q="nitrile chloraprep")) == []
    assert numbers(get_orders(client, q="wakefield")) == []  # the site's name isn't searched: use the site filter
    assert numbers(get_orders(client, q="4 west 100339")) == ["1", "2", "3"]


def test_like_wildcards_are_taken_literally(client):
    assert get_orders(client, q="%")["orders"] == [] and get_orders(client, q="_")["orders"] == []


def test_a_status_finds_orders_with_such_a_line(client):
    rejected = get_orders(client, status="rejected")
    assert numbers(rejected) == ["1"] and rejected["orders"][0]["matched"] == 1
    assert numbers(get_orders(client, status="not_confirmed")) == ["2"]
    assert numbers(get_orders(client, status="confirmed")) == ["1", "3"]
    assert numbers(get_orders(client, status="asn", q="3000000003")) == ["3"]
    response = client.get("/ordertiming/api/orders?status=delivery")  # not a status since 2026-11-16
    assert response.status_code == 400


def test_sites_and_days(client):
    assert numbers(get_orders(client, sites=SITE_B[0])) == ["2"]
    assert numbers(get_orders(client, sites=f"{SITE_A[0]},{SITE_B[0]}")) == ["1", "2", "3"]
    assert numbers(get_orders(client, start=day(29), end=day(0))) == ["1", "2", "3", "4"]
    assert numbers(get_orders(client, start=day(3), end=day(3))) == ["3"]
    assert numbers(get_orders(client, start=day(0), end=day(3))) == ["1", "2", "3"]  # given backwards: swapped


def test_no_further_back_than_the_last_30_days(client):
    data = get_orders(client, start=day(60), end=day(0))
    assert numbers(data) == ["1", "2", "3", "4"]  # not order 5, forty days old
    assert (data["filters"]["start"], data["filters"]["end"]) == (day(29), day(0))  # the days it took
    data = get_orders(client, start=day(60), end=day(35), q="3000000005")
    assert data["orders"] == [] and (data["filters"]["start"], data["filters"]["end"]) == (day(29), day(29))
    assert get_orders(client, start=day(0), end=day(-5))["filters"]["end"] == day(0)  # not past today either


def test_pages_newest_first(ot_app):
    with ot_app.app_context():
        today = now_ny_naive().date()
        last_30 = queries.Filters(today - timedelta(days=29), today)
        first = queries.find_orders(last_30, page=1, per_page=3)
        second = queries.find_orders(last_30, page=2, per_page=3)
        past = queries.find_orders(last_30, page=9, per_page=3)
    assert [o["order_no"][-1] for o in first["orders"]] == ["1", "2", "3"]
    assert (first["total"], first["pages"], first["page"], first["per_page"]) == (4, 2, 1, 3)
    assert [o["order_no"][-1] for o in second["orders"]] == ["4"] and second["page"] == 2
    assert [o["order_no"][-1] for o in past["orders"]] == ["4"] and past["page"] == 2  # past the last: the last


def test_main_pages_twenty_orders(client):
    data = get_orders(client, start=day(29), end=day(0))
    assert (data["page"], data["pages"], data["per_page"], data["total"]) == (1, 1, 20, 4)
    assert get_orders(client, page=3)["page"] == 1  # one page only
    assert "limit" not in data


def test_bad_requests(client):
    response = client.get("/ordertiming/api/orders?status=lost")
    assert response.status_code == 400 and "no status 'lost'" in response.get_json()["message"]
    response = client.get("/ordertiming/api/orders?start=11/16/2026")
    assert response.status_code == 400 and "2026-11-16" in response.get_json()["message"]
    for page in ("0", "two", "-1"):
        response = client.get(f"/ordertiming/api/orders?page={page}")
        assert response.status_code == 400 and "page" in response.get_json()["message"]


def test_export_every_line_picked(client):
    response = client.get("/ordertiming/export", query_string={"start": day(60), "end": day(0)})
    assert response.status_code == 200 and response.mimetype == "text/csv"
    assert "order-timing-" in response.headers["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.get_data(as_text=True).lstrip("﻿"))))
    header, body = rows[0], rows[1:]
    assert header[:4] == ["Report Date", "Sold-To #", "Sold-To Name", "Ship-To #"] and "Status" in header
    assert {"PO Type", "Line Type", "Bad Line", "Rej Code"} <= set(header)
    assert not [label for label in header if "Deliver" in label]
    assert len(body) == 7  # every line of orders 1 to 4; not order 5, past the last 30 days
    status, description = header.index("Status"), header.index("Item Description")
    assert {row[status] for row in body} == {"Rejected", "ASN sent", "Not confirmed", "Confirmed"}
    bad = [row for row in body if row[header.index("Bad Line")]]
    assert [(row[header.index("Bad Line")], row[header.index("Rej Code")]) for row in bad] == [("YES", "E1")]
    assert "'=SUM(A1)" in [row[description] for row in body]  # not run as a formula
    picked = client.get("/ordertiming/export", query_string={"status": "rejected"}).get_data(as_text=True)
    assert len(list(csv.reader(io.StringIO(picked.lstrip("﻿"))))) == 2  # the header and the rejected line


def _drop_line_view(app):
    from app import db

    with app.app_context(), db.engine.begin() as conn:
        conn.exec_driver_sql('DROP TABLE "OrderTiming"."vw_MedlineOrderLine"')


def test_without_its_view_admins_are_told_what_to_run(sqlite_app):
    _drop_line_view(sqlite_app)
    admin = logged_in(sqlite_app, "admin@example.org", role="admin", plm=None, fillkill=("viewer",))
    page = admin.get("/ordertiming/").get_data(as_text=True)
    assert "db/ordertiming/01_views.sql" in page and "Order Timing can" in page
    response = admin.get("/ordertiming/api/orders")
    assert response.status_code == 503 and "01_views.sql" in response.get_json()["message"]


def test_without_its_view_others_are_pointed_to_an_admin(sqlite_app):
    _drop_line_view(sqlite_app)
    viewer = logged_in(sqlite_app, "viewer@example.org", plm=None, fillkill=("viewer",))
    page = viewer.get("/ordertiming/").get_data(as_text=True)
    assert "Ask an admin to look at it" in page and "01_views.sql" not in page
    assert viewer.get("/ordertiming/api/orders").status_code == 503


def test_search_words():
    assert queries.search_terms(" 3000571298,3000571752;\n bd-930 ") == ["3000571298", "3000571752", "bd-930"]
    assert queries.search_condition("   ") is None
