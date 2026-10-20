"""The database check (app/fillkill/health.py): what this version needs, and which script provides it."""

from app.fillkill import health


def complete_catalog() -> dict:
    """A catalog with everything the app needs."""
    columns = {key: {column: True for column in wanted} for key, (wanted, _) in health.COLUMNS.items()}
    for (schema, obj, column) in health.NULLABLE:
        columns[(schema, obj)][column] = True
    return {
        "columns": columns,
        "indexes": {key: list(wanted) for key, (wanted, _) in health.INDEXES.items()},
        "checks": {key: f"([x]={marker})" for key, (marker, _) in health.CHECKS.items()},
        "procedures": {key: f"CREATE PROCEDURE ... -- {marker}" for key, (marker, _) in health.PROCEDURES.items()},
        "can_execute": {key: True for key in health.PROCEDURES},
        "unreadable": {},
    }


def test_a_complete_database_has_nothing_to_fix():
    assert health.problems(complete_catalog()) == []


def test_each_gap_names_the_script_that_fills_it():
    catalog = complete_catalog()
    del catalog["columns"][("FillKill", "vw_Vendor")]
    catalog["columns"][("FillKill", "Sub")].pop("deleted_at")
    catalog["columns"][("FillKill", "SubOrder")]["vendor_item_id"] = False
    catalog["indexes"][("FillKill", "Sub", "UX_Sub_item_reference_sku")] = ["medline_item", "vendor_part"]
    catalog["checks"][("FillKill", "CK_History_action")] = "([action]='void')"
    catalog["procedures"][("FillKill", "usp_SyncPboSubs")] = "CREATE PROCEDURE ... an older one"
    assert [(p["what"], p["script"]) for p in health.problems(catalog)] == [
        ("FillKill.Sub has no deleted_at", "12_workflow_tables.sql"),
        ("FillKill.vw_Vendor is missing", "13_contract_search.sql"),
        ("FillKill.SubOrder.vendor_item_id doesn't allow empty values", "12_workflow_tables.sql"),
        ("index UX_Sub_item_reference_sku is on (medline_item, vendor_part), not (medline_item, reference_sku)",
         "12_workflow_tables.sql"),
        ("FillKill.CK_History_action is an older version", "12_workflow_tables.sql"),
        ("FillKill.usp_SyncPboSubs is an older version", "14_pbo_sync.sql"),
    ]


def test_grants_and_definitions_it_cant_read_are_reported_without_a_script():
    catalog = complete_catalog()
    catalog["can_execute"][("FillKill", "usp_SyncPboSubs")] = False
    catalog["unreadable"][("FillKill", "vw_MedlineFillKill")] = "The SELECT permission was denied on MedlineFillKill"
    catalog["checks"] = {key: None for key in catalog["checks"]}
    found = health.problems(catalog)
    assert [p["script"] for p in found] == [None, None, None]  # three CHECKs unreadable: one line for them
    assert "VIEW DEFINITION" in found[0]["what"] and "09_verify.sql" in found[0]["what"]
    assert "grant it EXECUTE" in found[1]["what"]
    assert "can't read FillKill.vw_MedlineFillKill (The SELECT permission was denied" in found[2]["what"]


def test_nothing_to_check_on_sqlite(sqlite_app):
    with sqlite_app.app_context():
        assert health.check() == []
    result = sqlite_app.test_cli_runner().invoke(args=["fillkill", "check-db"])
    assert "has everything this version needs" in result.output
