from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import case
from sqlalchemy.orm import Session

from ..models.relations import ItemLink

CONFLICT_SELF_DIRECTED = "self-directed"
CONFLICT_RECIPROCAL = "reciprocal"
CONFLICT_CHAINING = "chaining"
CONFLICT_MANY_TO_MANY = "many-to-many"
CONFLICT_UNKNOWN = "Unknown"


@dataclass(frozen=True)
class ConflictResult:
	"""Represents a graph violation detected for a proposed ItemLink."""

	error_type: str
	message: str
	triggering_links: tuple[ItemLink, ...]

	def with_links(self, links: Iterable[ItemLink]) -> "ConflictResult":
		return ConflictResult(
			self.error_type,
			self.message,
			_dedupe_links((*self.triggering_links, *links)),
		)


def _dedupe_links(links: Iterable[ItemLink | None]) -> tuple[ItemLink, ...]:
	"""Deduplicate ItemLink objects while preserving insertion order."""

	seen: dict[int, ItemLink] = {}
	for link in links:
		if link is None:
			continue
		key = link.pkid if link.pkid is not None else id(link)
		if key not in seen:
			seen[key] = link
	return tuple(seen.values())


class RelationGraph:
	"""Directed graph helper over ItemLink rows for a specific item group."""

	def __init__(self) -> None:
		self._outgoing: dict[str, dict[str, ItemLink]] = {}
		self._incoming: dict[str, dict[str, ItemLink]] = {}
		self._direct: dict[tuple[str, str], ItemLink] = {}

	@classmethod
	def for_group(cls, session: Session, item_group: int) -> "RelationGraph":
		graph = cls()
		links: list[ItemLink] = (
			session.query(ItemLink)
			.filter(ItemLink.item_group == item_group)
			.all()
		)
		for link in links:
			graph._ingest(link)
		return graph

	def _ingest(self, link: ItemLink) -> None:
		if not link.replace_item:
			return
		self._outgoing.setdefault(link.item, {})[link.replace_item] = link
		self._incoming.setdefault(link.replace_item, {})[link.item] = link
		self._direct[link.item, link.replace_item] = link

	def register_link(self, link: ItemLink) -> None:
		"""Update the graph with a newly created ItemLink."""

		self._ingest(link)

	def conflicts_for(self, item: str, replace_item: Optional[str]) -> list[ConflictResult]:
		"""Return conflict reasons for a proposed relation."""

		results: list[ConflictResult] = []
		if not replace_item:
			return results

		# Self-directed relation
		if item == replace_item:
			results.append(
				ConflictResult(
					CONFLICT_SELF_DIRECTED,
					f"Item {item} cannot reference itself as a replacement.",
					tuple(),
				)
			)
			return results

		# Reciprocal relation (B already points to A)
		reciprocal = self._direct.get((replace_item, item))
		if reciprocal:
			results.append(
				ConflictResult(
					CONFLICT_RECIPROCAL,
					f"Reciprocal relation exists: {replace_item} -> {item}.",
					(reciprocal,),
				)
			)

		# Chaining detection from upstream and downstream paths
		chain_links: list[ItemLink] = []
		incoming = list(self._incoming.get(item, {}).values())
		outgoing = list(self._outgoing.get(replace_item, {}).values())
		if incoming:
			chain_links.extend(incoming)
		if outgoing:
			chain_links.extend(outgoing)
		if incoming or outgoing:
			upstream = ", ".join(sorted({link.item for link in incoming})) or "existing items"
			downstream = ", ".join(sorted({link.replace_item for link in outgoing})) or "existing replacements"
			message = (
				f"Adding {item} -> {replace_item} would create a chain"
				f" (upstream: {upstream}; downstream: {downstream})."
			)
			results.append(
				ConflictResult(
					CONFLICT_CHAINING,
					message,
					_dedupe_links(chain_links),
				)
			)

		# Detect longer cycles: search if replace_item reaches item through existing edges
		if not outgoing:
			if self._has_path(replace_item, item):
				message = (
					f"Adding {item} -> {replace_item} would close a cycle reaching back to {item}."
				)
				results.append(
					ConflictResult(CONFLICT_CHAINING, message, tuple())
				)

		# Many-to-many: existing outgoing from item and incoming to replace_item
		existing_outgoing = [
			link
			for dest, link in self._outgoing.get(item, {}).items()
			if dest != replace_item
		]
		existing_incoming = [
			link
			for src, link in self._incoming.get(replace_item, {}).items()
			if src != item
		]
		if existing_outgoing and existing_incoming:
			message = (
				f"Adding {item} -> {replace_item} would create a many-to-many relation"
				f" with existing links from {item} and to {replace_item}."
			)
			results.append(
				ConflictResult(
					CONFLICT_MANY_TO_MANY,
					message,
					_dedupe_links((*existing_outgoing, *existing_incoming)),
				)
			)

		return results

	def _has_path(self, start: str, target: str) -> bool:
		"""Breadth-first search to determine if ``target`` is reachable from ``start``."""

		visited: set[str] = set()
		queue: deque[str] = deque([start])
		while queue:
			current = queue.popleft()
			if current in visited:
				continue
			visited.add(current)
			for neighbour in self._outgoing.get(current, {}):
				if neighbour == target:
					return True
				queue.append(neighbour)
		return False


