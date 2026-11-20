"""Order Timing (2026-10-30): a module beside Fill/Kill with its own Main and Dashboard, for display.
Every Fill/Kill role can view it; it has no roles of its own.

Main (2026-11-16) finds our orders in Medline's feed (OrderTiming.vw_MedlineOrderLine, stood in on
SQLite by tests/conftest.py) by PO, item, site, day and line status, to see whether Medline received
and confirmed them. The Dashboard (2026-11-20) gives the whole picture of the feed."""

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
    short = client.get("/ordertiming/shortships").get_data(as_text=True)
    assert 'aria-current="page">Short Ships</a>' in short and "js/ordertiming/shortships.js" in short
    dash = client.get("/ordertiming/dashboard").get_data(as_text=True)
    assert 'aria-current="page">Dashboard</a>' in dash and 'id="ot-dash-headline"' in dash
    assert "js/ordertiming/dashboard.js" in dash
    assert 'href="/doc/ordertiming">Docs</a>' in dash


@pytest.mark.parametrize("path", ["/ordertiming/", "/ordertiming/dashboard", "/ordertiming/api/orders",
                                  "/ordertiming/export", "/ordertiming/shortships", "/ordertiming/api/shortships",
                                  "/ordertiming/shortships/export", "/ordertiming/api/dashboard"])
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
    assert [(p["label"], p["active"]) for p in nav["pages"]] == [("Main", False), ("Short Ships", False),
                                                                ("Dashboard", True)]


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
    assert "Not confirmed" in page and "ASN sent" in page and "Short shipped" in page  # the statuses explained
    assert "Short Ships" in page


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
        "Mins to Confirm": 4, "ASN Created At": None, "Line Status": "confirmed", "Short Qty": None,
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
        # 3: three days ago: confirmed and open, and shipped one short (ASN sent wins over short
        # shipped in the status, 2026-11-17; Short Qty tallies it)
        line(3, "000010", 3, **{"Medline Item #": "B-D930103", "Item Description": "CHLORAPREP APPLICATOR"}),
        line(3, "000020", 3, **{"Order Qty": 3, "Shipped Qty": 2, "Open Qty": None, "Line Status": "asn",
                                "Short Qty": 1, "ASN Created At": f"{day(3)} 13:00:00"}),
        # 4: ten days ago, past the default week; a description Excel would run as a formula
        line(4, "000010", 10, **{"Item Description": "=SUM(A1)"}),
        # 5: forty days ago, past the 30 days Main and the export reach, at a site with nothing newer
        line(5, "000010", 40, site=SITE_C),
    ]


@pytest.fixture
def ot_app(sqlite_app):
    add_view_rows(sqlite_app, "vw_MedlineOrderLine", lines())
    add_view_rows(sqlite_app, "vw_OrderTimingLastLoad",
                  [{"last_success": f"{day(0)} 12:00:00", "last_line_load": f"{day(0)} 12:30:00",
                    "last_file": rf"\\share\OrderTiming\Raw\MHS - ORDER DETAIL REPORT-{day(0)}-10-30-00.xls"}])
    return sqlite_app


@pytest.fixture
def client(ot_app):
    return logged_in(ot_app, "mm@example.org", plm=None, fillkill=("materials_manager",))


def get_orders(client, **params):
    """Main's API on the last week, unless the test gives its days (Main itself opens on today)."""
    if "start" not in params and "end" not in params:
        params = {"start": day(6), "end": day(0), **params}
    response = client.get("/ordertiming/api/orders", query_string=params)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def numbers(data):
    return [o["order_no"][-1] for o in data["orders"]]


