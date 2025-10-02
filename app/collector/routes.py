from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_login import login_required
from sqlalchemy import func, or_
from sqlalchemy.orm import noload
import re
from .. import db
from ..models import now_ny_naive
from ..models.relations import (
    ItemLink,
    ItemGroup,
    PendingItems,
    ItemGroupConflictError,
    ConflictError,
)
from ..models.inventory import Item, ContractItem
from ..utility.item_group import (
    validate_batch_inputs,
    validate_stage_and_items,
    BatchValidationError,
    BatchGroupPlanner,
)

"""Stage name definitions (canonical only)."""

ALLOWED_STAGES = [  # New canonical stage names (order meaningful for UI select)
    'Tracking - Discontinued',
    'Pending Item Number',
    'Pending Clinical Approval',
    'Tracking - Item Transition',
    'Deleted',
    'Tracking Completed'
]

def normalize_stage(value: str | None) -> str | None:  # kept for minimal refactor
    return value

SENTINEL_REPLACEMENTS = {"NO REPLACEMENT"}  # Dynamic PENDING*** codes handled separately

bp = Blueprint("collector", __name__, url_prefix="")

@bp.route("/collect")
@login_required
def collect():
    # Fetch a small sample set to verify Item view connectivity
    sample_items = Item.query.order_by(Item.item).limit(25).all()
    from datetime import date
    from calendar import monthrange

    def add_months(d: date, months: int) -> date:
        m = d.month - 1 + months
        y = d.year + m // 12
        m = m % 12 + 1
        day = min(d.day, monthrange(y, m)[1])
        from datetime import date as _d
        return _d(y, m, day)

    today = date.today()
    min_date = add_months(today, -3)
    max_date = add_months(today, 6)
    
    # Import config for batch limits
    from flask import current_app
    max_per_side = current_app.config.get('MAX_BATCH_PER_SIDE', 6)
    max_combinations = max_per_side * max_per_side  # Calculate total combinations for display
    
    return render_template(
        "collector/collect.html",
        allowed_stages=ALLOWED_STAGES,
        sample_items=sample_items,
        date_min=min_date.isoformat(),
        date_max=max_date.isoformat(),
        max_combinations=max_combinations,
        max_per_side=max_per_side,
    )

@bp.route("/groups")
@login_required
def groups():
    # Avoid eager loading any relationships (they are not needed for groups table)
    items = (
        ItemLink.query
        .options(noload('*'))
        .order_by(ItemLink.item_group, ItemLink.item)
        .all()
    )
    # Count rows currently flagged as deleted
    count_deleted = ItemLink.query.filter(ItemLink.stage == 'Deleted').count()
    return render_template("collector/groups.html", items=items, allowed_stages=ALLOWED_STAGES, count_deleted=count_deleted)

@bp.post('/groups/clear-deleted')
@login_required
def clear_deleted():
    # Delete only rows whose stage is Deleted
    q = ItemLink.query.filter(ItemLink.stage == 'Deleted')
    count = q.count()
    if count == 0:
        flash('No rows with stage Deleted to remove', 'info')
        return redirect(url_for('collector.groups'))
    q.delete(synchronize_session=False)
    db.session.commit()
    flash(f'Removed {count} deleted item link(s)', 'success')
    return redirect(url_for('collector.groups'))


