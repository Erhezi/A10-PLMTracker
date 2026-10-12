# Item Management database scripts (access + Fill/Kill)

Run on O2 (`YNBBSTVWP02\PROCDATASRVPROD`), database `PLM`, in order. Every script is safe to re-run.
The design is in `_ref/FillKill/fillkill_design.md`; the build plan is in
`_ref/FillKill/fillkill_implementation_plan_v1.md`.

## Deploy #1 (navigation, unified users and roles, CSRF, daily login reset)

**Before deploying the code.** The new code reads `users.requested_modules` and the module roles,
so it won't log anyone in until these scripts have run.

1. `01_schema.sql`: creates the empty `FillKill` schema (used from deploy #2).
2. `02_user_module_role.sql`: creates `PLM.UserModuleRole`, the one table for every permission:

   | Module | Roles |
   |---|---|
   | `app` | `admin` |
   | `plm` | `viewer` or `editor` |
   | `fillkill` | `viewer`, `proposer`, `clinical`, `materials` |

   It also repairs a table the app created by itself, and gives admins every Fill/Kill role.
3. `03_unify_roles.sql`: adds `users.requested_modules` and moves today's `users.user_role` into
   module roles, so everyone keeps their current access:

   | Today | After |
   |---|---|
   | admin | app admin + PLM editor |
   | user | PLM editor |
   | view-only | PLM viewer |

   It runs only once; re-running never overwrites changes made in User Control since.
4. `09_verify.sql`: every row should say `PASS`.

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

After deploying: everyone logs in once more, because logins from before this release have no
recorded login time.

**Rollback.** `users.user_role` is kept in step with the module roles (`admin` / `user` /
`view-only`), so redeploying the previous release still gives everyone their access. Leave the new
tables and column in place.

**Don't start this code against O2 before the scripts.** Running the app creates any missing table
from its models (`db.create_all`). That is how `UserModuleRole` first appeared with system-generated
constraint names, which `02` now repairs.

## Deploy #2

Scripts are written once the design's open questions (§9) are answered; see plan v2.
