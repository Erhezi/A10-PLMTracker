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


ROLE_PRESETS = {
    # today's user_role -> (user_role, PLM role), as on O2 after 03_unify_roles.sql
    # ('view-only' stays until 04_after_deploy.sql)
    "admin": ("admin", "editor"),
    "user": ("user", "editor"),
    "view-only": ("view-only", "viewer"),
    None: ("user", None),
}

_UNSET = object()


def make_user(app, email, *, role="user", plm=_UNSET, fillkill=(), active=True, password="pw",
              requested=None):
    """Create a user with module roles.

    ``role`` is a preset named after today's roles (see ROLE_PRESETS); ``plm``
    overrides the PLM role (None = no PLM access); ``fillkill`` adds Fill/Kill roles.
    """
    from app import db
    from app.models.auth import User, UserModuleRole

    user_role, plm_role = ROLE_PRESETS[role]
    if plm is not _UNSET:
        plm_role = plm

    with app.app_context():
        user = User(
            email=email,
            name=email.split("@")[0],
            is_active=active,
            requested_modules=requested,
            user_role=user_role,
        )
        user.set_password(password)
        if plm_role:
            user.module_roles.append(UserModuleRole(module="plm", role=plm_role))
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