@bp.route("/groups/<item>/<replace_item>/update", methods=["POST"])
@login_required
def update_item(item: str, replace_item: str):
    # The template may render Python None as the string 'None' (or similar) into
    # the data-replace-item attribute. Normalize common textual null
    # representations to actual None so SQL queries match NULL values.
    if isinstance(replace_item, str) and replace_item.lower() in ('none', 'null', 'nan', ''):
        replace_item = None
    record = ItemLink.query.filter_by(item=item, replace_item=replace_item).first_or_404()
    print(record) #debugging
    stage = request.form.get("stage")
    expected_go_live_date = request.form.get("expected_go_live_date") or None
    wrike_id = request.form.get("wrike_id") or None
    wants_json = (request.args.get('ajax') == '1') or ('application/json' in request.headers.get('Accept','')) or request.headers.get('X-Requested-With') == 'fetch'

    # Server-side Wrike ID validation: allow empty or exactly 10 digits
    if wrike_id:
        wrike_id = wrike_id.strip()
        import re
        if not re.match(r"\A\d{10}\Z", wrike_id):
            if wants_json:
                return jsonify({"status":"error","field":"wrike_id","message":"Wrike ID must be 10 digits or left blank"}), 400
            flash("Wrike ID must be 10 digits or left blank", "warning")
            return redirect(url_for("collector.groups"))

    if stage not in ALLOWED_STAGES:
        if wants_json:
            return jsonify({"status":"error","field":"stage","message":"Invalid stage value"}), 400
        flash("Invalid stage value", "danger")
        return redirect(url_for("collector.groups"))

    # Transition rules:
    #  - If current stage is Tracking - Discontinued, only allow Deleted or Tracking Completed
    #  - If current stage is not Tracking - Discontinued, disallow moving into it directly
    current_stage = record.stage or ''
    if current_stage == 'Tracking - Discontinued':
        if stage not in ('Tracking - Discontinued', 'Deleted', 'Tracking Completed'):
            if wants_json:
                return jsonify({"status":"error","field":"stage","message":"Invalid transition from Tracking - Discontinued"}), 400
            flash("Cannot transition from Tracking - Discontinued to that stage (only Deleted or Tracking Completed allowed)", "warning")
            return redirect(url_for("collector.groups"))
    else:
        if stage == 'Tracking - Discontinued':
            if wants_json:
                return jsonify({"status":"error","field":"stage","message":"Cannot set stage to Tracking - Discontinued here"}), 400
            flash("Cannot set stage to Tracking - Discontinued here", "warning")
            return redirect(url_for("collector.groups"))

    record.stage = stage
    # Parse date (YYYY-MM-DD) if provided
    if expected_go_live_date:
        try:
            from datetime import datetime
            record.expected_go_live_date = datetime.strptime(expected_go_live_date, "%Y-%m-%d").date()
        except ValueError:
            if wants_json:
                return jsonify({"status":"error","field":"expected_go_live_date","message":"Invalid date format; use YYYY-MM-DD"}), 400
            flash("Invalid date format; use YYYY-MM-DD", "warning")
    else:
        record.expected_go_live_date = None

    record.wrike_id = wrike_id
    record.update_dt = now_ny_naive()
    db.session.commit()
    if wants_json:
        # Also return current deleted count for client-side UI updates
        count_deleted = ItemLink.query.filter(ItemLink.stage == 'Deleted').count()
        return jsonify({
            "status":"ok",
            "message":"ItemLink updated",
            "record":{
                "item": record.item,
                "replace_item": record.replace_item,
                "stage": record.stage,
                "expected_go_live_date": record.expected_go_live_date.isoformat() if record.expected_go_live_date else None,
                "wrike_id": record.wrike_id,
                "update_dt": record.update_dt.isoformat() if record.update_dt else None,
            },
            "count_deleted": count_deleted,
        })
    flash("ItemLink updated", "success")
    return redirect(url_for("collector.groups"))

@bp.route("/conflicts")
@login_required
def conflicts():
    return render_template("collector/conflicts.html")


# -------------------- API: Item search --------------------
@bp.get("/api/items/search")
@login_required
def api_search_items():
    q = (request.args.get("q") or "").strip()
    if not q:
        # For HTMX we still return a table skeleton
        if request.headers.get("HX-Request"):
            return render_template("collector/_item_search_table.html", items=[])
        return jsonify([])
    limit = min(int(request.args.get("limit", 15) or 15), 50)
    active_only = request.args.get("active_only") == "1"

    query = Item.query
    like_term = f"%{q}%" if len(q) > 3 else f"{q}%"
    query = query.filter(Item.item.ilike(like_term))
    if active_only:
        query = query.filter(Item.is_active == 'Yes')

    items = query.order_by(Item.item).limit(limit).all()

    # Debug logging
    print(f"Search query: '{q}', like_term: '{like_term}', found {len(items)} items")

    if request.headers.get("HX-Request"):
        return render_template("collector/_item_search_table.html", items=items)

    return jsonify([
        {
            "item": it.item,
            "manufacturer": it.manufacturer,
            "mfg_part_num": it.mfg_part_num,
            "item_description": it.item_description,
            "is_active": it.is_active == 'Yes',
            "is_discontinued": it.is_discontinued == 'Yes',
        }
        for it in items
    ])


