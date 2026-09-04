# PLM migration — runbook

Moving the `PLM` schema from `PRIME` on `MISCPrdAdhocDB` to the `PLM` database on
`YNBBSTVWP02\PROCDATASRVPROD`. Rationale, decisions and risks are in
[MIGRATION_PLAN.md](MIGRATION_PLAN.md).

**The source is never written to.** Every script here either reads from PRIME or writes to the
target. Nothing drops, truncates or alters anything on `MISCPrdAdhocDB`.

## Files

| File | What it does |
|---|---|
| `generate_ddl.py` | Scripts the schema out of **live** PRIME into `sql/`. Re-run any time; never hand-edit the output. |
| `sql/01_tables.sql` | 23 `CREATE TABLE` — columns, identity, defaults, primary keys |
| `sql/02_indexes.sql` | Unique constraints and nonclustered indexes |
| `sql/03_foreignkeys.sql` | The 6 FKs — applied **after** the data load |
| `sql/04_views.sql` | 16 views, in dependency-tier order, remapped to three-part names |
| `sql/05_procs.sql` | 11 stored procedures, remapped |
| `sql/06_verify.sql` | Smoke test — object counts, reference resolution, every view executed |
| `sql/remap_report.txt` | Every external reference that was rewritten, for review |
| `copy_data.py` | Moves the table data, preserves identity seeds |

## Order of operations

```bash
# Phase 0 — regenerate from live PRIME (read-only)
python _migration/generate_ddl.py
#   then read sql/remap_report.txt and confirm "UNMAPPED: none"

# Phase 2 — structure
sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -i _migration/sql/01_tables.sql

# Phase 3 — data
python _migration/copy_data.py --dry-run     # counts both sides, changes nothing
python _migration/copy_data.py               # loads all 23 tables
python _migration/copy_data.py --verify      # row counts + identity seeds must match

sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -i _migration/sql/02_indexes.sql
sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -i _migration/sql/03_foreignkeys.sql

# Phases 4–5 — code
sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -i _migration/sql/04_views.sql
sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -i _migration/sql/05_procs.sql

# Phase 6 — verify, then uncomment the batch run at the bottom of the file
sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -i _migration/sql/06_verify.sql
```

`copy_data.py` is re-runnable — it clears each target table before reloading, so a failed run can
simply be repeated. Load it before `03_foreignkeys.sql`; on a re-run with FKs already in place it
loads parents first and uses `DELETE` on the two FK-referenced tables.

## Two things that are deliberately different from the source

1. **`ParItemBin` is not migrated** (Decision B). The target already carries `infor.ParItemBin`,
   sourced straight from Infor. Verified: no PLM view or procedure references it, so nothing breaks.
2. **External tables use three-part names** (Decision A) — `PLMPreprocessorShared.infor.<TABLE>`.
   Two are renamed on the target: `INVENTORY_LOCATION` → `ITEM_LOCATION` and
   `MDM_MANUFACTURER_NAME_INFOR` → `MDM_MANUFACTURER_NAME`.

## Cutover

Hard switch, after everything above is verified. The app change is two environment values:

```
DB_SERVER=YNBBSTVWP02\PROCDATASRVPROD
DB_NAME=PLM
```

Set them in `.env` (and regenerate `.env.enc`) rather than editing the defaults in
`app/config.py`, so rollback is a one-line revert. No model changes — the schema is still `PLM`.

## Status — migrated and verified 2026-09-04

Phases 2–6 are done. 23 tables, 16 views, 11 procedures live on the target; 2,168,280 rows loaded;
`usp_RunPLM_Batch` ran end to end with all 7 steps `Success`; the column and index diff against
source reports **zero differences**. Not yet cut over.

## Remaining work

- **Repoint the daily job.** The batch is driven by a daily job in a separate Python package, not a
  SQL Agent job. That package's connection string needs to move to
  `YNBBSTVWP02\PROCDATASRVPROD` / `PLM` at cutover.
- **Repoint this app** — the two `.env` values above, plus regenerate `.env.enc`.
- **Post-cutover (owner: Erhezi):** move the `BullardBurnDown` structure to the new server and
  repoint the Power BI dashboard.

## Note on `process_log.duration_ms`

It is a PERSISTED computed column. `copy_data.py` deliberately skips computed columns, and
`generate_ddl.py` emits them as formulas — do not "fix" either to insert into it.
