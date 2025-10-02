import pytest

from app.models.relations import ItemLink, ConflictError
from app.utility.node_check import (
    RelationGraph,
    register_link_in_graph,
    CONFLICT_CHAINING,
    CONFLICT_MANY_TO_MANY,
    CONFLICT_RECIPROCAL,
    CONFLICT_SELF_DIRECTED,
)


def _link(item: str, replace_item: str, pkid: int) -> ItemLink:
    link = ItemLink(item=item, replace_item=replace_item, item_group=1)
    link.pkid = pkid
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
