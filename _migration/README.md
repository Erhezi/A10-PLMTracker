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
| `copy_bullard.py` | One-time — moves the `BullardBurnDown` data to the `PBI` database on O2 |

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

## Cutover — the app connection

`app/config.py` holds a registry of named backends, so switching is one environment variable and
no code edit:

```python
DB_TARGETS = {
    "O2":    {"server": r"YNBBSTVWP02\PROCDATASRVPROD", "database": "PLM"},
    "PRIME": {"server": "MISCPrdAdhocDB",                "database": "PRIME"},
}
DEFAULT_DB_TARGET = "O2"
```

**O2 is the default**, so the cutover needs no configuration at all — nothing to add to `.env`, and
`.env.enc` does not need regenerating (it never held connection details).

To roll back, set one variable:

```
DB_TARGET=PRIME
```

Escape hatches, in precedence order: `DATABASE_URL` overrides everything; `DB_SERVER` / `DB_NAME` /
`ODBC_DRIVER` / `DB_TRUSTED` override individual values of the selected target; otherwise the
registry wins. An unknown `DB_TARGET` fails loudly at import rather than silently falling back.

`Config.describe_db()` reports which backend the running process is actually using — worth logging
or exposing on a health endpoint for the first few days after cutover.

No model changes were needed: `app/__init__.py` binds `MetaData(schema="PLM")` and the schema name
is `PLM` on both servers.

### Code rollback point — `c981975`

The state of `main` **before this branch was merged** is the rollback point for everything in this
migration:

```
c981975  adding discontinued field to par table, add discontinued field to group.html export
```

It is tagged `pre-o2-cutover` so it stays findable no matter what `main` does next. That commit is
the last version of the app with no migration code in the tree, still pointing at
`MISCPrdAdhocDB` / `PRIME`.

If the cutover has to be undone:

```bash
# preferred on a shared main — no force push
git revert -m 1 6699ad4          # the "Merge branch 'migrateO2'" commit

# or, to inspect / redeploy the pre-migration tree
git checkout pre-o2-cutover
```

Nothing has to be undone on the database side: PRIME was never written to, so it is still live and
authoritative. `DB_TARGET=PRIME` (above) is the fast rollback and needs no git operation at all —
going back to `c981975` is the fuller one, for when the code changes themselves are the suspect.

### A note on the URI format

The URI is built with `odbc_connect` rather than putting the host in the URL, because
`YNBBSTVWP02\PROCDATASRVPROD` is a **named instance** — that backslash is not valid unescaped in a
URL host and the old `mssql+pyodbc://{server}/{db}` form is unreliable with it.

## Status — migrated and verified 2026-09-04

Phases 2–6 are done. 23 tables, 16 views, 11 procedures live on the target; 2,168,280 rows loaded;
`usp_RunPLM_Batch` ran end to end with all 7 steps `Success`; the column and index diff against
source reports **zero differences**. Not yet cut over.

## Remaining work

- **Repoint the daily job.** The batch is driven by a daily job in a separate Python package, not a
  SQL Agent job. That package's connection string needs to move to
  `YNBBSTVWP02\PROCDATASRVPROD` / `PLM` at cutover.
- ~~Repoint this app~~ — **done.** `DEFAULT_DB_TARGET = "O2"` in `app/config.py`; app verified live against the new server, 50/50 tests passing.
- ~~Move the `BullardBurnDown` data~~ — **done 2026-09-08.** See below.
- **Repoint the Power BI dashboard** at `PBI` on `YNBBSTVWP02\PROCDATASRVPROD` (owner: Erhezi).
- **Repoint whatever writes `BullardBurnDown.DailyArchive` daily.** Until then PRIME keeps
  collecting new rows and the O2 copy goes stale — re-run `copy_bullard.py` when it moves.

## BullardBurnDown data move — 2026-09-08

The structure was already created on the target by Erhezi, in the **`PBI`** database (not `PLM`),
schema `BullardBurnDown`. `copy_bullard.py` moved the contents:

| Table | Rows | Checksum |
|---|---|---|
| `DailyArchive` | 183,623 | matches source |
| `SearchTerms` | 1,365 | matches source |

Verified with `--verify`: row counts and `CHECKSUM_AGG(BINARY_CHECKSUM(*))` identical on both sides.
All 6 `BullardBurnDown` views on the target return counts identical to PRIME, `vw_PLMIntegration`
included — so its cross-database reference to `PLM` on O2 resolves.

Index parity was restored after the load — the target was missing the source's nonclustered
`IX_DailyArchive_Date`, created 2026-09-08:

```sql
CREATE NONCLUSTERED INDEX IX_DailyArchive_Date
    ON BullardBurnDown.DailyArchive ([Date]);
```

Both tables now match source on the PK and on every nonclustered index.

Note the table is `SearchTerms`, plural, on both servers.

## Note on `process_log.duration_ms`

It is a PERSISTED computed column. `copy_data.py` deliberately skips computed columns, and
`generate_ddl.py` emits them as formulas — do not "fix" either to insert into it.
