from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from .. import db
from ..models.auth import User
import random
import string
from datetime import datetime, timedelta, timezone
from ..utility.msgraph import send_mail
from ..utility import session_policy
from ..utility.access import MODULES, legacy_user_role

bp = Blueprint("auth", __name__, url_prefix="/auth")

# A correctly entered reset code lets this browser, and only for that email, set
# a new password within this window. The update page trusts nothing else: before
# this, anyone could open it with any email and set that account's password.
RESET_VERIFIED_KEY = "reset_verified"
RESET_VERIFIED_WINDOW = timedelta(minutes=15)


def _mark_reset_verified(email: str) -> None:
    session[RESET_VERIFIED_KEY] = {"email": email, "at": datetime.now().isoformat(timespec="seconds")}


def _verified_reset_email() -> str | None:
    data = session.get(RESET_VERIFIED_KEY) or {}
    try:
        verified_at = datetime.fromisoformat(data.get("at", ""))
    except (TypeError, ValueError):
        return None
    if datetime.now() - verified_at > RESET_VERIFIED_WINDOW:
        return None
    return data.get("email") or None


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        name = request.form.get("name")
        if not email or not password:
            flash("Email and password required", "error")
            return render_template("auth/register.html", modules=MODULES)
        existing = User.query.filter_by(email=email).first()
        if existing:
            if not existing.is_active:
                flash(
                    "Your registration is pending administrator approval. Thank you for your patience.",
                    "info",
                )
                return redirect(url_for("auth.register_pending", email=email))
            flash("Email already registered", "error")
            return render_template("auth/register.html", modules=MODULES)
        # One account for the whole app; module access is granted by an admin.
        requested = [key for key in request.form.getlist("modules") if key in MODULES]
        user = User(
            email=email,
            name=name,
            is_active=False,
            requested_modules=",".join(requested) or None,
            user_role=legacy_user_role(admin=False, plm_roles=()),
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("Registration received. Please wait for admin approval.", "info")
        return redirect(url_for("auth.register_pending", email=email))
    return render_template("auth/register.html", modules=MODULES)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Invalid credentials", "error")
            return render_template("auth/login.html")
        if not user.is_active:
            flash(
                "Your account is pending administrator approval.",
                "warning",
            )
            return redirect(url_for("auth.register_pending", email=email))
        login_user(user)
        session_policy.mark_login()
        user.last_login_at = db.func.now()
        db.session.commit()
        flash("Logged in", "success")
        next_path = session_policy.safe_next(
            request.form.get("next") or request.args.get("next"), request.script_root
        )
        if next_path:
            return redirect(request.script_root + next_path)
        return redirect(url_for("main.index"))
    return render_template("auth/login.html")


@bp.route("/register/pending")
def register_pending():
    email = request.args.get("email", "")
    return render_template("auth/register_pending.html", email=email)


@bp.route("/logout", methods=["POST"])  # POST + CSRF token (CSRFProtect)
@login_required
def logout():
    logout_user()
    session_policy.clear_login()
    flash("Logged out", "info")
    return redirect(url_for("auth.login"))


@bp.route("/reset_password", methods=["GET", "POST"])
def reset_password_request():

    def generate_temp_code(length=6):
        return "".join(random.choices(string.digits, k=length))
    
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if not user:
            flash("If the email exists, a code will be sent.", "info")
            return redirect(url_for("auth.reset_password_request"))
        code = generate_temp_code()
        user.reset_code = code
        user.reset_code_expiry = datetime.now() + timedelta(minutes=30)
        db.session.commit()
        # In production, send code via email. For demo, flash it.
        # flash(f"Your reset code is: {code}", "info")
        # Send code via Microsoft Graph email
        send_mail(
            to_email=email,
            subject="Item Management Password Reset Instructions",
            body=(
                "You (or someone using your email) requested to reset your Item Management password.\n"
                f"Use this verification code within 30 minutes: {code}\n\n"
                "If you did not request a reset you can ignore this email."
            ),
        )
        flash("If the email exists, a code has been sent.", "info")
        return redirect(url_for("auth.reset_password_verify", email=email))
    return render_template("auth/reset_password_request.html")

@bp.route("/reset_password/verify", methods=["GET", "POST"])
def reset_password_verify():
    email = request.args.get("email", "")
    if request.method == "POST":
        code = request.form.get("code", "")
        email = request.form.get("email", "")
        user = User.query.filter_by(email=email).first()
        if not user or user.reset_code != code or user.reset_code_expiry < datetime.now():
            flash("Invalid or expired code.", "error")
            # return redirect(url_for("auth.reset_password_request"))
            return render_template("auth/reset_password_verify.html", email=email)
        # Code is valid: this browser may now set a new password for this email.
        _mark_reset_verified(user.email)
        return redirect(url_for("auth.reset_password_update"))
    return render_template("auth/reset_password_verify.html", email=email)

@bp.route("/reset_password/update", methods=["GET", "POST"])
def reset_password_update():
    # Only the email whose code this browser just verified; never the URL or form.
    email = _verified_reset_email()
    user = User.query.filter_by(email=email).first() if email else None
    if (
        not user
        or not user.reset_code
        or not user.reset_code_expiry
        or user.reset_code_expiry < datetime.now()
    ):
        session.pop(RESET_VERIFIED_KEY, None)
        flash("Please request a reset code and enter it before setting a new password.", "error")
        return redirect(url_for("auth.reset_password_request"))
    if request.method == "POST":
        password = request.form.get("password", "")
        if not password:
            flash("Password required.", "error")
            return render_template("auth/reset_password_update.html", email=email)
        user.set_password(password)
        user.reset_code = None  # one use only
        user.reset_code_expiry = None
        db.session.commit()
        session.pop(RESET_VERIFIED_KEY, None)
        flash("Password updated. Please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset_password_update.html", email=email)
