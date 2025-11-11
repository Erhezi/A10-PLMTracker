"""WSGI entry point for IIS via wfastcgi."""

import os

from app import create_app

ENV = os.getenv("FLASK_ENV", "production")
URL_PREFIX = os.getenv("URL_PREFIX", "/plm" if ENV == "production" else "")

app = create_app(ENV)
application = app

__all__ = ["app", "application"]
