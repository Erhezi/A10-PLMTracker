"""The /plm mount: anything requested outside it is sent inside it.

Flask's test client presets SCRIPT_NAME from APPLICATION_ROOT, which hides this behaviour. wfastcgi
blanks SCRIPT_NAME and passes the full URL in PATH_INFO, so these tests pass ``base_url=IIS`` to
get that same environ.
"""

import re

import pytest

from conftest import csrf_from, make_user

IIS = "http://ynbbstvwp03:5080/"


@pytest.fixture
def plm_app(sqlite_app_factory):
    app = sqlite_app_factory(url_prefix="/plm")
    make_user(app, "viewer@example.org", fillkill=("viewer",))
    return app


@pytest.fixture
def client(plm_app):
    return plm_app.test_client()


@pytest.mark.parametrize("requested, location", [
    ("/", "/plm/"),
    ("/auth/login", "/plm/auth/login"),
    ("/auth/login?next=/fillkill/", "/plm/auth/login?next=/fillkill/"),
    ("/fillkill/?site=a&site=b", "/plm/fillkill/?site=a&site=b"),
    ("/plmtracker", "/plm/plmtracker"),  # starts with the letters, but is not inside the mount
    # The session cookie's path is case-sensitive, so the wrong case has to land on /plm itself.
    ("/PLM", "/plm"),
    ("/PLM/", "/plm/"),
    ("/Plm/auth/login?next=/fillkill/", "/plm/auth/login?next=/fillkill/"),
    ("/PLMtracker", "/plm/PLMtracker"),
])
def test_request_outside_the_prefix_is_redirected_inside(client, requested, location):
    response = client.get(requested, base_url=IIS)
    assert response.status_code == 307
    assert response.headers["Location"] == location


@pytest.mark.parametrize("requested", ["/plm", "/plm/", "/plm/auth/login"])
def test_request_inside_the_prefix_is_not_redirected(client, requested):
    response = client.get(requested, base_url=IIS)
    assert not response.headers.get("Location", "").startswith("/plm/plm")
    assert response.status_code in (200, 302)
    if response.status_code == 302:  # not logged in: the login page, not a prefix redirect
        assert response.headers["Location"].startswith("/plm/auth/login")


@pytest.mark.parametrize("start", ["/", "/PLM", "/PLM/"])
def test_bare_host_and_upper_case_reach_a_styled_login_that_works(client, start):
    page = client.get(start, base_url=IIS, follow_redirects=True)
    assert page.status_code == 200
    assert page.request.path == "/plm/auth/login"

    html = page.get_data(as_text=True)
    stylesheet = re.search(r'href="([^"]*app\.css[^"]*)"', html).group(1)
    assert client.get(stylesheet, base_url=IIS).status_code == 200

    response = client.post("/plm/auth/login", base_url=IIS, data={
        "email": "viewer@example.org", "password": "pw", "csrf_token": csrf_from(html),
    })
    assert response.status_code == 302
    assert "/auth/login" not in response.headers["Location"]
    assert client.get("/plm/fillkill/", base_url=IIS).status_code == 200


def test_post_from_a_page_left_open_outside_the_prefix_stays_a_post(client):
    response = client.post("/auth/login", base_url=IIS, data={"email": "x"})
    assert response.status_code == 307
    assert response.headers["Location"] == "/plm/auth/login"


def test_prefix_already_stripped_by_the_server_does_not_loop(plm_app):
    """wfastcgi strips the prefix itself when SCRIPT_NAME is set in its environment."""
    response = plm_app.test_client().get("/auth/login", environ_overrides={
        "SCRIPT_NAME": "/plm", "PATH_INFO": "/auth/login",
    })
    assert response.status_code == 200


@pytest.mark.parametrize("requested", [
    "//evil.example/x", "/\\evil.example", "/a%0d%0aSet-Cookie:x=1", "/PLM//evil.example/x",
])
def test_redirect_stays_on_this_site_and_adds_no_headers(client, requested):
    response = client.get(requested, base_url=IIS)
    assert response.status_code == 307
    assert response.headers["Location"].startswith("/plm/")
    assert "Set-Cookie" not in response.headers


def test_without_a_prefix_nothing_is_redirected(sqlite_app):
    assert sqlite_app.test_client().get("/auth/login", base_url=IIS).status_code == 200