def detect_conflicts(
	session: Session,
	*,
	item_group: int,
	item: str,
	replace_item: Optional[str],
	graph: Optional[RelationGraph] = None,
) -> tuple[list[ConflictResult], RelationGraph]:
	"""Return detected conflicts for a proposed ItemLink."""

	relation_graph = graph or RelationGraph.for_group(session, item_group)
	conflicts = relation_graph.conflicts_for(item, replace_item)
	return conflicts, relation_graph


def register_link_in_graph(graph: RelationGraph, link: ItemLink) -> None:
	"""Helper to keep the relation graph in sync with freshly created links."""

	graph.register_link(link)


def detect_many_to_many_conflict(
	session: Session,
	*,
	item: str,
	replace_item: Optional[str],
	skip_item: Optional[str] = None,
	limit: int = 10,
) -> Optional[ConflictResult]:
	"""Return a many-to-many ConflictResult by inspecting existing ItemLink rows.

	This helper is useful when conflict detection needs to consider global state
	across groups beyond what an in-memory RelationGraph currently tracks.
	"""

	if not replace_item:
		return None

	def _order_recent(q):
		update_null_flag = case((ItemLink.update_dt.is_(None), 1), else_=0)
		create_null_flag = case((ItemLink.create_dt.is_(None), 1), else_=0)
		return q.order_by(
			update_null_flag,
			ItemLink.update_dt.desc(),
			create_null_flag,
			ItemLink.create_dt.desc(),
		)

	outgoing_links = (
		_order_recent(
			session.query(ItemLink)
			.filter(
				ItemLink.item == item,
				ItemLink.replace_item.isnot(None),
				ItemLink.replace_item != replace_item,
			)
		)
		.limit(limit)
		.all()
	)
	outgoing_links = [link for link in outgoing_links if link.replace_item and link.replace_item != replace_item]

	incoming_links = (
		_order_recent(
			session.query(ItemLink)
			.filter(
				ItemLink.replace_item == replace_item,
				ItemLink.item != (skip_item or item),
			)
		)
		.limit(limit)
		.all()
	)
	incoming_links = [link for link in incoming_links if link.item != (skip_item or item)]

	if not outgoing_links or not incoming_links:
		return None

	existing_replacements = ", ".join(sorted({link.replace_item for link in outgoing_links if link.replace_item}))
	existing_sources = ", ".join(sorted({link.item for link in incoming_links if link.item}))
	if not existing_replacements:
		existing_replacements = "other replacements"
	if not existing_sources:
		existing_sources = "other source items"

	message = (
		f"Item {item} already has replacement(s) {existing_replacements}; "
		f"replacement {replace_item} already belongs to {existing_sources}. "
		"Creating this link would form a many-to-many relation."
	)

	seen_links: dict[int, ItemLink] = {}
	for link in (*outgoing_links, *incoming_links):
		if link is None:
			continue
		key = link.pkid if link.pkid is not None else id(link)
		if key not in seen_links:
			seen_links[key] = link

	return ConflictResult(
		error_type=CONFLICT_MANY_TO_MANY,
		message=message,
		triggering_links=tuple(seen_links.values()),
	)