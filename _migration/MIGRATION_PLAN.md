# PLM Migration Plan — PRIME → PLM (branch `migrateO2`)

**Status:** DRAFT FOR REVIEW — no changes made to any server yet.
**Rule for this whole effort:** nothing is dropped, truncated, or altered on the source. Source stays live and authoritative until we jointly agree to cut over.

---

## 1. Endpoints

| | **Source** | **Target** |
|---|---|---|
| Alias used by app | `MISCPrdAdhocDB` | `YNBBSTVWP02\PROCDATASRVPROD` |
| Real instance | `ODCUCSSQLBWP02` (10.161.88.221) | `YNBBSTVWP02\PROCDATASRVPROD` (10.87.192.93) |
| Database | `PRIME` | `PLM` |
| Schema | `PLM` | `PLM` — exists, currently **empty** |
| Collation | `SQL_Latin1_General_CP1_CI_AS` | identical ✓ |
| Compatibility level | 130 (SQL 2016) | **150 (SQL 2019)** ⚠ |
| Recovery model | FULL | FULL |
| Our access | read | **db_owner** ✓ (CREATE TABLE/VIEW/PROC/SCHEMA all confirmed) |

**These are two different physical machines.** Nothing can be done with cross-database queries — every row has to move over the wire, and the source's `[DM_MONTYNT\dli2]` tables are not reachable from the target.

---

## 2. What has to move — 51 objects

**24 tables · 16 views · 11 stored procedures**, totalling **2,862,947 rows / 375 MB**. This is small; the data copy is not the hard part.

### 2.1 Tables (24)

| Table | Rows | Size | Identity | Written by |
|---|---:|---:|:--:|---|
| `DailyIssueOutQty` | 1,291,669 | 277.9 MB | | sp_PLM_extractDailyIssueOutQty_FullRefresh |
| `PLMItemBRRolling_Log` | 894,710 | 28.0 MB | `run_id` | sp_PLM_MakePLMItemBRRolling_InvID_PKID |
| `PLMItemGroupBRRolling_Log` | 480,210 | 16.5 MB | `run_id` | sp_PLM_MakePLMItemGroupBRRolling_ItemGroup |
| `PastYearRequestersCount` | 44,585 | 2.3 MB | | **external ETL — no writer found** |
| `ItemLocations` | 43,981 | 14.8 MB | | sp_PLM_MakeItemLocations_FullRefresh |
| `ItemLocationsBR` | 43,981 | 13.0 MB | | sp_PLM_MakeItemLocationsBR_FullRefresh |
| `ItemStartEndDate` | 43,981 | 8.0 MB | | sp_PLM_MakeItemStartEndDate_FullRefresh |
| `PLMItemBRRolling` | 6,305 | 7.1 MB | | sp_PLM_MakePLMItemBRRolling / Persist |
| `ParItemBin` | 5,824 | 1.6 MB | | **external ETL — no writer found** |
| `PLMItemGroupBRRolling` | 3,681 | 2.0 MB | | sp_PLM_MakePLMItemGroupBRRolling / Persist |
| `process_log` | 2,758 | 0.8 MB | `pkid` | usp_RunPLM_Batch |
| `ItemGroupLink` | 344 | 0.3 MB | `PKID` | sp_ProcessPendingItems |
| `ItemGroup` | 336 | 0.2 MB | `PKID` | sp_ProcessPendingItems / Persist procs |
| `ItemLink` | 173 | 0.6 MB | `PKID` | sp_ProcessPendingItems, sp_MakeCopyItemLink, app |
| `ItemLinkWrike` | 173 | 0.2 MB | `PKID` | app |
| `ItemLink_copy` | 164 | 0.1 MB | `PKID` | sp_MakeCopyItemLink |
| `burn_rate_refresh_job` | 18 | 0.1 MB | `id` | app |
| `ItemLinkArchived` | 16 | 0.4 MB | `PKID` | app |
| `PendingItems` | 15 | 0.3 MB | `PKID` | sp_ProcessPendingItems |
| `users` | 14 | 0.2 MB | `user_id` | app (auth) |
| `WrikeTask` | 6 | 0.1 MB | | **external ETL — no writer found** |
| `ConflictError` | 3 | 0.3 MB | `PKID` | sp_ProcessPendingItems |
| `ConflictErrorPendingItemAddition_log` | 0 | 0.0 MB | `PKID` | sp_ProcessPendingItems |
| `ItemLinkDeleted` | 0 | 0.4 MB | `PKID` | app |

