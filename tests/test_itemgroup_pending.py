from unittest.mock import Mock

from app.models.relations import (
    ItemGroup,
    ItemLink,
    PENDING_PLACEHOLDER_PREFIX,
)


def _link(item: str, replace: str | None) -> ItemLink:
    link = ItemLink(item=item, replace_item=replace, item_group=99)
    link.pkid = 123
    return link


def test_desired_pairs_standard_replacement_includes_both_sides():
    link = _link("A10001", "B20002")

    pairs = ItemGroup._desired_pairs_for_link(link)

    assert pairs == [
        ("A10001", "O"),
        ("B20002", "R"),
    ]


def test_desired_pairs_pending_placeholder_only_tracks_source_side():
    placeholder = f"{PENDING_PLACEHOLDER_PREFIX}FOO123"
    link = _link("A10001", placeholder)

    pairs = ItemGroup._desired_pairs_for_link(link)

    assert pairs == [("A10001", "O")]


def test_desired_pairs_discontinue_marks_discontinued_side():
    link = _link("A10001", None)

    pairs = ItemGroup._desired_pairs_for_link(link)

    assert pairs == [("A10001", "D")]


def test_ensure_allowed_side_skips_pending_placeholder_session_queries():
    session = Mock()

    ItemGroup.ensure_allowed_side(75, f"{PENDING_PLACEHOLDER_PREFIX}BAR456", "R", session=session)

    session.query.assert_not_called()
