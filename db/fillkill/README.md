# Item Management database scripts (access + Fill/Kill)

Run by hand on O2 (`YNBBSTVWP02\PROCDATASRVPROD`), database `PLM`, in number order, with sqlcmd or
SSMS. Every script is safe to re-run. The app never changes the database's structure itself, with
one exception to avoid: **don't start this code against O2 before the scripts.** On startup it
creates any missing table from its models (`db.create_all`), with constraint names SQL Server makes
up. That is how `UserModuleRole` first appeared; `02` repairs it, and `12` matches the app's names
for its tables.

The design is in `_ref/FillKill/fillkill_design.md`; the build plans are
`_ref/FillKill/fillkill_implementation_plan_v1.md` (access) and `..._v2.md` (Fill/Kill).

## Is the database up to date?

- **`09_verify.sql`**, read-only, after any script: every row says `PASS`, except
  `users.user_role is admin or user`, which says `PENDING` until `04` runs after the deploy. A
  Fill/Kill check names the script that fixes it.
- **The app checks too:** admins see a warning on Fill/Kill's Main page listing anything missing,
  with the script to run; on the web server, `flask fillkill check-db` prints the same list. It
  uses the app's own account, so it also catches a missing read grant or EXECUTE permission, which
  `09` can't.
- `app/fillkill/health.py` holds what the app needs. When a script changes that, change
  `health.py` and `09` with it.

## The scripts

