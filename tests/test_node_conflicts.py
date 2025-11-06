import pytest

from app.models.relations import ItemLink, ConflictError
from app.utility.node_check import (
    RelationGraph,
    register_link_in_graph,
    detect_many_to_many_conflict,
    CONFLICT_CHAINING,
    CONFLICT_MANY_TO_MANY,
    CONFLICT_RECIPROCAL,
    CONFLICT_SELF_DIRECTED,
)


def _link(item: str, replace_item: str, pkid: int, *, stage: str | None = None) -> ItemLink:
    link = ItemLink(item=item, replace_item=replace_item, item_group=1)
    link.pkid = pkid
    if stage is not None:
        link.stage = stage
    return link


def test_self_directed_conflict():
    graph = RelationGraph()
    conflicts = graph.conflicts_for("A", "A")
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.error_type == CONFLICT_SELF_DIRECTED
    assert conflict.triggering_links == tuple()


def test_reciprocal_conflict_includes_trigger():
    graph = RelationGraph()
    existing = _link("B", "A", 10)
    register_link_in_graph(graph, existing)

    conflicts = graph.conflicts_for("A", "B")
    types = {c.error_type for c in conflicts}
    assert CONFLICT_RECIPROCAL in types

    reciprocal_conflict = next(c for c in conflicts if c.error_type == CONFLICT_RECIPROCAL)
    assert [link.pkid for link in reciprocal_conflict.triggering_links] == [10]


def test_chaining_collects_upstream_and_downstream_links():
    graph = RelationGraph()
    upstream = _link("X", "A", 11)
    downstream = _link("B", "C", 12)
    register_link_in_graph(graph, upstream)
    register_link_in_graph(graph, downstream)

    conflicts = graph.conflicts_for("A", "B")
    types = {c.error_type for c in conflicts}
    assert CONFLICT_CHAINING in types

    chaining_conflict = next(c for c in conflicts if c.error_type == CONFLICT_CHAINING)
    ids = sorted(link.pkid for link in chaining_conflict.triggering_links)
    assert ids == [11, 12]


def test_many_to_many_conflict_reference_links():
    graph = RelationGraph()
    outgoing = _link("A", "X", 21)
    incoming = _link("Y", "B", 22)
    register_link_in_graph(graph, outgoing)
    register_link_in_graph(graph, incoming)

    conflicts = graph.conflicts_for("A", "B")
    types = {c.error_type for c in conflicts}
    assert CONFLICT_MANY_TO_MANY in types

    mm_conflict = next(c for c in conflicts if c.error_type == CONFLICT_MANY_TO_MANY)
    assert {link.pkid for link in mm_conflict.triggering_links} == {21, 22}


def test_many_to_many_conflict_detects_groupwide_violation():
    graph = RelationGraph()
    first = _link("A", "B", 31)
    second = _link("A", "C", 32)
    register_link_in_graph(graph, first)
    register_link_in_graph(graph, second)

    conflicts = graph.conflicts_for("D", "C")
    types = {c.error_type for c in conflicts}
    assert CONFLICT_MANY_TO_MANY in types

    mm_conflict = next(c for c in conflicts if c.error_type == CONFLICT_MANY_TO_MANY)
    assert {link.pkid for link in mm_conflict.triggering_links} == {31, 32}


def test_conflict_error_log_rejects_unknown_type():
    with pytest.raises(ValueError):
        ConflictError.log(
            item_group=1,
            item="A",
            replace_item="B",
            error_type="invalid",  # not one of the allowed types
            error_message="should fail",
            triggering_links=[],
        )


class _StubQuery:
    def __init__(self, rows):
        self._rows = rows
        self._limit = None

    def filter(self, *_, **__):
        return self

    def order_by(self, *_, **__):
        return self

    def limit(self, limit_value):
        self._limit = limit_value
        return self

    def all(self):
        if self._limit is None:
            return list(self._rows)
        return list(self._rows)[: self._limit]


class _StubSession:
    def __init__(self, result_batches):
        self._result_batches = list(result_batches)
        self._call_index = 0

    def query(self, model):  # noqa: ARG002 - model unused in stub
        rows = self._result_batches[self._call_index]
        self._call_index += 1
        return _StubQuery(rows)


def test_detect_many_to_many_conflict_with_global_state():
    outgoing = [_link("A", "X", 101)]
    incoming = [_link("C", "B", 202)]
    session = _StubSession([outgoing, incoming])

    conflict = detect_many_to_many_conflict(session, item="A", replace_item="B")

    assert conflict is not None
    assert conflict.error_type == CONFLICT_MANY_TO_MANY
    assert {link.pkid for link in conflict.triggering_links} == {101, 202}


def test_detect_many_to_many_conflict_respects_skip_item():
    outgoing = [_link("A", "X", 301)]
    incoming = [_link("A", "B", 302)]  # same source as proposed link
    session = _StubSession([outgoing, incoming])

    conflict = detect_many_to_many_conflict(
        session,
        item="A",
        replace_item="B",
        skip_item="A",
    )

    assert conflict is None


def test_detect_many_to_many_conflict_requires_both_sides():
    session = _StubSession([[], [_link("C", "B", 402)]])

    conflict = detect_many_to_many_conflict(session, item="A", replace_item="B")

    assert conflict is None


def test_relation_graph_ignores_inactive_stage_links():
    graph = RelationGraph()
    completed = _link("A", "X", 501, stage="Tracking Completed")
    incoming = _link("Y", "Z", 502)
    register_link_in_graph(graph, completed)
    register_link_in_graph(graph, incoming)

    conflicts = graph.conflicts_for("A", "Z")

    assert CONFLICT_MANY_TO_MANY not in {c.error_type for c in conflicts}


def test_detect_many_to_many_conflict_ignores_inactive_rows():
    outgoing = [_link("A", "X", 601, stage="Deleted")]
    incoming = [_link("C", "B", 602)]
    session = _StubSession([outgoing, incoming])

    conflict = detect_many_to_many_conflict(session, item="A", replace_item="B")

    assert conflict is None
