import os 
from pathlib import Path
from dotenv import load_dotenv

root_env = Path(__file__).resolve().parents[1] / ".env"
if root_env.exists():
    load_dotenv(root_env)

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

    @classmethod
    def validate(cls):
        missing = [k for k in ["TENANT_ID", "CLIENT_ID", "CLIENT_SECRET"] if not getattr(cls, k)]
        if missing:
            raise ValueError(f"Missing required environment variables for Microsoft Graph: {', '.join(missing)}")
        
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
