from types import SimpleNamespace

from app.utility import access
from conftest import login, make_user


def viewer():
    return SimpleNamespace(
        is_authenticated=True,
        user_role="user",
        module_roles=[SimpleNamespace(module="fillkill", role="viewer")],
    )


def test_fillkill_docs_are_public_with_a_docs_page_row(sqlite_app):
    page = sqlite_app.test_client().get("/doc/fillkill").get_data(as_text=True)
    assert "Fill/Kill Management Docs" in page
    assert 'aria-label="Docs"' in page
    assert 'aria-current="page">Fill/Kill Management</a>' in page
    assert ">PLM Tracker</a>" in page  # the other docs tab
    assert 'class="nav-link active" href="/doc/fillkill">Docs</a>' in page


def test_docs_link_follows_the_active_module(sqlite_app):
    user = viewer()
    with sqlite_app.test_request_context("/fillkill/"):
        assert access.build_nav(user)["docs_url"] == "/doc/fillkill"
    with sqlite_app.test_request_context("/conflicts"):
        assert access.build_nav(user)["docs_url"] == "/doc/"
    with sqlite_app.test_request_context("/admin/user-control"):
        assert access.build_nav(user)["docs_url"] == "/doc/"


def test_docs_page_row_without_login(sqlite_app):
    anonymous = SimpleNamespace(is_authenticated=False)
    with sqlite_app.test_request_context("/doc/"):
        nav = access.build_nav(anonymous)
    assert nav["modules"] == []
    assert nav["active"] == "docs"
    assert [p["label"] for p in nav["pages"]] == ["PLM Tracker", "Fill/Kill Management"]
    assert [p["active"] for p in nav["pages"]] == [True, False]


def test_navbar_has_no_app_name_text(sqlite_app):
    make_user(sqlite_app, "v@example.org", fillkill=("viewer",))
    client = sqlite_app.test_client()
    login(client, "v@example.org")
    page = client.get("/fillkill/").get_data(as_text=True)
    assert "navbar-brand" not in page
    assert "Item Management Assistant" not in page
    assert "<title>Fill/Kill Management — Item Management</title>" in page


def test_plm_docs_keep_their_content_and_get_the_page_row(sqlite_app):
    response = sqlite_app.test_client().get("/doc/")
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Welcome to PLM Tracker Docs" in page
    assert 'aria-current="page">PLM Tracker</a>' in page