@bp.get("/api/contract-items/search")
@login_required
def api_search_contract_items():
    """Search ContractItem by normalized user input against Item.search_shadow.

    Behavior changes:
      - Only searches on Item.search_shadow (joined via ContractItem.item)
      - Input is normalized by removing spaces and hyphens before building LIKE pattern
      - LIKE pattern: if length > 3 use %term%, else term% (prefix search for short inputs)
    """
    q_raw = (request.args.get("q") or "").strip()
    if not q_raw:
        if request.headers.get("HX-Request"):
            return render_template("collector/_contract_item_search_table.html", contract_items=[])
        return jsonify([])
    # normalize: remove spaces and dashes
    q_norm = q_raw.replace(" ", "").replace("-", "")
    if not q_norm:
        if request.headers.get("HX-Request"):
            return render_template("collector/_contract_item_search_table.html", contract_items=[])
        return jsonify([])
    limit = min(int(request.args.get("limit", 15) or 15), 50)

    query = ContractItem.query
    like_term = f"%{q_norm}%" if len(q_norm) > 3 else f"{q_norm}%"
    query = query.filter(ContractItem.search_shadow.ilike(like_term))

    rows = (
        query.order_by(ContractItem.mfg_part_num, ContractItem.manufacturer, ContractItem.item)
        .limit(limit)
        .all()
    )

    if request.headers.get("HX-Request"):
        return render_template("collector/_contract_item_search_table.html", contract_items=rows)

    return jsonify([
        {
            "contract_id": r.contract_id,
            "manufacturer": r.manufacturer,
            "mfg_part_num": r.mfg_part_num,
            "item_description": r.item_description,
            "item_type": r.item_type,
            "item": r.item,
        }
        for r in rows
    ])

