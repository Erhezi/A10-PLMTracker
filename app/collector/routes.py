from flask import Blueprint, render_template
from flask_login import login_required

bp = Blueprint("collector", __name__, url_prefix="")

@bp.route("/collect")
@login_required
def collect():
    return render_template("collector/collect.html")

@bp.route("/groups")
@login_required
def groups():
    return render_template("collector/groups.html")

@bp.route("/conflicts")
@login_required
def conflicts():
    return render_template("collector/conflicts.html")