def test_main_page_settings(client):
    page = client.get("/ordertiming/").get_data(as_text=True)
    today = now_ny_naive().date()
    assert f'"start": "{today.isoformat()}"' in page and f'"end": "{today.isoformat()}"' in page  # today (2026-11-17)
    assert f'"earliest": "{day(29)}"' in page and '"max_days": 30' in page  # the last 30 days, today included
    assert '"per_page": 20' in page
    assert '"name": "MONTEFIORE WAKEFIELD LAB"' in page  # the sites in those days
    assert SITE_C[1] not in page  # not a site with only older orders
    assert '["rejected", "Rejected"], ["asn", "ASN sent"], ["confirmed", "Confirmed"], ["not_confirmed", "Not confirmed"]' in page
    assert '"short_tab": ["short", "Short shipped"]' in page
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
    assert first["short_lines"] == 0
    assert [(ln["order_line"], ln["status"], ln["matched"]) for ln in first["lines"]] == [
        ("000010", "confirmed", True), ("000020", "rejected", True), ("000030", "asn", True)]
    rejected = first["lines"][1]
    assert (rejected["line_type"], rejected["bad_line"], rejected["rej_code"]) == ("STD", "YES", "E1")
    assert first["lines"][0]["bad_line"] is None and first["lines"][0]["rej_code"] is None
    assert "site" not in rejected and "po_type" not in rejected  # order values on the order
    assert not any(key.startswith("delivery") for key in rejected)  # SAP's delivery isn't shown
    assert data["filters"]["picks_lines"] is False
    # As Fill/Kill's Main: A13's last good run ("Last loaded"), with whether it's stale, and when
    # Medline made the file it loaded ("Data as of"): 10:30 AM Central, 11:30 here.
    assert data["data"]["loaded_at"].endswith("12:00:00") and isinstance(data["data"]["stale"], bool)
    assert data["data"]["data_as_of"] == f"{day(0)}T11:30:00"
    assert data["data"]["file"] == f"MHS - ORDER DETAIL REPORT-{day(0)}-10-30-00.xls"


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
    assert numbers(get_orders(client, status="asn")) == ["1", "3"]
    short = get_orders(client, status="short")  # short shipped, whatever the status (2026-11-17)
    assert numbers(short) == ["3"] and short["orders"][0]["matched"] == 1 and short["orders"][0]["short_lines"] == 1
    assert [ln["short_qty"] for ln in short["orders"][0]["lines"]] == [None, 1]
    response = client.get("/ordertiming/api/orders?status=delivery")  # not a status since 2026-11-16
    assert response.status_code == 400


def test_status_tabs_count_orders_whatever_the_status_chosen(client):
    # Last week: order 1 has a confirmed, a rejected and a shipped line; 2 isn't confirmed; 3 has a
    # confirmed line and a shipped one that's short. An order counts under each status its lines
    # are in, and under short shipped when a line is short, whatever its status.
    expected = {"all": 3, "rejected": 1, "asn": 2, "confirmed": 2, "not_confirmed": 1, "short": 1}
    assert get_orders(client)["status_counts"] == expected
    picked = get_orders(client, status="rejected")
    assert picked["status_counts"] == expected and picked["total"] == 1  # the tab chosen doesn't change them
    # The days, sites and search do.
    assert get_orders(client, sites=SITE_B[0])["status_counts"] == {
        "all": 1, "rejected": 0, "asn": 0, "confirmed": 0, "not_confirmed": 1, "short": 0}
    assert get_orders(client, q="invalid")["status_counts"] == {
        "all": 1, "rejected": 1, "asn": 0, "confirmed": 0, "not_confirmed": 0, "short": 0}
    assert get_orders(client, start=day(29), end=day(0))["status_counts"]["confirmed"] == 3  # order 4 too
    assert get_orders(client, q="nothing like it")["status_counts"] == {
        "all": 0, "rejected": 0, "asn": 0, "confirmed": 0, "not_confirmed": 0, "short": 0}


def test_main_opens_on_today(client):
    # 2026-11-17, the user: Main opens on today; Short Ships too (2026-11-18; the last 7 days before).
    data = client.get("/ordertiming/api/orders").get_json()
    assert (data["filters"]["start"], data["filters"]["end"]) == (day(0), day(0))
    assert numbers(data) == ["1", "2"]
    short = client.get("/ordertiming/api/shortships").get_json()["filters"]
    assert (short["start"], short["end"]) == (day(0), day(0))
    assert f'"start": "{day(0)}"' in client.get("/ordertiming/shortships").get_data(as_text=True)


