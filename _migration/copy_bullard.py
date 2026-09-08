r"""
One-time - copy the BullardBurnDown table data from PRIME to PBI on O2.

The PLM migration moved the PLM schema only; BullardBurnDown was left behind as
post-cutover follow-up. The target tables already exist in the PBI database on
YNBBSTVWP02\PROCDATASRVPROD - this moves their contents across.

Reads from PRIME. Writes ONLY to the target. The source is never modified:
no DELETE, no TRUNCATE, no ALTER is ever issued against PRIME.

Usage
    python copy_bullard.py --dry-run     # connect, count both sides, change nothing
    python copy_bullard.py               # load both tables
    python copy_bullard.py --only SearchTerms
    python copy_bullard.py --verify      # compare row counts + table checksums only

Re-runnable: each table is cleared on the target before reloading, so a failed run
can simply be repeated. Re-run it once the daily job is repointed, to pick up the
rows PRIME collected in the meantime.
"""
import argparse
import sys
import time

import pyodbc

SRC = ("DRIVER={ODBC Driver 17 for SQL Server};SERVER=MISCPrdAdhocDB;"
       "DATABASE=PRIME;Trusted_Connection=yes;")
TGT = (r"DRIVER={ODBC Driver 17 for SQL Server};SERVER=YNBBSTVWP02\PROCDATASRVPROD;"
       "DATABASE=PBI;Trusted_Connection=yes;")

SCHEMA = "BullardBurnDown"
BATCH = 5000

# No FKs in this schema on either side, so plain TRUNCATE is safe on the target.
TABLES = [
    "DailyArchive",
    "SearchTerms",
]


def columns(cur, table):
    # is_computed columns are formulas - they cannot be inserted into.
    cur.execute("""SELECT c.name, c.is_identity
                   FROM sys.columns c
                   JOIN sys.objects o ON c.object_id = o.object_id
                   JOIN sys.schemas s ON o.schema_id = s.schema_id
                   WHERE s.name = ? AND o.name = ? AND c.is_computed = 0
                   ORDER BY c.column_id""", SCHEMA, table)
    rows = cur.fetchall()
    return [r[0] for r in rows], any(r[1] for r in rows)


def count(cur, table):
    cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.[{table}]")
    return cur.fetchone()[0]


def checksum(cur, table):
    """Order-independent fingerprint of the whole table, for verification."""
    cur.execute(f"SELECT CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM {SCHEMA}.[{table}]")
    return cur.fetchone()[0]


def copy_table(s, t, table, dry):
    sc, tc = s.cursor(), t.cursor()
    cols, has_identity = columns(sc, table)
    src_n = count(sc, table)

    try:
        tgt_n_before = count(tc, table)
    except pyodbc.Error:
        print(f"  {table:<30} TARGET TABLE MISSING on PBI")
        return False

    if dry:
        print(f"  {table:<30} source={src_n:>10,}  target={tgt_n_before:>10,}  "
              f"cols={len(cols)}  identity={'yes' if has_identity else 'no'}")
        return True

    collist = ", ".join(f"[{c}]" for c in cols)
    params = ", ".join("?" * len(cols))

    tc.execute(f"TRUNCATE TABLE {SCHEMA}.[{table}]")
    t.commit()

    t0 = time.time()
    if src_n:
        tc.fast_executemany = True
        if has_identity:
            tc.execute(f"SET IDENTITY_INSERT {SCHEMA}.[{table}] ON")
        sc.execute(f"SELECT {collist} FROM {SCHEMA}.[{table}]")
        while True:
            rows = sc.fetchmany(BATCH)
            if not rows:
                break
            tc.executemany(
                f"INSERT INTO {SCHEMA}.[{table}] ({collist}) VALUES ({params})",
                [tuple(r) for r in rows])
            t.commit()
        if has_identity:
            tc.execute(f"SET IDENTITY_INSERT {SCHEMA}.[{table}] OFF")
        t.commit()

    tgt_n = count(tc, table)
    ok = tgt_n == src_n
    print(f"  {'OK ' if ok else 'BAD'} {table:<28} {tgt_n:>10,} / {src_n:<10,} rows  "
          f"{time.time() - t0:>6.1f}s")
    return ok


def verify(s, t, tables):
    sc, tc = s.cursor(), t.cursor()
    print(f"  {'TABLE':<30}{'SOURCE':>12}{'TARGET':>12}   {'CHECKSUM src/tgt':<30}")
    bad = []
    for table in tables:
        src_n = count(sc, table)
        try:
            tgt_n = count(tc, table)
        except pyodbc.Error:
            print(f"  {table:<30}{src_n:>12,}{'MISSING':>12}")
            bad.append(table)
            continue
        a, b = checksum(sc, table), checksum(tc, table)
        note = f"{a} / {b}" + ("" if a == b else "   <-- CHECKSUM MISMATCH")
        if a != b or src_n != tgt_n:
            bad.append(table)
        flag = "" if src_n == tgt_n else "   <-- ROW COUNT MISMATCH"
        print(f"  {table:<30}{src_n:>12,}{tgt_n:>12,}   {note:<30}{flag}")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()

    tables = [x.strip() for x in a.only.split(",") if x.strip()] or TABLES
    unknown = [x for x in tables if x not in TABLES]
    if unknown:
        sys.exit(f"unknown table(s): {unknown}  (known: {TABLES})")

    s = pyodbc.connect(SRC, timeout=60)
    t = pyodbc.connect(TGT, timeout=60, autocommit=False)
    print(f"source : PRIME @ MISCPrdAdhocDB   (read-only)")
    print(r"target : PBI   @ YNBBSTVWP02\PROCDATASRVPROD")
    print(f"schema : {SCHEMA}   tables: {len(tables)}\n")

    if a.verify:
        bad = verify(s, t, tables)
        print("\n" + ("ALL MATCH" if not bad else f"MISMATCHES: {bad}"))
        return 0 if not bad else 1

    t0 = time.time()
    failed = [x for x in tables if not copy_table(s, t, x, a.dry_run)]
    if not a.dry_run:
        print(f"\ntotal {time.time() - t0:.1f}s")
        print("OK - now run --verify" if not failed else f"FAILED: {failed}")
    s.close()
    t.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
