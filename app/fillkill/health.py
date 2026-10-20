"""Does the database have what this version of the app needs? (2026-10-19)

Most Fill/Kill failures so far came from the app running ahead of a script on O2: a view, a column,
a constraint or the PBO procedure not yet updated. This checks for each thing the app needs and
names the script in db/fillkill that provides it. Admins see the result on Main; before a deploy,
``flask fillkill check-db`` prints it.

``problems(catalog)`` compares; ``read_catalog()`` reads SQL Server's catalog. On SQLite (tests,
local runs) there is nothing to check.

When a script changes what the app needs, change the lists below with it.
"""

from __future__ import annotations

from sqlalchemy import text

from .. import db

# Columns the app reads or writes, per table or view.
COLUMNS = {
    ("FillKill", "vw_MedlineFillKill"): (("Reason", "Reason Date", "Is Test", "Test Purpose"), "10_kill_lines.sql"),
    ("FillKill", "vw_FillKillLastLoad"): (("last_success", "last_line_update"), "10_kill_lines.sql"),
    ("FillKill", "vw_MedlineFillKillItemCollection"): (
        ("Medline Item", "Infor Item", "Infor Item Consistency", "Item.UOMConversion", "Item.LongDescription",
         "CommodityCode", "CommodityCode.Description", "Medline.Sub"), "11_item_qty_views.sql"),
    ("FillKill", "vw_MedlineFillKillQtyAgg"): (("Medline Item", "Total Killed Qty", "Total PO Line Count"),
                                                "11_item_qty_views.sql"),
    ("FillKill", "Sub"): (("vendor_id", "deleted_at", "deleted_by", "delete_reason", "entered_part",
                           "manufacturer_part", "infor_item"), "12_workflow_tables.sql"),
    ("FillKill", "SubOrder"): (("sub_id", "ordered_dt", "voided_at", "vendor_id"), "12_workflow_tables.sql"),
    ("FillKill", "History"): (("entity", "entity_id", "action", "comment"), "12_workflow_tables.sql"),
    ("FillKill", "vw_ContractLineSearch"): (("vendor_id", "vendor_name", "infor_item", "item_type", "is_mhs"),
                                             "13_contract_search.sql"),
    ("FillKill", "vw_Vendor"): (("vendor_id", "vendor_name", "legal_name", "search_name", "vendor_status"),
                                 "13_contract_search.sql"),
    ("PLM", "UserModuleRole"): (("user_id", "module", "role"), "02_user_module_role.sql"),
}

# Columns that must allow NULL: nursing enters a sub without its vendor (2026-10-15).
NULLABLE = {("FillKill", "Sub", "vendor"): "12_workflow_tables.sql"}

# Indexes and their key columns, in order.
INDEXES = {
    ("FillKill", "Sub", "UX_Sub_item_vendor_part"): (("medline_item", "vendor_part"), "12_workflow_tables.sql"),
}

# Check constraints and a value their definition must allow.
CHECKS = {
    ("FillKill", "CK_History_action"): ("'delete'", "12_workflow_tables.sql"),
    ("PLM", "CK_UserModuleRole_role"): ("'materials_manager'", "02_user_module_role.sql"),
}

# Procedures, the version marker in their body, and whether the app runs them.
PROCEDURES = {
    ("FillKill", "usp_SyncPboSubs"): ("version 2026-10-19", "14_pbo_sync.sql"),
}

# Views the app's account must be able to read: a view reading another database (SCSFileIngestor,
# PLMPreprocessorShared) needs a grant there too, which only reading it shows.
READABLE = tuple(key for key in COLUMNS if key[1].startswith("vw_"))


def _name(schema: str, name: str) -> str:
    return f"{schema}.{name}"


