from flask import Blueprint, render_template
from flask_login import login_required

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")

@bp.route("/")
@login_required
def index():
    return render_template("dashboard/index.html")

@bp.route("/groups/<int:group_id>")
@login_required
def group_detail(group_id: int):
    # Placeholder; later will query KPIs
    return render_template("dashboard/group.html", group_id=group_id)
