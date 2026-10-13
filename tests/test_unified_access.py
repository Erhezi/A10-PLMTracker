"""One account per person: an app-level role (admin or user) plus roles per module
(PLM, Fill/Kill), wired back into PLM."""

import pytest

from app.utility import access
from app.utility.access import FILLKILL, PLM
from conftest import csrf_from, login, make_user


# --- the rules -------------------------------------------------------------

def test_validate_roles():
    assert access.validate_roles(admin=False, roles={PLM: {"editor"}, FILLKILL: {"sub_finder", "sub_approver"}}) is None
    assert "Pick one PLM Tracker role" in access.validate_roles(admin=False, roles={PLM: {"viewer", "editor"}})
    assert "Unknown PLM Tracker role" in access.validate_roles(admin=False, roles={PLM: {"owner"}})
    assert "Unknown Fill/Kill" in access.validate_roles(admin=False, roles={FILLKILL: {"boss"}})
    assert access.validate_roles(admin=False, roles={FILLKILL: {"sub_approver", "materials_manager"}}) == access.APPROVE_ORDER_CONFLICT_MESSAGE
    assert access.validate_roles(admin=True, roles={FILLKILL: {"sub_approver", "materials_manager"}}) is None


@pytest.mark.parametrize("admin", [False, True])
def test_fillkill_viewer_is_held_alone(admin):
    assert access.validate_roles(admin=admin, roles={FILLKILL: {"viewer"}}) is None
    problem = access.validate_roles(admin=admin, roles={FILLKILL: {"viewer", "sub_finder"}})
    assert problem == "Fill/Kill Management Viewer can't be combined with other roles."


@pytest.mark.parametrize("user_role, authenticated, expected", [
    ("admin", True, True),
    ("user", True, False),
    ("view-only", True, False),  # left by the previous release until 04_after_deploy.sql
    (None, True, False),
    ("admin", False, False),
])
def test_admin_is_the_app_level_role(user_role, authenticated, expected):
    from types import SimpleNamespace

    user = SimpleNamespace(is_authenticated=authenticated, user_role=user_role, module_roles=[])
    assert access.is_admin(user) is expected


@pytest.mark.parametrize("endpoint, blueprint, method, expected", [
    ("dashboard.index", "dashboard", "GET", "view"),
    ("dashboard.api_stats", "dashboard", "POST", "view"),         # filters sent as POST, read only
    ("dashboard.export_table", "dashboard", "POST", "view"),
    ("collector.groups", "collector", "GET", "view"),
    ("collector.api_search_items", "collector", "GET", "view"),
    ("collector.collect", "collector", "GET", "edit"),           # editor-only pages
    ("collector.conflicts", "collector", "GET", "edit"),
    ("collector.batch_update_stage", "collector", "POST", "edit"),
    ("collector.api_delete_item_link", "collector", "DELETE", "edit"),
    ("collector.batch_export_wrike_item_numbers", "collector", "POST", "view"),
    ("collector.clear_deleted", "collector", "POST", "edit"),     # the view also requires admin
    ("playground.index", "playground", "GET", "view"),
])
def test_plm_capability_needed_per_request(endpoint, blueprint, method, expected):
    assert access.plm_capability_for(endpoint, blueprint, method) == expected


# --- PLM enforcement through the app -----------------------------------------

def client_for(app, email, **kwargs):
    make_user(app, email, **kwargs)
    client = app.test_client()
    login(client, email)
    return client


def post_json(client, path, payload, token_page="/auth/register/pending"):
    token = csrf_from(client.get(token_page).get_data(as_text=True))
    return client.post(path, json=payload, headers={"X-Requested-With": "fetch", "X-CSRFToken": token})


def test_plm_viewer_can_read_but_not_change(sqlite_app):
    viewer = client_for(sqlite_app, "viewer@example.org", role="view-only")
    assert viewer.get("/dashboard/").status_code == 200

    denied = post_json(viewer, "/groups/batch/stage", {})
    assert denied.status_code == 403
    assert "Viewer" in denied.get_json()["message"]

    page = viewer.get("/collect")
    assert page.status_code == 302  # editor-only page


