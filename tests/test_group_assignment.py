from app.utility.item_group import BatchGroupPlanner
from app.models.relations import ItemLink
from app.utility.node_check import CONFLICT_MANY_TO_MANY


def make_link(item: str, replace_item: str | None, group: int, pkid: int) -> ItemLink:
    link = ItemLink(item=item, replace_item=replace_item, item_group=group)
    link.pkid = pkid
    return link


def planner_with_sample_links():
    existing = [
        make_link("A", "B", 1, 1),
        make_link("C", "D", 2, 2),
        make_link("E", "F", 3, 3),
    ]
    return BatchGroupPlanner(existing_links=existing, next_group_id=4)


def test_planner_uses_existing_group_from_source():
    planner = planner_with_sample_links()

    assignment = planner.plan_group("A", "X")

    assert assignment.group_id == 1
    assert assignment.relevant_groups == frozenset({1})
    conflicts = planner.graph_for(assignment).conflicts_for("A", "X")
    assert conflicts == []


def test_planner_uses_existing_group_from_replacement():
    planner = planner_with_sample_links()

    assignment = planner.plan_group("Y", "F")

    assert assignment.group_id == 3
    assert assignment.relevant_groups == frozenset({3})


def test_planner_allocates_new_group_for_unseen_codes():
    planner = planner_with_sample_links()

    first = planner.plan_group("J", "K")
    second = planner.plan_group("L", "M")

    assert first.group_id == 4
    assert second.group_id == 5


def test_planner_detects_many_to_many_conflict():
    planner = planner_with_sample_links()

    assignment = planner.plan_group("A", "D")
    assert assignment.relevant_groups == frozenset({1, 2})

    conflicts = planner.graph_for(assignment).conflicts_for("A", "D")
    assert any(conflict.error_type == CONFLICT_MANY_TO_MANY for conflict in conflicts)


def test_planner_records_merges_after_success():
    planner = planner_with_sample_links()

    assignment = planner.plan_group("A", "F")
    link = make_link("A", "F", assignment.group_id, 99)

    planner.register_success(assignment, link)

    follow_up = planner.plan_group("Y", "F")
    assert follow_up.group_id == assignment.group_id

    merges = planner.consume_pending_merges()
    assert assignment.group_id in merges
    assert 3 in merges[assignment.group_id]
