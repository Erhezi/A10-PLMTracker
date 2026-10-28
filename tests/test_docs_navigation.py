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
    # The MM Lead's instructions by the name Main gives them (2026-10-27).
    assert "<strong>Will&#39;s Comments</strong>, between the approved substitutes and their vendor items" in page


def test_fillkill_docs_say_who_can_do_what_from_the_role_rules(sqlite_app):
    # Every capability has its lines in the table, and the ticks follow MODULES (2026-10-21).
    from app.selfawareness.routes import FILLKILL_ROLE_COLUMNS
    from app.utility.access import FILLKILL, FILLKILL_FUNCTIONS, MODULES
    assert {capability for _, capability in FILLKILL_FUNCTIONS} == set(MODULES[FILLKILL].capabilities)
    assert set(FILLKILL_ROLE_COLUMNS) == set(MODULES[FILLKILL].role_codes)
    page = sqlite_app.test_client().get("/doc/fillkill").get_data(as_text=True)
    table = page[page.index('id="who-can-do-what"'):]
    table = table[:table.index("</table>")]
    vendor = table[table.index("Add, correct or delete a sub&#39;s vendor items"):]
    vendor = vendor[:vendor.index("</tr>")]
    # Viewer, Sub Approver, MM/SCM, Materials Manager, Sub Finder
    assert [cell.startswith('<i class="bi bi-check-lg') for cell in
            [part.split(">", 1)[1].strip() for part in vendor.split('<td class="text-center"')[1:]]] == [False, False, True, True, True]


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
