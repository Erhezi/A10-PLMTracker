from __future__ import annotations

from collections import defaultdict

from flask import Blueprint, current_app, render_template, request
from flask_login import login_required

from sqlalchemy import func, or_

from .. import db
from ..models.inventory import ItemLocations
from ..models.relations import ItemLink, PLMItemGroupLocation

bp = Blueprint("playground", __name__, url_prefix="/playground")

DISCONTINUED_STAGE_NAME = "Tracking - Discontinued"
DEFAULT_TRANSITION_STAGES = (
    "Pending Clinical Readiness",
    DISCONTINUED_STAGE_NAME,
    "Tracking - Item Transition",
)
EXPANDED_STAGE_ADDITIONS = (
    "Tracking Completed",
    "Deleted",
)


def _looks_like_or_location(value: object | None) -> bool:
    if not value:
        return False
    normalized = str(value).strip().upper()
    if not normalized:
        return False
    return normalized.endswith("OR")


def _is_skip_candidate(raw_value: str | None) -> bool:
    if not raw_value:
        return True
    value = str(raw_value).strip()
    if not value:
        return True
    upper_value = value.upper()
    if upper_value == "NO REPLACEMENT":
        return True
    if upper_value.startswith("PENDING***"):
        return True
    return False


def _build_search_filter(term: str):
    like_pattern = f"%{term}%"
    return or_(
        ItemLink.item.ilike(like_pattern),
        ItemLink.replace_item.ilike(like_pattern),
        ItemLink.item_description.ilike(like_pattern),
        ItemLink.repl_item_description.ilike(like_pattern),
        ItemLink.manufacturer.ilike(like_pattern),
        ItemLink.repl_manufacturer.ilike(like_pattern),
    )


@bp.route("/documents/overview")
@login_required
def documentation():
    return render_template("documents/playgroundOverview.html")


