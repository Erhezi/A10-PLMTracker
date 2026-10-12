from datetime import datetime, time
from urllib.parse import parse_qs, urlsplit

import pytest

from app.utility import session_policy as sp
from conftest import csrf_from, login, make_user

RESET = time(2, 30)


def next_of(location):
    """The login page and the ?next= it carries, from a redirect target."""
    parts = urlsplit(location)
    return parts.path, parse_qs(parts.query).get("next", [None])[0]


# --- the rules -------------------------------------------------------------

@pytest.mark.parametrize("now, expected", [
    (datetime(2026, 10, 12, 2, 29, 59), datetime(2026, 10, 11, 2, 30)),
    (datetime(2026, 10, 12, 2, 30), datetime(2026, 10, 12, 2, 30)),
    (datetime(2026, 10, 12, 23, 59), datetime(2026, 10, 12, 2, 30)),
    (datetime(2026, 10, 13, 0, 5), datetime(2026, 10, 12, 2, 30)),
])
def test_last_reset_is_the_most_recent_reset_moment(now, expected):
    assert sp.last_reset(now, RESET) == expected


def test_evening_login_ends_at_the_next_reset():
    login_at = datetime(2026, 10, 12, 22, 0)
    assert not sp.login_expired(login_at, datetime(2026, 10, 13, 2, 29), RESET)
    assert sp.login_expired(login_at, datetime(2026, 10, 13, 2, 30), RESET)


def test_login_just_after_reset_lasts_a_full_day():
    login_at = datetime(2026, 10, 12, 2, 31)
    assert not sp.login_expired(login_at, datetime(2026, 10, 13, 2, 29), RESET)
    assert sp.login_expired(login_at, datetime(2026, 10, 13, 2, 30), RESET)


def test_login_shortly_before_reset_is_short():
    login_at = datetime(2026, 10, 12, 2, 15)
    assert sp.login_expired(login_at, datetime(2026, 10, 12, 2, 30), RESET)


def test_spring_forward_sunday():
    # 2027-03-14: New York clocks jump from 2:00 to 3:00, so 2:30 never shows on the clock.
    login_at = datetime(2027, 3, 14, 1, 50)
    assert not sp.login_expired(login_at, datetime(2027, 3, 14, 1, 59), RESET)
    assert sp.login_expired(login_at, datetime(2027, 3, 14, 3, 0), RESET)


def test_fall_back_sunday():
    # 2026-11-01: 1:00-1:59 happens twice; the reset still happens once, at 2:30.
    login_at = datetime(2026, 11, 1, 1, 30)
    assert not sp.login_expired(login_at, datetime(2026, 11, 1, 1, 45), RESET)
    assert not sp.login_expired(login_at, datetime(2026, 11, 1, 2, 29), RESET)
    assert sp.login_expired(login_at, datetime(2026, 11, 1, 2, 30), RESET)


def test_login_without_a_recorded_time_counts_as_expired():
    assert sp.login_expired(None, datetime(2026, 10, 12, 9, 0), RESET)


def test_reset_can_be_disabled():
    assert not sp.login_expired(None, datetime(2026, 10, 12, 9, 0), None)
    assert sp.parse_reset_time("") is None


def test_reset_time_and_label():
    assert sp.parse_reset_time("02:30") == time(2, 30)
    assert sp.parse_reset_time("23:05") == time(23, 5)
    assert sp.reset_label(time(2, 30)) == "2:30 AM"
    assert sp.reset_label(time(14, 0)) == "2:00 PM"


@pytest.mark.parametrize("value, script_root, expected", [
    ("/dashboard/", "", "/dashboard/"),
    ("/groups?stage=x", "", "/groups?stage=x"),
    ("/plm/fillkill/", "/plm", "/fillkill/"),
    ("/plm", "/plm", "/"),
    ("/fillkill/", "/plm", "/fillkill/"),
    ("https://evil.example/", "", None),
    ("//evil.example/x", "", None),
    ("/\\evil.example", "", None),
    ("javascript:alert(1)", "", None),
    ("dashboard", "", None),
    ("", "", None),
    (None, "", None),
])
def test_safe_next_only_allows_paths_inside_the_app(value, script_root, expected):
    assert sp.safe_next(value, script_root) == expected


# --- through the app ---------------------------------------------------------

@pytest.fixture
def clock(monkeypatch):
    """A clock the test can move; both login and the reset check read it."""
    state = {"now": datetime(2026, 10, 12, 9, 0)}
    monkeypatch.setattr(sp, "_now", lambda: state["now"])
    return state


