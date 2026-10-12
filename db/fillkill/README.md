# Fill/Kill database scripts

Run on O2 (`YNBBSTVWP02\PROCDATASRVPROD`), database `PLM`, in order. Every script is safe to re-run.
The design is in `_ref/FillKill/fillkill_design.md`; the build plan is in
`_ref/FillKill/fillkill_implementation_plan_v1.md`.

## Deploy #1 (shell: navigation, roles, CSRF, daily login reset)

Before deploying the code:

1. `01_schema.sql`: creates the empty `FillKill` schema (used from deploy #2).
2. `02_user_module_role.sql`: creates `PLM.UserModuleRole` and gives existing admins all four
   Fill/Kill roles.
3. `09_verify.sql`: every row should say `PASS`.

```bash
sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -i db/fillkill/01_schema.sql
sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -i db/fillkill/02_user_module_role.sql
sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -i db/fillkill/09_verify.sql
```

On the web server, before recycling the app pool:

- `python -m pip show Flask-WTF` reports 1.2.2. It has been in `requirements.txt` since the first
  commit, but no code imported it until now; if it's missing, the app won't start.
- `.env` sets its own `SECRET_KEY`, not the built-in `dev-secret-change-me`. Login cookies and CSRF
  tokens are signed with it.

After deploying: everyone logs in once more, because logins from before this release have no
recorded login time.

## Deploy #2

Scripts are written once the design's open questions (§9) are answered; see plan v2.
