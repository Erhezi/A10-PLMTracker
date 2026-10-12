"""Password reset: only the browser that entered a valid code may set the new password."""

from datetime import datetime, timedelta

import pytest

from app.auth import routes as auth_routes
from conftest import csrf_from, make_user


@pytest.fixture
def app_with_users(sqlite_app, monkeypatch):
    monkeypatch.setattr(auth_routes, "send_mail", lambda **kwargs: True)
    make_user(sqlite_app, "victim@example.org", password="old-victim")
    make_user(sqlite_app, "attacker@example.org", password="old-attacker")
    return sqlite_app


def token(client, path="/auth/reset_password"):
    return csrf_from(client.get(path).get_data(as_text=True))


def password_ok(app, email, password):
    from app.models.auth import User
    with app.app_context():
        return User.query.filter_by(email=email).one().check_password(password)


def reset_code(app, email):
    from app.models.auth import User
    with app.app_context():
        return User.query.filter_by(email=email).one().reset_code


def request_and_verify(client, app, email):
    client.post("/auth/reset_password", data={"email": email, "csrf_token": token(client)})
    code = reset_code(app, email)
    return client.post(
        "/auth/reset_password/verify",
        data={"email": email, "code": code, "csrf_token": token(client)},
    )


def test_update_page_refuses_anyone_who_has_not_verified_a_code(app_with_users):
    client = app_with_users.test_client()

    page = client.get("/auth/reset_password/update?email=victim@example.org")
    assert page.status_code == 302
    assert page.headers["Location"].endswith("/auth/reset_password")

    client.post(
        "/auth/reset_password/update?email=victim@example.org",
        data={"email": "victim@example.org", "password": "hacked", "csrf_token": token(client)},
    )
    assert password_ok(app_with_users, "victim@example.org", "old-victim")


def test_requested_but_unverified_code_is_not_enough(app_with_users):
    client = app_with_users.test_client()
    client.post("/auth/reset_password", data={"email": "victim@example.org", "csrf_token": token(client)})
    client.post(
        "/auth/reset_password/update?email=victim@example.org",
        data={"password": "hacked", "csrf_token": token(client)},
    )
    assert password_ok(app_with_users, "victim@example.org", "old-victim")


def test_verified_code_sets_the_password_once(app_with_users):
    client = app_with_users.test_client()
    verified = request_and_verify(client, app_with_users, "victim@example.org")
    assert verified.headers["Location"].endswith("/auth/reset_password/update")
    assert client.get("/auth/reset_password/update").status_code == 200

    done = client.post("/auth/reset_password/update", data={"password": "new-pass", "csrf_token": token(client)})
    assert done.headers["Location"].endswith("/auth/login")
    assert password_ok(app_with_users, "victim@example.org", "new-pass")
    assert reset_code(app_with_users, "victim@example.org") is None

    # The code is used up: a second attempt from the same browser is refused.
    client.post("/auth/reset_password/update", data={"password": "again", "csrf_token": token(client)})
    assert password_ok(app_with_users, "victim@example.org", "new-pass")


def test_verifying_your_own_email_does_not_unlock_someone_elses(app_with_users):
    client = app_with_users.test_client()
    request_and_verify(client, app_with_users, "attacker@example.org")

    client.post(
        "/auth/reset_password/update?email=victim@example.org",
        data={"email": "victim@example.org", "password": "hacked", "csrf_token": token(client)},
    )
    assert password_ok(app_with_users, "victim@example.org", "old-victim")
    assert password_ok(app_with_users, "attacker@example.org", "hacked")  # only their own


def test_wrong_code_does_not_verify(app_with_users):
    client = app_with_users.test_client()
    client.post("/auth/reset_password", data={"email": "victim@example.org", "csrf_token": token(client)})
    response = client.post(
        "/auth/reset_password/verify",
        data={"email": "victim@example.org", "code": "000000x", "csrf_token": token(client)},
    )
    assert response.status_code == 200  # back on the verify form
    with client.session_transaction() as session:
        assert auth_routes.RESET_VERIFIED_KEY not in session


def test_verification_goes_stale(app_with_users):
    client = app_with_users.test_client()
    request_and_verify(client, app_with_users, "victim@example.org")
    with client.session_transaction() as session:
        stale = datetime.now() - auth_routes.RESET_VERIFIED_WINDOW - timedelta(minutes=1)
        session[auth_routes.RESET_VERIFIED_KEY]["at"] = stale.isoformat(timespec="seconds")
        session.modified = True

    client.post("/auth/reset_password/update", data={"password": "late", "csrf_token": token(client)})
    assert password_ok(app_with_users, "victim@example.org", "old-victim")
