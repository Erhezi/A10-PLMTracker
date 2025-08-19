"""Auth blueprint routes initial implementation (register, verify email, login, logout)."""
from __future__ import annotations
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask import abort
from flask_login import login_user, logout_user, current_user
from ..extensions import db
from ..models import User, EmailVerificationToken
from .services import generate_email_verification_token, send_verification_email, audit, _hash_token
from werkzeug.security import generate_password_hash

bp = Blueprint("auth", __name__, url_prefix="/auth")

# Simple inline forms (WTForms can be added later)

def _allowed_domain(email: str) -> bool:
    domain = email.split("@")[-1].lower()
    return domain in {d.strip().lower() for d in current_app.config["ALLOWED_EMAIL_DOMAINS"]}

@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        if not email or not password:
            flash("Email and password required", "danger")
        elif not _allowed_domain(email):
            flash("Email domain not allowed", "danger")
        elif db.session.scalar(db.select(User).filter_by(email=email)):
            flash("Email already registered", "warning")
        else:
            user = User(email=email, name=name, pw_hash=generate_password_hash(password))
            db.session.add(user)
            raw, token = generate_email_verification_token(user)
            audit("register", user=user)
            db.session.commit()
            send_verification_email(user, raw)
            # In dev show token
            flash(f"Registered. Verification token: {raw}", "success")
            return redirect(url_for("auth.verify_notice"))
    return render_template("auth/register.html")

@bp.route("/verify-notice")
def verify_notice():
    return render_template("auth/verify_notice.html")

@bp.route("/verify-email")
def verify_email():
    token_raw = request.args.get("token")
    if not token_raw:
        abort(400)
    token_hash = _hash_token(token_raw)
    token = db.session.scalar(db.select(EmailVerificationToken).filter_by(token_hash=token_hash))
    if not token or not token.is_valid():
        flash("Invalid or expired token", "danger")
        return redirect(url_for("auth.verify_notice"))
    token.user.email_verified_at = token.user.email_verified_at or token.created_at
    token.used_at = token.used_at or token.user.email_verified_at
    audit("verify_email", user=token.user)
    db.session.commit()
    flash("Email verified. You can login now.", "success")
    return redirect(url_for("auth.login"))

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.session.scalar(db.select(User).filter_by(email=email))
        if not user or not user.check_password(password):
            flash("Invalid credentials", "danger")
        elif not user.email_verified_at:
            flash("Email not verified", "warning")
            return redirect(url_for("auth.verify_notice"))
        elif not user.is_active:
            flash("Account inactive", "danger")
        else:
            login_user(user)
            user.mark_login()
            audit("login", user=user)
            db.session.commit()
            flash("Logged in", "success")
            return redirect(url_for("auth.login"))  # placeholder redirect
    return render_template("auth/login.html")

@bp.route("/logout", methods=["POST"])  # Use POST for CSRF protection
def logout():
    if current_user.is_authenticated:
        audit("logout", user=current_user)  # type: ignore[arg-type]
        logout_user()
        flash("Logged out", "info")
    return redirect(url_for("auth.login"))
