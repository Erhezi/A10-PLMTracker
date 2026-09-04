"""
Phase 3 - copy PLM table data from PRIME to the new PLM database.

Reads from PRIME. Writes ONLY to the target. The source is never modified:
no DELETE, no TRUNCATE, no ALTER is ever issued against PRIME.

Usage
    python copy_data.py --dry-run      # connect, count both sides, change nothing
    python copy_data.py                # load every table
    python copy_data.py --only ItemLink,ItemGroup
    python copy_data.py --verify       # compare row counts + identity seeds only

Run AFTER sql/01_tables.sql and BEFORE sql/03_foreignkeys.sql.
Re-runnable: each table is cleared on the target before reloading.
"""
import argparse
import sys
import time

import pyodbc

SRC = ("DRIVER={ODBC Driver 17 for SQL Server};SERVER=MISCPrdAdhocDB;"
       "DATABASE=PRIME;Trusted_Connection=yes;")
TGT = (r"DRIVER={ODBC Driver 17 for SQL Server};SERVER=YNBBSTVWP02\PROCDATASRVPROD;"
       "DATABASE=PLM;Trusted_Connection=yes;")

BATCH = 5000

# Parents first. Matters only when the FKs are already in place (a re-run);
# on a first pass 03_foreignkeys.sql has not been applied yet.
LOAD_ORDER = [
    "ItemGroup",
    "ItemLink",
    "ItemGroupLink",
    "PendingItems",
    "ConflictError",
    "ConflictErrorPendingItemAddition_log",
    "ItemLinkWrike",
    "burn_rate_refresh_job",
    "ItemLinkArchived",
    "ItemLinkDeleted",
    "ItemLink_copy",
    "users",
    "process_log",
    "WrikeTask",
    "PastYearRequestersCount",
    "ItemLocations",
    "ItemLocationsBR",
    "ItemStartEndDate",
    "PLMItemBRRolling",
    "PLMItemGroupBRRolling",
    "PLMItemBRRolling_Log",
    "PLMItemGroupBRRolling_Log",
    "DailyIssueOutQty",
]

# Referenced by a FK, so TRUNCATE is refused once 03 has run - use DELETE.
FK_REFERENCED = {"ItemGroup", "ItemLink"}

# Decision B - the target already has infor.ParItemBin, straight from Infor.
EXCLUDED = {"ParItemBin"}


def columns(cur, table):
    cur.execute("""SELECT c.name, c.is_identity
                   FROM sys.columns c
                   JOIN sys.objects o ON c.object_id = o.object_id
                   JOIN sys.schemas s ON o.schema_id = s.schema_id
                   WHERE s.name = 'PLM' AND o.name = ?
                   ORDER BY c.column_id""", table)
    rows = cur.fetchall()
    return [r[0] for r in rows], any(r[1] for r in rows)


def count(cur, table):
    cur.execute(f"SELECT COUNT(*) FROM PLM.[{table}]")
    return cur.fetchone()[0]


def ident_current(cur, table):
    cur.execute("SELECT IDENT_CURRENT(?)", f"PLM.{table}")
    v = cur.fetchone()[0]
    return int(v) if v is not None else None


def copy_table(s, t, table, dry):
    sc, tc = s.cursor(), t.cursor()
    cols, has_identity = columns(sc, table)
    src_n = count(sc, table)

    try:
        tgt_n_before = count(tc, table)
    except pyodbc.Error:
        print(f"  {table:<40} TARGET TABLE MISSING - run sql/01_tables.sql first")
        return False

    if dry:
        print(f"  {table:<40} source={src_n:>10,}  target={tgt_n_before:>10,}  "
              f"cols={len(cols)}  identity={'yes' if has_identity else 'no'}")
        return True

    collist = ", ".join(f"[{c}]" for c in cols)
    params = ", ".join("?" * len(cols))

    if table in FK_REFERENCED:
        tc.execute(f"DELETE FROM PLM.[{table}]")
    else:
        tc.execute(f"TRUNCATE TABLE PLM.[{table}]")
    t.commit()

    t0 = time.time()
    moved = 0
    if src_n:
        tc.fast_executemany = True
        if has_identity:
            tc.execute(f"SET IDENTITY_INSERT PLM.[{table}] ON")
        sc.execute(f"SELECT {collist} FROM PLM.[{table}]")
        while True:
            rows = sc.fetchmany(BATCH)
            if not rows:
                break
            tc.executemany(
                f"INSERT INTO PLM.[{table}] ({collist}) VALUES ({params})",
                [tuple(r) for r in rows])
            moved += len(rows)
            t.commit()
        if has_identity:
            tc.execute(f"SET IDENTITY_INSERT PLM.[{table}] OFF")
        t.commit()

    # Preserve the source's next-value so the app cannot collide on insert.
    seed_note = ""
    if has_identity:
        src_seed = ident_current(sc, table)
        if src_seed is not None:
            tc.execute(f"DBCC CHECKIDENT ('PLM.{table}', RESEED, {src_seed}) WITH NO_INFOMSGS")
            t.commit()
            seed_note = f"  reseed={src_seed:,}"

    tgt_n = count(tc, table)
    ok = tgt_n == src_n
    print(f"  {'OK ' if ok else 'BAD'} {table:<38} {tgt_n:>10,} / {src_n:<10,} rows  "
          f"{time.time() - t0:>6.1f}s{seed_note}")
    return ok


def verify(s, t, tables):
    sc, tc = s.cursor(), t.cursor()
    print(f"  {'TABLE':<40}{'SOURCE':>12}{'TARGET':>12}   {'SEED src/tgt':<24}")
    bad = []
    for table in tables:
        src_n = count(sc, table)
        try:
            tgt_n = count(tc, table)
        except pyodbc.Error:
            print(f"  {table:<40}{src_n:>12,}{'MISSING':>12}")
            bad.append(table)
            continue
        _, has_identity = columns(sc, table)
        seed = ""
        if has_identity:
            a, b = ident_current(sc, table), ident_current(tc, table)
            seed = f"{a:,} / {b:,}" + ("" if a == b else "   <-- MISMATCH")
            if a != b:
                bad.append(table)
        flag = "" if src_n == tgt_n else "   <-- ROW COUNT MISMATCH"
        if src_n != tgt_n:
            bad.append(table)
        print(f"  {table:<40}{src_n:>12,}{tgt_n:>12,}   {seed:<24}{flag}")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()

    tables = [x.strip() for x in a.only.split(",") if x.strip()] or LOAD_ORDER
    unknown = [x for x in tables if x not in LOAD_ORDER]
    if unknown:
        sys.exit(f"unknown table(s): {unknown}  (excluded by design: {sorted(EXCLUDED)})")

    s = pyodbc.connect(SRC, timeout=60)
    t = pyodbc.connect(TGT, timeout=60, autocommit=False)
    print(f"source : PRIME @ MISCPrdAdhocDB   (read-only)")
    print(f"target : PLM   @ YNBBSTVWP02\\PROCDATASRVPROD")
    print(f"tables : {len(tables)}   excluded: {sorted(EXCLUDED)}\n")

    if a.verify:
        bad = verify(s, t, tables)
        print("\n" + ("ALL MATCH" if not bad else f"MISMATCHES: {bad}"))
        return 0 if not bad else 1

    t0 = time.time()
    failed = [x for x in tables if not copy_table(s, t, x, a.dry_run)]
    if not a.dry_run:
        print(f"\ntotal {time.time() - t0:.1f}s")
        print("OK - now run sql/02_indexes.sql then sql/03_foreignkeys.sql"
              if not failed else f"FAILED: {failed}")
    s.close()
    t.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
