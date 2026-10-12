from types import SimpleNamespace

import pytest

from app.utility import access
from conftest import csrf_from, login, make_user


def fake_user(role="user", fillkill=(), authenticated=True):
    return SimpleNamespace(
        is_authenticated=authenticated,
        user_role=role,
        module_roles=[SimpleNamespace(module="fillkill", role=code) for code in fillkill],
    )


# --- capabilities ------------------------------------------------------------

@pytest.mark.parametrize("roles, expected", [
    (("viewer",), {"view"}),
    (("proposer",), {"view", "add_sub"}),
    (("clinical",), {"view", "review"}),
    (("materials",), {"view", "add_sub", "order"}),
    (("proposer", "clinical"), {"view", "add_sub", "review"}),
    ((), set()),
])
def test_capabilities_follow_roles(roles, expected):
    user = fake_user(fillkill=roles)
    granted = {cap for cap in access.CAPABILITIES if access.can(user, cap)}
    assert granted == expected


def test_admin_can_always_view_but_acts_only_through_roles():
    bare_admin = fake_user(role="admin")
    assert access.can(bare_admin, "view")
    assert not access.can(bare_admin, "review")

    full_admin = fake_user(role="admin", fillkill=access.FILLKILL_ROLES)
    assert all(access.can(full_admin, cap) for cap in access.CAPABILITIES)

    without_c = fake_user(role="admin", fillkill=("viewer", "proposer", "clinical"))
    assert not access.can(without_c, "order")


def test_anonymous_user_can_do_nothing():
    anonymous = fake_user(authenticated=False, fillkill=access.FILLKILL_ROLES)
    assert not any(access.can(anonymous, cap) for cap in access.CAPABILITIES)


def test_unknown_capability_is_an_error():
    with pytest.raises(KeyError):
        access.can(fake_user(fillkill=("viewer",)), "approve")


def test_b_and_c_together_only_for_admins():
    assert access.role_conflict({"clinical", "materials"}, admin=False)
    assert access.role_conflict({"clinical", "materials"}, admin=True) is None
    assert access.role_conflict({"proposer", "clinical"}, admin=False) is None
    assert access.role_conflict({"proposer", "materials"}, admin=False) is None


# --- navigation and the module page -------------------------------------------

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


def test_admin_without_roles_can_still_open_the_module(sqlite_app):
    client = logged_in(sqlite_app, "admin@example.org", role="admin")
    response = client.get("/fillkill/")
    assert response.status_code == 200
    assert "as an admin you can still view this module" in response.get_data(as_text=True)


def test_plm_page_row(sqlite_app):
    user = logged_in(sqlite_app, "user@example.org")
    page = user.get("/conflicts").get_data(as_text=True)
    for label in ("Collect", "Groups", "Conflicts", "Dashboard", "Playground"):
        assert f">{label}</a>" in page
    assert 'aria-current="page">Conflicts</a>' in page


def test_view_only_plm_page_row_hides_collect_and_conflicts(sqlite_app):
    with sqlite_app.test_request_context("/groups"):
        nav = access.build_nav(fake_user(role="view-only"))
    assert nav["active"] == "plm"
    assert [page["label"] for page in nav["pages"]] == ["Groups", "Dashboard", "Playground"]
    assert [module["label"] for module in nav["modules"]] == ["PLM Tracker"]


# --- User Control: Fill/Kill roles --------------------------------------------

@pytest.fixture
def admin(sqlite_app):
    client = logged_in(sqlite_app, "admin@example.org", role="admin", fillkill=access.FILLKILL_ROLES)
    return client


def roles_of(app, email):
    from app.models.auth import User
    with app.app_context():
        return access.fillkill_roles(User.query.filter_by(email=email).one())


def post_form(client, path, data):
    token = csrf_from(client.get("/admin/user-control").get_data(as_text=True))
    return client.post(path, data={**data, "csrf_token": token}, follow_redirects=True)


