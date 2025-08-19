"""Core SQLAlchemy models (auth + audit subset for first milestone).
Remaining domain models (items, conversions, groups, tracking) will be added later.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint, Text
from sqlalchemy.orm import relationship, Mapped, mapped_column
from .extensions import db, login_manager

# Association table for many-to-many user<->roles
class UserRole(db.Model):
    __tablename__ = "user_roles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.role_id"), primary_key=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

class Role(db.Model):
    __tablename__ = "roles"
    role_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    users: Mapped[list['User']] = relationship(
        secondary="user_roles", back_populates="roles", lazy="selectin"
    )

class User(db.Model):
    __tablename__ = "users"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(120))
    pw_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    roles: Mapped[list[Role]] = relationship(
        secondary="user_roles", back_populates="users", lazy="selectin"
    )
    verification_tokens: Mapped[list['EmailVerificationToken']] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    reset_tokens: Mapped[list['PasswordResetToken']] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    audits: Mapped[list['AuditLog']] = relationship(back_populates="user")

    # Flask-Login integration
    @property
    def is_authenticated(self) -> bool:  # type: ignore[override]
        return True

    @property
    def is_anonymous(self) -> bool:  # type: ignore[override]
        return False

    def get_id(self) -> str:  # type: ignore[override]
        return str(self.user_id)

    def set_password(self, password: str) -> None:
        self.pw_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.pw_hash, password)

    def has_role(self, role_name: str) -> bool:
        return any(r.name == role_name for r in self.roles)

    def mark_login(self) -> None:
        self.last_login_at = datetime.utcnow()

@login_manager.user_loader  # type: ignore[misc]
def load_user(user_id: str) -> Optional[User]:
    return db.session.get(User, int(user_id))

class EmailVerificationToken(db.Model):
    __tablename__ = "email_verification_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="verification_tokens")

    def is_valid(self) -> bool:
        return self.used_at is None and datetime.utcnow() < self.expires_at

class PasswordResetToken(db.Model):
    __tablename__ = "password_reset_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="reset_tokens")

    def is_valid(self) -> bool:
        return self.used_at is None and datetime.utcnow() < self.expires_at

class AuditLog(db.Model):
    __tablename__ = "audit_log"
    audit_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[Optional[str]] = mapped_column(String(64))
    entity_id: Mapped[Optional[str]] = mapped_column(String(64))
    payload_json: Mapped[Optional[str]] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    user: Mapped[Optional[User]] = relationship(back_populates="audits")

# Placeholder comment for remaining domain models to be added in later milestones.
