from flask import Blueprint, redirect, url_for
from flask_login import login_required, current_user

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def index():
    return redirect(url_for("dashboard.index"))