def test_no_further_back_than_the_go_live_day(client, ot_app):
    # ORDERTIMING_FIRST_DAY (Medline's LUM go-live, 2026-11-16): the 30 days start there until 30
    # days have passed. Here, three days ago.
    ot_app.config["ORDERTIMING_FIRST_DAY"] = day(3)
    data = get_orders(client, start=day(29), end=day(0))
    assert numbers(data) == ["1", "2", "3"] and data["filters"]["start"] == day(3)  # not order 4, ten days old
    page = client.get("/ordertiming/").get_data(as_text=True)
    assert f'"earliest": "{day(3)}"' in page and f'"start": "{day(0)}"' in page
    short = client.get("/ordertiming/api/shortships", query_string={"start": day(29), "end": day(0)})
    assert short.get_json()["filters"]["start"] == day(3)  # Short Ships too
    ot_app.config["ORDERTIMING_FIRST_DAY"] = now_ny_naive().date() + timedelta(days=5)  # not yet: today only
    assert get_orders(client, start=day(29), end=day(0))["filters"]["start"] == day(0)
    ot_app.config["ORDERTIMING_FIRST_DAY"] = ""  # none: the last 30 days
    assert get_orders(client, start=day(60), end=day(0))["filters"]["start"] == day(29)


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
    assert [row[header.index("Short Qty")] for row in body if row[header.index("Short Qty")]] == ["1"]
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


# --- Short Ships (2026-11-17) ---------------------------------------------------------------------
# Order 3's second line is short one (three days ago, site A); order 6, today at site B, has two
# FILL-KILL lines shipped none, one of them not in Fill/Kill yet, and a full one. Short Ships reads
# two views, which join the feeds in SQL (db/ordertiming/01_views.sql): stood in here as they'd come.
# The cup's CS holds 12 eaches (its QOE); Infor has none for the gloves' CS.
CUP_QOE = 12


def short_line(row: dict, po_lines: int, reason=None, reason_date=None, in_fillkill=True, qoe=None) -> dict:
    """A line of vw_ShortShipLine: a short line of Main's view, then its PO's total lines, its line
    in Fill/Kill's feed (``in_fillkill`` False: not in it yet), and its QOE with its ordered and short
    quantities in eaches (2026-11-18; none without a QOE)."""
    return {**row, "PO Total Lines": po_lines, "In Fill/Kill": 1 if in_fillkill else 0,
            "Fill/Kill Reason": reason, "Est Avail Date": reason_date, "QOE": qoe,
            "Order Qty EA": row["Order Qty"] * qoe if qoe else None,
            "Short Qty EA": row["Short Qty"] * qoe if qoe else None}


def kills(item: str, site: tuple, ago: int, n: int = 1) -> dict:
    """A row of vw_ItemKillDay: an item's kill lines at a Sold-To (as Main's view writes it) on a day."""
    return {"Medline Item #": item, "Sold-To #": site[0], "Order Date": day(ago), "Kill Lines": n}


