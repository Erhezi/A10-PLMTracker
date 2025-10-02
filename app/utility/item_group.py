from __future__ import annotations
from typing import List, Dict, Optional, Set, Tuple, Iterable
import re
from datetime import date, datetime
from calendar import monthrange
from dataclasses import dataclass
from collections import defaultdict

from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import aliased

from .. import db
from ..models.relations import ItemLink  # new consolidated view
from ..models.inventory import Item
from .node_check import RelationGraph


class BatchValidationError(Exception):
    """Exception raised for batch validation errors."""
    def __init__(self, message: str, error_code: str = None):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)


@dataclass(frozen=True)
class GroupAssignment:
    """Result describing the group mapping for a proposed link."""

    group_id: int
    relevant_groups: frozenset[int]

    @property
    def groups_to_merge(self) -> Set[int]:
        return set(self.relevant_groups) - {self.group_id}


class BatchGroupPlanner:
    """In-memory coordinator for assigning Item Group ids within a batch."""

    def __init__(self, existing_links: Iterable[ItemLink], *, next_group_id: int):
        self._next_group_id = max(next_group_id, 1)
        self._item_to_groups: Dict[str, Set[int]] = defaultdict(set)
        self._group_to_items: Dict[int, Set[str]] = defaultdict(set)
        self._group_links: Dict[int, List[ItemLink]] = defaultdict(list)
        self._group_graphs: Dict[int, RelationGraph] = {}
        self._pending_merges: Dict[int, Set[int]] = defaultdict(set)

        for link in existing_links:
            if link.item_group is None:
                continue
            self._ingest_existing_link(link)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def plan_group(self, item: str, replacement: Optional[str]) -> GroupAssignment:
        """Return the canonical group mapping for a prospective link."""

        candidate_groups = set(self._item_to_groups.get(item, set()))
        if replacement:
            candidate_groups.update(self._item_to_groups.get(replacement, set()))

        if not candidate_groups:
            group_id = self._allocate_new_group()
            return GroupAssignment(group_id=group_id, relevant_groups=frozenset({group_id}))

        group_id = min(candidate_groups)
        return GroupAssignment(group_id=group_id, relevant_groups=frozenset(candidate_groups))

    def graph_for(self, assignment: GroupAssignment) -> RelationGraph:
        """Provide a relation graph covering all relevant groups for conflict checks."""

        groups = assignment.relevant_groups
        if len(groups) == 1:
            group = assignment.group_id
            return self._group_graphs.get(group, RelationGraph())

        graph = RelationGraph()
        for group in groups:
            for link in self._group_links.get(group, []):
                graph.register_link(link)
        return graph

    def register_success(self, assignment: GroupAssignment, link: ItemLink) -> None:
        """Update planner state after successfully creating a link."""

        group_id = assignment.group_id
        self._group_links[group_id].append(link)
        graph = self._group_graphs.get(group_id)
        if graph is None:
            graph = RelationGraph()
            self._group_graphs[group_id] = graph
        graph.register_link(link)

        self._register_code(group_id, link.item)
        if link.replace_item:
            self._register_code(group_id, link.replace_item)

        if assignment.groups_to_merge:
            self._merge_into(group_id, assignment.groups_to_merge)

    def consume_pending_merges(self) -> Dict[int, Set[int]]:
        """Return and clear pending merge directives for persistence."""

        merges = {canonical: set(groups) for canonical, groups in self._pending_merges.items() if groups}
        self._pending_merges.clear()
        return merges

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _allocate_new_group(self) -> int:
        group_id = self._next_group_id
        self._next_group_id += 1
        # Ensure basic containers exist for the new group
        self._group_links.setdefault(group_id, [])
        self._group_graphs.setdefault(group_id, RelationGraph())
        return group_id

    def _register_code(self, group_id: int, code: Optional[str]) -> None:
        if not code:
            return
        self._group_to_items[group_id].add(code)
        self._item_to_groups[code].add(group_id)

    def _ingest_existing_link(self, link: ItemLink) -> None:
        group = link.item_group
        self._group_links[group].append(link)
        self._register_code(group, link.item)
        if link.replace_item:
            self._register_code(group, link.replace_item)

        graph = self._group_graphs.get(group)
        if graph is None:
            graph = RelationGraph()
            self._group_graphs[group] = graph
        graph.register_link(link)

    def _merge_into(self, canonical: int, to_merge: Set[int]) -> None:
        for group in sorted(to_merge):
            if group == canonical:
                continue
            # Update item-to-group mappings
            for code in self._group_to_items.get(group, set()):
                groups = self._item_to_groups.get(code)
                if groups and group in groups:
                    groups.remove(group)
                    groups.add(canonical)
                self._group_to_items[canonical].add(code)
            self._group_to_items.pop(group, None)

            # Move existing links and rebuild canonical graph
            links = self._group_links.pop(group, [])
            if links:
                self._group_links[canonical].extend(links)
            old_graph = self._group_graphs.pop(group, None)
            if old_graph is not None:
                # Rebuild canonical graph to avoid duplicate edges
                new_graph = RelationGraph()
                for link in self._group_links[canonical]:
                    new_graph.register_link(link)
                self._group_graphs[canonical] = new_graph

            self._pending_merges[canonical].add(group)


