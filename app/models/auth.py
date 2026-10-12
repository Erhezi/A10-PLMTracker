from __future__ import annotations
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from .. import db
from . import now_ny_naive
from sqlalchemy import text


class User(db.Model, UserMixin):
    __tablename__ = "users"

    user_id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120))
    user_role = db.Column(db.String(50), nullable=False, server_default=text("'user'"), index=True)  # e.g., 'admin', 'user'
    pw_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=False, server_default=text("0"))
    created_at = db.Column(db.DateTime(timezone=False), default=now_ny_naive, nullable=False)
    last_login_at = db.Column(db.DateTime)

    # For Resetting Password, adding tempcode feature
    reset_code = db.Column(db.String(10))
    reset_code_expiry = db.Column(db.DateTime)

    # For user approval
    approved_by = db.Column(db.String(255))
    approved_at = db.Column(db.DateTime)

    # For user disabling
    disabled_by = db.Column(db.String(255))
    disabled_at = db.Column(db.DateTime)

    # Roles in modules other than PLM (e.g. Fill/Kill); user_role stays the PLM role.
    module_roles = db.relationship(
        "UserModuleRole",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    # Flask-Login required attribute name is 'id' or 'get_id'; we map id property.
    @property
    def id(self):  # type: ignore[override]
        return self.user_id

    def set_password(self, password: str):
        self.pw_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.pw_hash, password)


class UserModuleRole(db.Model):
    """A user's role in a module other than PLM.

    db/fillkill/02_user_module_role.sql creates this table. The constraints are
    spelled out here with the same names, because the app's startup
    (db.create_all) creates the table itself if it runs before that script.
    """

    __tablename__ = "UserModuleRole"
    __table_args__ = (
        db.PrimaryKeyConstraint("user_id", "module", "role", name="PK_UserModuleRole"),
        db.ForeignKeyConstraint(
            ["user_id"], ["PLM.users.user_id"],
            name="FK_UserModuleRole_users", ondelete="CASCADE",
        ),
        db.CheckConstraint(
            "module <> 'fillkill' OR role IN ('viewer', 'proposer', 'clinical', 'materials')",
            name="CK_UserModuleRole_fillkill_role",
        ),
    )

    user_id = db.Column(db.Integer, nullable=False)
    module = db.Column(db.String(30), nullable=False)
    role = db.Column(db.String(30), nullable=False)
    granted_by = db.Column(db.String(255))
    granted_at = db.Column(
        db.DateTime, nullable=False, default=now_ny_naive, server_default=db.func.current_timestamp()
    )
