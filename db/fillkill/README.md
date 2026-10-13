# Item Management database scripts (access + Fill/Kill)

Run on O2 (`YNBBSTVWP02\PROCDATASRVPROD`), database `PLM`, in order. Every script is safe to re-run.
The design is in `_ref/FillKill/fillkill_design.md`; the build plan is in
`_ref/FillKill/fillkill_implementation_plan_v1.md`.

## Deploy #1 (navigation, unified users and roles, CSRF, daily login reset)

Access has two levels:

- **App level:** `users.user_role` is `admin` (approves accounts, assigns module roles) or `user`.
  Admin grants nothing inside a module; admins hold module roles like anyone else.
- **Module level:** each role inside a module is a row in `PLM.UserModuleRole`:

  | Module | Roles |
  |---|---|
  | `plm` | `viewer` or `editor` (one at most) |
  | `fillkill` | `viewer` on its own, or any of `sub_finder`, `sub_approver`, `materials_manager` |

**Before deploying the code.** The new code reads `users.requested_modules` and the module roles,
so it won't log anyone in until these scripts have run.

**Keep `02` in step with the code.** The table's CHECK lists the role codes the code uses. Whenever
`02` changes, re-run it (and `09`) before running the new code against O2; otherwise saving roles
in User Control is refused.

1. `01_schema.sql`: creates the empty `FillKill` schema (used from deploy #2).
2. `02_user_module_role.sql`: creates `PLM.UserModuleRole`, or repairs one the app created by
   itself. If an earlier `03` stored admins in this table (module `app`), it moves them to
   `users.user_role`. It also renames the Fill/Kill roles from their first codes
   (`proposer`, `clinical`, `materials`), and drops Fill/Kill Viewer from anyone who holds
   another Fill/Kill role (the others can already view). (An earlier version also gave admins every Fill/Kill role; on O2 those
   roles are still there and can be changed in User Control.)
3. `03_unify_roles.sql`: adds `users.requested_modules` and gives everyone the PLM role matching
   today's `users.user_role`, so everyone keeps their current access:

   | Today | After |
   |---|---|
   | admin | admin + PLM editor |
   | user | user + PLM editor |
   | view-only | PLM viewer (`view-only` stays until step 5) |

   It copies roles only once; re-running never overwrites changes made in User Control since.
   A role changed in the release still on the server after `03` has run doesn't carry over:
   check the listing at the end of `09` just before deploying.
4. `09_verify.sql`: every row should say `PASS`, except `users.user_role is admin or user`,
   which says `PENDING` until step 5.

```bash
sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -i db/fillkill/01_schema.sql
sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -i db/fillkill/02_user_module_role.sql
sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -i db/fillkill/03_unify_roles.sql
sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -i db/fillkill/09_verify.sql
```

On the web server, before recycling the app pool:

- `python -m pip show Flask-WTF` reports 1.2.2. It has been in `requirements.txt` since the first
  commit, but no code imported it until now; if it's missing, the app won't start.
- `.env` sets its own `SECRET_KEY`, not the built-in `dev-secret-change-me`. Login cookies and CSRF
  tokens are signed with it.

**After deploying.** Everyone logs in once more, because logins from before this release have no
recorded login time.

5. Once the new release is live, `04_after_deploy.sql` renames `view-only` to `user`. Not before:
   the previous release reads `view-only`, and would let those accounts edit. Then `09` is all
   `PASS`.

**Rollback.** Just before putting the previous release back, run `rollback_deploy1.sql`. It sets
`users.user_role` back to `admin` / `user` / `view-only` from each person's PLM role, which is all
the previous release reads. Leave the new tables and column in place.

**Don't start this code against O2 before the scripts.** Running the app creates any missing table
from its models (`db.create_all`). That is how `UserModuleRole` first appeared with system-generated
constraint names, which `02` now repairs.

## Kill lines and test data (no app deploy needed)

Run any time, in order. Both are safe to re-run.

1. `10_kill_lines.sql`:
   - creates `FillKill.vw_MedlineFillKill`, the one view the module reads kill lines from. It
     combines Medline's table in `SCSFileIngestor` with `FillKill.TestFillKillLine`, and adds an
     `Is Test` column.
   - loads test copies: for each of the latest 3 order dates, the last 10 lines of the day, under
     Sold-To `test site` and with `TEST` in front of the Sales Order #. Re-running reloads them.
2. `11_item_qty_views.sql`: `vw_MedlineFillKillItemCollection` and `vw_MedlineFillKillQtyAgg`,
   copied from O2 with one change: they read `vw_MedlineFillKill` instead of Medline's table, so
   the test site shows up. If you change either view on O2, change it here too.
3. `09_verify.sql`: the last result set checks both, and counts the test lines.

**At go-live:** `TRUNCATE TABLE [FillKill].[TestFillKillLine];`

## Deploy #2 (Main page, subs, orders, Dashboard)

Plan: `_ref/FillKill/fillkill_implementation_plan_v2.md`. Run before deploying the code, in order;
all are safe to re-run.

1. `10_kill_lines.sql` again: `vw_MedlineFillKill` gains `Reason` and `Reason Date`, and
   `vw_FillKillLastLoad` (for "data as of") is added. Re-running also reloads the test lines.
2. `12_workflow_tables.sql`: `Sub`, `SubOrder` and `History`.
3. `13_contract_search.sql`: `vw_ContractLineSearch`, Infor contract lines active today, for
   "Add sub".
4. `14_pbo_sync.sql`: `usp_SyncPboSubs`, which adds Medline PBO subs. The app runs it when the
   main table loads; today it would add one (`MMO2329H` → `2329RH`).
5. `09_verify.sql`: the kill-line and workflow result sets should say `PASS`.

**Read access for the app's account** (plan v2 §3): `SCSFileIngestor` (`MedlineFillKill`,
`ETLHealth`, `MedlineSubCollection`) and `PLMPreprocessorShared.infor` (`MDM_ITEMUOM`,
`CONTRACTLINE`, `MDM_VENDORITEM`). A view in PLM doesn't carry permissions into another database.

**Go-live:** `TRUNCATE TABLE [FillKill].[TestFillKillLine];`. Subs and orders entered during UAT
are kept; `90_reset_workflow.sql` empties them only if you edit it to confirm.