@pytest.fixture
def short_client(ot_app):
    fill_kill = {"Line Type": "FILL-KILL", "Shipped Qty": 0, "Open Qty": None}
    order6 = [
        line(6, "000010", 0, site=SITE_B, **fill_kill, **{"Order Qty": 4, "Short Qty": 4}),
        line(6, "000020", 0, site=SITE_B, **fill_kill, **{"Order Qty": 5, "Short Qty": 5, "Medline Item #": "MDS2585H",
                                                          "Item Description": "GLOVE,EXAM,NITRILE,M"}),
        line(6, "000030", 0, site=SITE_B, **{"Line Type": "FILL-KILL", "Shipped Qty": 10, "Open Qty": None}),
    ]
    add_view_rows(ot_app, "vw_MedlineOrderLine", order6)
    order3 = next(row for row in lines() if row["Short Qty"])
    add_view_rows(ot_app, "vw_ShortShipLine", [
        short_line(order3, 2, "Backorder", "2026-12-01", qoe=CUP_QOE),
        short_line(order6[0], 3, "Allocated Item", qoe=CUP_QOE),
        short_line(order6[1], 3, in_fillkill=False),
    ])
    add_view_rows(ot_app, "vw_ItemKillDay", [
        kills("DYND70294BH", SITE_A, 3),  # order 3's short line
        kills("DYND70294BH", SITE_B, 0),  # order 6's first line
        kills("DYND70294BH", SITE_A, 10),  # past the last week
        kills("DYND70294BH", SITE_A, 40),  # past the last 30 days
        kills("OTHER", SITE_B, 0),
    ])
    return logged_in(ot_app, "mm@example.org", plm=None, fillkill=("materials_manager",))


def get_short(client, **params):
    """Short Ships' items: in the last 7 days, which the fixture's lines span, unless the days are
    given (it opens on today: test_main_opens_on_today)."""
    params = {"start": day(6), "end": day(0), **params}
    response = client.get("/ordertiming/api/shortships", query_string=params)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def items_of(data):
    return [item["medline_item"] for item in data["items"]]


def test_short_ships_an_item_a_row_with_its_kills(short_client):
    data = get_short(short_client)
    assert items_of(data) == ["DYND70294BH", "MDS2585H"]  # the most killed in 30 days first
    assert (data["sort"], data["dir"], data["total"]) == ("kills_30", "desc", 2)
    cup = data["items"][0]
    assert (cup["short_lines"], cup["pos"], cup["sites"], cup["short_qty"], cup["um"]) == (2, 2, 2, 5, "CS")
    assert cup["site_names"] == sorted([SITE_A[1], SITE_B[1]])
    assert (cup["kills_today"], cup["kills_7"], cup["kills_30"]) == (1, 2, 3)  # not the kill 40 days ago
    assert cup["last_short"].endswith("09:03:00") and cup["last_short"].startswith(day(0))
    gloves = data["items"][1]
    assert (gloves["short_lines"], gloves["short_qty"], gloves["kills_30"]) == (1, 5, 0)
    assert data["kill_windows"] == {"today": day(0), "week": day(6), "month": day(29)}


def test_short_ships_lines_with_their_po_and_fillkill_reason(short_client):
    cup, gloves = get_short(short_client)["items"]
    newest, older = cup["lines"]  # newest first
    assert (newest["po"], newest["po_lines"], newest["line_type"], newest["short_qty"]) == ("3000000006", 3, "FILL-KILL", 4)
    assert newest["created_at"].startswith(day(0))
    assert (newest["in_fillkill"], newest["kill_reason"]) == (True, "Allocated Item")
    assert (older["po"], older["po_lines"], older["short_qty"], older["kill_reason"], older["kill_reason_date"]) == (
        "3000000003", 2, 1, "Backorder", "2026-12-01")
    assert (gloves["lines"][0]["in_fillkill"], gloves["lines"][0]["kill_reason"]) == (False, None)  # not in Fill/Kill yet


def test_short_ships_sites_narrow_the_lines_and_the_kills(short_client):
    # The kill counts' Sold-Tos are written as Main's (the view pads Fill/Kill's with its zeros).
    data = get_short(short_client, sites=SITE_B[0])
    assert items_of(data) == ["DYND70294BH", "MDS2585H"]
    cup = data["items"][0]
    assert (cup["short_lines"], cup["kills_today"], cup["kills_7"], cup["kills_30"]) == (1, 1, 1, 1)
    data = get_short(short_client, sites=SITE_A[0])
    assert items_of(data) == ["DYND70294BH"]
    assert [data["items"][0][key] for key in ("kills_today", "kills_7", "kills_30")] == [0, 1, 2]


