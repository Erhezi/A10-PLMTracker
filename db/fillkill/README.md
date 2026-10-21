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

**"Lock request time out period exceeded" after a script** (SSMS error 1222, e.g. in Object
Explorer): the window that ran it still has a transaction open, so nothing it changed is saved and
other sessions wait on those tables. It happens when SSMS's *Tools > Options > Query Execution >
SQL Server > ANSI > SET IMPLICIT_TRANSACTIONS* is on, or after a `BEGIN TRAN` earlier in the window.
In that window, `SELECT @@TRANCOUNT;` says how many; `COMMIT;` (once per transaction) keeps the
changes, `ROLLBACK;` undoes them. Closing the window asks the same question. Every script that
changes something now ends with a red error when a transaction is still open (2026-10-20).

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
| `12_workflow_tables.sql` | `Sub` (the Reference SKU nursing entered, its status and pick), `SubVendorItem` (what can be ordered for it: a vendor part, vendor, vendor ID and UOM each), `SubOrder`, `History`, and step 2, which turns subs that carry their own vendor details into vendor items (listed at its top). | Whenever it changes, before running that code. |
| `13_contract_search.sql` | `vw_ContractLineSearch` (Infor contract lines active today, with `is_mhs`), `vw_Vendor` (Infor's vendors, with their legal and search names) and `vw_UomAlias` (Infor's UOM for one typed another way, from `MDM_EDI_SUB_UOM`: CS is CA, VL is VI). | Whenever it changes, before running that code. |
| `14_pbo_sync.sql` | `usp_SyncPboSubs`, which adds Medline PBO subs as pending review, with a vendor item when Medline's contract lines give one UOM. The app runs it each time Main loads; it skips a part the item already has, whoever entered it, and deleted ones. | Whenever it changes, after `12`. Its version line is what `09` and the app check. |
| `90_reset_workflow.sql` | Empties `Sub`, `SubVendorItem`, `SubOrder` and `History` (with DELETE: `TRUNCATE` is refused on tables other tables' keys point at), numbers new ones from 1, and drops `12`'s copy `Sub_before_vendor_items`. Does nothing unless you edit it to confirm. | Only to throw away UAT subs and orders. |
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

## On O2 now (checked 2026-10-21, read-only)

- `01`-`03`, `10`-`14`: run and current; `13` re-run at 13:36 on 10/21 for `vw_UomAlias` (32 of
  Infor's UOM aliases). The app's own check finds nothing missing with a developer's login; the
  web server's account still needs its grants (go-live step 2).
- `04`: not yet (deploy #1 isn't live); 3 accounts still say `view-only`.
- `90` ran on 10/20, after `12`'s vendor items step and `14`: `Sub_before_vendor_items` is gone, and
  what's there since is new UAT data (5 subs, 1 of them Medline's PBO sub, 3 vendor items, 2 orders,
  33 History rows), each with its "created" History row, so `09`'s History check passes.
- The 39 test lines (`TestFillKillLine`) are still there: go-live step 10 removes them.
- A local `run.py` on this code against O2 is fine. It runs the app's startup, which creates any
  table its models have and O2 lacks: it made `SubVendorItem` at 12:46 on 10/20, before `12` did.
- `PLMPreprocessorShared.infor.CONTRACTLINE` was empty earlier on 10/19 and is loaded again
  (631,677 lines that afternoon). It is loaded upstream; when it's empty, the contract search, and
  PLM's contract item search, find nothing.

## Go-live checklist

One release brings deploy #1 (navigation, unified users and roles, CSRF, daily login reset) and
deploy #2 (Fill/Kill: Main, Subs, Dashboard); as of 2026-10-19 it isn't deployed. Each step that
runs a script or query has its command under **Commands** below.

**Before the deploy**

1. On O2, in order: `01`, `02`, `03`, `10`, `11`, `12`, `13`, `14`. Then `09`: all `PASS` except
   `users.user_role ...` (`PENDING`). Check the role listing at the end of `09`: a role changed on
   the old release after `03` ran doesn't carry over.
2. Grants for the app's account (a view in PLM doesn't carry permissions into another database):
   - read `SCSFileIngestor`: `MedlineFillKill`, `ETLHealth`, `MedlineSubCollection`
   - read `PLMPreprocessorShared.infor`: `MDM_ITEM`, `MDM_ITEMUOM`, `CONTRACTLINE`,
     `MDM_VENDORITEM`, `MDM_VENDOR`, `MDM_EDI_SUB_UOM` (2026-10-20)
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

6. `04_after_deploy.sql`, once the release is live (not before: the old release would let
   `view-only` accounts edit). Then `09`: all `PASS`, except the History check if step 11's
   query hasn't run.
7. Everyone logs in once more: logins from before this release have no recorded login time.
8. An admin opens Fill/Kill's Main page: no "The database needs an update" warning, and the
   Fill/Kill dates are **today's**. On the server Main opens on today (2026-10-20); locally it opens
   on the latest day with kill lines (9/30 in O2's data now). That follows `FLASK_ENV=production`
   in `web.config`: `ProductionConfig` sets `FILLKILL_OPEN_ON` to `today`. Nothing to change for it,
   but if Main opens on an older day, the server's `.env` has `FILLKILL_OPEN_ON=latest`: remove it.
9. In User Control, give the Fill/Kill roles: nursing Sub Approver, Materials Managers Materials
   Manager, viewers Viewer.

**When the team starts using it**

10. Remove the test lines: `TRUNCATE TABLE [FillKill].[TestFillKillLine];`
11. Decide on the subs and orders entered during UAT:
    - keep them (the default), and give any that lost its "created" History row one, so `09`'s
      History check passes (none lacks one on O2 today); or
    - empty them with `90_reset_workflow.sql`, edited to confirm.

    `12`'s copy of `Sub` from before vendor items, `FillKill.Sub_before_vendor_items`, is already
    gone on O2 (`90` dropped it on 10/20); the `DROP` below is only for a database where it's left.
    Then `09`: all `PASS`.

**Rollback:** just before putting the previous release back, run `rollback_deploy1.sql`.

### Commands

Before the deploy (steps 1 and 4):

```bash
for s in 01_schema 02_user_module_role 03_unify_roles 10_kill_lines 11_item_qty_views \
         12_workflow_tables 13_contract_search 14_pbo_sync 09_verify; do
  sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -b -i "db/fillkill/$s.sql" || break
done
flask fillkill check-db        # on the web server, with its .env
```

After the deploy (step 6):

```bash
sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -b -i db/fillkill/04_after_deploy.sql
sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -i db/fillkill/09_verify.sql
```

When the team starts using it (steps 10 and 11):

```sql
TRUNCATE TABLE [FillKill].[TestFillKillLine];

-- Keeping the UAT subs and orders: a "created" History row for each that has none, dated when it
-- was made, by who made it. Adds nothing once every row has one.
INSERT INTO [FillKill].[History] ([entity], [entity_id], [medline_item], [action], [actor], [acted_at])
SELECT 'sub', s.[sub_id], s.[medline_item], 'created', s.[entered_by], s.[create_dt]
FROM [FillKill].[Sub] AS s
WHERE NOT EXISTS (SELECT 1 FROM [FillKill].[History] AS h
                  WHERE h.[entity] = 'sub' AND h.[entity_id] = s.[sub_id] AND h.[action] = 'created')
UNION ALL
SELECT 'vendoritem', v.[vendor_item_id], s.[medline_item], 'created', v.[entered_by], v.[create_dt]
FROM [FillKill].[SubVendorItem] AS v JOIN [FillKill].[Sub] AS s ON s.[sub_id] = v.[sub_id]
WHERE NOT EXISTS (SELECT 1 FROM [FillKill].[History] AS h
                  WHERE h.[entity] = 'vendoritem' AND h.[entity_id] = v.[vendor_item_id] AND h.[action] = 'created')
UNION ALL
SELECT 'order', o.[order_id], o.[medline_item], 'created', o.[ordered_by], o.[create_dt]
FROM [FillKill].[SubOrder] AS o
WHERE NOT EXISTS (SELECT 1 FROM [FillKill].[History] AS h
                  WHERE h.[entity] = 'order' AND h.[entity_id] = o.[order_id] AND h.[action] = 'created');

-- Once the subs look right after 12's vendor items (2026-10-20): its copy of Sub from before.
DROP TABLE IF EXISTS [FillKill].[Sub_before_vendor_items];
```

Then `09_verify.sql` once more.
