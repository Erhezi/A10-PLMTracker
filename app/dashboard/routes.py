from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from sqlalchemy import select, func
from ..utility.item_locations import build_location_pairs
from .. import db
from ..models.relations import ItemLink, PLMTrackerBase, PLMQty

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

    # Support multi-select item_group as comma-separated values
    item_group_param = request.args.get("item_group") or ""
    item_group_filters = []
    if item_group_param:
        for part in item_group_param.split(','):
            part = part.strip()
            if not part:
                continue
            try:
                item_group_filters.append(int(part))
            except ValueError:
                continue
    item_group_filters = list(dict.fromkeys(item_group_filters))  # dedupe preserving order

    # Multi-location support (comma-separated)
    location_param = request.args.get("location") or ""
    location_filters = [loc.strip() for loc in location_param.split(',') if loc.strip()] if location_param else []

    company = request.args.get("company") or None  # reserved / future
    active_param = request.args.get("active")
    require_active = active_param.lower() == "true" if active_param else False

    desc_search = request.args.get("desc_search") or ""
    desc_search_lower = desc_search.lower().strip()

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
        location=None,  # handled post-fetch for multi list
        require_active=require_active,
        include_par=False,
        location_types=["Inventory Location"],
    )
    if location_filters:
        loc_set = set(location_filters)
        all_rows = [r for r in all_rows if (r.get("location") in loc_set)]
    if item_group_filters:
        allowed_set = set(item_group_filters)
        all_rows = [r for r in all_rows if r.get("item_group") in allowed_set]
    # Description search filter (case-insensitive substring match on either side)
    if desc_search_lower:
        all_rows = [r for r in all_rows if (
            str(r.get("item_description") or "").lower().find(desc_search_lower) != -1 or
            str(r.get("item_description_ri") or "").lower().find(desc_search_lower) != -1
        )]
    total = len(all_rows)
    start = (page - 1) * per_page
    end = start + per_page
    rows = all_rows[start:end]
    if rows:
        print(rows[0]) #debug (keep it for now)
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


@bp.route("/api/par")
@login_required
def api_par():
    """Par location data (Par Locations table).

    Similar filtering semantics as inventory endpoint but restricted to Par Location types.
    Weeks Reorder = ReorderPoint / weekly_burn (and we negate to present positive like inventory logic).
    """
    allowed_stage_values = {
        "Tracking - Discontinued",
        "Tracking - Item Transition",
        "Pending Clinical Approval",
    }
    stage_param = request.args.get("stage") or request.args.get("stages")
    if stage_param:
        stage_list_raw = [s.strip() for s in stage_param.split(",") if s.strip()]
        stages_list = [s for s in stage_list_raw if s in allowed_stage_values] or list(allowed_stage_values)
    else:
        stages_list = list(allowed_stage_values)

    # Multi-select item_group support
    item_group_param = request.args.get("item_group") or ""
    item_group_filters = []
    if item_group_param:
        for part in item_group_param.split(','):
            part = part.strip()
            if not part:
                continue
            try:
                item_group_filters.append(int(part))
            except ValueError:
                continue
    item_group_filters = list(dict.fromkeys(item_group_filters))
    location_param = request.args.get("location") or ""
    location_filters = [loc.strip() for loc in location_param.split(',') if loc.strip()] if location_param else []

    desc_search = request.args.get("desc_search") or ""
    desc_search_lower = desc_search.lower().strip()

    # Pagination
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get("per_page", 100))
    except ValueError:
        per_page = 100
    page = max(page, 1)
    per_page = max(min(per_page, 200), 1)

    # Fetch par location rows
    all_rows = build_location_pairs(
        stages=stages_list,
        location=None,
        include_par=True,
        location_types=["Par Location"],
    )
    if location_filters:
        loc_set = set(location_filters)
        all_rows = [r for r in all_rows if (r.get("location") in loc_set)]
    # Filter by item_group if needed
    if item_group_filters:
        allowed_set = set(item_group_filters)
        all_rows = [r for r in all_rows if r.get("item_group") in allowed_set]
    # Description search
    if desc_search_lower:
        all_rows = [r for r in all_rows if (
            str(r.get("item_description") or "").lower().find(desc_search_lower) != -1 or
            str(r.get("item_description_ri") or "").lower().find(desc_search_lower) != -1
        )]

    # Recompute weeks_reorder using reorder point instead of available qty
    for r in all_rows:
        reorder_pt = r.get("reorder_point")
        wb = r.get("weekly_burn")
        if reorder_pt is None or wb in (None, 0):
            r["weeks_reorder"] = "unknown"
        else:
            try:
                val = float(reorder_pt) / float(wb) if float(wb) != 0 else None
                if val is None:
                    r["weeks_reorder"] = "unknown"
                else:
                    # Keep sign convention consistent (inventory negates weeks_on_hand)
                    r["weeks_reorder"] = -1 * val if val is not None else "unknown"
            except Exception:
                r["weeks_reorder"] = "unknown"

    total = len(all_rows)
    start = (page - 1) * per_page
    end = start + per_page
    rows = all_rows[start:end]
    return jsonify({
        "rows": rows,
        "count": len(rows),
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if per_page else 1,
    })


@bp.route("/api/qty/<int:item_group>")
@login_required
def api_qty(item_group: int):
    """Return historical quantity time-series (AvailableQty) per (Item, Location)
    for a given item_group from the PLMQty view.

    Response structure:
    {
      "item_group": <int>,
      "series": [
          {"item": "12345", "location": "LOC1", "points": [
              {"t": "2025-08-01T00:00:00", "qty": 42}, ...
          ]}, ...
      ]
    }
    """
    # Query all rows for this item group ordered for stable client-side rendering
    stmt = (
        select(
            PLMQty.Item.label("item"),
            PLMQty.Location.label("location"),
            PLMQty.report_stamp.label("stamp"),
            PLMQty.AvailableQty.label("qty"),
        )
        .where(PLMQty.Item_Group == item_group)
        .order_by(PLMQty.Item, PLMQty.Location, PLMQty.report_stamp)
    )

    rows = db.session.execute(stmt).all()
    series_map = {}
    for item, location, stamp, qty in rows:
        key = (item, location)
        bucket = series_map.setdefault(key, [])
        bucket.append({
            "t": stamp.isoformat() if stamp else None,
            "qty": int(qty) if qty is not None else None,
        })

    series = [
        {"item": k[0], "location": k[1], "points": v}
        for k, v in series_map.items()
    ]

    return jsonify({
        "item_group": item_group,
        "series": series,
        "series_count": len(series),
        "point_count": sum(len(s["points"]) for s in series),
    })
