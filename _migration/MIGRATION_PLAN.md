# PLM Migration Plan — PRIME → PLM (branch `migrateO2`)

**Status:** REVIEWED — decisions locked 2026-09-04. Building migration scripts.
**Rule for this whole effort:** nothing is dropped, truncated, or altered on the source. Source stays live and authoritative until we jointly agree to cut over.

---

## 0. Decisions (locked)

| # | Decision | Ruling |
|---|---|---|
| A | How to reference the `infor` tables | **Three-part names** — `PLMPreprocessorShared.infor.MDM_ITEM`. Traditional and unambiguous; no synonym layer for other team members to decode. |
| B | `ParItemBin` | **Not migrated.** `infor.ParItemBin` already on the target is an unchanged table sourced directly from Infor, used only by the PLM app. Already marked done. `PLM.ParItemBin` stays behind → **23 tables to migrate, not 24.** |
| C | `PastYearRequestersCount`, `WrikeTask` | **Migrate as-is.** Not used today, but keep them available for future use. |
| D | `usp_RunPLM_Batch` | Definition supplied. It is a sequential driver — a cursor over 7 procs at ord 10/20/30/40/50/70/80, each wrapped in TRY/CATCH and logged to `PLM.process_log`, continuing on error (fail-fast `THROW` is commented out). No external table references; migrates unchanged. |
| E | `BullardBurnDown.vw_PLMIntegration` | **Owned by you.** Stays on PRIME for now. → see Post-migration follow-up below. |
| F | Cutover style | **Hard switch**, once everything is verified and tested. No parallel-run period. |

### Post-migration follow-up (owner: Erhezi)

After PLM is live on the new server:
1. Move the **BullardBurnDown** structure to `YNBBSTVWP02\PROCDATASRVPROD`.
2. Repoint the **Power BI dashboard** to the new server.

Until step 1 happens, `BullardBurnDown.vw_PLMIntegration` on PRIME reads a `PLM` schema that is no longer being written to — it goes stale at cutover, by design.

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

## 2. What has to move — 50 objects

**23 tables · 16 views · 11 stored procedures**, totalling **2,857,123 rows / 373.6 MB** (ParItemBin excluded per Decision B). This is small; the data copy is not the hard part.

### 2.1 Tables (23 migrated + 1 excluded)

| Table | Rows | Size | Identity | Written by |
|---|---:|---:|:--:|---|
| `DailyIssueOutQty` | 1,291,669 | 277.9 MB | | sp_PLM_extractDailyIssueOutQty_FullRefresh |
| `PLMItemBRRolling_Log` | 894,710 | 28.0 MB | `run_id` | sp_PLM_MakePLMItemBRRolling_InvID_PKID |
| `PLMItemGroupBRRolling_Log` | 480,210 | 16.5 MB | `run_id` | sp_PLM_MakePLMItemGroupBRRolling_ItemGroup |
| `PastYearRequestersCount` | 44,585 | 2.3 MB | | external ETL — no writer; migrate as-is (Decision C) |
| `ItemLocations` | 43,981 | 14.8 MB | | sp_PLM_MakeItemLocations_FullRefresh |
| `ItemLocationsBR` | 43,981 | 13.0 MB | | sp_PLM_MakeItemLocationsBR_FullRefresh |
| `ItemStartEndDate` | 43,981 | 8.0 MB | | sp_PLM_MakeItemStartEndDate_FullRefresh |
| `PLMItemBRRolling` | 6,305 | 7.1 MB | | sp_PLM_MakePLMItemBRRolling / Persist |
| ~~`ParItemBin`~~ | ~~5,824~~ | ~~1.6 MB~~ | | **EXCLUDED** — target already has `infor.ParItemBin` (Decision B) |
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
| `WrikeTask` | 6 | 0.1 MB | | external ETL — no writer; migrate as-is (Decision C) |
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

