"""Application-wide extension instances (no app bound yet)."""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf import CSRFProtect

# Stubs / optional future imports
# from flask_mail import Mail (could add later)

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()

# mail = Mail()  # if configured later

login_manager.login_view = "auth.login"
login_manager.login_message_category = "info"