def test_plm_editor_reaches_the_route(sqlite_app):
    editor = client_for(sqlite_app, "editor@example.org", role="user")
    response = post_json(editor, "/groups/batch/stage", {})
    assert response.status_code == 400
    assert response.get_json()["message"] == "Missing stage"


def test_user_without_plm_role_cannot_open_plm(sqlite_app):
    client = client_for(sqlite_app, "fk@example.org", plm=None, fillkill=("viewer",))
    response = client.get("/dashboard/")
    assert response.status_code == 302
    landing = client.get(response.headers["Location"])
    assert landing.headers["Location"].endswith("/fillkill/")  # their only module
    assert post_json(client, "/groups/batch/stage", {}).status_code == 403


def test_admin_obeys_their_plm_role(sqlite_app):
    viewer = client_for(sqlite_app, "admin.viewer@example.org", role="admin", plm="viewer")
    assert viewer.get("/dashboard/").status_code == 200
    assert post_json(viewer, "/groups/batch/stage", {}).status_code == 403

    none = client_for(sqlite_app, "admin.none@example.org", role="admin", plm=None)
    assert none.get("/dashboard/").status_code == 302
    denied = post_json(none, "/groups/batch/stage", {})
    assert denied.status_code == 403
    assert "don't have access to PLM Tracker" in denied.get_json()["message"]


def test_cleanup_actions_stay_admin_only(sqlite_app):
    editor = client_for(sqlite_app, "editor@example.org", role="user")
    token = csrf_from(editor.get("/auth/register/pending").get_data(as_text=True))
    response = editor.post("/groups/clear-deleted", data={"csrf_token": token}, follow_redirects=True)
    assert "Only admins can clear deleted rows" in response.get_data(as_text=True)

    admin = client_for(sqlite_app, "admin@example.org", role="admin")
    token = csrf_from(admin.get("/auth/register/pending").get_data(as_text=True))
    response = admin.post("/groups/clear-deleted", data={"csrf_token": token}, follow_redirects=True)
    assert "No rows with stage Deleted to remove" in response.get_data(as_text=True)

    # ...with the PLM Editor role: an admin who is a PLM Viewer can't.
    admin_viewer = client_for(sqlite_app, "admin.viewer@example.org", role="admin", plm="viewer")
    token = csrf_from(admin_viewer.get("/auth/register/pending").get_data(as_text=True))
    response = admin_viewer.post("/groups/clear-deleted", data={"csrf_token": token}, follow_redirects=True)
    assert "Your PLM Tracker role is Viewer" in response.get_data(as_text=True)


# --- landing -------------------------------------------------------------------

def test_landing_goes_to_the_first_module_you_can_open(sqlite_app):
    plm = client_for(sqlite_app, "plm@example.org", role="user")
    assert plm.get("/").headers["Location"].endswith("/dashboard/")

    fk = client_for(sqlite_app, "fk@example.org", plm=None, fillkill=("viewer",))
    assert fk.get("/").headers["Location"].endswith("/fillkill/")


def test_admin_without_any_module_lands_in_user_control(sqlite_app):
    admin = client_for(sqlite_app, "admin@example.org", role="admin", plm=None)
    assert admin.get("/").headers["Location"].endswith("/admin/user-control")


def test_landing_without_any_module_explains(sqlite_app):
    nobody = client_for(sqlite_app, "new@example.org", role=None, requested="plm,fillkill")
    response = nobody.get("/")
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "No module access yet" in page
    assert "PLM Tracker" in page and "Fill/Kill Management" in page  # what they asked for


# --- registration ----------------------------------------------------------------

def test_registration_records_requested_modules_and_grants_nothing(sqlite_app):
    from app.models.auth import User

    client = sqlite_app.test_client()
    page = client.get("/auth/register").get_data(as_text=True)
    assert 'name="modules" value="plm"' in page
    assert 'name="modules" value="fillkill"' in page

    client.post("/auth/register", data={
        "email": "New.Person@example.org", "password": "secret1", "name": "New",
        "modules": ["fillkill", "bogus"], "csrf_token": csrf_from(page),
    })
    with sqlite_app.app_context():
        user = User.query.filter_by(email="new.person@example.org").one()
        assert user.requested_modules == "fillkill"
        assert user.module_roles == []
        assert user.user_role == "user"
        assert not user.is_active