@bp.route("/")
@login_required
def index():
    limit_param = request.args.get("limit", type=int)
    limit = limit_param if limit_param is not None else 50
    limit = max(50, min(limit, 1500))
    row_limit = limit * 3

    search_query_raw = request.args.get("search", default="", type=str) or ""
    search_query = search_query_raw.strip()

    apply_quantity_param = request.args.get("apply_quantity", default=0, type=int)
    apply_quantity = bool(apply_quantity_param)
    selected_inventory_location_raw = request.args.get("inventory_location", default="", type=str)
    selected_inventory_location = (
        selected_inventory_location_raw.strip() or None
    )

    expanded_param = request.args.get("expanded", default=0, type=int)
    expanded_scope = bool(expanded_param)
    if apply_quantity:
        expanded_scope = False

    trimmed_stage_expr = func.rtrim(func.ltrim(ItemLink.stage))

    stage_scope = (
        DEFAULT_TRANSITION_STAGES + EXPANDED_STAGE_ADDITIONS
        if expanded_scope
        else DEFAULT_TRANSITION_STAGES
    )
    available_stages = list(stage_scope)

    selected_stages_raw = [s.strip() for s in request.args.getlist("stage") if s and s.strip()]
    selected_stages = [stage for stage in selected_stages_raw if stage in available_stages]

    base_filters = [
        ItemLink.replace_item.isnot(None),
        trimmed_stage_expr.in_(stage_scope),
    ]

    search_filter = None
    search_pattern: str | None = None

    query = (
        db.session.query(
            ItemLink.item,
            ItemLink.replace_item,
            ItemLink.item_group,
            ItemLink.stage,
            ItemLink.item_description,
            ItemLink.manufacturer,
            ItemLink.repl_item_description,
            ItemLink.repl_manufacturer,
        )
        .filter(*base_filters)
    )

    if selected_stages:
        query = query.filter(trimmed_stage_expr.in_(selected_stages))

    if search_query:
        search_pattern = f"%{search_query}%"
        search_filter = _build_search_filter(search_query)
        query = query.filter(search_filter)
        base_filters.append(search_filter)

    stage_counts_query = (
        db.session.query(
            trimmed_stage_expr.label("stage"),
            func.count(func.distinct(ItemLink.item_group)).label("group_count"),
        )
        .filter(*base_filters)
        .group_by(trimmed_stage_expr)
    )

    include_or_locations = current_app.config.get("INCLUDE_OR_INVENTORY_LOCATIONS")

    location_rows = (
        db.session.query(
            PLMItemGroupLocation.LocationType,
            PLMItemGroupLocation.Group_Locations,
        )
        .filter(PLMItemGroupLocation.LocationType == "Inventory Location")
        .filter(PLMItemGroupLocation.Group_Locations.isnot(None))
        .distinct()
        .order_by(PLMItemGroupLocation.Group_Locations.asc())
        .all()
    )

    inventory_locations = []
    for location_type, group_location in location_rows:
        if not include_or_locations and _looks_like_or_location(group_location):
            continue
        label = f"{location_type} - {group_location}" if location_type else str(group_location)
        inventory_locations.append(
            {
                "value": group_location,
                "label": label,
                "type": location_type,
            }
        )

    location_label_lookup = {option["value"]: option["label"] for option in inventory_locations}
    selected_inventory_location_label = (
        location_label_lookup.get(selected_inventory_location)
        if selected_inventory_location
        else None
    )

    rows = (
        query
    .order_by(ItemLink.update_dt.desc(), ItemLink.item_group.desc())
    .limit(row_limit)
        .all()
    )

    discontinued_rows: list[tuple[str | None, int | None, str | None, str | None, str | None]] = []
    include_discontinued = not selected_stages or DISCONTINUED_STAGE_NAME in selected_stages
    if include_discontinued:
        discontinued_query = (
            db.session.query(
                ItemLink.item,
                ItemLink.item_group,
                ItemLink.stage,
                ItemLink.item_description,
                ItemLink.manufacturer,
            )
            .filter(
                ItemLink.replace_item.is_(None),
                trimmed_stage_expr == DISCONTINUED_STAGE_NAME,
            )
        )

        if search_pattern:
            discontinued_query = discontinued_query.filter(
                or_(
                    ItemLink.item.ilike(search_pattern),
                    ItemLink.item_description.ilike(search_pattern),
                    ItemLink.manufacturer.ilike(search_pattern),
                )
            )

        discontinued_rows = (
            discontinued_query
            .order_by(ItemLink.update_dt.desc(), ItemLink.item_group.desc())
            .limit(row_limit)
            .all()
        )

    node_roles: dict[str, set[str]] = defaultdict(set)
    node_stages: dict[str, set[str]] = defaultdict(set)
    node_groups: dict[str, set[int]] = defaultdict(set)
    node_descriptions: dict[str, set[str]] = defaultdict(set)
    node_manufacturers: dict[str, set[str]] = defaultdict(set)
    links: list[dict[str, object]] = []

    for (
        item,
        replace_item,
        item_group,
        stage,
        item_description,
        manufacturer,
        replace_description,
        replace_manufacturer,
    ) in rows:
        if _is_skip_candidate(replace_item):
            continue
        item_code = (item or "").strip()
        repl_code = (replace_item or "").strip()
        if not item_code or not repl_code:
            continue

        node_roles[item_code].add("origin")
        node_roles[repl_code].add("replacement")

        if item_description:
            node_descriptions[item_code].add(item_description.strip())
        if manufacturer:
            node_manufacturers[item_code].add(manufacturer.strip())
        if replace_description:
            node_descriptions[repl_code].add(replace_description.strip())
        if replace_manufacturer:
            node_manufacturers[repl_code].add(replace_manufacturer.strip())

        if stage:
            stage_value = stage.strip()
            if stage_value:
                node_stages[item_code].add(stage_value)
                node_stages[repl_code].add(stage_value)

        if item_group is not None:
            node_groups[item_code].add(int(item_group))
            node_groups[repl_code].add(int(item_group))

        links.append(
            {
                "source": item_code,
                "target": repl_code,
                "item_group": int(item_group) if item_group is not None else None,
                "stage": stage.strip() if stage else None,
            }
        )

    for (item, item_group, stage, item_description, manufacturer) in discontinued_rows:
        item_code = (item or "").strip()
        if not item_code or _is_skip_candidate(item_code):
            continue

        node_roles[item_code].add("origin")

        if stage:
            stage_value = stage.strip()
            if stage_value:
                node_stages[item_code].add(stage_value)
        node_stages[item_code].add(DISCONTINUED_STAGE_NAME)

        if item_group is not None:
            node_groups[item_code].add(int(item_group))

        if item_description:
            node_descriptions[item_code].add(item_description.strip())
        if manufacturer:
            node_manufacturers[item_code].add(manufacturer.strip())

    location_quantities: dict[str, int | None] = {}
    if apply_quantity and selected_inventory_location:
        quantity_rows = (
            db.session.query(ItemLocations.Item, ItemLocations.AvailableQty)
            .filter(ItemLocations.Location == selected_inventory_location)
            .all()
        )
        for item_code_raw, available_qty in quantity_rows:
            code = (item_code_raw or "").strip()
            if not code:
                continue
            if available_qty is None:
                location_quantities[code] = None
            else:
                try:
                    location_quantities[code] = int(available_qty)
                except (TypeError, ValueError):
                    location_quantities[code] = None

    nodes = []
    for code in sorted({*node_roles, *node_stages, *node_groups}):
        groups_sorted = sorted(node_groups.get(code, []))
        available_quantity = (
            location_quantities.get(code)
            if apply_quantity and selected_inventory_location
            else None
        )
        nodes.append(
            {
                "id": code,
                "label": code,
                "roles": sorted(node_roles.get(code, {"unknown"})),
                "stages": sorted(node_stages.get(code, {"Unspecified"})),
                "groups": groups_sorted[:10],
                "primary_group": groups_sorted[0] if groups_sorted else None,
                "descriptions": sorted(node_descriptions.get(code, []))[:5],
                "manufacturers": sorted(node_manufacturers.get(code, []))[:5],
                "available_quantity": available_quantity,
            }
        )

    graph_data = {
        "nodes": nodes,
        "links": links,
        "meta": {
            "apply_quantity": apply_quantity,
            "selected_location": selected_inventory_location,
            "selected_location_label": selected_inventory_location_label,
        },
    }

    stage_counts_lookup = {
        (stage_name or ""): count
        for stage_name, count in stage_counts_query.all()
    }

    if DISCONTINUED_STAGE_NAME in available_stages:
        discontinued_count_query = (
            db.session.query(func.count(func.distinct(ItemLink.item_group)))
            .filter(
                ItemLink.replace_item.is_(None),
                trimmed_stage_expr == DISCONTINUED_STAGE_NAME,
            )
        )
        if search_pattern:
            discontinued_count_query = discontinued_count_query.filter(
                or_(
                    ItemLink.item.ilike(search_pattern),
                    ItemLink.item_description.ilike(search_pattern),
                    ItemLink.manufacturer.ilike(search_pattern),
                )
            )
        discontinued_group_count = discontinued_count_query.scalar() or 0
        if discontinued_group_count:
            stage_counts_lookup[DISCONTINUED_STAGE_NAME] = (
                stage_counts_lookup.get(DISCONTINUED_STAGE_NAME, 0) + discontinued_group_count
            )

    stage_counts = {stage: stage_counts_lookup.get(stage, 0) for stage in available_stages}

    summary = {
        "requested_limit": limit,
        "row_limit": row_limit,
        "rendered_links": len(links),
        "rendered_nodes": len(nodes),
        "explicit_limit": limit_param,
        "selected_stages": selected_stages,
        "search_query": search_query,
        "discontinued_nodes": len(discontinued_rows),
        "expanded_scope": expanded_scope,
        "apply_quantity": apply_quantity,
        "selected_inventory_location": selected_inventory_location,
        "selected_inventory_location_label": selected_inventory_location_label,
    }

    return render_template(
        "playground/index.html",
        graph_data=graph_data,
        summary=summary,
        stages=available_stages,
        selected_stages=selected_stages,
        search_query=search_query,
        expanded_scope=expanded_scope,
        stage_counts=stage_counts,
        apply_quantity=apply_quantity,
        inventory_locations=inventory_locations,
        selected_inventory_location=selected_inventory_location,
        selected_inventory_location_label=selected_inventory_location_label,
    )
