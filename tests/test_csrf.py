import re
from pathlib import Path

import pytest

from conftest import csrf_from, login, make_user

TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "templates"
POST_FORM = re.compile(r"<form\b[^>]*\bmethod=[\"']post[\"'][^>]*>(.*?)</form>", re.IGNORECASE | re.DOTALL)


def test_every_post_form_carries_the_csrf_token():
    forms = []
    missing = []
    for path in TEMPLATES.rglob("*.html"):
        for match in POST_FORM.finditer(path.read_text(encoding="utf-8")):
            forms.append(path.name)
            if "csrf_token()" not in match.group(1):
                missing.append(f"{path.relative_to(TEMPLATES)}: {match.group(0)[:80]}")
    assert len(forms) >= 14, f"expected at least 14 POST forms, found {len(forms)}"
    assert not missing, "POST forms without a csrf_token field:\n" + "\n".join(missing)


def test_base_template_gives_scripts_the_token_and_marks_their_requests():
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert '<meta name="csrf-token" content="{{ csrf_token() }}"' in base
    assert "headers.set('X-CSRFToken', csrfToken)" in base
    assert "headers.set('X-Requested-With', 'fetch')" in base
    assert "data.error === 'login_expired'" in base


@pytest.fixture
def user_client(sqlite_app):
    make_user(sqlite_app, "user@example.org")
    client = sqlite_app.test_client()
    login(client, "user@example.org")
    return client


def test_login_form_without_token_is_refused(sqlite_app):
    make_user(sqlite_app, "user@example.org")
    client = sqlite_app.test_client()
    client.get("/auth/login")
    response = client.post("/auth/login", data={"email": "user@example.org", "password": "pw"})
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]
    with client.session_transaction() as session:
        assert "_user_id" not in session


def test_form_post_without_token_goes_to_login_with_message(user_client):
    response = user_client.post("/auth/logout", headers={"Referer": "http://localhost/fillkill/"})
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]
    page = user_client.get("/auth/login").get_data(as_text=True)
    assert "Your login has expired. Please log in again to continue." in page


def test_form_post_with_token_works(user_client):
    token = csrf_from(user_client.get("/auth/register/pending").get_data(as_text=True))
    response = user_client.post("/auth/logout", data={"csrf_token": token})
    assert response.status_code == 302
    with user_client.session_transaction() as session:
        assert "_user_id" not in session
        assert "login_at" not in session


def test_script_post_without_token_gets_401(user_client):
    response = user_client.post(
        "/groups/batch/stage", json={}, headers={"X-Requested-With": "fetch"}
    )
    assert response.status_code == 401
    assert response.get_json()["error"] == "login_expired"


def test_script_post_with_token_reaches_the_route(user_client):
    token = csrf_from(user_client.get("/auth/register/pending").get_data(as_text=True))
    response = user_client.post(
        "/groups/batch/stage",
        json={},
        headers={"X-Requested-With": "fetch", "X-CSRFToken": token},
    )
    # The route's own validation answers, so the CSRF check passed.
    assert response.status_code == 400
    assert response.get_json()["message"] == "Missing stage"