# -------------------- API: Batch create links --------------------
@bp.post("/api/item-links/batch")
@login_required
def api_batch_item_links():
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    replace_items = data.get("replace_items") or []
    pending_meta = data.get("pending_meta") or {}
    explicit_stage = data.get("stage") or None
    expected_go_live_date_raw = (data.get("expected_go_live_date") or "").strip() or None
    wrike_id = (data.get("wrike_id") or "").strip() or None

    # Basic validation
    if not items or not replace_items:
        return jsonify({"error": "Both items and replace_items required"}), 400

    validated_wrike_id = None
    validated_date = None
    stage = None
    locked = False
    items_map = {}
    missing = []

    # Use utility functions for validation and group resolution
    try:
        # Get config value for max per side
        from flask import current_app
        max_per_side = current_app.config.get('MAX_BATCH_PER_SIDE', 6)
        
        # Validate and normalize inputs
        items, replace_items, validated_wrike_id, validated_date = validate_batch_inputs(
            items=items,
            replace_items=replace_items,
            wrike_id=wrike_id,
            expected_go_live_date_raw=expected_go_live_date_raw,
            sentinel_replacements=SENTINEL_REPLACEMENTS,
            max_per_side=max_per_side
        )
        
        # Validate stage and lookup items
        stage, locked, items_map, missing = validate_stage_and_items(
            items=items,
            replace_items=replace_items,
            explicit_stage=explicit_stage,
            allowed_stages=ALLOWED_STAGES,
            sentinel_replacements=SENTINEL_REPLACEMENTS
        )
        
        # Extract real codes for planning (exclude sentinel and dynamic pending placeholders)
        real_codes = set(
            items
            + [r for r in replace_items if (r not in SENTINEL_REPLACEMENTS and not r.startswith("PENDING***"))]
        )

        # Determine existing links touching involved codes to seed planner
        max_group_value = db.session.query(func.coalesce(func.max(ItemLink.item_group), 0)).scalar() or 0
        existing_links: list[ItemLink] = []
        if real_codes:
            group_rows = (
                db.session.query(ItemLink.item_group)
                .filter(
                    or_(
                        ItemLink.item.in_(real_codes),
                        ItemLink.replace_item.in_(real_codes),
                    )
                )
                .distinct()
                .all()
            )
            group_ids = [row[0] for row in group_rows if row[0] is not None]
            if group_ids:
                existing_links = (
                    ItemLink.query
                    .options(noload('*'))
                    .filter(ItemLink.item_group.in_(group_ids))
                    .all()
                )

        planner = BatchGroupPlanner(existing_links, next_group_id=max_group_value + 1)

        # Ensure batch does not assign conflicting sides for the same item/group combination
        batch_side_tracker: dict[tuple[str, int], str] = {}

        def register_batch_side(code: str | None, group_id: int, desired_side: str):
            if not code:
                return
            key = (code, group_id)
            prev = batch_side_tracker.get(key)
            if prev and prev != desired_side:
                raise BatchValidationError(
                    f"Item {code} cannot be both side {prev} and {desired_side} within the same group"
                )
            batch_side_tracker[key] = desired_side

    except BatchValidationError as e:
        db.session.rollback()
        if e.error_code == "missing_items":
            return jsonify({"error": e.message, "missing": missing}), 400
        return jsonify({"error": e.message}), 400

    except ItemGroupConflictError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

    # -------- Optimized creation to avoid per-pair queries --------
    from sqlalchemy import and_ as _and

    created = 0
    skipped = []
    created_records = []
    pending_items_to_create = []  # Store info for PendingItems creation
    conflict_entries: list[ConflictError] = []
    conflict_reports: list[dict[str, object]] = []

    # Prefetch existing pairs in one query (excluding self-pairs early)
    candidate_src = items
    candidate_repl = replace_items
    if candidate_src and candidate_repl:
        existing_rows = db.session.query(ItemLink.item, ItemLink.replace_item).filter(
            ItemLink.item.in_(candidate_src),
            ItemLink.replace_item.in_(candidate_repl),
            ItemLink.item != ItemLink.replace_item
        ).all()
        existing_pairs = set(existing_rows)
    else:
        existing_pairs = set()

    # Prefetch contract items for all pending placeholders
    pending_parts = {r.split('***',1)[1] for r in candidate_repl if r.startswith('PENDING***') and '***' in r}
    pending_ci_map = {}
    if pending_parts:
        for ci in ContractItem.query.filter(ContractItem.mfg_part_num.in_(pending_parts)).all():
            pending_ci_map.setdefault(ci.mfg_part_num, ci)

    ts_now = now_ny_naive()

    for src in candidate_src:
        src_item = items_map[src]
        for repl in candidate_repl:
            raw_replacement = repl
            if src == raw_replacement:
                skipped.append([src, raw_replacement])
                continue
            if (src, raw_replacement) in existing_pairs:
                skipped.append([src, raw_replacement])
                continue

            normalized_replace = None if raw_replacement in SENTINEL_REPLACEMENTS else raw_replacement

            assignment = planner.plan_group(src, normalized_replace)

            # Validate batch-level side consistency and historical constraints
            register_batch_side(src, assignment.group_id, 'O')
            ItemGroup.ensure_allowed_side(assignment.group_id, src, 'O', session=db.session)
            if normalized_replace:
                register_batch_side(normalized_replace, assignment.group_id, 'R')
                ItemGroup.ensure_allowed_side(assignment.group_id, normalized_replace, 'R', session=db.session)

            graph = planner.graph_for(assignment)
            conflicts = graph.conflicts_for(src, normalized_replace)
            if conflicts:
                for conflict in conflicts:
                    # Ensure any triggering links have PKIDs before logging the conflict
                    links_to_flush = [
                        link for link in conflict.triggering_links if link is not None and link.pkid is None
                    ]
                    if links_to_flush:
                        db.session.flush(links_to_flush)

                    conflict_entries.extend(
                        ConflictError.log(
                            item_group=assignment.group_id,
                            item=src,
                            replace_item=normalized_replace,
                            error_type=conflict.error_type,
                            error_message=conflict.message,
                            triggering_links=conflict.triggering_links,
                            session=db.session,
                        )
                    )

                    conflict_reports.append(
                        {
                            "item": src,
                            "replace_item": normalized_replace,
                            "error_type": conflict.error_type,
                            "message": conflict.message,
                            "triggering_item_link_ids": [
                                link.pkid for link in conflict.triggering_links if link is not None and link.pkid is not None
                            ],
                        }
                    )

                skipped.append([src, raw_replacement])
                continue

            link_stage = stage
            repl_value_for_model = normalized_replace
            repl_mfg_part = None
            repl_manufacturer = None
            repl_desc = None

            if raw_replacement in SENTINEL_REPLACEMENTS:
                # Sentinel means intentionally no replacement item number; neutralize replacement metadata
                link_stage = 'Tracking - Discontinued'
                repl_value_for_model = None
            elif raw_replacement and raw_replacement.startswith('PENDING***'):
                part_num = raw_replacement.split('***',1)[1] if '***' in raw_replacement else None
                link_stage = 'Pending Item Number'
                ci = pending_ci_map.get(part_num)
                if ci:
                    repl_mfg_part = ci.mfg_part_num
                    repl_manufacturer = ci.manufacturer
                    repl_desc = ci.item_description or 'Pending replacement item description'
                else:
                    repl_mfg_part = part_num
                    repl_manufacturer = '(Pending)'
                    repl_desc = 'Pending replacement item'
            elif repl_value_for_model:
                repl_item = items_map[repl_value_for_model]
                repl_mfg_part = repl_item.mfg_part_num
                repl_manufacturer = repl_item.manufacturer
                repl_desc = repl_item.item_description

            link = ItemLink(
                item_group=assignment.group_id,
                item=src,
                replace_item=repl_value_for_model,
                mfg_part_num=src_item.mfg_part_num,
                manufacturer=src_item.manufacturer,
                item_description=src_item.item_description,
                stage=link_stage,
                expected_go_live_date=validated_date,
                wrike_id=validated_wrike_id,
                create_dt=ts_now,
                update_dt=ts_now,
                repl_mfg_part_num=repl_mfg_part,
                repl_manufacturer=repl_manufacturer,
                repl_item_description=repl_desc,
            )
            db.session.add(link)
            planner.register_success(assignment, link)
            created += 1
            created_records.append(link)
            
            # If this is a 'Pending Item Number' stage, queue PendingItems creation
            if (
                link_stage == 'Pending Item Number'
                and repl_value_for_model
                and repl_value_for_model.startswith('PENDING***')
            ):
                meta = pending_meta.get(repl_value_for_model) or {}
                contract_id_meta = meta.get('contract_id')
                mfg_part_meta = meta.get('mfg_part_num') or repl_value_for_model.split('***',1)[1]
                if contract_id_meta and mfg_part_meta:
                    pending_items_to_create.append((link, contract_id_meta, mfg_part_meta))

    pending_merges = planner.consume_pending_merges()

    # Apply any required merges at the database level
    merged_groups: list[int] = []
    for canonical, groups_to_merge in pending_merges.items():
        groups = sorted(g for g in groups_to_merge if g != canonical)
        if not groups:
            continue
        (
            ItemLink.query.filter(ItemLink.item_group.in_(groups))
            .update({ItemLink.item_group: canonical}, synchronize_session=False)
        )
        (
            ItemGroup.query.filter(ItemGroup.item_group.in_(groups))
            .update({ItemGroup.item_group: canonical, ItemGroup.update_dt: now_ny_naive()}, synchronize_session=False)
        )
        merged_groups.extend(groups)

    should_commit = bool(created_records or conflict_entries or merged_groups)

    if created_records or merged_groups:
        # Flush to assign PKIDs to ItemLink records before creating PendingItems
        db.session.flush()

        try:
            for link in created_records:
                ItemGroup.sync_from_item_link(link, session=db.session)
        except ItemGroupConflictError as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 400
        
        # Create PendingItems for links with 'Pending Item Number' stage
        for link, contract_id_meta, mfg_part_meta in pending_items_to_create:
            pending_item = PendingItems.create_from_contract_item(
                item_link_id=link.pkid,
                contract_id=contract_id_meta,
                mfg_part_num=mfg_part_meta
            )
            db.session.add(pending_item)

    if should_commit:
        db.session.commit()

    # Build created record details for client display
    records = []
    if created_records:
        for r in created_records:
            records.append({
                "item_group": r.item_group,
                "item": r.item,
                "replace_item": r.replace_item,
                "mfg_part_num": r.mfg_part_num,
                "manufacturer": r.manufacturer,
                "item_description": r.item_description,
                "repl_mfg_part_num": r.repl_mfg_part_num,
                "repl_manufacturer": r.repl_manufacturer,
                "repl_item_description": r.repl_item_description,
                "stage": r.stage,
                "expected_go_live_date": r.expected_go_live_date.isoformat() if r.expected_go_live_date else None,
                "wrike_id": r.wrike_id,
                "create_dt": r.create_dt.isoformat() if r.create_dt else None,
                "update_dt": r.update_dt.isoformat() if r.update_dt else None,
            })

    return jsonify({
        "group_id": created_records[0].item_group if created_records else None,
        "created": created,
        "skipped": skipped,
        "conflicts": conflict_reports,
        "stage": stage,
        "stage_locked": locked,
        "merged_groups": sorted(set(merged_groups)),
        "records": records,
    }), 201


# -------------------- API: Delete single item link --------------------
@bp.delete('/api/item-links/<item>/<replace_item>')
@login_required
def api_delete_item_link(item: str, replace_item: str):
    # Normalize textual null markers coming from client URLs to None so
    # we can delete rows where replace_item IS NULL.
    if isinstance(replace_item, str) and replace_item.lower() in ('none', 'null', 'nan', ''):
        replace_item = None
    record = ItemLink.query.filter_by(item=item, replace_item=replace_item).first()
    if not record:
        return jsonify({"error": "Not found"}), 404
    db.session.delete(record)
    db.session.commit()
    return jsonify({"status": "deleted", "item": item, "replace_item": replace_item})