def dedupe_preserve_order(seq: List[str]) -> List[str]:
    """Deduplicate sequence while preserving original order."""
    seen = set()
    out = []
    for s in seq:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def validate_batch_inputs(
    items: List[str], 
    replace_items: List[str], 
    wrike_id: str = None,
    expected_go_live_date_raw: str = None,
    sentinel_replacements: Set[str] = None,
    max_per_side: int = None
) -> Tuple[List[str], List[str], str, date]:
    """
    Validate and normalize batch input data.
    
    Args:
        items: List of source item codes
        replace_items: List of replacement item codes  
        wrike_id: Optional Wrike task ID (must be 10 digits)
        expected_go_live_date_raw: Optional date string (YYYY-MM-DD)
        sentinel_replacements: Set of sentinel replacement values (default: {"NO REPLACEMENT"})
        max_per_side: Maximum items allowed per side (default: from config)
    
    Returns:
        Tuple of (normalized_items, normalized_replace_items, validated_wrike_id, validated_date)
        
    Raises:
        BatchValidationError: If validation fails
    """
    if sentinel_replacements is None:
        sentinel_replacements = {"NO REPLACEMENT"}
    
    if max_per_side is None:
        from ..config import Config
        max_per_side = Config.MAX_BATCH_PER_SIDE
    
    # Basic validation
    if not items or not replace_items:
        raise BatchValidationError("Both items and replace_items required")
    
    # Disallow sentinel (NO REPLACEMENT) or dynamic pending placeholder on left side
    if any(c in sentinel_replacements or str(c).startswith("PENDING***") for c in items):
        raise BatchValidationError("Placeholder / sentinel values only allowed as replacement items")
    
    # Deduplicate while preserving original order
    items = dedupe_preserve_order([str(s).strip() for s in items if s and str(s).strip()])
    replace_items = dedupe_preserve_order([str(s).strip() for s in replace_items if s and str(s).strip()])
    
    # Limit per side instead of total combinations
    if len(items) > max_per_side:
        raise BatchValidationError(f"Too many source items (max {max_per_side})")
    if len(replace_items) > max_per_side:
        raise BatchValidationError(f"Too many replacement items (max {max_per_side})")
    
    # Validate wrike id (optional, must be 10 digits if provided)
    validated_wrike_id = None
    if wrike_id:
        if not re.fullmatch(r"\d{10}", wrike_id):
            raise BatchValidationError("Wrike Task ID must be exactly 10 digits")
        validated_wrike_id = wrike_id
    
    # Parse and validate expected go live date (optional, within next 6 months)
    validated_date = None
    if expected_go_live_date_raw:
        def add_months(d: date, months: int) -> date:
            m = d.month - 1 + months
            y = d.year + m // 12
            m = m % 12 + 1
            day = min(d.day, monthrange(y, m)[1])
            return date(y, m, day)
        
        try:
            validated_date = datetime.strptime(expected_go_live_date_raw, "%Y-%m-%d").date()
        except ValueError:
            raise BatchValidationError("Invalid expected_go_live_date format; use YYYY-MM-DD")
        
        today = date.today()
        max_allowed = add_months(today, 6)
        min_allowed = add_months(today, -3)
        if validated_date < min_allowed:
            raise BatchValidationError("Expected Go Live Date cannot be more than 3 months in the past")
        if validated_date > max_allowed:
            raise BatchValidationError("Expected Go Live Date cannot be more than 6 months in the future")
    
    return items, replace_items, validated_wrike_id, validated_date


def _fetch_items_map(codes: set[str]) -> dict[str, Item]:
    """Fetch items from database by codes."""
    if not codes:
        return {}
    rows = Item.query.filter(Item.item.in_(codes)).all()
    return {r.item: r for r in rows}


def validate_stage_and_items(
    items: List[str],
    replace_items: List[str],
    explicit_stage: str = None,
    allowed_stages: List[str] = None,
    sentinel_replacements: Set[str] = None
) -> Tuple[str, bool, Dict[str, Item], List[str]]:
    """
    Validate stage logic and lookup real items.
    
    Args:
        items: List of source item codes
        replace_items: List of replacement item codes
        explicit_stage: Explicitly requested stage
        allowed_stages: List of allowed stage values
        sentinel_replacements: Set of sentinel replacement values
    
    Returns:
        Tuple of (stage, locked, items_map, missing_items)
        
    Raises:
        BatchValidationError: If validation fails
    """
    if sentinel_replacements is None:
        sentinel_replacements = {"NO REPLACEMENT"}
    
    # Determine stage using existing logic
    stage, locked = _determine_stage(replace_items, explicit_stage, sentinel_replacements)
    
    if allowed_stages and stage not in allowed_stages:
        raise BatchValidationError("Invalid stage")
    
    if locked and explicit_stage and explicit_stage != stage:
        raise BatchValidationError("Stage override not allowed for this replacement type")
    
    # Lookup real items (exclude sentinel and dynamic pending placeholders)
    real_codes = set(items + [r for r in replace_items if (r not in sentinel_replacements and not r.startswith("PENDING***"))])
    items_map = _fetch_items_map(real_codes)
    missing = [c for c in real_codes if c not in items_map]
    
    if missing:
        raise BatchValidationError("Some items not found", "missing_items")
    
    return stage, locked, items_map, missing


def _determine_stage(replacements: List[str], explicit: str = None, sentinel_replacements: Set[str] = None) -> Tuple[str, bool]:
    """
    Return (default_stage, locked) for the *batch*.

    Dynamic pending placeholders (PENDING***<mfg_part>) are NOT treated as sentinel for locking; they will be
    assigned stage 'Pending Item Number' per-row later but do not lock others in the batch.

    Rules:
    - If only sentinel 'NO REPLACEMENT' => stage 'Tracking - Discontinued' (locked)
    - Else default 'Pending Clinical Approval' unless explicit provided.
    """
    if sentinel_replacements is None:
        sentinel_replacements = {"NO REPLACEMENT"}
    
    if len(replacements) == 1 and replacements[0] in sentinel_replacements:
        return 'Tracking - Discontinued', True
    if explicit:
        return explicit, False
    return 'Pending Clinical Approval', False