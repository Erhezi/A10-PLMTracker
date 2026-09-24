import os
import warnings
from pathlib import Path
from urllib.parse import quote_plus
from dotenv import load_dotenv

from .utility.env_secrets import load_env

root_env = Path(__file__).resolve().parents[1] / ".env"
if root_env.exists():
    load_dotenv(root_env)
    # Secrets are stored as KEY_HASHED=enc::... (see app/utility/env_secrets.py);
    # decrypt them and expose each under its plain name, e.g. CLIENT_SECRET.
    # A missing/wrong passphrase only warns: the DB side still works, and
    # first_time_setup.py must be importable on a machine without one yet.
    # Config.validate() reports the missing secret when Graph is actually used.
    try:
        for _key, _value in load_env(str(root_env)).items():
            os.environ.setdefault(_key, _value)
    except RuntimeError as exc:
        warnings.warn(f"Encrypted .env secrets not loaded: {exc}", RuntimeWarning)


# ---------------------------------------------------------------
#            Database targets
# ---------------------------------------------------------------
# Named backends for the PLM schema. Switch with DB_TARGET, e.g.
#   DB_TARGET=PRIME  -> fall back to the old server
# "O2" is the live target as of the 2026-09-04 cutover; "PRIME" is kept
# as the rollback path. See _migration/MIGRATION_PLAN.md.
DB_TARGETS = {
    "O2": {
        "server": r"YNBBSTVWP02\PROCDATASRVPROD",   # named instance
        "database": "PLM",
        "label": "O2 - procurement data server",
    },
    "PRIME": {
        "server": "MISCPrdAdhocDB",                 # alias for ODCUCSSQLBWP02
        "database": "PRIME",
        "label": "PRIME - legacy adhoc server (rollback)",
    },
}

DEFAULT_DB_TARGET = "O2"


def _resolve_target():
    name = os.getenv("DB_TARGET", DEFAULT_DB_TARGET).strip().upper()
    if name not in DB_TARGETS:
        raise ValueError(
            f"DB_TARGET={name!r} is not a known target. "
            f"Choose one of: {', '.join(sorted(DB_TARGETS))}"
        )
    return name, DB_TARGETS[name]


def build_mssql_uri(server, database, driver, trusted):
    """Build a SQLAlchemy URI for SQL Server via pyodbc.

    Uses the odbc_connect form rather than putting the host in the URL. A named
    instance carries a backslash (YNBBSTVWP02\\PROCDATASRVPROD), which is not
    valid unescaped in a URL host, so the whole ODBC string is encoded instead.
    """
    driver = driver.replace("+", " ")  # tolerate the old URL-encoded spelling
    odbc = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"Trusted_Connection={trusted};"
    )
    return "mssql+pyodbc:///?odbc_connect=" + quote_plus(odbc)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    DB_TARGET, _target = _resolve_target()
    # Per-value overrides still win, so a one-off host can be tried without
    # editing this file.
    SERVER = os.getenv("DB_SERVER", _target["server"])
    DATABASE = os.getenv("DB_NAME", _target["database"])
    DB_LABEL = _target["label"]
    DRIVER = os.getenv("ODBC_DRIVER", "ODBC Driver 17 for SQL Server")
    TRUSTED = os.getenv("DB_TRUSTED", "yes")

    # DATABASE_URL, if set, overrides everything above.
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", build_mssql_uri(SERVER, DATABASE, DRIVER, TRUSTED)
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    @classmethod
    def describe_db(cls):
        """Which backend is this process actually talking to."""
        if os.getenv("DATABASE_URL"):
            return "DATABASE_URL override (target registry bypassed)"
        return f"{cls.DB_TARGET} -> {cls.SERVER} / {cls.DATABASE}"

    # Microsoft Graph settings
    TENANT_ID = os.getenv("TENANT_ID")
    CLIENT_ID = os.getenv("CLIENT_ID")
    CLIENT_SECRET = os.getenv("CLIENT_SECRET")
    AAD_ENDPOINT = os.getenv("AAD_ENDPOINT", "https://login.microsoftonline.com")
    GRAPH_ENDPOINT = os.getenv("GRAPH_ENDPOINT", "https://graph.microsoft.com")
    FROM_EMAIL = os.getenv("FROM", "procurementdatateam@montefiore.org") # our service account

    # -------------------------------------------
    #            Program Parameters
    # -------------------------------------------
    # # Batch processing limits
    MAX_BATCH_PER_SIDE = int(os.getenv("MAX_BATCH_PER_SIDE", "6"))  # Max items or replace_items per side (total combinations = per_side^2)
    ENABLE_BURN_RATE_REFRESH = os.getenv("ENABLE_BURN_RATE_REFRESH", "1") not in {"0", "false", "False"}
    INCLUDE_OR_INVENTORY_LOCATIONS = os.getenv("INCLUDE_OR_INVENTORY_LOCATIONS", "0").lower() in {"1", "true", "yes"}

    @classmethod
    def validate(cls):
        missing = [k for k in ["TENANT_ID", "CLIENT_ID", "CLIENT_SECRET"] if not getattr(cls, k)]
        if missing:
            message = f"Missing required environment variables for Microsoft Graph: {', '.join(missing)}"
            if "CLIENT_SECRET" in missing and os.getenv("CLIENT_SECRET_HASHED"):
                message += (
                    " (CLIENT_SECRET_HASHED is present but could not be decrypted - set "
                    "E0_SECRET_PASSPHRASE for the account running the app, e.g. the IIS app pool)"
                )
            raise ValueError(message)
        
class DevelopmentConfig(Config):
    DEBUG = True
    # Allow override to SQLite for quick dev (set USE_SQLITE=1)
    if os.getenv("USE_SQLITE") == "1":
        SQLALCHEMY_DATABASE_URI = "sqlite:///plm_dev.db"

class ProductionConfig(Config):
    DEBUG = False

config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
