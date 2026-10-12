import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def sqlite_app_factory():
    """Build the real app (create_app) on in-memory SQLite, with PLM and FillKill attached as schemas.

    Nothing touches SQL Server, and CSRF protection is on, as in production.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    from sqlalchemy.pool import StaticPool

    from app import create_app, db

    def attach_schemas(dbapi_conn, _record):
        if type(dbapi_conn).__module__.startswith("sqlite3"):
            cursor = dbapi_conn.cursor()
            for schema in ("PLM", "FillKill"):
                cursor.execute(f"ATTACH DATABASE ':memory:' AS \"{schema}\"")
            cursor.close()

    built = []

    def build(url_prefix=None):
        app = create_app("development", url_prefix=url_prefix, config_overrides={
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "poolclass": StaticPool,
                "connect_args": {"check_same_thread": False},
            },
            "ENABLE_BURN_RATE_REFRESH": False,
        })
        built.append(app)
        return app

    event.listen(Engine, "connect", attach_schemas)
    try:
        yield build
        for app in built:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
    finally:
        event.remove(Engine, "connect", attach_schemas)


@pytest.fixture
def sqlite_app(sqlite_app_factory):
    return sqlite_app_factory()


def make_user(app, email, *, role="user", fillkill=(), active=True, password="pw"):
    """Create a user with a PLM role and optional Fill/Kill role codes."""
    from app import db
    from app.models.auth import User, UserModuleRole

    with app.app_context():
        user = User(email=email, name=email.split("@")[0], user_role=role, is_active=active)
        user.set_password(password)
        for code in fillkill:
            user.module_roles.append(UserModuleRole(module="fillkill", role=code))
        db.session.add(user)
        db.session.commit()
        return user.user_id


def csrf_from(html: str) -> str:
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    assert match, "page has no csrf-token meta tag"
    return match.group(1)


def login(client, email, password="pw", next_path=None):
    """Log in through the real form, CSRF token included."""
    page = client.get("/auth/login")
    data = {"email": email, "password": password, "csrf_token": csrf_from(page.get_data(as_text=True))}
    if next_path is not None:
        data["next"] = next_path
    return client.post("/auth/login", data=data)
