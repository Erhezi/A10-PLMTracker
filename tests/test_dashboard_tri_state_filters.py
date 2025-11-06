import copy

from flask import Flask

from app.dashboard import routes
from app.dashboard.routes import _normalize_tri_state, _apply_tri_state_filter


def test_normalize_tri_state_variants():
    assert _normalize_tri_state("Yes") == "yes"
    assert _normalize_tri_state(" no ") == "no"
    assert _normalize_tri_state(" ") == "blank"
    assert _normalize_tri_state(None) == "blank"
    assert _normalize_tri_state(True) == "yes"
    assert _normalize_tri_state(False) == "no"
    assert _normalize_tri_state("1") == "yes"
    assert _normalize_tri_state("0") == "no"
    assert _normalize_tri_state("n/a") == "blank"


def test_apply_tri_state_filter_matches_expected_values():
    rows = [
        {"auto_replenishment": "Yes"},
        {"auto_replenishment": "No"},
        {"auto_replenishment": None},
        {"auto_replenishment": ""},
        {"auto_replenishment": "TRUE"},
    ]

    yes_rows = _apply_tri_state_filter(rows, "auto_replenishment", "yes")
    no_rows = _apply_tri_state_filter(rows, "auto_replenishment", "no")
    blank_rows = _apply_tri_state_filter(rows, "auto_replenishment", "blank")
    untouched_rows = _apply_tri_state_filter(rows, "auto_replenishment", "maybe")

    assert len(yes_rows) == 2
    assert all(_normalize_tri_state(r["auto_replenishment"]) == "yes" for r in yes_rows)

    assert len(no_rows) == 1
    assert _normalize_tri_state(no_rows[0]["auto_replenishment"]) == "no"

    assert len(blank_rows) == 2
    assert all(_normalize_tri_state(r["auto_replenishment"]) == "blank" for r in blank_rows)

    assert untouched_rows is rows


def test_apply_inventory_recommended_bin_display_matches_ui_rules():
    rows = [
        {
            "action": "Create",
            "preferred_bin_ri": "RI-100",
            "preferred_bin": "SRC-100",
            "recommended_preferred_bin_ri": "",
        },
        {
            "action": "Update",
            "preferred_bin_ri": "RI-200",
            "recommended_preferred_bin_ri": "   ",
        },
        {
            "action": "Mute",
            "preferred_bin_ri": "RI-300",
            "recommended_preferred_bin_ri": "N.A.",
        },
        {
            "action": "",
            "preferred_bin_ri": "",
            "recommended_preferred_bin_ri": None,
        },
    ]

    routes._apply_inventory_recommended_bin_display(rows)

    assert rows[0]["recommended_preferred_bin_ri"] == "NEW ITEM"
    assert rows[1]["recommended_preferred_bin_ri"] == "RI-200"
    assert rows[2]["recommended_preferred_bin_ri"] == "N.A."
    assert rows[3]["recommended_preferred_bin_ri"] == "TBD"


def test_api_stats_respects_hide_r_only(monkeypatch):
    inventory_rows = [
        {
            "group_location": "LOC1",
            "location": "LOC1",
            "location_type": "Inventory Location",
            "item_group": 101,
            "item": "ITEM-A",
        },
        {
            "group_location": "R-ONLY LOC",
            "location": "R-ONLY LOC",
            "location_type": "R-Only Location",
            "item_group": 202,
            "item": "ITEM-B",
        },
    ]
    par_rows = [
        {
            "group_location": "PAR-01",
            "location": "PAR-01",
            "location_type": "Par Location",
            "item_group": 303,
            "item": "ITEM-C",
        }
    ]

    def fake_inventory(args, *, apply_filters=True):  # pragma: no cover - helper
        return copy.deepcopy(inventory_rows)

    def fake_par(args, *, apply_filters=True):  # pragma: no cover - helper
        return copy.deepcopy(par_rows)

    monkeypatch.setattr(routes, "_filtered_inventory_rows", fake_inventory)
    monkeypatch.setattr(routes, "_filtered_par_rows", fake_par)

    app = Flask(__name__)
    app.config["TESTING"] = True

    with app.test_request_context("/dashboard/api/stats"):
        response = routes.api_stats()
        data = response.get_json()
        assert data["distinct_locations"] == 3
        assert data["distinct_groups"] == 3
        assert data["distinct_items"] == 3

    with app.test_request_context("/dashboard/api/stats?hide_r_only=true"):
        response = routes.api_stats()
        data = response.get_json()
        # R-Only location should be excluded while others remain
        assert data["distinct_locations"] == 2
        assert data["distinct_groups"] == 3
        assert data["distinct_items"] == 3


def test_api_filter_options_limits_item_groups_to_active_stages(monkeypatch):
    captured_queries = []

    class DummyResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    def fake_execute(statement):  # pragma: no cover - helper
        captured_queries.append(statement)
        if len(captured_queries) == 1:
            return DummyResult([(101,), (202,)])
        if len(captured_queries) == 2:
            return DummyResult([
                (101, "ITEM-A"),
                (101, "ITEM-B"),
                (202, "ITEM-C"),
            ])
        raise AssertionError("Unexpected query execution")

    monkeypatch.setattr(routes.db.session, "execute", fake_execute)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["INCLUDE_OR_INVENTORY_LOCATIONS"] = False

    with app.test_request_context("/dashboard/api/filter-options"):
        response = routes.api_filter_options()
        payload = response.get_json()

    assert payload["item_groups"] == [
        {
            "value": 101,
            "items": ["ITEM-A", "ITEM-B"],
            "label": "101 - ITEM-A, ITEM-B",
        },
        {
            "value": 202,
            "items": ["ITEM-C"],
            "label": "202 - ITEM-C",
        },
    ]

    first_query = captured_queries[0]
    stage_clause = next(
        (
            criteria
            for criteria in first_query._where_criteria
            if getattr(criteria, "left", None) is not None and criteria.left.compare(routes.ItemLink.stage)
        ),
        None,
    )
    assert stage_clause is not None
    stage_values = stage_clause.right.value or ()
    assert set(stage_values) == routes.ALLOWED_STAGE_VALUES
