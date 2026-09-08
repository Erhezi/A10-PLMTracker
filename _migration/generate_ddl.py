"""
Phase 0 - script the PLM schema out of LIVE PRIME (never from _query_backup, which is stale).

Emits, into ./sql :
    01_tables.sql        23 CREATE TABLE (columns, identity, defaults, primary keys)
    02_indexes.sql       unique constraints + nonclustered indexes
    03_foreignkeys.sql   6 FKs, applied after the data load
    04_views.sql         16 views in dependency-tier order, remapped to three-part names
    05_procs.sql         11 stored procedures, remapped to three-part names
    remap_report.txt     every external reference rewritten, for eyeball review

Read-only against PRIME. Writes nothing to any server.
"""
import os
import re
import pyodbc

SRC = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=MISCPrdAdhocDB;DATABASE=PRIME;Trusted_Connection=yes;"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sql")

# Decision B - target already carries infor.ParItemBin, sourced straight from Infor.
EXCLUDE_TABLES = {"ParItemBin"}

# Decision A - three-part names, spelled out. Two of these are renames.
TARGET_DB = "PLMPreprocessorShared"
REMAP = {
    "INVENTORY_LOCATION":          "ITEM_LOCATION",
    "MDM_MANUFACTURER_NAME_INFOR": "MDM_MANUFACTURER_NAME",
    "CONTRACTLINE":                "CONTRACTLINE",
    "INVENTORY_TRANSACTION":       "INVENTORY_TRANSACTION",
    "MDM_ITEM":                    "MDM_ITEM",
    "MDM_ITEMUOM":                 "MDM_ITEMUOM",
    "MDM_REQUESTER":               "MDM_REQUESTER",
    "PURCHASEORDER_LINE":          "PURCHASEORDER_LINE",
    "REQUISITION_LINE":            "REQUISITION_LINE",
}

# [DM_MONTYNT\dli2].NAME  or  [DM_MONTYNT\dli2].[NAME]
EXT_REF = re.compile(r"\[DM_MONTYNT\\dli2\]\s*\.\s*(?:\[(?P<b>[^\]]+)\]|(?P<p>\w+))", re.I)

LEN_TYPES   = {"varchar", "nvarchar", "char", "nchar", "binary", "varbinary"}
PREC_TYPES  = {"decimal", "numeric"}
SCALE_TYPES = {"datetime2", "datetimeoffset", "time"}


def remap_sql(text, hits):
    """Rewrite every [DM_MONTYNT\\dli2].X to PLMPreprocessorShared.infor.Y."""
    def sub(m):
        name = m.group("b") or m.group("p")
        key = name.upper()
        if key not in REMAP:
            hits.append(("!! UNMAPPED", name, ""))
            return m.group(0)
        new = REMAP[key]
        hits.append(("renamed" if new.upper() != key else "moved", name, new))
        return f"{TARGET_DB}.infor.[{new}]"
    return EXT_REF.sub(sub, text)


def col_type(t, maxlen, prec, scale):
    t = t.lower()
    if t in LEN_TYPES:
        if maxlen == -1:
            return f"{t}(max)"
        n = maxlen // 2 if t in ("nvarchar", "nchar") else maxlen
        return f"{t}({n})"
    if t in PREC_TYPES:
        return f"{t}({prec},{scale})"
    if t in SCALE_TYPES:
        return f"{t}({scale})"
    if t == "float":
        return f"float({prec})"
    return t


