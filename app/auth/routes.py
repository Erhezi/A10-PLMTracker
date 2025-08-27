from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from .. import db
from ..models.auth import User
import random
import string
from datetime import datetime, timedelta, timezone
from ..utility.msgraph import send_mail

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        name = request.form.get("name")
        if not email or not password:
            flash("Email and password required", "error")
            return render_template("auth/register.html")
        existing = User.query.filter_by(email=email).first()
        if existing:
            flash("Email already registered", "error")
            return render_template("auth/register.html")
        user = User(email=email, name=name)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("Registered and logged in", "success")
        return redirect(url_for("main.index"))
    return render_template("auth/register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Invalid credentials", "error")
            return render_template("auth/login.html")
        login_user(user)
        user.last_login_at = db.func.now()
        db.session.commit()
        flash("Logged in", "success")
        return redirect(url_for("main.index"))
    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])  # POST to avoid CSRF (add token later)
@login_required
def logout():
    logout_user()
    flash("Logged out", "info")
    return redirect(url_for("auth.login"))


@bp.route("/reset_password", methods=["GET", "POST"])
def reset_password_request():

    def generate_temp_code(length=6):
        return ''.join(random.choices(string.digits, k=length))
    
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if not user:
            flash("If the email exists, a code will be sent.", "info")
            return redirect(url_for("auth.reset_password_request"))
        code = generate_temp_code()
        user.reset_code = code
        user.reset_code_expiry = datetime.now() + timedelta(minutes=2)
        db.session.commit()
        # In production, send code via email. For demo, flash it.
        # flash(f"Your reset code is: {code}", "info")
        # Send code via Microsoft Graph email
        send_mail(
            to_email=email,
            subject="Your PLM Tracker Password Reset Code",
            body=f"Your password reset code is: {code}\nThis code will expire in 2 minutes."
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
        # Code is valid, proceed to set new password
        return redirect(url_for("auth.reset_password_update", email=email))
    return render_template("auth/reset_password_verify.html", email=email)

@bp.route("/reset_password/update", methods=["GET", "POST"])
def reset_password_update():
    email = request.args.get("email", "")
    user = User.query.filter_by(email=email).first()
    if not user:
        flash("Invalid request.", "error")
        return redirect(url_for("auth.reset_password_request"))
    if request.method == "POST":
        password = request.form.get("password", "")
        if not password:
            flash("Password required.", "error")
            return render_template("auth/reset_password_update.html", email=email)
        user.set_password(password)
        user.reset_code = None
        user.reset_code_expiry = None
        db.session.commit()
        flash("Password updated. Please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset_password_update.html", email=email)