@pytest.fixture
def viewer(sqlite_app):
    make_user(sqlite_app, "viewer@example.org", fillkill=("viewer",))
    return sqlite_app.test_client()


def test_login_records_the_time_and_returns_to_next(viewer, clock):
    response = login(viewer, "viewer@example.org", next_path="/fillkill/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/fillkill/")
    with viewer.session_transaction() as session:
        assert session["login_at"] == "2026-10-12T09:00:00"


def test_login_ignores_a_next_that_leaves_the_app(viewer, clock):
    response = login(viewer, "viewer@example.org", next_path="https://evil.example/")
    assert response.status_code == 302
    assert "evil.example" not in response.headers["Location"]


def test_page_after_reset_goes_to_login_with_message_and_back(viewer, clock):
    login(viewer, "viewer@example.org")
    assert viewer.get("/fillkill/").status_code == 200

    clock["now"] = datetime(2026, 10, 13, 2, 31)
    response = viewer.get("/fillkill/")
    assert response.status_code == 302
    assert next_of(response.headers["Location"]) == ("/auth/login", "/fillkill/")

    page = viewer.get("/auth/login?next=/fillkill/").get_data(as_text=True)
    assert "Your login expired at 2:30 AM. Please log in again to continue." in page

    back = login(viewer, "viewer@example.org", next_path="/fillkill/")
    assert back.headers["Location"].endswith("/fillkill/")
    assert viewer.get("/fillkill/").status_code == 200


def test_script_call_after_reset_gets_401_json(viewer, clock):
    login(viewer, "viewer@example.org")
    clock["now"] = datetime(2026, 10, 13, 3, 0)
    response = viewer.get("/fillkill/", headers={"X-Requested-With": "fetch"})
    assert response.status_code == 401
    body = response.get_json()
    assert body["error"] == "login_expired"
    assert body["login_url"].endswith("/auth/login")


def test_htmx_call_after_reset_redirects_the_whole_page(viewer, clock):
    login(viewer, "viewer@example.org")
    clock["now"] = datetime(2026, 10, 13, 3, 0)
    response = viewer.get(
        "/api/items/search?q=abc",
        headers={"HX-Request": "true", "HX-Current-URL": "http://localhost/collect"},
    )
    assert response.status_code == 204
    assert next_of(response.headers["HX-Redirect"]) == ("/auth/login", "/collect")


def test_login_from_before_this_release_must_log_in_again(viewer, clock):
    login(viewer, "viewer@example.org")
    with viewer.session_transaction() as session:
        session.pop("login_at")
    response = viewer.get("/fillkill/")
    assert response.status_code == 302
    page = viewer.get("/auth/login").get_data(as_text=True)
    assert "Your login has expired. Please log in again to continue." in page


def test_round_trip_under_the_plm_prefix(sqlite_app_factory, clock):
    """Production is mounted at /plm; the return path must survive the prefix both ways."""
    app = sqlite_app_factory(url_prefix="/plm")
    make_user(app, "viewer@example.org", fillkill=("viewer",))
    client = app.test_client()

    def plm_login(next_path):
        token = csrf_from(client.get("/plm/auth/login").get_data(as_text=True))
        return client.post("/plm/auth/login", data={
            "email": "viewer@example.org", "password": "pw", "csrf_token": token, "next": next_path,
        })

    # appFetch sends window.location.pathname, which includes the prefix.
    assert plm_login("/plm/fillkill/").headers["Location"].endswith("/plm/fillkill/")

    clock["now"] = datetime(2026, 10, 13, 3, 0)
    expired = client.get("/plm/fillkill/")
    assert next_of(expired.headers["Location"]) == ("/plm/auth/login", "/fillkill/")

    # The page redirect carries the path without the prefix; login puts it back.
    assert plm_login("/fillkill/").headers["Location"].endswith("/plm/fillkill/")
    assert client.get("/plm/fillkill/").status_code == 200


def test_anonymous_page_and_script_requests(sqlite_app):
    client = sqlite_app.test_client()
    page = client.get("/fillkill/")
    assert page.status_code == 302
    assert next_of(page.headers["Location"]) == ("/auth/login", "/fillkill/")

    script = client.get("/fillkill/", headers={"X-Requested-With": "fetch"})
    assert script.status_code == 401
    assert script.get_json()["error"] == "login_expired"
