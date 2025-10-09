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