def test_short_ships_days_and_search(short_client):
    assert items_of(get_short(short_client, start=day(0), end=day(0))) == ["DYND70294BH", "MDS2585H"]
    today_cup = get_short(short_client, start=day(0), end=day(0))["items"][0]
    assert today_cup["short_lines"] == 1 and today_cup["kills_30"] == 3  # the kill counts don't follow the days
    assert items_of(get_short(short_client, start=day(3), end=day(3))) == ["DYND70294BH"]
    assert items_of(get_short(short_client, q="nitrile")) == ["MDS2585H"]
    assert items_of(get_short(short_client, q="3000000003")) == ["DYND70294BH"]
    assert get_short(short_client, q="nothing like it")["items"] == []


def test_short_ships_sorts_and_pages(short_client, ot_app):
    assert items_of(get_short(short_client, sort="medline_item", dir="asc")) == ["DYND70294BH", "MDS2585H"]
    assert items_of(get_short(short_client, sort="medline_item", dir="desc")) == ["MDS2585H", "DYND70294BH"]
    assert items_of(get_short(short_client, sort="kills_today", dir="asc")) == ["MDS2585H", "DYND70294BH"]
    assert items_of(get_short(short_client, sort="short_qty", dir="desc")) == ["DYND70294BH", "MDS2585H"]  # a tie: kills
    data = get_short(short_client, sort="nonsense", dir="sideways")
    assert (data["sort"], data["dir"]) == ("kills_30", "desc")  # back to the default
    with ot_app.app_context():
        today = now_ny_naive().date()
        week = queries.Filters(today - timedelta(days=6), today)
        second = queries.short_items(week, today, page=2, per_page=1)
        past = queries.short_items(week, today, page=5, per_page=1)
    assert [i["medline_item"] for i in second["items"]] == ["MDS2585H"] and (second["pages"], second["total"]) == (2, 2)
    assert past["page"] == 2


def test_short_ships_qty_ordered_and_qoe(short_client):
    # 2026-11-18, the user: Qty ordered beside Qty short, and the QOE when there is one, with both
    # quantities in eaches. Without a QOE (the gloves) there are none in eaches.
    cup, gloves = get_short(short_client)["items"]
    assert (cup["short_qty"], cup["qty"], cup["um"]) == (5, 7, "CS")  # order 3's 1 of 3, order 6's 4 of 4
    assert cup["qoes"] == [{"uom": "CS", "qoe": CUP_QOE}]
    assert (cup["short_qty_each"], cup["qty_each"]) == (5 * CUP_QOE, 7 * CUP_QOE)
    assert (gloves["short_qty"], gloves["qty"], gloves["qoes"]) == (5, 5, [{"uom": "CS", "qoe": None}])
    assert (gloves["short_qty_each"], gloves["qty_each"]) == (None, None)
    assert cup["lines"][0]["qoe"] == CUP_QOE and gloves["lines"][0]["qoe"] is None


def test_short_ships_sorts_quantities_in_eaches(short_client, ot_app):
    # Qty short and Qty ordered sort in eaches when they're known (a case outweighs an each), else as
    # they are; QOE by the largest, an item without one last either way.
    big = line(8, "000010", 0, **{"Medline Item #": "BIG", "Order Qty": 30, "Shipped Qty": 0, "Open Qty": None,
                                  "Short Qty": 30, "UM": "EA"})
    add_view_rows(ot_app, "vw_MedlineOrderLine", [big])
    add_view_rows(ot_app, "vw_ShortShipLine", [short_line(big, 1, qoe=1)])
    assert items_of(get_short(short_client, sort="short_qty", dir="desc")) == ["DYND70294BH", "BIG", "MDS2585H"]  # 60, 30, 5
    assert items_of(get_short(short_client, sort="qty", dir="asc")) == ["MDS2585H", "BIG", "DYND70294BH"]  # 5, 30, 84
    assert items_of(get_short(short_client, sort="qoe", dir="desc")) == ["DYND70294BH", "BIG", "MDS2585H"]
    assert items_of(get_short(short_client, sort="qoe", dir="asc")) == ["BIG", "DYND70294BH", "MDS2585H"]


