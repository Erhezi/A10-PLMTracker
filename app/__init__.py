"""Application factory setup."""
from __future__ import annotations
import os
from flask import Flask
from .config import DevConfig, ProdConfig
from .extensions import db, migrate, login_manager, csrf

# Blueprint imports will be deferred (placeholders) to avoid circular imports until implemented.

def create_app(env: str | None = None) -> Flask:
    app = Flask(__name__)

    env_name = env or os.getenv("FLASK_ENV", "development")
    if env_name == "production":
        app.config.from_object(ProdConfig())
    else:
        app.config.from_object(DevConfig())

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    register_blueprints(app)
    register_shellcontext(app)

    return app


def register_blueprints(app: Flask) -> None:
    # Local imports (blueprints will provide 'bp')
    from .auth import routes as auth_routes  # type: ignore
    from .items import routes as items_routes  # placeholders
    from .contracts import routes as contracts_routes
    from .groups import routes as groups_routes
    from .tracking import routes as tracking_routes
    from .admin import routes as admin_routes

    # Each routes.py will expose a blueprint named 'bp' later; for now we'll skip if missing
    for module in [auth_routes, items_routes, contracts_routes, groups_routes, tracking_routes, admin_routes]:
        bp = getattr(module, "bp", None)
        if bp is not None:
            app.register_blueprint(bp)


def register_shellcontext(app: Flask) -> None:
    from . import models

    @app.shell_context_processor
    def _ctx():  # pragma: no cover - convenience
        return {"db": db, "models": models}
