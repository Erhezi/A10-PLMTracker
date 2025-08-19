"""Access control helpers: role_required decorator and verification guard."""
from __future__ import annotations
from functools import wraps
from flask import abort
from flask_login import current_user


def role_required(*roles: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:  # type: ignore[attr-defined]
                abort(401)
            if not any(current_user.has_role(r) for r in roles):  # type: ignore[attr-defined]
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def verified_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:  # type: ignore[attr-defined]
            abort(401)
        if not getattr(current_user, 'email_verified_at', None):
            abort(403)
        return fn(*args, **kwargs)
    return wrapper
