from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from sqlalchemy import select, func
from ..utility.item_locations import build_location_pairs
from .. import db
from ..models.relations import ItemLink, PLMTrackerBase

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
    # Allowed stages (UI requirement) - restrict to these unless explicitly overridden
    allowed_stage_values = {
        "Tracking - Discontinued",
        "Tracking - Item Transition",
        "Pending Clinical Approval",
    }
    stage_param = request.args.get("stage") or request.args.get("stages")  # support singular for UI
    if stage_param:
        stage_list_raw = [s.strip() for s in stage_param.split(",") if s.strip()]
        # keep only allowed stages; if nothing remains fall back to default set
        stages_list = [s for s in stage_list_raw if s in allowed_stage_values] or list(allowed_stage_values)
    else:
        stages_list = list(allowed_stage_values)

    item_group_param = request.args.get("item_group")
    try:
        item_group_filter = int(item_group_param) if item_group_param else None
    except ValueError:
        item_group_filter = None

    location = request.args.get("location") or None

    company = request.args.get("company") or None  # reserved / future
    active_param = request.args.get("active")
    require_active = active_param.lower() == "true" if active_param else False

    # Pagination params
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get("per_page", 20))
    except ValueError:
        per_page = 20
    page = max(page, 1)
    per_page = max(min(per_page, 200), 1)

    # Fetch all (small view expected). For large sets, implement count + slice query.
    all_rows = build_location_pairs(
        stages=stages_list,
        company=company,
        location=location,
        require_active=require_active,
        include_par=False,
        location_types=["Inventory Location"],
    )
    if item_group_filter is not None:
        all_rows = [r for r in all_rows if r.get("item_group") == item_group_filter]
    total = len(all_rows)
    start = (page - 1) * per_page
    end = start + per_page
    rows = all_rows[start:end]
    if rows:
        print(rows[0])
    return jsonify({
        "rows": rows,
        "count": len(rows),
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if per_page else 1,
    })


@bp.route("/api/filter-options")
@login_required
def api_filter_options():
    """Return distinct lists for dashboard filters.

    - item_groups: from ItemLink.item_group (exclude NULL, sorted ascending)
    - locations: distinct (LocationType, Location) from PLMTrackerBase limited to inventory location types
      formatted as "{LocationType} - {Location}" and include raw location for querying.
    - stages: allowed stage values (static list)
    """
    # Item Groups
    item_groups_query = select(func.distinct(ItemLink.item_group)).where(ItemLink.item_group.isnot(None)).order_by(ItemLink.item_group)
    item_groups = [row[0] for row in db.session.execute(item_groups_query).all()]

    # Locations (pull from view)
    v = PLMTrackerBase
    loc_query = (
        select(func.distinct(v.LocationType), v.Location)
        .where(v.Location.isnot(None))
        .order_by(v.LocationType, v.Location)
    )
    locations = []
    for lt, loc in db.session.execute(loc_query).all():
        label = f"{lt} - {loc}" if lt else loc
        locations.append({"value": loc, "type": lt, "label": label})

    stages = [
        "Tracking - Discontinued",
        "Tracking - Item Transition",
        "Pending Clinical Approval",
    ]
    return jsonify({
        "item_groups": item_groups,
        "locations": locations,
        "stages": stages,
    })
