from types import SimpleNamespace

import pytest

from app.utility import access
from app.utility.access import FILLKILL, MODULES, PLM
from conftest import login, make_user


def fake_user(*, admin=False, plm=None, fillkill=(), authenticated=True):
    rows = [SimpleNamespace(module="fillkill", role=code) for code in fillkill]
    if plm:
        rows.append(SimpleNamespace(module="plm", role=plm))
    return SimpleNamespace(
        is_authenticated=authenticated,
        user_role="admin" if admin else "user",
        module_roles=rows,
    )


FILLKILL_CAPABILITIES = MODULES[FILLKILL].capabilities


@pytest.mark.parametrize("roles, expected", [
    (("viewer",), {"view"}),
    (("proposer",), {"view", "add_sub"}),
    (("clinical",), {"view", "review"}),
    (("materials",), {"view", "add_sub", "order"}),
    (("proposer", "clinical"), {"view", "add_sub", "review"}),
    ((), set()),
])
def test_fillkill_capabilities_follow_roles(roles, expected):
    user = fake_user(fillkill=roles)
    granted = {cap for cap in FILLKILL_CAPABILITIES if access.can(user, FILLKILL, cap)}
    assert granted == expected


def test_admin_can_always_view_but_acts_only_through_roles():
    bare_admin = fake_user(admin=True)
    assert access.can(bare_admin, FILLKILL, "view")
    assert access.can(bare_admin, PLM, "view")
    assert not access.can(bare_admin, FILLKILL, "review")
    assert not access.can(bare_admin, PLM, "edit")

    full_admin = fake_user(admin=True, plm="editor", fillkill=MODULES[FILLKILL].role_codes)
    assert all(access.can(full_admin, FILLKILL, cap) for cap in FILLKILL_CAPABILITIES)
    assert access.can(full_admin, PLM, "edit")

    without_c = fake_user(admin=True, fillkill=("viewer", "proposer", "clinical"))
    assert not access.can(without_c, FILLKILL, "order")


def test_anonymous_user_can_do_nothing():
    anonymous = fake_user(authenticated=False, admin=True, plm="editor", fillkill=("viewer",))
    assert not access.is_admin(anonymous)
    assert not access.can(anonymous, FILLKILL, "view")
    assert not access.can(anonymous, PLM, "view")


def test_unknown_capability_is_an_error():
    with pytest.raises(KeyError):
        access.can(fake_user(fillkill=("viewer",)), FILLKILL, "approve")


def logged_in(app, email, **kwargs):
    make_user(app, email, **kwargs)
    client = app.test_client()
    login(client, email)
    return client


def test_user_without_fillkill_role_sees_no_module_and_is_turned_away(sqlite_app):
    client = logged_in(sqlite_app, "plm@example.org")
    page = client.get("/auth/register/pending").get_data(as_text=True)
    assert "PLM Tracker" in page
    assert "Fill/Kill Management" not in page

    response = client.get("/fillkill/")
    assert response.status_code == 302
    assert client.get(response.headers["Location"], follow_redirects=True).status_code == 200


def test_viewer_sees_module_and_its_page_row(sqlite_app):
    client = logged_in(sqlite_app, "viewer@example.org", fillkill=("viewer",))
    page = client.get("/fillkill/").get_data(as_text=True)
    assert "Fill/Kill Management" in page
    assert 'class="page-nav' in page
    assert 'aria-current="page">Main</a>' in page
    assert "Viewer" in page


def test_admin_without_fillkill_roles_can_still_open_the_module(sqlite_app):
    client = logged_in(sqlite_app, "admin@example.org", role="admin")
    response = client.get("/fillkill/")
    assert response.status_code == 200
    assert "as an admin you can still view this module" in response.get_data(as_text=True)


def test_plm_editor_page_row(sqlite_app):
    user = logged_in(sqlite_app, "user@example.org")
    page = user.get("/conflicts").get_data(as_text=True)
    for label in ("Collect", "Groups", "Conflicts", "Dashboard", "Playground"):
        assert f">{label}</a>" in page
    assert 'aria-current="page">Conflicts</a>' in page


def test_plm_viewer_page_row_hides_collect_and_conflicts(sqlite_app):
    with sqlite_app.test_request_context("/groups"):
        nav = access.build_nav(fake_user(plm="viewer"))
    assert nav["active"] == "plm"
    assert [page["label"] for page in nav["pages"]] == ["Groups", "Dashboard", "Playground"]
    assert [module["label"] for module in nav["modules"]] == ["PLM Tracker"]


def test_module_row_lists_only_modules_you_can_open(sqlite_app):
    with sqlite_app.test_request_context("/fillkill/"):
        fillkill_only = access.build_nav(fake_user(fillkill=("viewer",)))
        admin = access.build_nav(fake_user(admin=True))
        nobody = access.build_nav(fake_user())
    assert [m["key"] for m in fillkill_only["modules"]] == ["fillkill"]
    assert [m["key"] for m in admin["modules"]] == ["plm", "fillkill"]
    assert nobody["modules"] == []
