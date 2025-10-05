from __future__ import annotations

from collections import defaultdict

from flask import Blueprint, render_template, request
from flask_login import login_required

from sqlalchemy import or_

from .. import db
from ..models.relations import ItemLink

bp = Blueprint("playground", __name__, url_prefix="/playground")


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


@bp.route("/")
@login_required
def index():
    limit_param = request.args.get("limit", type=int)
    limit = limit_param if limit_param is not None else 50
    limit = max(50, min(limit, 1500))

    search_query_raw = request.args.get("search", default="", type=str) or ""
    search_query = search_query_raw.strip()

    stage_rows = (
        db.session.query(ItemLink.stage)
        .filter(ItemLink.stage.isnot(None))
        .distinct()
        .order_by(ItemLink.stage.asc())
        .all()
    )
    available_stages = [value.strip() for (value,) in stage_rows if value and value.strip()]

    selected_stages_raw = [s.strip() for s in request.args.getlist("stage") if s and s.strip()]
    selected_stages = [stage for stage in selected_stages_raw if stage in available_stages]

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
        .filter(ItemLink.replace_item.isnot(None))
    )

    if selected_stages:
        query = query.filter(ItemLink.stage.in_(selected_stages))

    if search_query:
        pattern = f"%{search_query}%"
        query = query.filter(
            or_(
                ItemLink.item.ilike(pattern),
                ItemLink.replace_item.ilike(pattern),
                ItemLink.item_description.ilike(pattern),
                ItemLink.repl_item_description.ilike(pattern),
                ItemLink.manufacturer.ilike(pattern),
                ItemLink.repl_manufacturer.ilike(pattern),
            )
        )

    rows = (
        query
        .order_by(ItemLink.update_dt.desc(), ItemLink.item_group.desc())
        .limit(limit)
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

    nodes = []
    for code in sorted({*node_roles, *node_stages, *node_groups}):
        groups_sorted = sorted(node_groups.get(code, []))
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
            }
        )

    graph_data = {
        "nodes": nodes,
        "links": links,
    }

    summary = {
        "requested_limit": limit,
        "rendered_links": len(links),
        "rendered_nodes": len(nodes),
        "explicit_limit": limit_param,
        "selected_stages": selected_stages,
        "search_query": search_query,
    }

    return render_template(
        "playground/index.html",
        graph_data=graph_data,
        summary=summary,
        stages=available_stages,
        selected_stages=selected_stages,
        search_query=search_query,
    )
