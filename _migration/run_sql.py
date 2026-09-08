"""
Execute a .sql script against the TARGET PLM database, splitting on GO batches.
sqlcmd is not installed on this machine, so this stands in for it.

    python run_sql.py sql/01_tables.sql
    python run_sql.py sql/01_tables.sql --dry-run    # list batches, execute nothing

Target only. This script has no connection to PRIME and cannot touch it.
"""
import argparse
import re
import sys
import time

import pyodbc

TGT = (r"DRIVER={ODBC Driver 17 for SQL Server};SERVER=YNBBSTVWP02\PROCDATASRVPROD;"
       "DATABASE=PLM;Trusted_Connection=yes;")

GO = re.compile(r"^\s*GO\s*(?:--.*)?$", re.I | re.M)


def batches(text):
    return [b.strip() for b in GO.split(text) if b.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    sql = open(a.script, encoding="utf-8").read()
    # USE is pointless here - the connection is already bound to PLM.
    parts = [b for b in batches(sql) if not re.fullmatch(r"USE\s*\[?\w+\]?\s*;?", b, re.I)]

    print(f"{a.script}  ->  PLM @ YNBBSTVWP02\\PROCDATASRVPROD")
    print(f"batches: {len(parts)}\n")
    if a.dry_run:
        for i, b in enumerate(parts, 1):
            print(f"  [{i:>3}] {b.splitlines()[0][:100]}")
        return 0

    cn = pyodbc.connect(TGT, timeout=120, autocommit=True)
    c = cn.cursor()
    t0 = time.time()
    failed = []
    for i, b in enumerate(parts, 1):
        head = b.splitlines()[0][:88]
        try:
            c.execute(b)
            # drain any PRINT / result sets so the next batch starts clean
            while True:
                if c.description:
                    for r in c.fetchall():
                        print("        " + "  ".join("" if v is None else str(v) for v in r))
                if not c.nextset():
                    break
            for m in cn.cursor().messages or []:
                print("        " + str(m[1]))
            print(f"  ok   [{i:>3}] {head}")
        except pyodbc.Error as e:
            failed.append((i, head, str(e)))
            print(f"  FAIL [{i:>3}] {head}\n           {str(e)[:300]}")
    cn.close()

    print(f"\n{len(parts) - len(failed)}/{len(parts)} batches ok in {time.time() - t0:.1f}s")
    if failed:
        print("FAILURES:")
        for i, head, err in failed:
            print(f"  [{i}] {head}\n      {err[:300]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
