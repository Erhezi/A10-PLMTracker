"""Configuration object placeholders (Dev/Test/Prod)."""
import os
from datetime import timedelta

class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE_ME_DEV")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "mssql+pyodbc://username:password@dsn")  # placeholder DSN
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Auth / security
    ALLOWED_EMAIL_DOMAINS = os.getenv("ALLOWED_EMAIL_DOMAINS", "example.com").split(",")
    EMAIL_VERIFICATION_TOKEN_MINUTES = int(os.getenv("EMAIL_VERIFICATION_TOKEN_MINUTES", "60"))
    PASSWORD_RESET_TOKEN_MINUTES = int(os.getenv("PASSWORD_RESET_TOKEN_MINUTES", "30"))

    # Mail (stub defaults)
    MAIL_SERVER = os.getenv("MAIL_SERVER", "localhost")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "25"))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "false").lower() == "true"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "noreply@example.com")

class DevConfig(BaseConfig):
    DEBUG = True

class ProdConfig(BaseConfig):
    DEBUG = False
    # Could enable stricter settings / feature flags here