Structural facts that shape the load: **15 identity columns** (need `SET IDENTITY_INSERT` + reseed), **6 foreign keys** (dictate load order), **9 default constraints**, **0 check constraints, 0 triggers, 0 computed columns** — a clean, simple structure.

FK load order: `ItemGroup` and `ItemLink` must land before `ItemGroupLink`, `PendingItems`, `ConflictError`, `ItemLinkWrike`, `burn_rate_refresh_job`.

### 2.2 Views (16) — deploy in this order

```
TIER 1  vw_365Day_Requesters, vw_90Day_PO, vw_ContractItem, vw_Item,
        vw_ItemReplacementCardinality, vw_ItemUOM, vw_PLMDailyIssueOutQty,
        vw_PLMItemCommodityCode, vw_PLMItemGroupLocation,
        vw_PLMPendingItemsExport, vw_orphan_node
TIER 2  vw_PLMReplacementActiveStatus (→vw_Item), vw_PLMTrackerHead (→vw_PLMItemGroupLocation)
TIER 3  vw_PLMTrackerBase (→vw_PLMTrackerHead), vw_PLMZDate (→vw_PLMTrackerHead)
TIER 4  vw_PLMQty (→vw_PLMZDate)
```

### 2.3 Stored procedures (11)

`sp_MakeCopyItemLink`, `sp_PLM_extractDailyIssueOutQty_FullRefresh`, `sp_PLM_MakeItemLocations_FullRefresh`, `sp_PLM_MakeItemLocationsBR_FullRefresh`, `sp_PLM_MakeItemStartEndDate_FullRefresh`, `sp_PLM_MakePLMItemBRRolling_InvID_PKID`, `sp_PLM_MakePLMItemGroupBRRolling_ItemGroup`, `sp_PLM_PersistItemBRRolling`, `sp_PLM_PersistItemGroupBRRolling`, `sp_ProcessPendingItems`, `usp_RunPLM_Batch`

Deploy after tables + views (several call views; two call each other). `usp_RunPLM_Batch` is the orchestrator — it last ran **2026-09-04 08:09**, so a scheduler is actively driving it.

---

## 3. The external-data remap — this is the actual work

Every PLM view/proc that reaches outside the schema hits exactly **9 tables** in `PRIME.[DM_MONTYNT\dli2]`. All 9 exist on the target, in **`PLMPreprocessorShared.infor`**.

I verified each pair on both servers: **identical column count, identical column names, identical data types, identical row counts, and identical `MAX([update stamp])`.** The target feed is not a stale copy — it is in live lockstep with the source.

| Source `PRIME.[DM_MONTYNT\dli2].*` | Target `PLMPreprocessorShared.infor.*` | Cols | Rows | Note |
|---|---|---:|---:|---|
| `CONTRACTLINE` | `CONTRACTLINE` | 49 | 634,844 | |
| `INVENTORY_TRANSACTION` | `INVENTORY_TRANSACTION` | 41 | 3,555,523 | |
| `MDM_ITEM` | `MDM_ITEM` | 35 | 13,252 | |
| `MDM_ITEMUOM` | `MDM_ITEMUOM` | 18 | 25,266 | |
| `MDM_REQUESTER` | `MDM_REQUESTER` | 8 | 3,414 | |
| `PURCHASEORDER_LINE` | `PURCHASEORDER_LINE` | 87 | 2,545,248 | |
| `REQUISITION_LINE` | `REQUISITION_LINE` | 55 | 6,130,071 | |
| `INVENTORY_LOCATION` | **`ITEM_LOCATION`** | 50 | 1,771,362 | ⚠ **RENAMED** |
| `MDM_MANUFACTURER_NAME_INFOR` | **`MDM_MANUFACTURER_NAME`** | 5 | 2,071 | ⚠ **RENAMED** |

**The catch:** these live in the `PLMPreprocessorShared` database, *not* in the `PLM` database we are migrating into. Same server, so a cross-database reference works — but the object names in our code must change either way.

### 3.1 DECISION A — how to reference them

**Option 1 — three-part names.** Rewrite every reference to `PLMPreprocessorShared.infor.MDM_ITEM`. Explicit, but hard-codes the source database name into 12 modules; any future move means editing all of them again.