def test_user_control_shows_roles_and_saves_them(sqlite_app, admin):
    make_user(sqlite_app, "nurse@example.org")
    page = admin.get("/admin/user-control").get_data(as_text=True)
    assert "Fill/Kill Roles" in page
    assert 'name="fillkill_roles" value="clinical"' in page

    response = post_form(admin, "/admin/update-fillkill-roles/nurse@example.org",
                         {"fillkill_roles": ["proposer", "clinical"]})
    assert "A · Sub entry, B · Nursing" in response.get_data(as_text=True)
    assert roles_of(sqlite_app, "nurse@example.org") == {"proposer", "clinical"}

    post_form(admin, "/admin/update-fillkill-roles/nurse@example.org", {"fillkill_roles": ["viewer"]})
    assert roles_of(sqlite_app, "nurse@example.org") == {"viewer"}


def test_b_and_c_refused_for_a_non_admin(sqlite_app, admin):
    make_user(sqlite_app, "mm@example.org", fillkill=("materials",))
    response = post_form(admin, "/admin/update-fillkill-roles/mm@example.org",
                         {"fillkill_roles": ["clinical", "materials"]})
    assert "not saved" in response.get_data(as_text=True)
    assert roles_of(sqlite_app, "mm@example.org") == {"materials"}


def test_b_and_c_allowed_for_an_admin(sqlite_app, admin):
    make_user(sqlite_app, "admin2@example.org", role="admin")
    post_form(admin, "/admin/update-fillkill-roles/admin2@example.org",
              {"fillkill_roles": ["clinical", "materials"]})
    assert roles_of(sqlite_app, "admin2@example.org") == {"clinical", "materials"}


def test_unknown_role_refused(sqlite_app, admin):
    make_user(sqlite_app, "x@example.org")
    response = post_form(admin, "/admin/update-fillkill-roles/x@example.org", {"fillkill_roles": ["boss"]})
    assert "Invalid Fill/Kill role" in response.get_data(as_text=True)
    assert roles_of(sqlite_app, "x@example.org") == set()


def test_promotion_grants_every_role(sqlite_app, admin):
    make_user(sqlite_app, "new.admin@example.org", fillkill=("viewer",))
    post_form(admin, "/admin/update-user-role/new.admin@example.org", {"user_role": "admin"})
    assert roles_of(sqlite_app, "new.admin@example.org") == set(access.FILLKILL_ROLES)


def test_demoting_an_admin_holding_b_and_c_is_refused_until_one_is_removed(sqlite_app, admin):
    make_user(sqlite_app, "old.admin@example.org", role="admin", fillkill=access.FILLKILL_ROLES)
    response = post_form(admin, "/admin/update-user-role/old.admin@example.org", {"user_role": "user"})
    assert "Remove one of them" in response.get_data(as_text=True)

    from app.models.auth import User
    with sqlite_app.app_context():
        assert User.query.filter_by(email="old.admin@example.org").one().user_role == "admin"

    post_form(admin, "/admin/update-fillkill-roles/old.admin@example.org",
              {"fillkill_roles": ["viewer", "proposer", "clinical"]})
    post_form(admin, "/admin/update-user-role/old.admin@example.org", {"user_role": "user"})
    with sqlite_app.app_context():
        assert User.query.filter_by(email="old.admin@example.org").one().user_role == "user"


def test_deleting_a_user_removes_their_roles(sqlite_app, admin):
    make_user(sqlite_app, "gone@example.org", fillkill=("viewer", "proposer"))
    post_form(admin, "/admin/delete-user/gone@example.org", {})

    from app.models.auth import UserModuleRole
    with sqlite_app.app_context():
        assert UserModuleRole.query.count() == len(access.FILLKILL_ROLES)  # only the admin's remain


def test_non_admin_cannot_change_roles_even_their_own(sqlite_app):
    client = logged_in(sqlite_app, "self@example.org", fillkill=("viewer",))
    token = csrf_from(client.get("/auth/register/pending").get_data(as_text=True))
    client.post("/admin/update-fillkill-roles/self@example.org",
                data={"fillkill_roles": ["clinical", "proposer"], "csrf_token": token})
    assert roles_of(sqlite_app, "self@example.org") == {"viewer"}
