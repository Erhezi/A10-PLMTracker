from app.dashboard.routes import _collect_item_pool, _aggregate_requester_rows


def test_collect_item_pool_gathers_items_and_replacements():
    rows = [
        {"item": "ITEM-001", "replacement_item": "ITEM-002"},
        {"item": "ITEM-002", "replacement_item": "ITEM-003"},
        {"item": " ", "replacement_item": None},
        {"item": None, "replacement_item": "ITEM-004"},
    ]

    pool = _collect_item_pool(rows)

    assert pool == {"ITEM-001", "ITEM-002"}


def test_aggregate_requester_rows_groups_and_sorts():
    rows = [
        {
            "requester": "rq-200",
            "name": "Beta Tech",
            "email": "beta@example.com",
            "location": "R203",
            "item": "ITEM-002",
            "requisition": "REQ-5",
            "requests_count": 5,
        },
        {
            "requester": "rq-100",
            "name": "Alpha Nurse",
            "email": "alpha@example.com",
            "location": "R101",
            "item": "ITEM-001",
            "requisition": "REQ-1",
            "requests_count": 3,
        },
        {
            "requester": "rq-100",
            "name": "",
            "email": "",
            "location": "R105",
            "item": "ITEM-003",
            "requisition": "REQ-2",
            "requests_count": 2,
        },
        {
            "requester": "",
            "name": "Ignored",
            "email": "ignored@example.com",
            "location": "R999",
            "item": "ITEM-999",
            "requisition": "REQ-9",
            "requests_count": 10,
        },
    ]

    result = _aggregate_requester_rows(rows)

    assert [entry["requester"] for entry in result] == ["rq-100", "rq-200"]

    first = result[0]
    assert first["name"] == "Alpha Nurse"
    assert first["email"] == "alpha@example.com"
    assert first["locations"] == ["R101", "R105"]
    assert first["items"] == ["ITEM-001", "ITEM-003"]
    assert first["requisition_ids"] == ["REQ-1", "REQ-2"]
    assert first["request_count"] == 5

    second = result[1]
    assert second["name"] == "Beta Tech"
    assert second["email"] == "beta@example.com"
    assert second["locations"] == ["R203"]
    assert second["items"] == ["ITEM-002"]
    assert second["requisition_ids"] == ["REQ-5"]
    assert second["request_count"] == 5
