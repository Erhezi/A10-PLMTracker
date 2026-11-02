"""Order Timing (2026-10-30): a module beside Fill/Kill with its own Main and Dashboard, for display,
empty until Medline's order feed is ready. Every Fill/Kill role can view it; it has no roles of its own."""

import pytest

from app.utility import access
from app.utility.access import ORDERTIMING
from conftest import login, make_user
from test_fillkill_access import fake_user

FILLKILL_ROLES = ["viewer", "sub_finder", "sub_approver", "materials_manager", "scm"]


def logged_in(app, email, **kwargs):
    make_user(app, email, **kwargs)
    client = app.test_client()
    login(client, email)
    return client


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
    assert 'aria-current="page">Main</a>' in main and 'id="ot-main-empty"' in main
    dash = client.get("/ordertiming/dashboard").get_data(as_text=True)
    assert 'aria-current="page">Dashboard</a>' in dash and 'id="ot-dash-empty"' in dash
    assert 'href="/doc/ordertiming">Docs</a>' in dash


@pytest.mark.parametrize("path", ["/ordertiming/", "/ordertiming/dashboard"])
def test_users_without_a_fillkill_role_are_turned_away(sqlite_app, path):
    client = logged_in(sqlite_app, "plm@example.org")  # PLM editor, no Fill/Kill
    response = client.get(path)
    assert response.status_code == 302
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
