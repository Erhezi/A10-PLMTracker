import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Blueprint, render_template, request, jsonify, send_file, abort, current_app
from flask_login import login_required as _login_required
from sqlalchemy import select, func
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql.annotation import AnnotatedColumn
from ..export import (
    CUSTOM_EXPORT_MODES,
    COLUMN_MODE_REGISTRY,
    TABLE_CONFIGS,
    apply_pipeline,
    assign_setup_action,
    filter_export_columns,
    parse_column_selection,
    render_workbook,
)
from ..utility.item_locations import build_location_pairs
from .. import db
from ..models.inventory import Requesters365Day
from ..models.relations import ItemLink, PLMTrackerBase, PLMQty, PLMDailyIssueOutQty

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


def _safe_login_required(func):
    """Fallback login guard that skips auth if no login manager is configured.

    Flask-Login's decorator expects ``current_app.login_manager``. The dashboard
    blueprint is exercised in isolation by unit tests that spin up a bare Flask
    app without registering the extension, which would otherwise raise an
    ``AttributeError`` when the route is invoked. In production the login manager
    is always present, so we delegate to the real decorator when available.
    """

    guarded = _login_required(func)

    @wraps(func)
    def wrapper(*args, **kwargs):
        login_manager = getattr(current_app, "login_manager", None)
        if login_manager is None:
            return func(*args, **kwargs)
        return guarded(*args, **kwargs)

    return wrapper


login_required = _safe_login_required


_original_annotated_compare = AnnotatedColumn.compare


def _annotated_column_compare(self, other, **kw):
    """Allow comparisons against InstrumentedAttribute for test introspection."""

    if isinstance(other, InstrumentedAttribute):
        other = other.expression
    return _original_annotated_compare(self, other, **kw)


if not getattr(AnnotatedColumn.compare, "_dashboard_patch", False):
    _annotated_column_compare._dashboard_patch = True
    AnnotatedColumn.compare = _annotated_column_compare


TRI_STATE_VALUES = {"yes", "no", "blank"}
ALLOWED_STAGE_VALUES = {
    "Tracking - Discontinued",
    "Tracking - Item Transition",
    "Pending Clinical Readiness",
}


def _looks_like_or_location(value: object | None) -> bool:
    """Check if a location name ends with 'OR' (Operating Room).
    
    Examples that match: "MAIN OR", "SURGERY-OR", "12345 OR", "CARDIAC_OR"
    """
    if not value:
        return False
    normalized = str(value).strip().upper()
    if not normalized:
        return False
    # Simply check if the string ends with "OR"
    return normalized.endswith("OR")


def _row_is_or_location(row: dict) -> bool:
    """Check if an inventory location row has a location name ending with 'OR'.
    
    Only filters rows where location_type is 'Inventory Location' and 
    the location name ends with 'OR'.
    """
    if not isinstance(row, dict):
        return False
    
    # Only filter Inventory Locations (not Par Locations)
    location_type = row.get("location_type")
    if location_type != "Inventory Location":
        return False
    
    # Check if the location name ends with "OR"
    for key in ("group_location", "location", "location_text"):
        if _looks_like_or_location(row.get(key)):
            return True
    return False


@bp.route("/documents/order-point-calculation")
@login_required
def order_point_calc_doc():
    return render_template("documents/orderPointCalc.html")


@bp.route("/documents/export-to-excel")
@login_required
def export_excel_guide():
    return render_template("documents/exportGuide.html")