| Script | What it does | When to re-run |
| --- | --- | --- |
| `01_schema.sql` | Creates the empty `FillKill` schema. | Never needed. |
| `02_user_module_role.sql` | `PLM.UserModuleRole`, each user's roles per module, with a CHECK listing the role codes the code uses. Repairs a table the app made itself, moves admins stored there to `users.user_role`, renames the first Fill/Kill role codes (`proposer`, `clinical`, `materials`), and drops Fill/Kill Viewer from anyone with another Fill/Kill role. | Whenever it changes, before running that code: otherwise saving roles in User Control is refused. |
| `03_unify_roles.sql` | Adds `users.requested_modules` and gives everyone the PLM role matching their `users.user_role` (admin and user: PLM editor; view-only: PLM viewer). Copies only once, so re-running never undoes User Control changes. | Never needed. |
| `04_after_deploy.sql` | Renames `view-only` to `user`. **Only once the new release is live:** the previous release would let `view-only` accounts edit. | Never needed. |
| `09_verify.sql` | The checks above. Read-only. | After every script run. |
| `10_kill_lines.sql` | `vw_MedlineFillKill` (Medline's kill lines plus the test lines, with `Reason`, `Reason Date`, `Is Test`, `Test Purpose`), `vw_FillKillLastLoad` ("data as of"), and the test lines in `FillKill.TestFillKillLine`. | Any time; re-running reloads the test lines. |
| `11_item_qty_views.sql` | `vw_MedlineFillKillItemCollection` and `vw_MedlineFillKillQtyAgg`, O2's views with two changes: they read `vw_MedlineFillKill` (so the test site shows), and the QOE (`Item.UOMConversion`) is for the Infor item. The Infor item is matched on Medline vendor items only, never by manufacturer part alone (shared part numbers give false matches). | If O2's originals change: change them here too. |
| `12_workflow_tables.sql` | `Sub`, `SubOrder`, `History`, and the steps that bring older ones up to date (listed at its top). | Whenever it changes, before running that code. |
| `13_contract_search.sql` | `vw_ContractLineSearch` (Infor contract lines active today, with `is_mhs`) and `vw_Vendor` (Infor's vendors). | Whenever it changes, before running that code. |
| `14_pbo_sync.sql` | `usp_SyncPboSubs`, which adds Medline PBO subs as pending review. The app runs it each time Main loads; it skips a part the item already has, whoever entered it, and deleted ones. | Whenever it changes. Its version line is what `09` and the app check. |
| `90_reset_workflow.sql` | Empties `Sub`, `SubOrder` and `History`. Does nothing unless you edit it to confirm. | Only to throw away UAT subs and orders. |
| `rollback_deploy1.sql` | Sets `users.user_role` back to `admin` / `user` / `view-only` from each person's PLM role, which is all the previous release reads. | Only just before putting the previous release back. Leave the new tables and columns in place. |

### Test lines (`10`)

Under Sold-To `test site` (Sales Order # starting `TEST`); each says why it's there in
`[Test Purpose]`, which the item panel shows:

- **Sites:** for each of the latest 3 order dates, the last 10 lines of the day, copied.
- **Many Medline items to one Infor item** (9/28-9/30): JLCSFTP22A5S (BX) beside JLCSFTP22A5SH
  (EA) for 111848, with a different reason; J-J2015 (CA) and J-J2015Z (BX) beside J-J2015H (EA)
  for 101494.
- **Customer item that isn't the Infor item** (9/30): DYNJAA04 under 1296-DYNJAA04 (Infor's
  contract-only number; no Infor item); B-D930299H under itself (not a Medline vendor item in
  Infor); B-D367344 under 198765, a number not in Infor (Infor item 102205, by vendor item).
- **Contract search, MHS or not** (9/30): BXT2D0737H (EA, Infor item 112057), on Medline JIT
  contracts 1412 and 2421 (not MHS) and 2680 (MHS).

## On O2 now (checked 2026-10-19, read-only)

- `01`-`03`, `10`-`13`: run and current.
- `04`: not yet (deploy #1 isn't live).
- **`14`: O2 has an older `usp_SyncPboSubs`. Re-run `14`.**
- `09`'s "every sub and order has a created History row" says `FAIL` for one sub: the Medline PBO
  sub MMO2329H → 2329RH from 10/14. History was emptied after it was added (its ids restart on
  10/19), so its row went with it. That's test data; it goes away if the UAT subs are reset at
  go-live.
- `PLMPreprocessorShared.infor.CONTRACTLINE` is empty, so the contract search finds nothing. That
  table is loaded upstream; PLM's contract item search reads it too.

## Go-live checklist

One release brings deploy #1 (navigation, unified users and roles, CSRF, daily login reset) and
deploy #2 (Fill/Kill: Main, Subs, Dashboard).

**Before the deploy**

1. On O2, in order: `01`, `02`, `03`, `10`, `11`, `12`, `13`, `14`. Then `09`: all `PASS` except
   `users.user_role ...` (`PENDING`). Check the role listing at the end of `09`: a role changed on
   the old release after `03` ran doesn't carry over.
2. Grants for the app's account (a view in PLM doesn't carry permissions into another database):
   - read `SCSFileIngestor`: `MedlineFillKill`, `ETLHealth`, `MedlineSubCollection`
   - read `PLMPreprocessorShared.infor`: `MDM_ITEM`, `MDM_ITEMUOM`, `CONTRACTLINE`,
     `MDM_VENDORITEM`, `MDM_VENDOR`
   - EXECUTE on `FillKill.usp_SyncPboSubs`
3. The Medline kill-line load (A13) runs on its schedule in Task Scheduler. Main marks data more
   than 90 minutes old.
4. On the web server:
   - `.env` sets its own `SECRET_KEY`, not the built-in `dev-secret-change-me`: login cookies and
     CSRF tokens are signed with it.
   - `python -m pip show Flask-WTF` reports 1.2.2 (in `requirements.txt` all along, but imported
     only from this release on; without it the app won't start).
   - `flask fillkill check-db`, with the server's settings, says the database has everything.
5. Locally, `tools/fillkill_ui/smoke.mjs` passes on this release (see its README).

**The deploy** (on Abdallah's server; the `/plm` prefix and IIS settings stay as they are):
put the code in place and recycle the app pool.

**After the deploy**

6. `04_after_deploy.sql`, then `09`: all `PASS`.
7. Everyone logs in once more: logins from before this release have no recorded login time.
8. An admin opens Fill/Kill's Main page: no "The database needs an update" warning.
9. In User Control, give the Fill/Kill roles: nursing Sub Approver, Materials Managers Materials
   Manager, viewers Viewer.

**When the team starts using it**

10. `TRUNCATE TABLE [FillKill].[TestFillKillLine];` to remove the test lines.
11. Decide on the subs and orders entered during UAT: keep them (the default), or run
    `90_reset_workflow.sql`, edited to confirm.

**Rollback:** just before putting the previous release back, run `rollback_deploy1.sql`.

```bash
sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -i db/fillkill/14_pbo_sync.sql
sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -i db/fillkill/09_verify.sql
```
