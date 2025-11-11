from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from sqlalchemy import MetaData, text
import os

from .config import config_map

# Global DB + Login manager instances
metadata = MetaData(schema="PLM")
db = SQLAlchemy(metadata=metadata)
login_manager = LoginManager()
login_manager.login_view = "auth.login"


class PathPrefixMiddleware:
    """Adjust SCRIPT_NAME/PATH_INFO when the app is mounted under a URL prefix."""

    def __init__(self, app, prefix: str):
        self.app = app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        if self.prefix:
            path_info = environ.get("PATH_INFO", "")
            if path_info.startswith(self.prefix):
                environ["SCRIPT_NAME"] = self.prefix
                stripped = path_info[len(self.prefix):]
                environ["PATH_INFO"] = stripped if stripped else "/"
        return self.app(environ, start_response)


def _normalized_prefix(raw: str | None) -> str:
    if not raw:
        return ""
    prefix = raw.strip()
    if not prefix:
        return ""
    if not prefix.startswith("/"):
        prefix = f"/{prefix}"
    prefix = prefix.rstrip("/")
    return prefix if prefix else ""


def create_app(env: str | None = None, url_prefix: str | None = None):
    env = env or os.getenv("FLASK_ENV", "development")
    url_prefix = _normalized_prefix(url_prefix or os.getenv("URL_PREFIX"))

    static_url_path = f"{url_prefix}/static" if url_prefix else "/static"
    app = Flask(
        __name__,
        static_folder="static",
        static_url_path=static_url_path,
        template_folder="templates",
    )

    cfg_cls = config_map.get(env, config_map["default"])
    app.config.from_object(cfg_cls)
    if url_prefix:
        app.config["APPLICATION_ROOT"] = url_prefix

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)

    # Import models so that db.create_all sees them
    from .models.auth import User  # noqa: F401
    from .models.relations import ItemLink  # noqa: F401
    from .models.inventory import Item, ContractItem  # noqa: F401

    # Register blueprints
    from .auth.routes import bp as auth_bp
    from .collector.routes import bp as collector_bp
    from .dashboard.routes import bp as dashboard_bp
    from .playground.routes import bp as playground_bp
    from .main.routes import bp as main_bp
    from .admin.routes import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(collector_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(playground_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)

    if url_prefix:
        # WSGI middleware so IIS-hosted app sees the correct SCRIPT_NAME
        app.wsgi_app = PathPrefixMiddleware(app.wsgi_app, url_prefix)  # type: ignore[attr-defined]

    # Bootstrap schema + tables (no Alembic for MVP)
    with app.app_context():
        engine = db.engine
        if engine.url.get_backend_name().startswith("mssql"):
            with engine.begin() as conn:
                conn.execute(text("""
                    IF SCHEMA_ID('PLM') IS NULL EXEC('CREATE SCHEMA PLM AUTHORIZATION dbo;')
                """))
        db.create_all()

    return app


@login_manager.user_loader
def load_user(user_id: str):
    from .models.auth import User
    return db.session.get(User, int(user_id))
