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
