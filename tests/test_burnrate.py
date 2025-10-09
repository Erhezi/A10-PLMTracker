from app.utility.item_locations import burnrate_estimator


def test_burnrate_from_rolling_value():
    res = burnrate_estimator(2.5)
    assert res['daily_avg'] == 2.5
    assert res['weekly_burn'] == 17.5


def test_burnrate_sparse_usage_doubles_projection():
    res = burnrate_estimator(3.0, issued_count_365=4)
    assert res['daily_avg'] == 6.0
    assert res['weekly_burn'] == 42.0


def test_burnrate_none_returns_zero():
    res = burnrate_estimator(None)
    assert res['daily_avg'] == 0.0
    assert res['weekly_burn'] == 0.0
