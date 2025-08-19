import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    SERVER = os.getenv("DB_SERVER", "MISCPrdAdhocDB")
    DATABASE = os.getenv("DB_NAME", "PRIME")
    DRIVER = os.getenv("ODBC_DRIVER", "ODBC+Driver+17+for+SQL+Server")
    TRUSTED = os.getenv("DB_TRUSTED", "yes")
    # Build MSSQL URI (Integrated Security). If running locally w/out domain context, may need SQL auth.
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        f"mssql+pyodbc://{SERVER}/{DATABASE}?trusted_connection={TRUSTED}&driver={DRIVER}" if os.name == "nt" else f"mssql+pyodbc://{SERVER}/{DATABASE}?Trusted_Connection={TRUSTED}&driver={DRIVER}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

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
