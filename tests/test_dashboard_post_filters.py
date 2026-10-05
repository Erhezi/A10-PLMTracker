import copy
import io
from urllib.parse import urlencode

import pytest
from flask import Flask
from openpyxl import load_workbook

from app.dashboard import routes
from app.export import PAR_EXPORT_COLUMNS


# Sized like production: 164 Par locations averaging ~8 characters.
PAR_LOCATIONS = [f"PAR{index:05d}" for index in range(164)]
PAR_ROWS = [
    {"group_location": "PAR00001", "location": "PAR00001", "location_type": "Par Location", "item_group": 177},
]


@pytest.fixture
def client_and_calls(monkeypatch):
    calls = []

    def fake_inventory(args, *, apply_filters=True):
        calls.append(("inventory", args.to_dict()))
        return []

    def fake_par(args, *, apply_filters=True):
        calls.append(("par", args.to_dict()))
        return copy.deepcopy(PAR_ROWS)

    monkeypatch.setattr(routes, "_filtered_inventory_rows", fake_inventory)
    monkeypatch.setattr(routes, "_filtered_par_rows", fake_par)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(routes.bp)
    return app.test_client(), calls


def _filter_payload(**extra):
    payload = {
        "item_group": "177,178,179,180,181,182,183,184,185,186",
        "location": ",".join(PAR_LOCATIONS),
        "stage": "Tracking - Item Transition",
        "hide_r_only": "true",
    }
    payload.update(extra)
    return payload


def test_payload_is_longer_than_the_iis_query_string_limit():
    columns = ",".join(field for _, field in PAR_EXPORT_COLUMNS)
    query = urlencode(_filter_payload(row_scope="filtered", column_mode="visible", columns=columns))
    assert len(query) > 2048


def test_request_params_flattens_json_body():
    app = Flask(__name__)
    body = {"location": ["A", "B"], "hide_r_only": True, "page": 2, "desc_search": "glove", "stage": None}
    with app.test_request_context("/dashboard/api/par", method="POST", json=body):
        params = routes._request_params()
    assert params.to_dict() == {"location": "A,B", "hide_r_only": "true", "page": "2", "desc_search": "glove"}


def test_request_params_uses_query_string_for_get():
    app = Flask(__name__)
    with app.test_request_context("/dashboard/api/par?location=A,B&page=3"):
        params = routes._request_params()
    assert params.to_dict() == {"location": "A,B", "page": "3"}


@pytest.mark.parametrize(
    ("path", "expected_tables"),
    [
        ("/dashboard/api/inventory", ["inventory"]),
        ("/dashboard/api/par", ["par"]),
        ("/dashboard/api/stats", ["inventory", "par"]),
        ("/dashboard/api/requesters", ["inventory", "par"]),
    ],
)
def test_data_endpoints_accept_long_filters_as_json(client_and_calls, path, expected_tables):
    client, calls = client_and_calls
    response = client.post(path, json=_filter_payload(page="1", per_page="100"))

    assert response.status_code == 200
    assert [table for table, _ in calls] == expected_tables
    for _, args in calls:
        assert args["location"].split(",") == PAR_LOCATIONS
        assert args["item_group"] == "177,178,179,180,181,182,183,184,185,186"


def test_export_accepts_long_filters_and_columns_as_json(client_and_calls):
    client, calls = client_and_calls
    fields = [field for _, field in PAR_EXPORT_COLUMNS]
    response = client.post(
        "/dashboard/export/par",
        json=_filter_payload(row_scope="filtered", column_mode="visible", columns=",".join(fields)),
    )

    assert response.status_code == 200
    assert calls[0][1]["location"].split(",") == PAR_LOCATIONS
    headers = [cell.value for cell in load_workbook(io.BytesIO(response.data)).active[1]]
    assert headers == [header for header, _ in PAR_EXPORT_COLUMNS]


def test_export_still_accepts_get_for_groups_page(client_and_calls):
    client, _ = client_and_calls
    response = client.get("/dashboard/export/par?row_scope=filtered&item_group=177&column_mode=custom&columns=item_group,item")
    assert response.status_code == 200


def test_export_errors_are_json(client_and_calls):
    client, _ = client_and_calls
    response = client.post(
        "/dashboard/export/par",
        json={"row_scope": "all", "column_mode": "custom", "columns": "item,item_set"},
    )
    assert response.status_code == 400
    assert response.get_json() == {"error": "Requested columns are not available for export."}


def test_non_object_json_body_is_rejected(client_and_calls):
    client, _ = client_and_calls
    response = client.post("/dashboard/api/par", json=["not", "an", "object"])
    assert response.status_code == 400
    assert "JSON object" in response.get_json()["error"]
