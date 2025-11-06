from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, List, Optional, Set, Tuple

from flask import current_app
from sqlalchemy import text

from .. import db
from ..models.inventory import ItemLocations, PLMZDate
from ..models.log import BurnRateRefreshJob
from ..models.relations import ItemGroup, ItemLink

_THREAD_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="burn-rate")


def schedule_burn_rate_refresh(
    link_ids: Iterable[int | None],
    *,
    job_ids: Optional[Iterable[int | None]] = None,
) -> None:
    """Kick off background burn-rate calculations for the supplied ItemLink ids."""
    normalized_ids = _normalize_link_ids(link_ids)
    if not normalized_ids:
        return

    normalized_job_ids = _normalize_link_ids(job_ids or [])

    try:
        app = current_app._get_current_object()
    except RuntimeError:
        # No application context -> nothing to do.
        return

    if not _is_enabled(app):
        app.logger.debug(
            "Skipping burn rate refresh; feature disabled or unsupported backend.",
        )
        return

    app.logger.info(
        "Scheduling burn-rate refresh for ItemLink ids: %s (jobs: %s)",
        normalized_ids,
        normalized_job_ids if normalized_job_ids else "auto",
    )
    _THREAD_POOL.submit(
        _refresh_burn_rates,
        app,
        tuple(normalized_ids),
        tuple(normalized_job_ids),
    )


def _normalize_link_ids(link_ids: Iterable[int | None]) -> Tuple[int, ...]:
    cleaned: Set[int] = set()
    for raw in link_ids:
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        cleaned.add(value)
    return tuple(sorted(cleaned))


def _is_enabled(app) -> bool:
    if not app.config.get("ENABLE_BURN_RATE_REFRESH", True):
        return False
    engine = db.engine
    backend = engine.url.get_backend_name()
    return bool(backend and backend.startswith("mssql"))


def _refresh_burn_rates(app, link_ids: Tuple[int, ...], job_ids: Tuple[int, ...]) -> None:
    """Worker entry point executed inside the background thread."""
    if not link_ids:
        return

    app.logger.info(
        "[WORKER START] Burn-rate refresh worker starting for ItemLink ids: %s (jobs: %s)",
        link_ids,
        job_ids if job_ids else "auto",
    )

    with app.app_context():
        # Create a new session for this background thread
        session = db.session()
        try:
            jobs_to_mark = _select_jobs_for_update(session, link_ids, job_ids)
            for job in jobs_to_mark:
                job.mark_running()
            session.flush()

            item_pairs, group_pairs = _hydrate_pairs_from_plm_zdate(session, link_ids)

            if not item_pairs and not group_pairs:
                fallback_item_pairs, fallback_group_pairs = _hydrate_pairs_from_item_locations(session, link_ids)
                if fallback_item_pairs or fallback_group_pairs:
                    app.logger.info(
                        "PLMZDate returned no rows for ItemLink ids %s; using fallback hydration.",
                        link_ids,
                    )
                    item_pairs |= fallback_item_pairs
                    group_pairs |= fallback_group_pairs

            if not item_pairs and not group_pairs:
                app.logger.warning(
                    "Unable to determine burn-rate targets for ItemLink ids %s; skipping refresh.",
                    link_ids,
                )
                return

            summary = (
                f"{len(item_pairs)} item pairs, {len(group_pairs)} group pairs"
            )
            app.logger.info(
                "Refreshing burn rates for %s (ItemLink ids: %s)",
                summary,
                link_ids,
            )

            for inventory_id, pkid in sorted(item_pairs):
                session.execute(
                    text(
                        "EXEC [PLM].[sp_PLM_PersistItemBRRolling] "
                        "@Inventory_base_ID=:inventory_base_ID, @PKID=:pkid"
                    ),
                    {"inventory_base_ID": inventory_id, "pkid": pkid},
                )
                print(f"Executed sp_PLM_PersistItemBRRolling for Inventory_base_ID={inventory_id}, PKID={pkid}")

            for item_group, location in sorted(group_pairs):
                session.execute(
                    text(
                        "EXEC [PLM].[sp_PLM_PersistItemGroupBRRolling] "
                        "@ItemGroup=:item_group, @Location=:location"
                    ),
                    {"item_group": item_group, "location": location},
                )
                print(f"Executed sp_PLM_PersistItemGroupBRRolling for ItemGroup={item_group}, Location={location}")

            for job in jobs_to_mark:
                job.mark_success(message=summary)
            session.commit()
            app.logger.info(
                "[WORKER SUCCESS] Burn-rate refresh completed for ItemLink ids: %s",
                link_ids,
            )
        except Exception as exc:
            session.rollback()
            _mark_jobs_failure(app, link_ids, job_ids, str(exc))
            app.logger.exception(
                "Failed to refresh burn-rate for ItemLink ids: %s", link_ids,
            )
        finally:
            session.close()