**Option 2 — local synonyms (recommended).** Create an `infor` schema inside the `PLM` database holding 9 synonyms pointing at `PLMPreprocessorShared.infor.*`. Module code then reads `infor.MDM_ITEM` — short, matches the mental model of "the data is under schema infor", and if that data ever moves again we repoint 9 synonyms instead of editing 12 modules. It also absorbs the two renames in one place, so `INVENTORY_LOCATION` can stay spelled that way in our SQL if we want a smaller diff.

I recommend Option 2, with synonyms named after the **target** names (`infor.ITEM_LOCATION`, `infor.MDM_MANUFACTURER_NAME`) so the code reads truthfully.

### 3.2 Modules requiring query edits — 12 of 27

| Module | External tables it uses |
|---|---|
| `vw_365Day_Requesters` | REQUISITION_LINE, MDM_REQUESTER |
| `vw_90Day_PO` | PURCHASEORDER_LINE, MDM_ITEMUOM |
| `vw_ContractItem` | CONTRACTLINE, **MDM_MANUFACTURER_NAME_INFOR** (rename) |
| `vw_Item` | MDM_ITEM |
| `vw_ItemUOM` | MDM_ITEMUOM |
| `vw_PLMItemCommodityCode` | MDM_ITEM |
| `vw_PLMPendingItemsExport` | CONTRACTLINE |
| `vw_PLMQty` | **INVENTORY_LOCATION** (rename), MDM_ITEMUOM |
| `vw_PLMTrackerBase` | MDM_ITEM, MDM_ITEMUOM |
| `sp_PLM_MakeItemLocations_FullRefresh` | **INVENTORY_LOCATION** (rename), MDM_ITEMUOM |
| `sp_PLM_MakeItemStartEndDate_FullRefresh` | **INVENTORY_LOCATION** (rename) |
| `sp_PLM_extractDailyIssueOutQty_FullRefresh` | INVENTORY_TRANSACTION, MDM_ITEMUOM |

The other 15 modules are pure-PLM and move unchanged.

### 3.3 One thing to watch — `INVENTORY_TRANSACTION` history split

Source has `INVENTORY_TRANSACTION` + `INVENTORY_TRANSACTION_PR1_BEFORE2025`; target has `INVENTORY_TRANSACTION` + `INVENTORY_TRANSACTION_P1_PriorTo2025`. The main tables match row-for-row (3,555,523), and `sp_PLM_extractDailyIssueOutQty_FullRefresh` only looks back 365 days, so the archive split does not affect us. Worth a re-check if anyone ever widens that lookback.

---

## 4. ⚠ The `_query_backup` folder is stale — do not migrate from it

`_query_backup/*.sql` was scripted in **Feb 2026**. Since then at least three objects changed on the live server:

- `sp_ProcessPendingItems` — modified **2026-07-10**
- `vw_ContractItem` — modified **2026-07-09**
- `sp_MakeCopyItemLink` — modified **2026-04-06** (has no backup file at all)

Concrete proof of the drift: the backup copy of `vw_ContractItem` joins to `[DM_MONTYNT\dli2].ccx_dump_validation_stg` for an `is_mhs` flag. **That table no longer exists in PRIME**, and the live view no longer references it — the live view runs fine and returns 600,528 rows. Had we migrated from the backup, that view would have failed on the target and we'd have chased a phantom missing table.

**Action:** all DDL gets re-scripted from `sys.sql_modules` on the live server at migration time. I have already pulled a fresh set of all 27 module definitions as a baseline. Also note the backup filename `[PLM].usp_RunPLMBatch.sql` does not match the real object name `usp_RunPLM_Batch`.

---

## 5. Data movement

Nothing exotic needed at 375 MB. Ranked by my preference:

1. **Python + pyodbc `fast_executemany`** — already have the driver, the venv, and connectivity to both ends from this machine; scriptable, resumable, and diff-able. Handles `IDENTITY_INSERT` and per-table batching cleanly.
2. **SSIS / Import-Export Wizard** — fine, but manual and less repeatable for a rehearsal-then-real run.
3. **Linked server** — requires DBA setup and firewall between two subnets (10.161.x ↔ 10.87.x); more moving parts than this job warrants.
4. **BACPAC / backup-restore** — wrong shape; we want one schema out of an 888-table database, not the whole thing.

Load sequence per table: create table → disable/skip FKs → `SET IDENTITY_INSERT ON` where applicable → bulk insert → `IDENTITY_INSERT OFF` → **reseed identity to source `IDENT_CURRENT`** → re-add FKs → create indexes → row-count + checksum verification.