def test_short_ships_mixed_units_have_no_one_total(short_client, ot_app):
    each = line(7, "000010", 1, **{"Order Qty": 2, "Shipped Qty": 0, "Open Qty": None, "Short Qty": 2, "UM": "EA"})
    add_view_rows(ot_app, "vw_MedlineOrderLine", [each])
    add_view_rows(ot_app, "vw_ShortShipLine", [short_line(each, 1, in_fillkill=False, qoe=1)])
    cup = get_short(short_client)["items"][0]
    assert cup["medline_item"] == "DYND70294BH" and (cup["short_qty"], cup["um"], cup["short_lines"]) == (None, None, 3)
    assert cup["qty"] is None
    assert sorted(line_["um"] for line_ in cup["lines"]) == ["CS", "CS", "EA"]
    # In eaches, though, since every line has a QOE: 60 + 2 short, 84 + 2 ordered.
    assert (cup["short_qty_each"], cup["qty_each"]) == (5 * CUP_QOE + 2, 7 * CUP_QOE + 2)
    assert cup["qoes"] == [{"uom": "CS", "qoe": CUP_QOE}, {"uom": "EA", "qoe": 1}]


def test_short_ships_export(short_client):
    response = short_client.get("/ordertiming/shortships/export", query_string={"start": day(6), "end": day(0)})
    assert response.status_code == 200 and "short-ships-" in response.headers["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.get_data(as_text=True).lstrip("﻿"))))
    header, body = rows[0], rows[1:]
    assert len(body) == 3
    for label in ("PO", "PO Created", "PO Total Lines", "Line Type", "Short Qty", "In Fill/Kill", "Fill/Kill Reason",
                  "Item Killed Today", "Item Killed 7 Days", "Item Killed 30 Days", "QOE", "Order Qty EA",
                  "Short Qty EA"):
        assert label in header, label
    by_po = {(row[header.index("PO")], row[header.index("Medline Item #")]): row for row in body}
    gloves = by_po[("3000000006", "MDS2585H")]
    assert (gloves[header.index("In Fill/Kill")], gloves[header.index("Short Qty")]) == ("No", "5")
    cup = by_po[("3000000003", "DYND70294BH")]
    assert [cup[header.index(label)] for label in ("Fill/Kill Reason", "PO Total Lines", "Item Killed 30 Days")] == [
        "Backorder", "2", "3"]
    assert [cup[header.index(label)] for label in ("Order Qty", "QOE", "Order Qty EA", "Short Qty EA")] == [
        "3", "12", "36", "12"]
    assert [gloves[header.index(label)] for label in ("QOE", "Order Qty EA", "Short Qty EA")] == ["", "", ""]
    # It opens on today, as the page does: order 6's two lines.
    today = short_client.get("/ordertiming/shortships/export").get_data(as_text=True).lstrip("\ufeff")
    assert len(list(csv.reader(io.StringIO(today)))) == 3


def test_short_ships_without_its_views_says_so(short_client, ot_app):
    from app import db

    with ot_app.app_context(), db.engine.begin() as conn:
        conn.exec_driver_sql('DROP TABLE "OrderTiming"."vw_ShortShipLine"')
    response = short_client.get("/ordertiming/api/shortships")
    assert response.status_code == 503  # 01_views.sql not run yet: said, as for Main's views


# --- Dashboard (2026-11-20) ------------------------------------------------------------------------
# The fixture's orders in the last week (1 and 3 at site A, 2 at site B, not confirmed), and order 7:
# received at 21:58 two days ago, its order created and confirmed at 05:45 the next morning (467
# minutes), as Medline's evening POs were on O2.

from app.ordertiming import dashboard  # noqa: E402


def evening_order() -> list[dict]:
    times = {"Received At": f"{day(2)} 21:58:28", "Order Created At": f"{day(1)} 05:45:15",
             "Confirmed At": f"{day(1)} 05:45:22", "Mins  to Order Create": 467, "Mins to Confirm": 467}
    return [line(7, "000010", 1, site=SITE_B, **times), line(7, "000020", 1, site=SITE_B, **times)]


@pytest.fixture
def dash_client(ot_app):
    add_view_rows(ot_app, "vw_MedlineOrderLine", evening_order())
    return logged_in(ot_app, "viewer@example.org", plm=None, fillkill=("viewer",))


def get_dashboard(client, **params):
    response = client.get("/ordertiming/api/dashboard", query_string=params)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def test_dashboard_page_settings(dash_client):
    page = dash_client.get("/ordertiming/dashboard").get_data(as_text=True)
    assert f'"start": "{day(6)}"' in page and f'"end": "{day(0)}"' in page  # the last 7 days
    assert '"confirm_bands": [["within_15", "Within 15 min"], ["within_60", "15 min to 1 hour"]' in page
    assert '["not_confirmed", "Not confirmed yet"]]' in page and '"slow_minutes": 60' in page
    assert '"dashboard": "/ordertiming/api/dashboard"' in page and '"problem": null' in page
    assert 'id="ot-q"' not in page  # no search


def test_dashboard_headline(dash_client):
    data = get_dashboard(dash_client)
    assert data["scope"] == {"start": day(6), "end": day(0), "sites": []}
    h = data["headline"]
    assert (h["pos"], h["lines"], h["sites"]) == (4, 8, 2)
    assert (h["confirmed"], h["not_confirmed"], h["share_confirmed"]) == (3, 1, 75)
    assert h["median_confirm_minutes"] == 4 and h["slow"] == 1  # order 7 took 467 minutes
    assert (h["asn"], h["share_asn"]) == (2, 50)  # orders 1 and 3
    assert (h["rejected_lines"], h["rejected_pos"]) == (1, 1)
    assert (h["short_lines"], h["short_pos"], h["share_short"]) == (1, 1, 12.5)
    assert data["data"]["loaded_at"]


def test_dashboard_lines_per_day_by_status(dash_client):
    by_day = get_dashboard(dash_client)["by_day"]
    assert by_day["days"] == [day(n) for n in range(6, -1, -1)]  # every day of the week on the axis
    assert set(by_day["series"]) == {"rejected", "asn", "confirmed", "not_confirmed"}  # the page orders them
    today, three_ago, yesterday = 6, 3, 5
    assert by_day["series"]["asn"][today] == 1 and by_day["series"]["asn"][three_ago] == 1
    assert by_day["series"]["confirmed"][yesterday] == 2  # order 7's lines
    assert by_day["series"]["rejected"][today] == 1 and by_day["series"]["not_confirmed"][today] == 1
    assert sum(by_day["series"]["confirmed"]) == 4 and by_day["short"][three_ago] == 1 and sum(by_day["short"]) == 1


def test_dashboard_hours(dash_client):
    data = get_dashboard(dash_client)
    received = data["by_hour_received"]["series"]
    assert set(received) == {"within_15", "within_60", "within_240", "over_240", "not_confirmed"}
    assert received["within_15"][11] == 1 and received["within_15"][9] == 1  # orders 1 and 3, 4 minutes each
    assert received["over_240"][21] == 1  # the evening order
    assert received["not_confirmed"][8] == 1  # order 2
    assert sum(sum(values) for values in received.values()) == 4
    created = data["by_hour_created"]["series"]
    assert created["asn"][9] == 2 and created["no_asn"][9] == 1 and created["no_asn"][5] == 1


def test_dashboard_sites_slowest_and_rejected(dash_client):
    data = get_dashboard(dash_client)
    rows = [(s["site"], s["pos"], s["lines"], s["confirmed"], s["slow"], s["asn"]) for s in data["sites"]]
    assert rows == [(SITE_A[0], 2, 5, 2, 0, 2), (SITE_B[0], 2, 3, 1, 1, 0)]  # the most POs first, then by name
    assert data["sites"][1]["site_name"] == SITE_B[1] and data["sites"][1]["median_confirm_minutes"] == 467
    assert data["sites"][0]["median_asn_hours"] == pytest.approx(2.2, abs=0.05)  # 22 minutes and 4 hours
    slowest = data["slowest"]
    assert [o["order_no"][-1] for o in slowest] == ["7", "3", "1"]  # then the 4-minute ones, the oldest first
    assert slowest[0]["minutes"] == 467 and slowest[0]["lines"] == 2 and slowest[0]["po"] == "3000000007"
    assert slowest[0]["received_at"].endswith("21:58:28") and slowest[0]["confirmed_at"].endswith("05:45:22")
    assert data["rejected"] == [{"rej_code": "E1", "medline_item": "INVALID PART", "item_on_po": "DYND70294BH",
                                 "description": "CUP,DENTURE,8OZ", "lines": 1, "pos": 1}]


def test_dashboard_days_and_sites_but_no_search_or_status(dash_client):
    today = get_dashboard(dash_client, start=day(0), end=day(0))
    assert today["headline"]["pos"] == 2 and today["by_day"]["days"] == [day(0)]
    site_b = get_dashboard(dash_client, sites=SITE_B[0])
    assert site_b["headline"]["pos"] == 2 and [s["site"] for s in site_b["sites"]] == [SITE_B[0]]
    assert site_b["rejected"] == []
    ignored = get_dashboard(dash_client, q="3000000001", status="rejected")
    assert ignored["headline"]["pos"] == 4
    held = get_dashboard(dash_client, start=day(60), end=day(0))
    assert held["scope"]["start"] == day(29)  # held to the last 30 days, as Main
    assert dash_client.get("/ordertiming/api/dashboard", query_string={"start": "11/20"}).status_code == 400


def test_dashboard_without_its_view(sqlite_app):
    _drop_line_view(sqlite_app)
    admin = logged_in(sqlite_app, "admin@example.org", role="admin", plm=None, fillkill=("viewer",))
    page = admin.get("/ordertiming/dashboard").get_data(as_text=True)
    assert "db/ordertiming/01_views.sql" in page
    response = admin.get("/ordertiming/api/dashboard")
    assert response.status_code == 503 and "01_views.sql" in response.get_json()["message"]


def test_confirm_bands():
    def band(minutes, confirmed=True):
        return dashboard.confirm_band({"confirmed": confirmed, "minutes": minutes})
    assert [band(m) for m in (0, 15, 15.5, 60, 61, 240, 241, 467)] == [
        "within_15", "within_15", "within_60", "within_60", "within_240", "within_240", "over_240", "over_240"]
    assert band(None, confirmed=False) == "not_confirmed"


def test_a_po_is_confirmed_when_every_line_is():
    row = {"order_no": "1", "po": "P", "site": "S", "site_name": "N", "report_date": "2026-11-19",
           "received_at": "2026-11-19 10:00:00", "created_at": "2026-11-19 10:05:00",
           "confirmed_at": "2026-11-19 10:06:30", "confirmed_lines": 2, "line_rows": 2, "mins_to_confirm": None,
           "asn_at": "2026-11-19 15:00:00", "asn_lines": 1, "lines": 2, "rejected_lines": 0, "short_lines": 0}
    order = dashboard.order_figures(row)
    assert order["confirmed"] and order["minutes"] == 6.5  # from the times, when Medline left them out
    assert order["asn_hours"] == 5.0
    unconfirmed = dashboard.order_figures({**row, "confirmed_lines": 1, "mins_to_confirm": 6})
    assert not unconfirmed["confirmed"] and unconfirmed["minutes"] is None and unconfirmed["confirmed_at"] is None
    assert dashboard.summary([])["share_confirmed"] is None and dashboard.headline([])["sites"] == 0
