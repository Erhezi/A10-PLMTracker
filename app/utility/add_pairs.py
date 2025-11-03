from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple, Union

from sqlalchemy.orm import Session

from .. import db
from ..models import now_ny_naive
from ..models.inventory import ContractItem
from ..models.relations import (
    ConflictError,
    ItemGroup,
    ItemGroupConflictError,
    ItemLink,
    ItemLinkWrike,
    PendingItems,
    PENDING_PLACEHOLDER_PREFIX,
)
from ..models.log import BurnRateRefreshJob
from .item_group import (
    BatchGroupPlanner,
    validate_batch_inputs,
    validate_stage_and_items,
)
from .node_check import (
    CONFLICT_MANY_TO_MANY,
    CONFLICT_SELF_DIRECTED,
    CONFLICT_UNKNOWN,
    detect_many_to_many_conflict,
    is_active_link,
)
from .burn_rate_refresh import schedule_burn_rate_refresh


@dataclass(frozen=True)
class PairCandidate:
    item: str
    raw_replacement: Optional[str]
    normalized_replacement: Optional[str]
    addition_type: str  # "discontinue", "pending", "standard"
    item_index: int
    replacement_index: int

    def sort_key(self) -> Tuple[int, int, int]:
        order = {"discontinue": 0, "pending": 1, "standard": 2}
        return order[self.addition_type], self.item_index, self.replacement_index