Identity reseed values to preserve (app hands out these PKIDs): `ItemLink`=369, `ItemGroup`=714, `ItemGroupLink`=360, `PendingItems`=28, `ItemLinkWrike`=304, `users`=18, `process_log`=1434, `burn_rate_refresh_job`=204, `ConflictError`=105, `PLMItemBRRolling_Log`=1135370, `PLMItemGroupBRRolling_Log`=613203, plus `ItemLink_copy`=360, `ItemLinkArchived`=17, `ItemLinkDeleted`=18, `ConflictErrorPendingItemAddition_log`=1.

---

## 6. Application change

Smaller than expected. `app/__init__.py` binds `MetaData(schema="PLM")` and the target schema is also `PLM`, so **no model changes at all**. The entire app-side change is two values in [app/config.py:11-12](app/config.py#L11-L12), both already env-overridable:

```
DB_SERVER = YNBBSTVWP02\PROCDATASRVPROD     (was MISCPrdAdhocDB)
DB_NAME   = PLM                              (was PRIME)
```

Set them in `.env` rather than editing defaults, so rollback is a one-line revert. Note `.env` is encrypted to `.env.enc` — that needs regenerating too.

---

## 7. Proposed sequence

| Phase | Work | Touches source? |
|---|---|---|
| 0 | Re-script all 27 modules + 24 table DDL from live PRIME | read-only |
| 1 | Create `infor` schema + 9 synonyms in target PLM db (Decision A) | no |
| 2 | Create 24 tables (PKs, defaults, identity) in target | no |
| 3 | Copy data, reseed identities, add FKs + indexes, verify counts | read-only |
| 4 | Deploy 16 views in tier order, with the 12 remapped queries | no |
| 5 | Deploy 11 procs | no |
| 6 | Smoke test: run every view; run `usp_RunPLM_Batch` end-to-end on target | no |
| 7 | Parallel-run + reconcile target vs source outputs | read-only |
| 8 | Point app at target via `.env`; keep source untouched as rollback | no |
| 9 | Hand DBA the job/ETL repointing list | no |

Phases 0–6 are all reversible and invisible to production.

---

## 8. Open questions for you

1. **Decision A** — synonyms (my recommendation) or three-part names?
2. **`ParItemBin`** — the target PLM database *already* contains `infor.ParItemBin` with 5,824 rows and a byte-identical column list. Someone has started staging this. Do we keep our own `PLM.ParItemBin` copy, or adopt `infor.ParItemBin` as the single source? (Nothing in PLM code references this table today, so either is safe.)
3. **Three tables have no writer and no reader** — `ParItemBin`, `PastYearRequestersCount` (44,585 rows), `WrikeTask`. No live PLM module and no app code touches them. Migrate as-is, or leave them behind? If they are fed by an outside ETL that someone still consumes, that feed needs repointing and I need to know who owns it.
4. **SQL Agent jobs** — my login is denied `SELECT` on `msdb.dbo.sysjobsteps`, so I cannot enumerate what schedules `usp_RunPLM_Batch` (it ran today at 08:09). Need a DBA to list the source jobs and recreate them on the target, or grant `SQLAgentReaderRole`.
5. **`BullardBurnDown.vw_PLMIntegration`** — this view in PRIME reads from `PLM.*` and is the only outside consumer. It keeps working since we drop nothing, but it will go stale the moment PLM writes move to the new server. Who owns it?
6. **Compat level 130 → 150** — the target runs the newer cardinality estimator. Behaviour is equivalent but plans can differ; I'd rather find out during the phase 7 parallel run than after cutover. Flagging it, not proposing action.
7. **Cutover style** — hard switch, or parallel-run both for a period? Phase 7 assumes parallel; happy to compress if you want it faster.

---

## 9. Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Migrating from stale `_query_backup` | **High** | Re-script from live (§4). Already caught one broken view. |
| Missed rename (`INVENTORY_LOCATION`, `MDM_MANUFACTURER_NAME_INFOR`) | High | Both identified; synonyms confine them to one place. |
| Identity seeds not preserved → PK collisions | High | Explicit reseed list in §5. |
| FK load-order failure | Medium | Load `ItemGroup`/`ItemLink` first; add FKs after data. |
| Orphaned ETL feeds (`ParItemBin` etc.) | Medium | Open question 3 — needs an owner. |
| Unknown SQL Agent jobs | Medium | Open question 4 — needs DBA. |
| `infor` feed on target drifts from source | Low | Verified in exact sync today; re-verify at cutover. |
| Collation mismatch | None | Verified identical. |