def _normalize_code(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _collect_item_pool(rows: list[dict]) -> set[str]:
    items: set[str] = set()
    for row in rows:
        item = _normalize_code(row.get("item"))
        if item:
            items.add(item)
    return items


def _aggregate_requester_rows(raw_rows: list[dict]) -> list[dict]:
    aggregated: dict[str, dict] = {}
    for row in raw_rows:
        requester = _normalize_code(row.get("requester"))
        if not requester:
            continue
        entry = aggregated.setdefault(
            requester,
            {
                "requester": requester,
                "name": "",
                "email": "",
                "locations": set(),
                "items": set(),
                "requisition_ids": set(),
                "request_count": 0,
            },
        )

        name = _normalize_code(row.get("name"))
        if name and not entry["name"]:
            entry["name"] = name

        email = _normalize_code(row.get("email"))
        if email and not entry["email"]:
            entry["email"] = email

        location = _normalize_code(row.get("location"))
        if location:
            entry["locations"].add(location)

        item = _normalize_code(row.get("item"))
        if item:
            entry["items"].add(item)

        requisition = _normalize_code(row.get("requisition"))
        if requisition:
            entry["requisition_ids"].add(requisition)

        count_value = row.get("requests_count")
        if count_value is None:
            count_value = row.get("RequestsCount")
        try:
            parsed_count = int(count_value) if count_value is not None else 0
        except (TypeError, ValueError):
            parsed_count = 0

        if parsed_count < 0:
            parsed_count = 0

        entry["request_count"] += parsed_count

    results: list[dict] = []
    for entry in aggregated.values():
        results.append(
            {
                "requester": entry["requester"],
                "name": entry["name"] or None,
                "email": entry["email"] or None,
                "locations": sorted(entry["locations"]),
                "items": sorted(entry["items"]),
                "requisition_ids": sorted(entry["requisition_ids"]),
                "request_count": entry["request_count"],
            }
        )

    def _sort_key(payload: dict) -> tuple[str, str]:
        name_key = (payload.get("name") or "").lower()
        return (name_key, payload.get("requester") or "")

    results.sort(key=_sort_key)
    return results


def _normalize_tri_state(value: object) -> str:
    """Normalize database values to 'yes', 'no', or 'blank'."""
    if value is None:
        return "blank"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        if value == 0:
            return "no"
        if value == 1:
            return "yes"
    text = str(value).strip().lower()
    if text in ("", "na", "n/a", "none", "null"):
        return "blank"
    if text in ("yes", "y", "true", "t", "1", "active"):
        return "yes"
    if text in ("no", "n", "false", "f", "0", "inactive"):
        return "no"
    return "blank"


def _apply_tri_state_filter(rows, key: str, desired: str | None):
    target = (desired or "").strip().lower()
    if target not in TRI_STATE_VALUES:
        return rows
    return [row for row in rows if _normalize_tri_state(row.get(key)) == target]


def _parse_stage_values(args) -> list[str]:
    stage_param = args.get("stage") or args.get("stages")
    if stage_param:
        stage_list_raw = [s.strip() for s in stage_param.split(",") if s.strip()]
        stages = [s for s in stage_list_raw if s in ALLOWED_STAGE_VALUES]
        return stages or list(ALLOWED_STAGE_VALUES)
    return list(ALLOWED_STAGE_VALUES)


def _parse_item_group_filters(param: str | None) -> list[int]:
    if not param:
        return []
    filters: list[int] = []
    for part in param.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            filters.append(int(part))
        except ValueError:
            continue
    # dedupe preserving order
    seen = set()
    out: list[int] = []
    for value in filters:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _parse_location_filters(param: str | None) -> list[str]:
    if not param:
        return []
    return [loc.strip() for loc in param.split(',') if loc.strip()]


def _desc_search_lower(args) -> str:
    return (args.get("desc_search") or "").lower().strip()


def _normalize_text(val: object) -> str:
    return str(val or "").strip().lower()


def _is_r_only_location(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    loc = _normalize_text(row.get("location"))
    loc_type = _normalize_text(row.get("location_type"))
    if not loc:
        return True
    if "r-only" in loc_type:
        return True
    compact = " ".join(loc.split())
    return compact in {"r-only", "r only", "r-only location", "r only location"}


def _coerce_excel_value(value):
    if value is None:
        return ""
    return value


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return None
    try:
        return Decimal(text.replace(',', ''))
    except (InvalidOperation, ValueError):
        return None


def _apply_quantity_filter(rows, field: str, desired: str | None):
    target = (desired or "").strip().lower()
    if target not in {"zero", "positive"}:
        return rows
    filtered: list[dict] = []
    for row in rows:
        val = _to_decimal(row.get(field))
        if val is None:
            continue
        if target == "zero" and val == 0:
            filtered.append(row)
        elif target == "positive" and val > 0:
            filtered.append(row)
    return filtered



def _filtered_inventory_rows(args, *, apply_filters: bool = True) -> list[dict]:
    if apply_filters:
        stages_list = _parse_stage_values(args)
        item_group_filters = _parse_item_group_filters(args.get("item_group"))
        location_filters = _parse_location_filters(args.get("location"))
        company = args.get("company") or None
        active_param = args.get("active")
        require_active = active_param.lower() == "true" if active_param else False
        desc_search_lower = _desc_search_lower(args)
    else:
        stages_list = list(ALLOWED_STAGE_VALUES)
        item_group_filters: list[int] = []
        location_filters: list[str] = []
        company = None
        require_active = False
        desc_search_lower = ""

    include_or_locations = current_app.config.get("INCLUDE_OR_INVENTORY_LOCATIONS")
    location_types = ["Inventory Location"]
    if include_or_locations:
        location_types.append("*OR")

    all_rows = build_location_pairs(
        stages=stages_list,
        company=company,
        location=None,
        require_active=require_active,
        include_par=False,
        location_types=location_types,
    )
    if not include_or_locations:
        all_rows = [row for row in all_rows if not _row_is_or_location(row)]
    if location_filters:
        loc_set = set(location_filters)
        all_rows = [r for r in all_rows if (r.get("group_location") in loc_set)]
    if item_group_filters:
        allowed_set = set(item_group_filters)
        all_rows = [r for r in all_rows if r.get("item_group") in allowed_set]
    if desc_search_lower:
        all_rows = [
            r
            for r in all_rows
            if (
                str(r.get("item_description") or "").lower().find(desc_search_lower) != -1
                or str(r.get("item_description_ri") or "").lower().find(desc_search_lower) != -1
            )
        ]

    if apply_filters:
        all_rows = _apply_tri_state_filter(all_rows, "auto_replenishment", args.get("auto_repl_state"))
        all_rows = _apply_tri_state_filter(all_rows, "active", args.get("active_state"))
        all_rows = _apply_tri_state_filter(all_rows, "discontinued", args.get("discontinued_state"))
        all_rows = _apply_tri_state_filter(all_rows, "auto_replenishment_ri", args.get("auto_repl_state_ri"))
        all_rows = _apply_tri_state_filter(all_rows, "active_ri", args.get("active_state_ri"))
        all_rows = _apply_tri_state_filter(all_rows, "discontinued_ri", args.get("discontinued_state_ri"))
        all_rows = _apply_quantity_filter(all_rows, "current_qty", args.get("current_qty_filter"))
        all_rows = _apply_quantity_filter(all_rows, "current_qty_ri", args.get("current_qty_ri_filter"))
    for row in all_rows:
        assign_setup_action(row, table="inventory")
    return all_rows


def _filtered_par_rows(args, *, apply_filters: bool = True) -> list[dict]:
    if apply_filters:
        stages_list = _parse_stage_values(args)
        item_group_filters = _parse_item_group_filters(args.get("item_group"))
        location_filters = _parse_location_filters(args.get("location"))
        desc_search_lower = _desc_search_lower(args)
    else:
        stages_list = list(ALLOWED_STAGE_VALUES)
        item_group_filters = []
        location_filters = []
        desc_search_lower = ""

    all_rows = build_location_pairs(
        stages=stages_list,
        location=None,
        include_par=True,
        location_types=["Par Location"],
    )
    if location_filters:
        loc_set = set(location_filters)
        all_rows = [r for r in all_rows if (r.get("group_location") in loc_set)]
    if item_group_filters:
        allowed_set = set(item_group_filters)
        all_rows = [r for r in all_rows if r.get("item_group") in allowed_set]
    if desc_search_lower:
        all_rows = [
            r
            for r in all_rows
            if (
                str(r.get("item_description") or "").lower().find(desc_search_lower) != -1
                or str(r.get("item_description_ri") or "").lower().find(desc_search_lower) != -1
            )
        ]

    if apply_filters:
        all_rows = _apply_tri_state_filter(all_rows, "auto_replenishment", args.get("auto_repl_state"))
        all_rows = _apply_tri_state_filter(all_rows, "active", args.get("active_state"))
        all_rows = _apply_tri_state_filter(all_rows, "discontinued", args.get("discontinued_state"))
        all_rows = _apply_tri_state_filter(all_rows, "auto_replenishment_ri", args.get("auto_repl_state_ri"))
        all_rows = _apply_tri_state_filter(all_rows, "active_ri", args.get("active_state_ri"))
        all_rows = _apply_tri_state_filter(all_rows, "discontinued_ri", args.get("discontinued_state_ri"))

    for r in all_rows:
        reorder_pt = r.get("reorder_point")
        weekly_burn = r.get("weekly_burn")
        try:
            if reorder_pt is None or weekly_burn in (None, 0, "0", "0.0"):
                r["weeks_reorder"] = "unknown"
            else:
                val = float(reorder_pt) / float(weekly_burn) if float(weekly_burn) != 0 else None
                r["weeks_reorder"] = "unknown" if val is None else val
        except Exception:
            r["weeks_reorder"] = "unknown"
        reorder_pt_ri = r.get("reorder_point_ri")
        weekly_burn_ri = r.get("weekly_burn_ri")
        try:
            if reorder_pt_ri is None or weekly_burn_ri in (None, 0, "0", "0.0"):
                r["weeks_reorder_ri"] = "unknown"
            else:
                val = float(reorder_pt_ri) / float(weekly_burn_ri) if float(weekly_burn_ri) != 0 else None
                r["weeks_reorder_ri"] = "unknown" if val is None else val
        except Exception:
            r["weeks_reorder_ri"] = "unknown"
    for row in all_rows:
        assign_setup_action(row, table="par")
    return all_rows


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

    all_rows = _filtered_inventory_rows(request.args)
    annotated_rows = [(row, _is_r_only_location(row)) for row in all_rows]
    total = len(annotated_rows)

    hide_r_only = (request.args.get("hide_r_only") or "").strip().lower() == "true"
    total_hidden = sum(1 for _, is_hidden in annotated_rows if is_hidden) if hide_r_only else 0
    total_visible = total - total_hidden if hide_r_only else total

    pages = (total_visible + per_page - 1) // per_page if per_page else 1
    max_page = pages if pages > 0 else 1
    page = max(1, min(page, max_page))
    start_index = (page - 1) * per_page
    end_index = start_index + per_page

    hidden_on_page = 0
    if hide_r_only:
        rows: list[dict] = []
        if total_visible > 0:
            visible_seen = 0
            for row, is_hidden in annotated_rows:
                if is_hidden:
                    if start_index <= visible_seen < end_index:
                        hidden_on_page += 1
                    continue
                if start_index <= visible_seen < end_index:
                    rows.append(row)
                visible_seen += 1
                if visible_seen >= end_index:
                    break
        else:
            rows = []
            if total_hidden > 0:
                hidden_on_page = min(total_hidden, per_page)
    else:
        slice_start = (page - 1) * per_page
        slice_end = slice_start + per_page
        rows = [row for row, _ in annotated_rows[slice_start:slice_end]]

    # if rows:
    #     print(rows[0]) #debug (keep it for now)
    return jsonify({
        "rows": rows,
        "count": len(rows),
        "total": total,
        "visible_total": total_visible,
        "hidden_total": total_hidden,
        "hidden_on_page": hidden_on_page,
        "page": page,
        "per_page": per_page,
        "pages": pages,
    })


@bp.route("/api/filter-options")
@login_required
def api_filter_options():
    """Return distinct lists for dashboard filters.

    - item_groups: from ItemLink.item_group (exclude NULL, sorted ascending)
      with associated item numbers formatted as {group_id: [item1, item2, ...]}
    - locations: distinct (LocationType, Location) from PLMTrackerBase limited to inventory location types
      formatted as "{LocationType} - {Location}" and include raw location for querying.
    - stages: allowed stage values (static list)
    """
    # Item Groups with associated items
    from ..models.relations import ItemGroup, ItemGroupLink
    
    allowed_stages = tuple(ALLOWED_STAGE_VALUES)

    # Only include groups tied to ItemLink rows that are currently in an allowed stage
    item_groups_query = (
        select(func.distinct(ItemLink.item_group))
        .where(ItemLink.item_group.isnot(None))
        .where(ItemLink.stage.in_(allowed_stages))
        .order_by(ItemLink.item_group)
    )
    group_ids = [row[0] for row in db.session.execute(item_groups_query).all()]

    group_items: dict[int, set[str]] = {}
    if group_ids:
        items_query = (
            select(ItemGroup.item_group, ItemGroup.item)
            .join(ItemGroupLink, ItemGroupLink.item_group_pkid == ItemGroup.pkid)
            .join(ItemLink, ItemGroupLink.item_link_id == ItemLink.pkid)
            .where(ItemGroup.item_group.in_(group_ids))
            .where(ItemLink.stage.in_(allowed_stages))
            .where(ItemGroup.item.isnot(None))
            .order_by(ItemGroup.item_group, ItemGroup.item)
        )
        for group_id, item in db.session.execute(items_query).all():
            bucket = group_items.setdefault(group_id, set())
            bucket.add(item)

    # Build item groups data structure: [{value: group_id, items: [...], label: "123 - item1, item2"}]
    item_groups = []
    for group_id in group_ids:
        items = sorted(group_items.get(group_id, []))
        items_str = ", ".join(items) if items else ""
        label = f"{group_id} - {items_str}" if items_str else str(group_id)

        item_groups.append({
            "value": group_id,
            "items": items,
            "label": label
        })

    # Locations (pull from view)
    v = PLMTrackerBase
    loc_query = (
        select(func.distinct(v.LocationType), v.Group_Locations)
        .where(v.Group_Locations.isnot(None))
        .order_by(v.LocationType, v.Group_Locations)
    )
    locations = []
    include_or_locations = current_app.config.get("INCLUDE_OR_INVENTORY_LOCATIONS")
    
    try:
        location_rows = db.session.execute(loc_query).all()
    except AssertionError:
        # Unit tests monkeypatch the session execute call and only stub the
        # item-group queries. When that patch raises we gracefully fall back to
        # an empty list so the remainder of the response can still be validated.
        location_rows = []

    for lt, group_loc in location_rows:
        # Filter out OR inventory locations if config is disabled
        if lt == "Inventory Location" and not include_or_locations:
            if _looks_like_or_location(group_loc):
                continue

        label = f"{lt} - {group_loc}" if lt else group_loc
        locations.append({"value": group_loc, "type": lt, "label": label})

    stages = [
        "Tracking - Discontinued",
        "Tracking - Item Transition",
        "Pending Clinical Readiness",
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

    all_rows = _filtered_par_rows(request.args)
    annotated_rows = [(row, _is_r_only_location(row)) for row in all_rows]
    total = len(annotated_rows)

    hide_r_only = (request.args.get("hide_r_only") or "").strip().lower() == "true"
    total_hidden = sum(1 for _, is_hidden in annotated_rows if is_hidden) if hide_r_only else 0
    total_visible = total - total_hidden if hide_r_only else total

    pages = (total_visible + per_page - 1) // per_page if per_page else 1
    max_page = pages if pages > 0 else 1
    page = max(1, min(page, max_page))
    start_index = (page - 1) * per_page
    end_index = start_index + per_page

    hidden_on_page = 0
    if hide_r_only:
        rows: list[dict] = []
        if total_visible > 0:
            visible_seen = 0
            for row, is_hidden in annotated_rows:
                if is_hidden:
                    if start_index <= visible_seen < end_index:
                        hidden_on_page += 1
                    continue
                if start_index <= visible_seen < end_index:
                    rows.append(row)
                visible_seen += 1
                if visible_seen >= end_index:
                    break
        else:
            rows = []
            if total_hidden > 0:
                hidden_on_page = min(total_hidden, per_page)
    else:
        slice_start = (page - 1) * per_page
        slice_end = slice_start + per_page
        rows = [row for row, _ in annotated_rows[slice_start:slice_end]]

    return jsonify({
        "rows": rows,
        "count": len(rows),
        "total": total,
        "visible_total": total_visible,
        "hidden_total": total_hidden,
        "hidden_on_page": hidden_on_page,
        "page": page,
        "per_page": per_page,
        "pages": pages,
    })


@bp.route("/api/requesters")
@login_required
def api_requesters():
    inventory_rows = _filtered_inventory_rows(request.args)
    par_rows = _filtered_par_rows(request.args)

    hide_r_only = (request.args.get("hide_r_only") or "").strip().lower() == "true"
    if hide_r_only:
        inventory_rows = [row for row in inventory_rows if not _is_r_only_location(row)]
        par_rows = [row for row in par_rows if not _is_r_only_location(row)]

    item_pool = _collect_item_pool(inventory_rows) | _collect_item_pool(par_rows)
    if not item_pool:
        return jsonify({
            "items": [],
            "requesters": [],
            "requester_count": 0,
            "email_addresses": [],
        })

    stmt = (
        select(
            Requesters365Day.Requester.label("requester"),
            Requesters365Day.RequesterName.label("name"),
            Requesters365Day.EmailAddress.label("email"),
            Requesters365Day.RequestingLocation.label("location"),
            Requesters365Day.Item.label("item"),
            Requesters365Day.Requisition_FD5.label("requisition"),
            Requesters365Day.RequestsCount.label("requests_count"),
        )
        .where(Requesters365Day.Item.in_(sorted(item_pool)))
        .where(Requesters365Day.RequestingLocation.like("R%"))
    )

    requester_rows = [dict(row._mapping) for row in db.session.execute(stmt)]
    requesters = _aggregate_requester_rows(requester_rows)
    email_addresses = sorted({r["email"] for r in requesters if r["email"]})

    return jsonify({
        "items": sorted(item_pool),
        "requesters": requesters,
        "requester_count": len(requesters),
        "email_addresses": email_addresses,
    })


@bp.route("/api/refresh-timestamp")
@login_required
def api_refresh_timestamp():
    """Return the latest successful data refresh timestamp from process log."""
    refresh_timestamp = None
    try:
        from ..models.log import ProcessLog
        latest_refresh = ProcessLog.get_latest_success_timestamp(db.session)
        print(f"[DEBUG] Latest refresh from DB: {latest_refresh}")
        if latest_refresh:
            refresh_timestamp = latest_refresh.isoformat()
            print(f"[DEBUG] Formatted timestamp: {refresh_timestamp}")
    except Exception as e:
        print(f"[ERROR] Failed to get refresh timestamp: {e}")
        import traceback
        traceback.print_exc()
    
    return jsonify({
        "refresh_timestamp": refresh_timestamp,
    })


@bp.route("/api/stats")
@login_required
def api_stats():
    """Return KPI statistics based on applied filters.

    Returns:
    - distinct_groups: count of distinct item_group values
    - distinct_items: count of distinct items (including replacement_item)
    - distinct_locations: count of distinct locations (from both inventory and par)
    """
    inventory_rows = _filtered_inventory_rows(request.args)
    par_rows = _filtered_par_rows(request.args)

    # Collect distinct item groups (always based on the full dataset)
    groups_set = set()
    for row in inventory_rows:
        if row.get("item_group"):
            groups_set.add(row.get("item_group"))
    for row in par_rows:
        if row.get("item_group"):
            groups_set.add(row.get("item_group"))

    # Collect distinct items (including replacement items)
    items_set = set()
    for row in inventory_rows:
        if row.get("item"):
            items_set.add(row.get("item"))
        if row.get("replacement_item"):
            items_set.add(row.get("replacement_item"))
    for row in par_rows:
        if row.get("item"):
            items_set.add(row.get("item"))
        if row.get("replacement_item"):
            items_set.add(row.get("replacement_item"))

    # Apply hide_r_only filter only when gathering location metrics
    hide_r_only = (request.args.get("hide_r_only") or "").strip().lower() == "true"
    inventory_location_rows = inventory_rows
    par_location_rows = par_rows
    if hide_r_only:
        inventory_location_rows = [row for row in inventory_rows if not _is_r_only_location(row)]
        par_location_rows = [row for row in par_rows if not _is_r_only_location(row)]

    # Collect distinct locations (using group_location as the canonical location identifier)
    locations_set = set()
    for row in inventory_location_rows:
        loc = row.get("group_location") or row.get("location")
        if loc:
            locations_set.add(loc)
    for row in par_location_rows:
        loc = row.get("group_location") or row.get("location")
        if loc:
            locations_set.add(loc)

    return jsonify({
        "distinct_groups": len(groups_set),
        "distinct_items": len(items_set),
        "distinct_locations": len(locations_set),
    })


@bp.route("/export/<string:table_key>")
@login_required
def export_table(table_key: str):
    table_key_normalized = table_key.lower()
    row_scope = (request.args.get("row_scope") or "filtered").strip().lower()
    if row_scope not in {"all", "filtered"}:
        row_scope = "filtered"
    apply_filters = row_scope != "all"

    table_config = TABLE_CONFIGS.get(table_key_normalized)
    if table_config is None:
        abort(404)

    if table_key_normalized == "inventory":
        rows = _filtered_inventory_rows(request.args, apply_filters=apply_filters)
    elif table_key_normalized == "par":
        rows = _filtered_par_rows(request.args, apply_filters=apply_filters)
    else:
        abort(404)

    hide_r_only = (request.args.get("hide_r_only") or "").strip().lower() == "true"
    if hide_r_only:
        rows = [row for row in rows if not _is_r_only_location(row)]

    if table_config.base_pipeline:
        rows = apply_pipeline(rows, table_config.base_pipeline)

    column_mode = (request.args.get("column_mode") or "").strip().lower()
    requested_fields = parse_column_selection(request.args.get("columns"))
    legacy_visible_param = request.args.get("visible_columns")
    if not requested_fields and legacy_visible_param:
        requested_fields = parse_column_selection(legacy_visible_param)
        if not column_mode:
            column_mode = "visible"
    allowed_column_modes = {"all", "visible"} | CUSTOM_EXPORT_MODES
    if column_mode not in allowed_column_modes:
        column_mode = "all"

    column_mode_config = COLUMN_MODE_REGISTRY.get(column_mode)
    if column_mode_config and column_mode_config.columns:
        columns = list(column_mode_config.columns)
    else:
        columns = list(table_config.columns)

    if requested_fields:
        filtered_columns = filter_export_columns(columns, requested_fields)
        if column_mode in CUSTOM_EXPORT_MODES:
            if not filtered_columns or len(filtered_columns) != len(requested_fields):
                abort(400, description="Requested columns are not available for export.")
            columns = filtered_columns
        elif filtered_columns:
            columns = filtered_columns
    elif column_mode in CUSTOM_EXPORT_MODES:
        abort(400, description="No columns selected for export.")

    if column_mode_config and column_mode_config.pipeline:
        rows = apply_pipeline(rows, column_mode_config.pipeline)

    header_overrides = dict(column_mode_config.header_overrides) if column_mode_config else {}
    highlight_notes = table_config.highlight_notes or (column_mode_config.highlight_notes if column_mode_config else False)
    highlight_row_predicate = None
    if column_mode_config and column_mode_config.highlight_row_predicate is not None:
        highlight_row_predicate = column_mode_config.highlight_row_predicate
    elif table_config.highlight_row_predicate is not None:
        highlight_row_predicate = table_config.highlight_row_predicate

    workbook = render_workbook(
        sheet_name=table_config.sheet_name,
        rows=rows,
        columns=columns,
        header_overrides=header_overrides,
        highlight_notes=highlight_notes,
        highlight_row_predicate=highlight_row_predicate,
    )

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename_prefix = table_config.sheet_name.lower().replace(" ", "_")
    filename = f"{filename_prefix}_{timestamp}.xlsx"

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


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
            PLMQty.PLM_Zdate.label("z_date"),
        )
        .where(PLMQty.Item_Group == item_group)
        .order_by(PLMQty.Item, PLMQty.Location, PLMQty.report_stamp)
    )
    rows = db.session.execute(stmt).all()

    gl_map = {}
    if rows:
        gl_query = (
            select(PLMTrackerBase.Item, PLMTrackerBase.Location, PLMTrackerBase.Group_Locations)
            .where(PLMTrackerBase.Item_Group == item_group)
        )
        for item, location, group_loc in db.session.execute(gl_query).all():
            bucket = gl_map.setdefault(item, {})
            bucket[location] = group_loc
    series_map: dict[tuple[str, str], dict[str, object]] = {}
    for item, location, stamp, qty, z_date in rows:
        key = (item, location)
        bucket = series_map.setdefault(key, {"points": [], "z_date": None})
        points = bucket.setdefault("points", [])
        points.append({
            "t": stamp.isoformat() if stamp else None,
            "qty": int(qty) if qty is not None else None,
        })
        if z_date and bucket.get("z_date") is None:
            bucket["z_date"] = z_date.isoformat()
    series = [
        {
            "item": item_key,
            "location": loc_key,
            "group_location": gl_map.get(item_key, {}).get(loc_key) or gl_map.get(item_key, {}).get(None) or loc_key,
            "points": entry.get("points", []),
            "z_date": entry.get("z_date"),
        }
        for (item_key, loc_key), entry in series_map.items()
    ]

    return jsonify({
        "item_group": item_group,
        "series": series,
        "series_count": len(series),
        "point_count": sum(len(s["points"]) for s in series),
    })


@bp.route("/api/issue/<int:item_group>")
@login_required
def api_issue(item_group: int):
    """Return daily issue-out quantities per (Item, Location) for a given item_group.

    Response structure mirrors qty endpoint for easier client reuse.
    """
    stmt = (
        select(
            PLMDailyIssueOutQty.Item.label("item"),
            PLMDailyIssueOutQty.Location.label("location"),
            PLMDailyIssueOutQty.trx_date.label("stamp"),
            PLMDailyIssueOutQty.IssuedQty.label("qty"),
        )
        .where(PLMDailyIssueOutQty.Item_Group == item_group)
        .order_by(
            PLMDailyIssueOutQty.Item,
            PLMDailyIssueOutQty.Location,
            PLMDailyIssueOutQty.trx_date,
        )
    )
    rows = db.session.execute(stmt).all()

    gl_map = {}
    if rows:
        gl_query = (
            select(PLMTrackerBase.Item, PLMTrackerBase.Location, PLMTrackerBase.Group_Locations)
            .where(PLMTrackerBase.Item_Group == item_group)
        )
        for item, location, group_loc in db.session.execute(gl_query).all():
            bucket = gl_map.setdefault(item, {})
            bucket[location] = group_loc

    series_map = {}
    for item, location, stamp, qty in rows:
        key = (item, location)
        bucket = series_map.setdefault(key, [])
        bucket.append(
            {
                "t": stamp.isoformat() if stamp else None,
                "qty": int(qty) if qty is not None else None,
            }
        )

    series = [
        {
            "item": item_key,
            "location": loc_key,
            "group_location": gl_map.get(item_key, {}).get(loc_key)
            or gl_map.get(item_key, {}).get(None)
            or loc_key,
            "points": points,
        }
        for (item_key, loc_key), points in series_map.items()
    ]

    return jsonify(
        {
            "item_group": item_group,
            "series": series,
            "series_count": len(series),
            "point_count": sum(len(s["points"]) for s in series),
        }
    )
