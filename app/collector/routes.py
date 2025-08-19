from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_login import login_required
from sqlalchemy import func, or_
from .. import db
from ..models.relations import ItemLink
from ..models.inventory import Item

ALLOWED_STAGES = [
    'Discontinued',
    'Pending Item Number Assigned',
    'Pending OR Approval',
    'Transition Tracking',
    'Delete',
    'Tracking Completed'
]

SENTINEL_REPLACEMENTS = {"PENDING", "NO REPLACEMENT"}

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
    max_date = add_months(today, 6)
    return render_template(
        "collector/collect.html",
        allowed_stages=ALLOWED_STAGES,
        sample_items=sample_items,
        date_min=today.isoformat(),
        date_max=max_date.isoformat(),
    )

@bp.route("/groups")
@login_required
def groups():
    items = ItemLink.query.order_by(ItemLink.item_group, ItemLink.item).all()
    count_deleted = ItemLink.query.filter(ItemLink.stage == 'Delete').count()
    return render_template("collector/groups.html", items=items, allowed_stages=ALLOWED_STAGES, count_deleted=count_deleted)

@bp.post('/groups/clear-deleted')
@login_required
def clear_deleted():
    # Delete only rows whose stage is exactly 'Delete'
    q = ItemLink.query.filter(ItemLink.stage == 'Delete')
    count = q.count()
    if count == 0:
        flash('No rows with stage Delete to remove', 'info')
        return redirect(url_for('collector.groups'))
    q.delete(synchronize_session=False)
    db.session.commit()
    flash(f'Removed {count} deleted item link(s)', 'success')
    return redirect(url_for('collector.groups'))


@bp.route("/groups/<item>/<replace_item>/update", methods=["POST"])
@login_required
def update_item(item: str, replace_item: str):
    record = ItemLink.query.filter_by(item=item, replace_item=replace_item).first_or_404()
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
    #  - If current stage is Discontinued, only allow Delete or Tracking Completed
    #  - If current stage is not Discontinued, disallow moving into Discontinued directly
    current_stage = record.stage or ''
    if current_stage == 'Discontinued':
        if stage not in ('Discontinued', 'Delete', 'Tracking Completed'):
            if wants_json:
                return jsonify({"status":"error","field":"stage","message":"Invalid transition from Discontinued"}), 400
            flash("Cannot transition from Discontinued to that stage (only Delete or Tracking Completed allowed)", "warning")
            return redirect(url_for("collector.groups"))
    else:
        if stage == 'Discontinued':
            if wants_json:
                return jsonify({"status":"error","field":"stage","message":"Cannot set stage to Discontinued here"}), 400
            flash("Cannot set stage to Discontinued here", "warning")
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
    from ..models import now_ny_naive
    record.update_dt = now_ny_naive()
    db.session.commit()
    if wants_json:
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
            }
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
        query = query.filter(Item.is_active.is_(True))

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
            "is_active": bool(it.is_active),
            "is_discontinued": bool(it.is_discontinued),
        }
        for it in items
    ])


# -------------------- Helpers --------------------
def _fetch_items_map(codes: set[str]) -> dict[str, Item]:
    if not codes:
        return {}
    rows = Item.query.filter(Item.item.in_(codes)).all()
    return {r.item: r for r in rows}


def _determine_stage(replacements: list[str], explicit: str | None) -> tuple[str, bool]:
    """Return (stage, locked) where locked means user cannot override later.

    Business rules provided:
      - If only sentinel 'PENDING' => stage 'Pending Item Number Assigned' (locked)
      - If only sentinel 'NO REPLACEMENT' => stage 'Discontinued' (locked)
      - Else default 'Pending OR Approval' (not locked) unless explicit provided.
      - If explicit provided and not locked and valid, take explicit.
    """
    if len(replacements) == 1 and replacements[0] == "PENDING":
        return "Pending Item Number Assigned", True
    if len(replacements) == 1 and replacements[0] == "NO REPLACEMENT":
        return "Discontinued", True
    # normal case
    if explicit and explicit in ALLOWED_STAGES:
        return explicit, False
    return "Pending OR Approval", False


def _resolve_group(all_codes: set[str]) -> tuple[int, list[int]]:
    """Determine canonical group id for a new batch touching item codes.

    Returns (canonical_group_id, merged_group_ids).
    merged_group_ids is list of group ids that were merged into canonical (excluding canonical itself).
    """
    if not all_codes:
        # create a new group anyway
        max_group = db.session.query(func.coalesce(func.max(ItemLink.item_group), 0)).scalar() or 0
        return max_group + 1, []

    existing = (
        ItemLink.query.filter(
            or_(
                ItemLink.item.in_(all_codes),
                ItemLink.replace_item.in_(all_codes),
            )
        ).all()
    )
    groups = {row.item_group for row in existing if row.item_group is not None}
    if not groups:
        max_group = db.session.query(func.coalesce(func.max(ItemLink.item_group), 0)).scalar() or 0
        return max_group + 1, []
    canonical = min(groups)
    to_merge = sorted(g for g in groups if g != canonical)
    if to_merge:
        (
            ItemLink.query.filter(ItemLink.item_group.in_(to_merge))
            .update({ItemLink.item_group: canonical}, synchronize_session=False)
        )
    return canonical, to_merge


