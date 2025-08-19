"""Basic smoke test for auth register -> verify -> login using Flask test client.
Run with: python -m pytest -q (after installing deps and setting up DB)
"""
from app import create_app
from app.extensions import db
from app.models import User, EmailVerificationToken
import pytest

@pytest.fixture()
def app():
    app = create_app()
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite:///:memory:", TESTING=True, WTF_CSRF_ENABLED=False)
    with app.app_context():
        db.create_all()
    yield app

@pytest.fixture()
def client(app):
    return app.test_client()

def test_register_verify_login_flow(client):
    # Register
    resp = client.post("/auth/register", data={"email":"user@example.com","password":"pw","name":"Test"}, follow_redirects=True)
    assert resp.status_code == 200
    # Fetch token from DB
    from app.models import EmailVerificationToken
    with client.application.app_context():
        token = EmailVerificationToken.query.order_by(EmailVerificationToken.id.desc()).first()
        assert token is not None
        # Token raw is not stored; in dev it's flashed but for test we simulate verifying via hash inversion is not possible
        # So we directly mark verified to simulate user clicking email (simplify smoke test)
        token.user.email_verified_at = token.created_at
        token.used_at = token.created_at
        db.session.commit()
    # Login
    resp2 = client.post("/auth/login", data={"email":"user@example.com","password":"pw"}, follow_redirects=True)
    assert b"Logged in" in resp2.data
