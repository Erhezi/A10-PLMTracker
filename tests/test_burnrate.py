from app.utility.item_locations import burnrate_estimator


def test_burnrate_all_values():
    res = burnrate_estimator(1,2,3,4)
    # equal weights => (1+2+3+4)/4 = 2.5 daily, weekly = 17.5
    assert round(res['daily_avg'],2) == 2.50
    assert round(res['weekly_burn'],2) == 17.50


def test_burnrate_missing_values():
    res = burnrate_estimator(None,2,None,4)
    # values: 2 & 4; weights re-normalize: (0.25/(0.5))*2 + (0.25/(0.5))*4 = 1* ( (0.25/0.5)=0.5 )? Actually both weights 0.25-> sum 0.5 -> normalized 0.5 each => avg = (2*0.5 + 4*0.5)=3 daily
    assert round(res['daily_avg'],2) == 3.00
    assert round(res['weekly_burn'],2) == 21.00


def test_burnrate_all_none():
    res = burnrate_estimator(None,None,None,None)
    assert res['daily_avg'] == 0.0
    assert res['weekly_burn'] == 0.0
