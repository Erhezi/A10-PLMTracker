"""Auth service helpers: token generation, email sending stub, audit helper."""
from __future__ import annotations
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Tuple
from flask import current_app
from ..extensions import db
from ..models import User, EmailVerificationToken, AuditLog

TOKEN_BYTES = 32

def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def generate_email_verification_token(user: User) -> Tuple[str, EmailVerificationToken]:
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    token = EmailVerificationToken(
        user=user,
        token_hash=_hash_token(raw),
        expires_at=datetime.utcnow() + timedelta(minutes=current_app.config["EMAIL_VERIFICATION_TOKEN_MINUTES"]),
    )
    db.session.add(token)
    return raw, token

def mark_token_used(token: EmailVerificationToken) -> None:
    token.used_at = datetime.utcnow()

# Stub email sender; in dev we might just log token

def send_verification_email(user: User, raw_token: str) -> None:  # pragma: no cover
    # Replace with real email implementation later
    current_app.logger.info("Verification token for %s: %s", user.email, raw_token)


def audit(action: str, user: User | None = None, entity: str | None = None, entity_id: str | None = None, payload_json: str | None = None) -> None:
    entry = AuditLog(
        user=user,
        action=action,
        entity=entity,
        entity_id=entity_id,
        payload_json=payload_json,
    )
    db.session.add(entry)