# --- User Control ------------------------------------------------------------------

@pytest.fixture
def admin(sqlite_app):
    return client_for(sqlite_app, "admin@example.org", role="admin",
                      fillkill=("sub_finder", "sub_approver", "materials_manager"))


def save_access(client, email, *, admin=False, plm="", fillkill=()):
    token = csrf_from(client.get("/admin/user-control").get_data(as_text=True))
    data = {"csrf_token": token, "role_plm": plm, "role_fillkill": list(fillkill)}
    if admin:
        data["app_admin"] = "on"
    return client.post(f"/admin/update-access/{email}", data=data, follow_redirects=True)


def state(app, email):
    from app.models.auth import User
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        return {
            "admin": access.is_admin(user),
            "plm": set(access.roles_in(user, PLM)),
            "fillkill": set(access.roles_in(user, FILLKILL)),
            "app_role": user.user_role,
        }


def test_user_control_shows_a_row_per_user_with_every_module(sqlite_app, admin):
    make_user(sqlite_app, "nurse@example.org", role=None, requested="fillkill", active=False)
    page = admin.get("/admin/user-control").get_data(as_text=True)
    for heading in ("Admin", "PLM Tracker", "Fill/Kill Management"):
        assert f">{heading}</th>" in page
    assert 'type="radio" name="role_plm" value=""' in page  # No access
    assert 'type="radio" name="role_plm" value="editor"' in page
    assert 'type="checkbox" name="role_fillkill" value="viewer" form="access-2" id="fillkill-2-viewer" data-exclusive="1"' in page
    assert 'value="sub_approver" form="access-2" id="fillkill-2-sub_approver" >' in page  # not exclusive
    assert "Save access" in page
    assert ">Requested</th>" not in page
    assert "Asked for: Fill/Kill Management" in page


def test_save_access_sets_every_module(sqlite_app, admin):
    make_user(sqlite_app, "nurse@example.org", role="view-only")  # as migrated: PLM viewer
    response = save_access(admin, "nurse@example.org", plm="viewer", fillkill=("sub_finder", "sub_approver"))
    assert "PLM Tracker: Viewer; Fill/Kill Management: Sub Finder, Sub Approver" in response.get_data(as_text=True)
    assert state(sqlite_app, "nurse@example.org") == {
        "admin": False, "plm": {"viewer"}, "fillkill": {"sub_finder", "sub_approver"}, "app_role": "user",
    }

    save_access(admin, "nurse@example.org", plm="editor", fillkill=())
    assert state(sqlite_app, "nurse@example.org") == {
        "admin": False, "plm": {"editor"}, "fillkill": set(), "app_role": "user",
    }

    save_access(admin, "nurse@example.org", plm="")
    assert state(sqlite_app, "nurse@example.org")["plm"] == set()
    assert state(sqlite_app, "nurse@example.org")["app_role"] == "user"


def test_b_and_c_refused_unless_admin(sqlite_app, admin):
    make_user(sqlite_app, "mm@example.org", fillkill=("materials_manager",))
    response = save_access(admin, "mm@example.org", plm="editor", fillkill=("sub_approver", "materials_manager"))
    assert "not saved" in response.get_data(as_text=True)
    assert state(sqlite_app, "mm@example.org")["fillkill"] == {"materials_manager"}

    make_user(sqlite_app, "admin2@example.org", role="admin")
    save_access(admin, "admin2@example.org", admin=True, plm="editor", fillkill=("sub_approver", "materials_manager"))
    assert state(sqlite_app, "admin2@example.org")["fillkill"] == {"sub_approver", "materials_manager"}


def test_fillkill_viewer_with_another_role_refused(sqlite_app, admin):
    make_user(sqlite_app, "watcher@example.org", fillkill=("viewer",))
    response = save_access(admin, "watcher@example.org", plm="editor", fillkill=("viewer", "sub_finder"))
    assert "Viewer can&#39;t be combined with other roles" in response.get_data(as_text=True)
    assert state(sqlite_app, "watcher@example.org")["fillkill"] == {"viewer"}