def main():
    os.makedirs(OUT, exist_ok=True)
    cn = pyodbc.connect(SRC, timeout=60)
    c = cn.cursor()

    c.execute("""SELECT t.name, t.object_id FROM sys.tables t
                 JOIN sys.schemas s ON t.schema_id = s.schema_id
                 WHERE s.name = 'PLM' ORDER BY t.name""")
    tables = [(n, oid) for n, oid in c.fetchall() if n not in EXCLUDE_TABLES]

    hdr = ("/* Generated from LIVE PRIME by _migration/generate_ddl.py.\n"
           "   Do not hand-edit - regenerate instead. */\nUSE [PLM];\nGO\n\n")

    # ---------- 01 tables ----------
    parts = [hdr,
             "IF SCHEMA_ID('PLM') IS NULL EXEC('CREATE SCHEMA [PLM]');\nGO\n\n"]
    for name, oid in tables:
        c.execute("""SELECT c.name, ty.name, c.max_length, c.precision, c.scale, c.is_nullable,
                            c.is_identity, CONVERT(bigint, ISNULL(ic.seed_value,0)), CONVERT(bigint, ISNULL(ic.increment_value,0)),
                            dc.name, dc.definition, c.is_computed, cc.definition, ISNULL(cc.is_persisted,0)
                     FROM sys.columns c
                     JOIN sys.types ty ON c.user_type_id = ty.user_type_id
                     LEFT JOIN sys.identity_columns ic
                            ON c.object_id = ic.object_id AND c.column_id = ic.column_id
                     LEFT JOIN sys.default_constraints dc
                            ON c.object_id = dc.parent_object_id AND c.column_id = dc.parent_column_id
                     LEFT JOIN sys.computed_columns cc
                            ON c.object_id = cc.object_id AND c.column_id = cc.column_id
                     WHERE c.object_id = ? ORDER BY c.column_id""", oid)
        lines = []
        for (cn_, ty, ml, pr, sc, nul, ident, seed, incr, dname, ddef,
             computed, cdef, persisted) in c.fetchall():
            if computed:
                # A computed column is a formula, not storage - no type, no nullability,
                # and copy_data.py must never try to insert into it.
                lines.append(f"    [{cn_}] AS {cdef}" + (" PERSISTED" if persisted else ""))
                continue
            piece = f"    [{cn_}] {col_type(ty, ml, pr, sc)}"
            if ident:
                piece += f" IDENTITY({seed},{incr})"
            piece += " NULL" if nul else " NOT NULL"
            if dname:
                piece += f" CONSTRAINT [{dname}] DEFAULT {ddef}"
            lines.append(piece)

        # primary key
        c.execute("""SELECT i.name, i.type_desc, col.name, ixc.is_descending_key
                     FROM sys.indexes i
                     JOIN sys.index_columns ixc ON i.object_id = ixc.object_id AND i.index_id = ixc.index_id
                     JOIN sys.columns col ON ixc.object_id = col.object_id AND ixc.column_id = col.column_id
                     WHERE i.object_id = ? AND i.is_primary_key = 1
                     ORDER BY ixc.key_ordinal""", oid)
        pk = c.fetchall()
        if pk:
            cols = ", ".join(f"[{r[2]}]{' DESC' if r[3] else ''}" for r in pk)
            lines.append(f"    CONSTRAINT [{pk[0][0]}] PRIMARY KEY {pk[0][1]} ({cols})")

        parts.append(f"CREATE TABLE [PLM].[{name}] (\n" + ",\n".join(lines) + "\n);\nGO\n\n")
    open(os.path.join(OUT, "01_tables.sql"), "w", encoding="utf-8").write("".join(parts))

    # ---------- 02 indexes ----------
    parts = [hdr]
    for name, oid in tables:
        c.execute("""SELECT i.name, i.is_unique, i.is_unique_constraint, i.type_desc, i.filter_definition
                     FROM sys.indexes i
                     WHERE i.object_id = ? AND i.is_primary_key = 0 AND i.index_id > 0
                     ORDER BY i.index_id""", oid)
        for iname, uniq, uconst, tdesc, filt in c.fetchall():
            c.execute("""SELECT col.name, ixc.is_descending_key, ixc.is_included_column
                         FROM sys.index_columns ixc
                         JOIN sys.columns col ON ixc.object_id = col.object_id AND ixc.column_id = col.column_id
                         JOIN sys.indexes i ON i.object_id = ixc.object_id AND i.index_id = ixc.index_id
                         WHERE ixc.object_id = ? AND i.name = ?
                         ORDER BY ixc.is_included_column, ixc.key_ordinal""", oid, iname)
            rows = c.fetchall()
            keys = [f"[{r[0]}]{' DESC' if r[1] else ''}" for r in rows if not r[2]]
            incl = [f"[{r[0]}]" for r in rows if r[2]]
            if uconst:
                parts.append(f"ALTER TABLE [PLM].[{name}] ADD CONSTRAINT [{iname}] "
                             f"UNIQUE {tdesc} ({', '.join(keys)});\nGO\n")
            else:
                stmt = (f"CREATE {'UNIQUE ' if uniq else ''}{tdesc} INDEX [{iname}] "
                        f"ON [PLM].[{name}] ({', '.join(keys)})")
                if incl:
                    stmt += f" INCLUDE ({', '.join(incl)})"
                if filt:
                    stmt += f" WHERE {filt}"
                parts.append(stmt + ";\nGO\n")
    open(os.path.join(OUT, "02_indexes.sql"), "w", encoding="utf-8").write("".join(parts))

    # ---------- 03 foreign keys ----------
    c.execute("""SELECT fk.name, OBJECT_NAME(fk.parent_object_id), OBJECT_NAME(fk.referenced_object_id),
                        fk.delete_referential_action_desc, fk.update_referential_action_desc
                 FROM sys.foreign_keys fk
                 JOIN sys.schemas s ON fk.schema_id = s.schema_id
                 WHERE s.name = 'PLM' ORDER BY fk.name""")
    parts = [hdr, "-- Run AFTER the data load (see copy_data.py).\n\n"]
    for fkname, ptab, rtab, ddel, dupd in c.fetchall():
        c.execute("""SELECT pc.name, rc.name FROM sys.foreign_key_columns fkc
                     JOIN sys.columns pc ON fkc.parent_object_id = pc.object_id
                                        AND fkc.parent_column_id = pc.column_id
                     JOIN sys.columns rc ON fkc.referenced_object_id = rc.object_id
                                        AND fkc.referenced_column_id = rc.column_id
                     WHERE fkc.constraint_object_id = OBJECT_ID(?)
                     ORDER BY fkc.constraint_column_id""", f"PLM.{fkname}")
        pairs = c.fetchall()
        stmt = (f"ALTER TABLE [PLM].[{ptab}] WITH CHECK ADD CONSTRAINT [{fkname}]\n"
                f"    FOREIGN KEY ({', '.join('[' + p[0] + ']' for p in pairs)}) "
                f"REFERENCES [PLM].[{rtab}] ({', '.join('[' + p[1] + ']' for p in pairs)})")
        if ddel != "NO_ACTION":
            stmt += f"\n    ON DELETE {ddel.replace('_', ' ')}"
        if dupd != "NO_ACTION":
            stmt += f"\n    ON UPDATE {dupd.replace('_', ' ')}"
        parts.append(stmt + ";\nGO\n\n")
    open(os.path.join(OUT, "03_foreignkeys.sql"), "w", encoding="utf-8").write("".join(parts))

    # ---------- 04 views (tier order) / 05 procs ----------
    report = []

    c.execute("""SELECT o.name, m.definition, o.type
                 FROM sys.sql_modules m
                 JOIN sys.objects o ON m.object_id = o.object_id
                 JOIN sys.schemas s ON o.schema_id = s.schema_id
                 WHERE s.name = 'PLM'""")
    mods = {n: (d, t.strip()) for n, d, t in c.fetchall()}

    # view -> view dependency tiers
    c.execute("""SELECT o.name, d.referenced_entity_name
                 FROM sys.sql_expression_dependencies d
                 JOIN sys.objects o ON d.referencing_id = o.object_id
                 JOIN sys.schemas s ON o.schema_id = s.schema_id
                 WHERE s.name = 'PLM' AND o.type = 'V' AND d.referenced_schema_name = 'PLM'""")
    views = {n for n, (d, t) in mods.items() if t == "V"}
    dep = {v: set() for v in views}
    for a, b in c.fetchall():
        if a in views and b in views:
            dep[a].add(b)
    tiers, done, rem = [], set(), set(views)
    while rem:
        ready = sorted(v for v in rem if not (dep[v] - done))
        tiers.append(ready)
        done |= set(ready)
        rem -= set(ready)

    def emit(name):
        body, _ = mods[name]
        hits = []
        body = remap_sql(body, hits)
        for kind, old, new in hits:
            report.append(f"{name:<45} {kind:<12} {old} -> {new}")
        # CREATE -> CREATE OR ALTER so redeploys are idempotent
        body = re.sub(r"^\s*CREATE\s+(OR\s+ALTER\s+)?(VIEW|PROCEDURE|PROC)\b",
                      lambda m: f"CREATE OR ALTER {m.group(2)}", body, count=1,
                      flags=re.I | re.M)
        return body.rstrip() + "\nGO\n\n"

    parts = [hdr]
    for i, tier in enumerate(tiers, 1):
        parts.append(f"-- ===== TIER {i} =====\n")
        for v in tier:
            parts.append(emit(v))
    open(os.path.join(OUT, "04_views.sql"), "w", encoding="utf-8").write("".join(parts))

    procs = sorted(n for n, (d, t) in mods.items() if t == "P")
    parts = [hdr]
    for p in procs:
        parts.append(emit(p))
    open(os.path.join(OUT, "05_procs.sql"), "w", encoding="utf-8").write("".join(parts))

    open(os.path.join(OUT, "remap_report.txt"), "w", encoding="utf-8").write(
        "Every external reference rewritten by generate_ddl.py\n"
        "'moved'  = same table name, now three-part\n"
        "'renamed'= table name changed on the target\n\n" + "\n".join(report) + "\n")

    cn.close()
    print(f"tables   : {len(tables)} (excluded {sorted(EXCLUDE_TABLES)})")
    print(f"views    : {len(views)} in {len(tiers)} tiers")
    print(f"procs    : {len(procs)}")
    print(f"remapped : {len(report)} references")
    unmapped = [r for r in report if "UNMAPPED" in r]
    print("UNMAPPED :", unmapped if unmapped else "none")


if __name__ == "__main__":
    main()