class AddItemPairs:
    """Sequential processor for inserting ItemLink pairs with full validation."""

    def __init__(
        self,
        *,
        items: List[str],
        replace_items: List[str],
        pending_meta: Optional[Dict[str, Union[Dict[str, str], List[Dict[str, str]]]]] = None,
        explicit_stage: Optional[str] = None,
        expected_go_live_date_raw: Optional[str] = None,
        sentinel_replacements: Optional[Set[str]] = None,
        allowed_stages: Optional[List[str]] = None,
        max_per_side: Optional[int] = None,
        session: Optional[Session] = None,
    ) -> None:
        self.session: Session = session or db.session
        self.pending_meta = pending_meta or {}
        self.sentinel_replacements = sentinel_replacements or {"NO REPLACEMENT"}
        self.allowed_stages = allowed_stages or []
        self.max_per_side = max_per_side

        # Output collections
        self.created_links: List[ItemLink] = []
        self.reused_links: List[ItemLink] = []
        self._touched_links: List[ItemLink] = []
        self.conflict_reports: List[Dict[str, object]] = []
        self.conflict_entries: List[ConflictError] = []
        self.skipped_pairs: List[Tuple[str, Optional[str]]] = []
        self.skipped_details: List[Dict[str, object]] = []
        self.pending_items_to_create: List[Tuple[ItemLink, str, str]] = []
        self.merged_groups: List[int] = []
        self.burn_rate_jobs: List[BurnRateRefreshJob] = []

        # Normalized inputs
        (
            self.items,
            self.replace_items,
            self.validated_date,
        ) = validate_batch_inputs(
            items=items,
            replace_items=replace_items,
            expected_go_live_date_raw=expected_go_live_date_raw,
            sentinel_replacements=self.sentinel_replacements,
            max_per_side=self.max_per_side,
        )

        (
            self.stage,
            self.stage_locked,
            self.items_map,
            _missing,
        ) = validate_stage_and_items(
            items=self.items,
            replace_items=self.replace_items,
            explicit_stage=explicit_stage,
            allowed_stages=self.allowed_stages,
            sentinel_replacements=self.sentinel_replacements,
        )

        self.ts_now = now_ny_naive()

        # Batch helper state
        self.batch_side_tracker: Dict[Tuple[str, int], str] = {}
        self._existing_links: Dict[Tuple[str, Optional[str]], ItemLink] = self._fetch_existing_links()
        self._existing_pairs: Set[Tuple[str, Optional[str]]] = set(self._existing_links.keys())

        self.planner = self._build_planner()
        self.pending_ci_map = self._prefetch_contract_items()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def execute(self) -> Dict[str, object]:
        candidates = self._build_candidates()
        for candidate in candidates:
            self._process_candidate(candidate)

        pending_merges = self.planner.consume_pending_merges()
        self._apply_merges(pending_merges)

        for link in self._touched_links:
            ItemLinkWrike.ensure_for_link(link)

        should_flush = bool(self._touched_links or self.merged_groups)
        should_commit = bool(self.conflict_entries or should_flush)
        burn_rate_link_ids: List[int] = []

        if should_flush:
            self.session.flush()
            burn_rate_link_ids = [link.pkid for link in self._touched_links if link.pkid]
            if burn_rate_link_ids:
                self.burn_rate_jobs = [
                    BurnRateRefreshJob(item_link_id=int(pkid))
                    for pkid in burn_rate_link_ids
                ]
                self.session.add_all(self.burn_rate_jobs)
                self.session.flush()
            try:
                self._sync_item_groups()
            except ItemGroupConflictError:
                self.session.rollback()
                raise
            self._create_pending_items()

        if should_commit:
            self.session.commit()
            print("committed and start burn rate refresh")
            if burn_rate_link_ids:
                job_ids = [job.id for job in self.burn_rate_jobs if job.id]
                schedule_burn_rate_refresh(burn_rate_link_ids, job_ids=job_ids)

        created_total = len(self.created_links) + len(self.reused_links)
        return {
            "created": created_total,
            "reactivated": len(self.reused_links),
            "skipped": [[item, repl] for item, repl in self.skipped_pairs],
            "skipped_details": self.skipped_details,
            "conflicts": self.conflict_reports,
            "stage": self.stage,
            "stage_locked": self.stage_locked,
            "merged_groups": sorted(set(self.merged_groups)),
            "records": self._serialize_result_records(),
            "burn_rate_jobs": self._serialize_burn_rate_jobs(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _build_candidates(self) -> List[PairCandidate]:
        seen: Set[Tuple[str, Optional[str]]] = set()
        candidates: List[PairCandidate] = []
        for item_index, item in enumerate(self.items):
            for repl_index, raw_replacement in enumerate(self.replace_items):
                normalized = self._normalize_replacement(raw_replacement)
                key = (item, normalized)
                if key in seen:
                    continue
                seen.add(key)
                addition_type = self._determine_addition_type(raw_replacement, normalized)
                candidate = PairCandidate(
                    item=item,
                    raw_replacement=raw_replacement,
                    normalized_replacement=normalized,
                    addition_type=addition_type,
                    item_index=item_index,
                    replacement_index=repl_index,
                )
                candidates.append(candidate)
        candidates.sort(key=PairCandidate.sort_key)
        return candidates

    def _normalize_replacement(self, replacement: Optional[str]) -> Optional[str]:
        if replacement is None:
            return None
        replacement_str = str(replacement).strip()
        if not replacement_str:
            return None
        if replacement_str in self.sentinel_replacements:
            return None
        return replacement_str

    @staticmethod
    def _determine_addition_type(raw_replacement: Optional[str], normalized: Optional[str]) -> str:
        if normalized is None:
            return "discontinue"
        if raw_replacement and str(raw_replacement).startswith("PENDING***"):
            return "pending"
        return "standard"

    def _process_candidate(self, candidate: PairCandidate) -> None:
        item = candidate.item
        normalized_replace = candidate.normalized_replacement
        raw_replace = candidate.raw_replacement
        addition_type = candidate.addition_type

        if normalized_replace is not None and item == normalized_replace:
            assignment = self.planner.plan_group(item, normalized_replace)
            reason = f"Item {item} cannot reference itself as a replacement."
            self._log_conflict(
                group_id=assignment.group_id,
                item=item,
                replace_item=normalized_replace,
                error_type=CONFLICT_SELF_DIRECTED,
                message=reason,
                triggering_links=(),
            )
            self._record_skip(
                item=item,
                raw_replace=raw_replace,
                normalized_replace=normalized_replace,
                reason=reason,
                error_type=CONFLICT_SELF_DIRECTED,
                group_id=assignment.group_id,
            )
            return

        key = (item, normalized_replace)
        existing_link = self._existing_links.get(key)
        if existing_link:
            if addition_type == "discontinue":
                if (
                    existing_link.replace_item is None
                    and (existing_link.stage or "").strip().lower() == "tracking - discontinued".lower()
                ):
                    reason = (
                        f"Item {item} already has a discontinued record in group {existing_link.item_group}."
                    )
                    self._record_skip(
                        item=item,
                        raw_replace=raw_replace,
                        normalized_replace=normalized_replace,
                        reason=reason,
                        group_id=existing_link.item_group,
                    )
                    return
                success, failure_reason, failure_type = self._reactivate_existing_discontinue(
                    existing_link,
                    item,
                )
                if success:
                    return
                if failure_reason:
                    self._record_skip(
                        item=item,
                        raw_replace=raw_replace,
                        normalized_replace=normalized_replace,
                        reason=failure_reason,
                        error_type=failure_type or CONFLICT_UNKNOWN,
                        group_id=existing_link.item_group,
                    )
                    return
            display_target = normalized_replace or raw_replace or "NO REPLACEMENT"
            reason = (
                f"Link {item} -> {display_target} already exists in group {existing_link.item_group}."
            )
            self._record_skip(
                item=item,
                raw_replace=raw_replace,
                normalized_replace=normalized_replace,
                reason=reason,
                group_id=existing_link.item_group,
            )
            return

        assignment = self.planner.plan_group(item, normalized_replace)
        graph = self.planner.graph_for(assignment)

        try:
            self._register_side(item, assignment.group_id, addition_type)
            if normalized_replace:
                self._register_replacement_side(
                    normalized_replace,
                    assignment.group_id,
                    addition_type,
                )
        except ItemGroupConflictError as err:
            conflicts = self._detect_conflicts(graph, item, normalized_replace)
            if conflicts:
                messages: List[str] = []
                for conflict in conflicts:
                    messages.append(conflict.message)
                    self._log_conflict(
                        group_id=assignment.group_id,
                        item=item,
                        replace_item=normalized_replace,
                        error_type=conflict.error_type,
                        message=conflict.message,
                        triggering_links=conflict.triggering_links,
                    )
                primary_type = conflicts[0].error_type
                reason = "; ".join(messages)
            else:
                primary_type = CONFLICT_UNKNOWN
                reason = str(err)
                self._log_conflict(
                    group_id=assignment.group_id,
                    item=item,
                    replace_item=normalized_replace,
                    error_type=CONFLICT_UNKNOWN,
                    message=reason,
                    triggering_links=(),
                )
            self._record_skip(
                item=item,
                raw_replace=raw_replace,
                normalized_replace=normalized_replace,
                reason=reason,
                error_type=primary_type,
                group_id=assignment.group_id,
            )
            return

        conflicts = self._detect_conflicts(graph, item, normalized_replace)

        if conflicts:
            messages: List[str] = []
            for conflict in conflicts:
                messages.append(conflict.message)
                self._log_conflict(
                    group_id=assignment.group_id,
                    item=item,
                    replace_item=normalized_replace,
                    error_type=conflict.error_type,
                    message=conflict.message,
                    triggering_links=conflict.triggering_links,
                )
            reason = "; ".join(messages)
            self._record_skip(
                item=item,
                raw_replace=raw_replace,
                normalized_replace=normalized_replace,
                reason=reason,
                error_type=conflicts[0].error_type,
                group_id=assignment.group_id,
            )
            return

        link = self._build_item_link(
            item=item,
            normalized_replace=normalized_replace,
            raw_replace=raw_replace,
            addition_type=addition_type,
            group_id=assignment.group_id,
        )
        self.session.add(link)
        self.planner.register_success(assignment, link)
        self.created_links.append(link)
        self._touched_links.append(link)
        self._existing_pairs.add((item, normalized_replace))
        self._existing_links[(item, normalized_replace)] = link

    def _record_skip(
        self,
        *,
        item: str,
        raw_replace: Optional[str],
        normalized_replace: Optional[str],
        reason: str,
        error_type: str = CONFLICT_UNKNOWN,
        group_id: Optional[int] = None,
    ) -> None:
        self.skipped_pairs.append((item, raw_replace))
        display_replace = raw_replace if raw_replace not in (None, "") else normalized_replace
        self.skipped_details.append(
            {
                "item": item,
                "replace_item": display_replace,
                "raw_replace_item": raw_replace,
                "normalized_replace_item": normalized_replace,
                "reason": reason,
                "error_type": error_type,
                "item_group": group_id,
            }
        )

    def _detect_conflicts(
        self,
        graph,
        item: str,
        normalized_replace: Optional[str],
    ):
        conflicts = graph.conflicts_for(item, normalized_replace)
        if normalized_replace and not any(c.error_type == CONFLICT_MANY_TO_MANY for c in conflicts):
            fallback = detect_many_to_many_conflict(
                self.session,
                item=item,
                replace_item=normalized_replace,
                skip_item=item,
            )
            if fallback:
                conflicts.append(fallback)
        return conflicts

    def _reactivate_existing_discontinue(
        self,
        existing_link: ItemLink,
        item: str,
    ) -> tuple[bool, Optional[str], Optional[str]]:
        group_id = existing_link.item_group
        try:
            self._register_side(
                item,
                group_id,
                "discontinue",
                item_link_id=existing_link.pkid,
            )
        except ItemGroupConflictError as err:
            self._log_conflict(
                group_id=group_id,
                item=item,
                replace_item=None,
                error_type=CONFLICT_UNKNOWN,
                message=str(err),
                triggering_links=(),
            )
            return False, str(err), CONFLICT_UNKNOWN

        src_item = self.items_map[item]
        existing_link.stage = "Tracking - Discontinued"
        existing_link.expected_go_live_date = self.validated_date
        existing_link.update_dt = self.ts_now
        existing_link.replace_item = None
        existing_link.mfg_part_num = src_item.mfg_part_num
        existing_link.manufacturer = src_item.manufacturer
        existing_link.item_description = src_item.item_description
        existing_link.repl_mfg_part_num = None
        existing_link.repl_manufacturer = None
        existing_link.repl_item_description = None
        ItemLinkWrike.ensure_for_link(existing_link)

        self.session.add(existing_link)
        if existing_link not in self.reused_links:
            self.reused_links.append(existing_link)
        if existing_link not in self._touched_links:
            self._touched_links.append(existing_link)
        key = (existing_link.item, existing_link.replace_item)
        self._existing_links[key] = existing_link
        self._existing_pairs.add(key)
        return True, None, None

    def _register_side(
        self,
        item: str,
        group_id: int,
        addition_type: str,
        *,
        item_link_id: Optional[int] = None,
    ) -> None:
        desired_side = "D" if addition_type == "discontinue" else "O"
        self._track_batch_side(item, group_id, desired_side)
        ItemGroup.ensure_allowed_side(
            group_id,
            item,
            desired_side,
            session=self.session,
            item_link_id=item_link_id,
        )

    def _register_replacement_side(
        self,
        replacement: str,
        group_id: int,
        addition_type: str,
    ) -> None:
        desired_side = "R"
        if addition_type == "discontinue":
            raise ValueError("Discontinue addition should not register replacement side")
        if replacement.startswith(PENDING_PLACEHOLDER_PREFIX):
            return
        self._track_batch_side(replacement, group_id, desired_side)
        ItemGroup.ensure_allowed_side(
            group_id,
            replacement,
            desired_side,
            session=self.session,
        )

    def _track_batch_side(self, code: Optional[str], group_id: int, side: str) -> None:
        if not code:
            return
        key = (code, group_id)
        existing = self.batch_side_tracker.get(key)
        if existing and existing != side:
            raise ItemGroupConflictError(group_id, code, existing, side)
        self.batch_side_tracker[key] = side

    def _build_item_link(
        self,
        *,
        item: str,
        normalized_replace: Optional[str],
        raw_replace: Optional[str],
        addition_type: str,
        group_id: int,
    ) -> ItemLink:
        src_item = self.items_map[item]
        link_stage = self.stage
        repl_value_for_model = normalized_replace
        repl_mfg_part = None
        repl_manufacturer = None
        repl_desc = None
        pending_meta_entries: List[Dict[str, str]] = []
        primary_pending_meta: Dict[str, str] = {}

        if addition_type == "discontinue":
            link_stage = "Tracking - Discontinued"
            repl_value_for_model = None
        elif addition_type == "pending":
            link_stage = "Pending Item Number"
            pending_meta_entries = self._pending_meta_entries(normalized_replace or "")
            primary_pending_meta = pending_meta_entries[0] if pending_meta_entries else {}
            part = self._extract_pending_part(raw_replace)
            contract = self.pending_ci_map.get(part)
            repl_mfg_part = contract.mfg_part_num if contract else (primary_pending_meta.get("mfg_part_num") or part)
            repl_manufacturer = contract.manufacturer if contract else "(Pending)"
            repl_desc = (
                contract.item_description
                if contract and contract.item_description
                else primary_pending_meta.get("item_description")
                or "Pending replacement item"
            )
            if not repl_mfg_part:
                repl_mfg_part = self._extract_pending_part(normalized_replace)
        else:
            repl_item = self.items_map.get(normalized_replace)
            if repl_item:
                repl_mfg_part = repl_item.mfg_part_num
                repl_manufacturer = repl_item.manufacturer
                repl_desc = repl_item.item_description

        link = ItemLink(
            item_group=group_id,
            item=item,
            replace_item=repl_value_for_model,
            mfg_part_num=src_item.mfg_part_num,
            manufacturer=src_item.manufacturer,
            item_description=src_item.item_description,
            stage=link_stage,
            expected_go_live_date=self.validated_date,
            create_dt=self.ts_now,
            update_dt=self.ts_now,
            repl_mfg_part_num=repl_mfg_part,
            repl_manufacturer=repl_manufacturer,
            repl_item_description=repl_desc,
        )

        link.wrike = ItemLinkWrike.from_item_link(link)

        if addition_type == "pending" and repl_value_for_model:
            entries = pending_meta_entries or ([primary_pending_meta] if primary_pending_meta else [])
            fallback_part = primary_pending_meta.get("mfg_part_num") or self._extract_pending_part(repl_value_for_model)
            seen_pairs: Set[Tuple[str, str]] = set()
            for entry in entries:
                contract_id_raw = entry.get("contract_id")
                contract_id = str(contract_id_raw).strip() if contract_id_raw else ""
                part_raw = entry.get("mfg_part_num") or fallback_part
                mfg_part = str(part_raw).strip() if part_raw else ""
                if not contract_id or not mfg_part:
                    continue
                pair_key = (contract_id, mfg_part)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                self.pending_items_to_create.append((link, contract_id, mfg_part))

        return link

    def _pending_meta_entries(self, placeholder: Optional[str]) -> List[Dict[str, str]]:
        if not placeholder:
            return []
        raw_meta = self.pending_meta.get(placeholder)
        if raw_meta is None:
            return []
        if isinstance(raw_meta, dict):
            if "entries" in raw_meta and isinstance(raw_meta["entries"], list):
                return [dict(entry) for entry in raw_meta["entries"] if isinstance(entry, dict)]
            return [dict(raw_meta)]
        if isinstance(raw_meta, list):
            return [dict(entry) for entry in raw_meta if isinstance(entry, dict)]
        return []

    def _log_conflict(
        self,
        *,
        group_id: int,
        item: str,
        replace_item: Optional[str],
        error_type: str,
        message: str,
        triggering_links: Iterable[Optional[ItemLink]]
    ) -> None:
        links_to_flush = [link for link in triggering_links if link is not None and link.pkid is None]
        if links_to_flush:
            self.session.flush(links_to_flush)

        records = ConflictError.log(
            item_group=group_id,
            item=item,
            replace_item=replace_item,
            error_type=error_type,
            error_message=message,
            triggering_links=triggering_links,
            session=self.session,
        )
        self.conflict_entries.extend(records)
        self.conflict_reports.append(
            {
                "item_group": group_id,
                "item": item,
                "replace_item": replace_item,
                "error_type": error_type,
                "message": message,
                "triggering_item_link_ids": [
                    link.pkid
                    for link in triggering_links
                    if link is not None and link.pkid is not None
                ],
            }
        )

    def _sync_item_groups(self) -> None:
        for link in self._touched_links:
            ItemGroup.sync_from_item_link(link, session=self.session)

    def _create_pending_items(self) -> None:
        if not self.pending_items_to_create:
            return
        seen: Set[Tuple[int, str, str]] = set()
        for link, contract_id, mfg_part in self.pending_items_to_create:
            link_id = link.pkid
            if not link_id:
                continue
            key = (int(link_id), contract_id, mfg_part)
            if key in seen:
                continue
            seen.add(key)
            placeholder = f"PENDING***{mfg_part}"
            exists = (
                self.session.query(PendingItems.pkid)
                .filter(
                    PendingItems.item_link_id == link_id,
                    PendingItems.contract_id == contract_id,
                    PendingItems.replace_item_pending == placeholder,
                )
                .first()
            )
            if exists:
                continue
            pending = PendingItems.create_from_contract_item(
                item_link_id=int(link_id),
                contract_id=contract_id,
                mfg_part_num=mfg_part,
            )
            self.session.add(pending)

    def _apply_merges(self, pending_merges: Dict[int, Set[int]]) -> None:
        for canonical, groups in pending_merges.items():
            merge_targets = sorted(g for g in groups if g != canonical)
            if not merge_targets:
                continue
            (
                self.session.query(ItemLink)
                .filter(ItemLink.item_group.in_(merge_targets))
                .update({ItemLink.item_group: canonical}, synchronize_session=False)
            )
            (
                self.session.query(ItemGroup)
                .filter(ItemGroup.item_group.in_(merge_targets))
                .update(
                    {
                        ItemGroup.item_group: canonical,
                        ItemGroup.update_dt: now_ny_naive(),
                    },
                    synchronize_session=False,
                )
            )
            self.merged_groups.extend(merge_targets)

    def _serialize_result_records(self) -> List[Dict[str, object]]:
        records: List[Dict[str, object]] = []
        for link in self._touched_links:
            records.append(
                {
                    "item_group": link.item_group,
                    "item": link.item,
                    "replace_item": link.replace_item,
                    "mfg_part_num": link.mfg_part_num,
                    "manufacturer": link.manufacturer,
                    "item_description": link.item_description,
                    "repl_mfg_part_num": link.repl_mfg_part_num,
                    "repl_manufacturer": link.repl_manufacturer,
                    "repl_item_description": link.repl_item_description,
                    "stage": link.stage,
                    "expected_go_live_date": link.expected_go_live_date.isoformat() if link.expected_go_live_date else None,
                    "wrike_id1": link.wrike.wrike_id1 if link.wrike else None,
                    "wrike_id2": link.wrike.wrike_id2 if link.wrike else None,
                    "wrike_id3": link.wrike.wrike_id3 if link.wrike else None,
                    "create_dt": link.create_dt.isoformat() if link.create_dt else None,
                    "update_dt": link.update_dt.isoformat() if link.update_dt else None,
                }
            )
        return records

    def _serialize_burn_rate_jobs(self) -> List[Dict[str, object]]:
        jobs: List[Dict[str, object]] = []
        for job in self.burn_rate_jobs:
            jobs.append(
                {
                    "job_id": job.id,
                    "item_link_id": job.item_link_id,
                    "status": job.status,
                }
            )
        return jobs

    def _fetch_existing_links(self) -> Dict[Tuple[str, Optional[str]], ItemLink]:
        rows = (
            self.session.query(ItemLink)
            .filter(ItemLink.item.in_(self.items))
            .all()
        )
        existing: Dict[Tuple[str, Optional[str]], ItemLink] = {}
        for link in rows:
            if not is_active_link(link):
                continue
            key = (link.item, link.replace_item)
            existing[key] = link
        return existing

    def _build_planner(self) -> BatchGroupPlanner:
        max_group_value = (
            self.session.query(ItemLink.item_group)
            .order_by(ItemLink.item_group.desc())
            .limit(1)
            .scalar()
            or 0
        )

        real_codes = set(self.items)
        for repl in self.replace_items:
            normalized = self._normalize_replacement(repl)
            if normalized and not normalized.startswith("PENDING***"):
                real_codes.add(normalized)

        existing_links: List[ItemLink] = []
        if real_codes:
            group_rows = (
                self.session.query(ItemLink.item_group)
                .filter(
                    (ItemLink.item.in_(real_codes))
                    | (ItemLink.replace_item.in_(real_codes))
                )
                .distinct()
                .all()
            )
            group_ids = [row[0] for row in group_rows if row[0] is not None]
            if group_ids:
                existing_links = (
                    ItemLink.query
                    .filter(ItemLink.item_group.in_(group_ids))
                    .all()
                )
        existing_links = [link for link in existing_links if is_active_link(link)]

        return BatchGroupPlanner(existing_links, next_group_id=max_group_value + 1)

    def _prefetch_contract_items(self) -> Dict[str, ContractItem]:
        parts = {
            self._extract_pending_part(repl)
            for repl in self.replace_items
            if repl and repl.startswith("PENDING***")
        }
        parts = {p for p in parts if p}
        if not parts:
            return {}
        rows = (
            ContractItem.query
            .filter(ContractItem.mfg_part_num.in_(parts))
            .all()
        )
        return {row.mfg_part_num: row for row in rows}

    @staticmethod
    def _extract_pending_part(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        if "***" not in value:
            return value
        return value.split("***", 1)[1] or None