def problems(catalog: dict) -> list[dict]:
    """Each thing missing or out of date, as {"what", "script"} (script None: not a script's job).

    ``catalog`` holds ``columns`` {(schema, object): {column: nullable}}, ``indexes``
    {(schema, table, index): [columns]}, ``checks`` and ``procedures`` {(schema, name): definition
    or None when it can't be read}, ``can_execute`` {(schema, procedure): bool} and ``unreadable``
    {(schema, view): error}.
    """
    found: list[dict] = []

    def need(what: str, script: str | None) -> None:
        found.append({"what": what, "script": script})

    columns = catalog.get("columns", {})
    for (schema, obj), (wanted, script) in COLUMNS.items():
        have = columns.get((schema, obj))
        if have is None:
            need(f"{_name(schema, obj)} is missing", script)
            continue
        missing = [column for column in wanted if column not in have]
        if missing:
            need(f"{_name(schema, obj)} has no {', '.join(missing)}", script)
    for (schema, obj, column), script in NULLABLE.items():
        have = columns.get((schema, obj), {})
        if column in have and not have[column]:
            need(f"{_name(schema, obj)}.{column} doesn't allow empty values", script)
    indexes = catalog.get("indexes", {})
    for (schema, table, index), (wanted, script) in INDEXES.items():
        have = indexes.get((schema, table, index))
        if have is None:
            need(f"index {index} on {_name(schema, table)} is missing", script)
        elif tuple(have) != wanted:
            need(f"index {index} is on ({', '.join(have)}), not ({', '.join(wanted)})", script)

    unknown = []
    for kind, wanted_map in (("checks", CHECKS), ("procedures", PROCEDURES)):
        have_map = catalog.get(kind, {})
        for (schema, name), (marker, script) in wanted_map.items():
            if (schema, name) not in have_map:
                need(f"{_name(schema, name)} is missing", script)
            elif have_map[(schema, name)] is None:
                unknown.append(_name(schema, name))
            elif marker.lower() not in have_map[(schema, name)].lower():
                need(f"{_name(schema, name)} is an older version", script)
    if unknown:
        need(f"couldn't read the definition of {', '.join(unknown)} to check it (VIEW DEFINITION permission); "
             "check them with 09_verify.sql", None)

    for (schema, name), can in catalog.get("can_execute", {}).items():
        if not can:
            need(f"the app's account can't run {_name(schema, name)}: grant it EXECUTE", None)
    for (schema, view), error in catalog.get("unreadable", {}).items():
        if (schema, view) in columns:  # a missing view is already listed
            need(f"the app's account can't read {_name(schema, view)} ({error}): check its read grants", None)
    return found


def read_catalog(session) -> dict:
    """SQL Server's catalog for the objects above, read through ``session`` (a SQLAlchemy session or
    connection) with the app's own account."""
    catalog: dict = {"columns": {}, "indexes": {}, "checks": {}, "procedures": {}, "can_execute": {}, "unreadable": {}}
    rows = session.execute(text(
        """SELECT s.name AS sch, o.name AS obj, c.name AS col, c.is_nullable AS nullable
           FROM sys.objects AS o
           JOIN sys.schemas AS s ON s.schema_id = o.schema_id
           JOIN sys.columns AS c ON c.object_id = o.object_id
           WHERE s.name IN ('FillKill', 'PLM') AND o.type IN ('U', 'V')"""
    )).mappings()
    for row in rows:
        catalog["columns"].setdefault((row["sch"], row["obj"]), {})[row["col"]] = bool(row["nullable"])
    rows = session.execute(text(
        """SELECT s.name AS sch, t.name AS tbl, i.name AS idx, c.name AS col
           FROM sys.indexes AS i
           JOIN sys.tables AS t ON t.object_id = i.object_id
           JOIN sys.schemas AS s ON s.schema_id = t.schema_id
           JOIN sys.index_columns AS ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
           JOIN sys.columns AS c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
           WHERE s.name = 'FillKill' AND i.name IS NOT NULL AND ic.is_included_column = 0
           ORDER BY s.name, t.name, i.name, ic.key_ordinal"""
    )).mappings()
    for row in rows:
        catalog["indexes"].setdefault((row["sch"], row["tbl"], row["idx"]), []).append(row["col"])
    rows = session.execute(text(
        """SELECT s.name AS sch, cc.name AS name, cc.definition AS definition
           FROM sys.check_constraints AS cc JOIN sys.schemas AS s ON s.schema_id = cc.schema_id
           WHERE s.name IN ('FillKill', 'PLM')"""
    )).mappings()
    catalog["checks"] = {(row["sch"], row["name"]): row["definition"] for row in rows}
    rows = session.execute(text(
        """SELECT s.name AS sch, p.name AS name, OBJECT_DEFINITION(p.object_id) AS definition,
                  HAS_PERMS_BY_NAME(QUOTENAME(s.name) + '.' + QUOTENAME(p.name), 'OBJECT', 'EXECUTE') AS can_execute
           FROM sys.procedures AS p JOIN sys.schemas AS s ON s.schema_id = p.schema_id
           WHERE s.name = 'FillKill'"""
    )).mappings()
    for row in rows:
        catalog["procedures"][(row["sch"], row["name"])] = row["definition"]
        if (row["sch"], row["name"]) in PROCEDURES:
            catalog["can_execute"][(row["sch"], row["name"])] = bool(row["can_execute"])
    for schema, view in READABLE:
        if (schema, view) not in catalog["columns"]:
            continue
        try:
            session.execute(text(f"SELECT TOP (0) * FROM [{schema}].[{view}]")).all()
        except Exception as error:  # a grant missing on what the view reads
            session.rollback()
            catalog["unreadable"][(schema, view)] = str(getattr(error, "orig", error)).split("\n")[0][:200]
    return catalog


def check() -> list[dict]:
    """The problems now; nothing on SQLite. A failure to read the catalog is itself reported."""
    if not db.engine.url.get_backend_name().startswith("mssql"):
        return []
    try:
        return problems(read_catalog(db.session))
    except Exception as error:
        db.session.rollback()
        return [{"what": f"couldn't check the database: {str(getattr(error, 'orig', error)).splitlines()[0][:200]}",
                 "script": None}]