Deploy after tables + views (several call views; two call each other). `usp_RunPLM_Batch` is the orchestrator: a cursor over 7 procs in ord order **10 MakeItemLocations → 20 MakeItemStartEndDate → 30 extractDailyIssueOutQty → 40 MakeItemLocationsBR → 50 ProcessPendingItems → 70 MakePLMItemGroupBRRolling → 80 MakePLMItemBRRolling**, each in TRY/CATCH and logged to `PLM.process_log`, continuing past errors. Note `sp_MakeCopyItemLink` and the two Persist procs are *not* in the batch — the Persist procs are called from inside the two Make…Rolling procs. Last ran **2026-09-04 08:09**.

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

### 3.1 How we reference them — RESOLVED (Decision A)

**Three-part names.** Every reference becomes `PLMPreprocessorShared.infor.<TABLE>`, spelled out in
full in each module. No synonym layer — the point is that any team member reading the view can see
exactly which database and schema the data comes from without chasing an indirection.

The two renames are applied literally at each site:

```
[DM_MONTYNT\dli2].INVENTORY_LOCATION           -> PLMPreprocessorShared.infor.ITEM_LOCATION
[DM_MONTYNT\dli2].MDM_MANUFACTURER_NAME_INFOR  -> PLMPreprocessorShared.infor.MDM_MANUFACTURER_NAME
[DM_MONTYNT\dli2].<other 7>                    -> PLMPreprocessorShared.infor.<same name>
```

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
| 1 | *(dropped — Decision A chose three-part names; no synonyms to create)* | n/a |
| 2 | Create **23** tables (PKs, defaults, identity) in target — ParItemBin excluded | no |
| 3 | Copy data, reseed identities, add FKs + indexes, verify counts | read-only |
| 4 | Deploy 16 views in tier order, with the 12 remapped queries | no |
| 5 | Deploy 11 procs | no |
| 6 | Smoke test: run every view; run `usp_RunPLM_Batch` end-to-end on target | no |
| 7 | Parallel-run + reconcile target vs source outputs | read-only |
| 8 | Point app at target via `.env`; keep source untouched as rollback | no |
| 9 | Hand DBA the job/ETL repointing list | no |

Phases 0–6 are all reversible and invisible to production.

---

## 8. Questions — all resolved

| Q | Answer |
|---|---|
| 1. Synonyms or three-part names? | Three-part names. Keep it traditional so naming does not confuse other team members. |
| 2. `ParItemBin` | Keep the target's `infor.ParItemBin`; do not migrate `PLM.ParItemBin`. It is an unchanged Infor-sourced table used only by the PLM app, already marked done. |
| 3. `PastYearRequestersCount`, `WrikeTask` | Migrate as-is. Not needed today, possibly needed later. |
| 4. What schedules `usp_RunPLM_Batch`? | Proc definition supplied (see §0/D). The SQL Agent job that *calls* it still needs a DBA to enumerate and recreate — `msdb.dbo.sysjobsteps` remains unreadable to us. **Still open as an operational task, not a design question.** |
| 5. `BullardBurnDown.vw_PLMIntegration` | Owned by Erhezi. Will be moved to the new server after PLM go-live, along with a Power BI repoint. |
| 6. Cutover style | Hard switch after full verification and testing. |

## 9. Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Migrating from stale `_query_backup` | **High** | Re-script from live (§4). Already caught one broken view. |
| Missed rename (`INVENTORY_LOCATION`, `MDM_MANUFACTURER_NAME_INFOR`) | High | Both identified; remap is scripted, not hand-edited, and the deploy verifies every module compiles. |
| Identity seeds not preserved → PK collisions | High | Explicit reseed list in §5. |
| FK load-order failure | Medium | Load `ItemGroup`/`ItemLink` first; add FKs after data. |
| Orphaned ETL feeds | Low | Resolved: ParItemBin stays on target as `infor.ParItemBin`; the other two migrate as-is. |
| Unknown SQL Agent job wrapping `usp_RunPLM_Batch` | **Medium — still open** | Needs a DBA to list source jobs and recreate on target, or grant `SQLAgentReaderRole`. Blocks phase 9 only. |
| `infor` feed on target drifts from source | Low | Verified in exact sync today; re-verify at cutover. |
| Hard switch leaves no parallel safety net | Medium | Phase 6/7 verification must be thorough: every view runs, full batch executes, row counts reconcile against source before the switch. Source stays intact as rollback. |
| Collation mismatch | None | Verified identical. |
