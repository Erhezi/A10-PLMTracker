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
    # App-level role: 'admin' (manage users, see every module) or 'user'.
    # What someone can do inside a module lives in UserModuleRole.
    user_role = db.Column(db.String(50), nullable=False, server_default=text("'user'"), index=True)
    # Modules asked for at registration, e.g. "plm,fillkill". Grants nothing by itself.
    requested_modules = db.Column(db.String(100))
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

    # Roles inside each module: PLM, Fill/Kill (see utility/access.py).
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


ROLE_CHECK_SQL = (
    "(module = 'plm' AND role IN ('viewer', 'editor'))"
    " OR (module = 'fillkill' AND role IN ('viewer', 'proposer', 'clinical', 'materials'))"
)


class UserModuleRole(db.Model):
    """One permission: a user's role in a module (PLM, Fill/Kill).

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
        db.CheckConstraint(ROLE_CHECK_SQL, name="CK_UserModuleRole_role"),
        # PLM roles are Viewer or Editor, never both.
        db.Index(
            "UX_UserModuleRole_one_plm_role", "user_id", unique=True,
            mssql_where=text("module = 'plm'"), sqlite_where=text("module = 'plm'"),
        ),
    )

    user_id = db.Column(db.Integer, nullable=False)
    module = db.Column(db.String(30), nullable=False)
    role = db.Column(db.String(30), nullable=False)
    granted_by = db.Column(db.String(255))
    granted_at = db.Column(
        db.DateTime, nullable=False, default=now_ny_naive, server_default=db.func.current_timestamp()
    )
