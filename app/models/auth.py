from __future__ import annotations
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from .. import db


class User(db.Model, UserMixin):
    __tablename__ = "users"

    user_id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120))
    pw_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime)

    # Flask-Login required attribute name is 'id' or 'get_id'; we map id property.
    @property
    def id(self):  # type: ignore[override]
        return self.user_id

    def set_password(self, password: str):
        self.pw_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.pw_hash, password)