def _select_jobs_for_update(session, link_ids: Tuple[int, ...], job_ids: Tuple[int, ...]) -> List[BurnRateRefreshJob]:
    if job_ids:
        return (
            session.query(BurnRateRefreshJob)
            .filter(BurnRateRefreshJob.id.in_(job_ids))
            .all()
        )
    if not link_ids:
        return []
    return (
        session.query(BurnRateRefreshJob)
        .filter(
            BurnRateRefreshJob.item_link_id.in_(link_ids),
            BurnRateRefreshJob.status.in_(["PENDING", "RUNNING"]),
        )
        .order_by(BurnRateRefreshJob.created_at.desc())
        .all()
    )


def _mark_jobs_failure(app, link_ids: Tuple[int, ...], job_ids: Tuple[int, ...], message: str) -> None:
    with app.app_context():
        # Create a new session for this background thread
        session = db.session()
        try:
            jobs_to_mark = _select_jobs_for_update(session, link_ids, job_ids)
            for job in jobs_to_mark:
                job.mark_failure(message)
            if jobs_to_mark:
                session.commit()
        finally:
            session.close()


def _hydrate_pairs_from_plm_zdate(session, link_ids: Tuple[int, ...]) -> Tuple[Set[Tuple[int, int]], Set[Tuple[int, str]]]:
    rows = (
        session.query(
            PLMZDate.Inventory_base_ID,
            PLMZDate.item_link_id,
            PLMZDate.item_group,
            PLMZDate.Location,
        )
        .filter(PLMZDate.item_link_id.in_(link_ids))
        .all()
    )

    item_pairs: Set[Tuple[int, int]] = {
        (int(row.Inventory_base_ID), int(row.item_link_id))
        for row in rows
        if row.Inventory_base_ID is not None and row.item_link_id is not None
    }
    group_pairs: Set[Tuple[int, str]] = {
        (int(row.item_group), row.Location.strip())
        for row in rows
        if row.item_group is not None and isinstance(row.Location, str) and row.Location.strip()
    }
    return item_pairs, group_pairs


def _hydrate_pairs_from_item_locations(session, link_ids: Tuple[int, ...]) -> Tuple[Set[Tuple[int, int]], Set[Tuple[int, str]]]:
    links: List[ItemLink] = (
        session.query(ItemLink)
        .filter(ItemLink.pkid.in_(link_ids))
        .all()
    )
    if not links:
        return set(), set()

    group_to_items: dict[int, Set[str]] = {}
    link_items: dict[int, Set[str]] = {}

    for link in links:
        if link.pkid is None:
            continue
        base_items: Set[str] = set()
        if link.item:
            base_items.add(link.item)
        if link.replace_item and not link.replace_item.startswith("PENDING***"):
            base_items.add(link.replace_item)
        link_items[int(link.pkid)] = base_items
        if link.item_group is not None:
            items = group_to_items.setdefault(int(link.item_group), set())
            items.update(base_items)

    if not group_to_items:
        return set(), set()

    extra_group_items = (
        session.query(ItemGroup.item_group, ItemGroup.item)
        .filter(ItemGroup.item_group.in_(group_to_items.keys()))
        .all()
    )
    for group_id, item in extra_group_items:
        if item and not item.startswith("PENDING***"):
            group_to_items.setdefault(int(group_id), set()).add(item)

    all_items = {item for items in group_to_items.values() for item in items}
    if not all_items:
        return set(), set()

    location_rows = (
        session.query(
            ItemLocations.Inventory_base_ID,
            ItemLocations.Location,
            ItemLocations.Item,
        )
        .filter(ItemLocations.Item.in_(all_items))
        .all()
    )

    item_pairs: Set[Tuple[int, int]] = set()
    group_pairs: Set[Tuple[int, str]] = set()

    for link in links:
        pkid = link.pkid
        if pkid is None:
            continue
        items_for_link = link_items.get(int(pkid), set())
        for row in location_rows:
            if row.Inventory_base_ID is None:
                continue
            if row.Item in items_for_link:
                item_pairs.add((int(row.Inventory_base_ID), int(pkid)))

    for group_id, items in group_to_items.items():
        for row in location_rows:
            if row.Location and row.Item in items:
                group_pairs.add((int(group_id), row.Location.strip()))

    return item_pairs, group_pairs