def test_database_refusing_roles_is_reported_and_nothing_changes(sqlite_app, admin, monkeypatch):
    # As on O2 when its role CHECK is older than the app: the app allows a role the table doesn't.
    from app.admin import routes as admin_routes

    make_user(sqlite_app, "x@example.org", fillkill=("sub_finder",))
    monkeypatch.setattr(admin_routes, "validate_roles", lambda **kwargs: None)
    response = save_access(admin, "x@example.org", plm="editor", fillkill=("not_in_the_check",))
    assert response.status_code == 200
    assert "the database refused these roles" in response.get_data(as_text=True)
    assert state(sqlite_app, "x@example.org")["fillkill"] == {"sub_finder"}  # removal rolled back too


def test_unknown_plm_role_refused(sqlite_app, admin):
    make_user(sqlite_app, "x@example.org")
    response = save_access(admin, "x@example.org", plm="owner")
    assert "Unknown PLM Tracker role" in response.get_data(as_text=True)
    assert state(sqlite_app, "x@example.org")["plm"] == {"editor"}


def test_promotion_keeps_the_module_roles_in_the_row(sqlite_app, admin):
    make_user(sqlite_app, "new.admin@example.org", role="view-only")
    save_access(admin, "new.admin@example.org", admin=True, plm="viewer")
    assert state(sqlite_app, "new.admin@example.org") == {
        "admin": True, "plm": {"viewer"}, "fillkill": set(), "app_role": "admin",
    }


def test_demoting_an_admin_who_keeps_b_and_c_is_refused(sqlite_app, admin):
    make_user(sqlite_app, "old.admin@example.org", role="admin", fillkill=("sub_approver", "materials_manager"))
    save_access(admin, "old.admin@example.org", admin=False, plm="editor", fillkill=("sub_approver", "materials_manager"))
    assert state(sqlite_app, "old.admin@example.org")["admin"] is True

    save_access(admin, "old.admin@example.org", admin=False, plm="editor", fillkill=("sub_approver",))
    assert state(sqlite_app, "old.admin@example.org") == {
        "admin": False, "plm": {"editor"}, "fillkill": {"sub_approver"}, "app_role": "user",
    }


def test_admins_cannot_remove_their_own_admin_access(sqlite_app, admin):
    response = save_access(admin, "admin@example.org", admin=False, plm="editor")
    assert "can't remove your own admin access" in response.get_data(as_text=True)
    assert state(sqlite_app, "admin@example.org")["admin"] is True

    # ...but can switch off their own module roles to test what others see.
    save_access(admin, "admin@example.org", admin=True, plm="viewer", fillkill=("viewer",))
    assert state(sqlite_app, "admin@example.org") == {
        "admin": True, "plm": {"viewer"}, "fillkill": {"viewer"}, "app_role": "admin",
    }


def test_non_admin_cannot_change_access(sqlite_app):
    client = client_for(sqlite_app, "self@example.org", fillkill=("viewer",))
    token = csrf_from(client.get("/auth/register/pending").get_data(as_text=True))
    client.post("/admin/update-access/self@example.org",
                data={"csrf_token": token, "app_admin": "on", "role_plm": "editor"})
    assert state(sqlite_app, "self@example.org")["admin"] is False


def test_approving_someone_without_roles_says_so(sqlite_app, admin):
    make_user(sqlite_app, "pending@example.org", role=None, active=False)
    token = csrf_from(admin.get("/admin/user-control").get_data(as_text=True))
    from app.admin import routes as admin_routes
    admin_routes.send_mail = lambda **kwargs: True  # no email in tests
    response = admin.post("/admin/approve-user/pending@example.org",
                          data={"csrf_token": token}, follow_redirects=True)
    assert "They have no module roles yet" in response.get_data(as_text=True)


def test_deleting_a_user_removes_their_roles(sqlite_app, admin):
    from app.models.auth import UserModuleRole

    make_user(sqlite_app, "gone@example.org", fillkill=("sub_finder", "sub_approver"))
    token = csrf_from(admin.get("/admin/user-control").get_data(as_text=True))
    admin.post("/admin/delete-user/gone@example.org", data={"csrf_token": token})
    with sqlite_app.app_context():
        emails_with_roles = {
            row.user_id for row in UserModuleRole.query.all()
        }
        assert len(emails_with_roles) == 1  # only the admin's rows remain
