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
  | `fillkill` | `viewer`, `proposer`, `clinical`, `materials` |

**Before deploying the code.** The new code reads `users.requested_modules` and the module roles,
so it won't log anyone in until these scripts have run.

1. `01_schema.sql`: creates the empty `FillKill` schema (used from deploy #2).
2. `02_user_module_role.sql`: creates `PLM.UserModuleRole`, or repairs one the app created by
   itself. If an earlier `03` stored admins in this table (module `app`), it moves them to
   `users.user_role`. (An earlier version also gave admins every Fill/Kill role; on O2 those
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

## Deploy #2

Scripts are written once the design's open questions (§9) are answered; see plan v2.