# -------------------- API: Batch create links --------------------
@bp.post("/api/item-links/batch")
@login_required
def api_batch_item_links():
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    replace_items = data.get("replace_items") or []
    explicit_stage = data.get("stage") or None
    expected_go_live_date_raw = (data.get("expected_go_live_date") or "").strip() or None
    wrike_id = (data.get("wrike_id") or "").strip() or None

    # Basic validation
    if not items or not replace_items:
        return jsonify({"error": "Both items and replace_items required"}), 400
    # Disallow sentinel on left side
    if any(c in SENTINEL_REPLACEMENTS for c in items):
        return jsonify({"error": "Sentinel values only allowed as replacement items"}), 400
    # Reject mixing sentinel + real replacements
    sentinel_in_repl = [c for c in replace_items if c in SENTINEL_REPLACEMENTS]
    if sentinel_in_repl and len(replace_items) > 1:
        return jsonify({"error": "Cannot mix sentinel replacement with real replacements"}), 400
    # Deduplicate while preserving original order
    def _dedupe(seq):
        seen = set()
        out = []
        for s in seq:
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out
    items = _dedupe([s.strip() for s in items if s and s.strip()])
    replace_items = _dedupe([s.strip() for s in replace_items if s and s.strip()])

    # Limit pairs (<=36)
    if len(items) * len(replace_items) > 36:
        return jsonify({"error": "Too many combinations (max 36)"}), 400

    # Validate wrike id (optional, must be 10 digits if provided)
    if wrike_id:
        import re
        if not re.fullmatch(r"\d{10}", wrike_id):
            return jsonify({"error": "Wrike Task ID must be exactly 10 digits"}), 400

    # Parse and validate expected go live date (optional, within next 6 months)
    expected_go_live_date = None
    if expected_go_live_date_raw:
        from datetime import date, datetime
        from calendar import monthrange
        def add_months(d: date, months: int) -> date:
            m = d.month - 1 + months
            y = d.year + m // 12
            m = m % 12 + 1
            day = min(d.day, monthrange(y, m)[1])
            return date(y, m, day)
        try:
            expected_go_live_date = datetime.strptime(expected_go_live_date_raw, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Invalid expected_go_live_date format; use YYYY-MM-DD"}), 400
        today = date.today()
        max_allowed = add_months(today, 6)
        if not (today <= expected_go_live_date <= max_allowed):
            return jsonify({"error": "Expected Go Live Date must be between today and 6 months from today"}), 400

    # Determine stage
    stage, locked = _determine_stage(replace_items, explicit_stage)
    if stage not in ALLOWED_STAGES:
        return jsonify({"error": "Invalid stage"}), 400
    if locked and explicit_stage and explicit_stage != stage:
        return jsonify({"error": "Stage override not allowed for this replacement type"}), 400

    # Lookup real items (exclude sentinel)
    real_codes = set(items + [r for r in replace_items if r not in SENTINEL_REPLACEMENTS])
    items_map = _fetch_items_map(real_codes)
    missing = [c for c in real_codes if c not in items_map]
    if missing:
        return jsonify({"error": "Some items not found", "missing": missing}), 400

    # Determine group id & merge groups
    canonical_group, merged = _resolve_group(real_codes | set(replace_items))

    created = 0
    skipped = []
    from ..models import now_ny_naive
    for src in items:
        src_item = items_map[src]
        for repl in replace_items:
            if src == repl:
                skipped.append([src, repl])
                continue
            exists = ItemLink.query.filter_by(item=src, replace_item=repl).first()
            if exists:
                skipped.append([src, repl])
                continue
            # Build new link
            link = ItemLink(
                item_group=canonical_group,
                item=src,
                replace_item=repl,
                mfg_part_num=src_item.mfg_part_num,
                manufacturer=src_item.manufacturer,
                item_description=src_item.item_description,
                stage=stage,
                expected_go_live_date=expected_go_live_date,
                wrike_id=wrike_id,
                create_dt=now_ny_naive(),
                update_dt=now_ny_naive(),
            )
            if repl in SENTINEL_REPLACEMENTS:
                if repl == "PENDING":
                    link.repl_manufacturer = "(Pending)"
                    link.repl_item_description = "Pending replacement item"
                else:  # NO REPLACEMENT
                    link.repl_manufacturer = "(N/A)"
                    link.repl_item_description = "No replacement planned"
                link.repl_mfg_part_num = None
            else:
                repl_item = items_map[repl]
                link.repl_mfg_part_num = repl_item.mfg_part_num
                link.repl_manufacturer = repl_item.manufacturer
                link.repl_item_description = repl_item.item_description
            db.session.add(link)
            created += 1

    if created:
        db.session.commit()
    else:
        # if only merges happened without new rows, still commit merges
        if merged:
            db.session.commit()

    # Build created record details for client display
    records = []
    if created:
        # Fetch just-created links (could filter by group & create_dt ~ now, simpler: query by group and items involved)
        # To avoid race conditions, filter by group and source items provided & replacement items provided
        fetched = (
            ItemLink.query.filter(
                ItemLink.item_group == canonical_group,
                ItemLink.item.in_(items),
                ItemLink.replace_item.in_(replace_items),
                ItemLink.stage == stage,
            ).all()
        )
        from datetime import datetime as _dt
        for r in fetched:
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
        "group_id": canonical_group,
        "created": created,
        "skipped": skipped,
        "stage": stage,
        "stage_locked": locked,
        "merged_groups": merged,
        "records": records,
    }), 201


# -------------------- API: Delete single item link --------------------
@bp.delete('/api/item-links/<item>/<replace_item>')
@login_required
def api_delete_item_link(item: str, replace_item: str):
    record = ItemLink.query.filter_by(item=item, replace_item=replace_item).first()
    if not record:
        return jsonify({"error": "Not found"}), 404
    db.session.delete(record)
    db.session.commit()
    return jsonify({"status": "deleted", "item": item, "replace_item": replace_item})
