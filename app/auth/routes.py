from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from .. import db
from ..models.auth import User

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
