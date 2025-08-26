from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from ..utility.item_locations import build_location_pairs

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


@bp.route("/api/inventory")
@login_required
def api_inventory():
    stages_default = [
        "Tracking - Discontinued",
        "Tracking - Item Transition",
        "Pending Clinical Approval",
    ]
    stages = request.args.get("stages")
    if stages:
        # comma separated list
        stages_list = [s.strip() for s in stages.split(",") if s.strip()]
    else:
        stages_list = stages_default
    company = request.args.get("company") or None
    location = request.args.get("location") or None
    active_param = request.args.get("active")
    require_active = active_param.lower() == "true" if active_param else False
    rows = build_location_pairs(
        stages=stages_list,
        company=company,
        location=location,
        require_active=require_active,
        include_par=False,
        location_types=["Inventory Location"],
    )
    print(rows[0])
    return jsonify({"rows": rows, "count": len(rows)})
