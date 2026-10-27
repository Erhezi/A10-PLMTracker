# Fill/Kill UI tools

Two tools for trying the Fill/Kill pages in a browser on your own computer, and checking them after
a change. Nothing in `app/` imports this folder, and it doesn't need to go to the server.

| File | What it does |
| --- | --- |
| `dev_server.py` | Runs the real app on an in-memory SQLite database at http://127.0.0.1:5099, with sample data or O2's data copied read-only. |
| `smoke.mjs` | Drives headless Edge through Main, the item panel, the forms, the Subs page and the Dashboard on the sample data, and fails on anything that doesn't show up or any browser error. |

## Is it safe?

- The app's database is SQLite in memory: every start is fresh and nothing is kept. The Fill/Kill
  views, which exist only on SQL Server, become SQLite tables with the same names and columns
  (`tests/conftest.py`).
- `--data o2` reads O2 with your Windows login on a read-only connection and only runs `SELECT`s.
  It never writes to O2.
- `/dev-login` signs you in without a password. It exists only in `dev_server.py`, never in the app,
  and the server listens only on this computer (127.0.0.1).

## Running it

From the repo root, with the repo's virtual environment active:

```
python tools/fillkill_ui/dev_server.py              # sample data, dated around today
python tools/fillkill_ui/dev_server.py --data o2    # O2's data, read-only
```

Then open http://127.0.0.1:5099/dev-login. Add `?as=` to sign in with fewer roles:

| `?as=` | App role | Fill/Kill roles |
| --- | --- | --- |
| `all` (default) | admin | Sub Finder, Sub Approver, Materials Manager, MM Lead |
| `nurse` | user | Sub Approver |
| `mm` | user | Materials Manager |
| `lead` | user | MM Lead |
| `finder` | user | Sub Finder |
| `viewer` | user | Viewer |

`--port` changes the port. Stop the server with Ctrl+C.

The sample data has kill lines from the last three days: an item with one UOM (DYND70294BH), an
Infor item with two (999999: MDS2585H by the box, whose Medline customer item isn't the Infor item,
and MDS2585HC by the case), and an item that isn't in Infor (SAMPLE0001). The contract search finds
vendor item 88885 on an MHS contract and another vendor's 88885-CS on a non-MHS one, and five
ChloraPrep lines as O2 has them ("930103 chloraprep" finds one). The vendors are the tests' four
(1000001 Cardinal, 1000002 Owens & Minor, 1000931 Medline, 1000099 inactive) and a few of Infor's,
several Cardinal Health ones among them, so the vendor search has a list to scroll. Medline's own
contract line for DYND70294BH is there too, which the vendor item form shows but won't take (the
killed item itself), and a few of Infor's UOM aliases (CS is CA, VL is VI).

With `--data o2`, the contract search reads Infor's contract lines through this repo's
`db/fillkill/13_contract_search.sql`, limited to the vendor items Medline has killed plus nitrile
gloves. A view column O2 doesn't have yet (its script not run) comes back empty.

## The smoke walkthrough

It needs Node 22 or later and Edge (or Chrome: set `EDGE` to its path). It adds subs and an order,
so start a fresh sample server for each run:

```
python tools/fillkill_ui/dev_server.py            # terminal 1
node tools/fillkill_ui/smoke.mjs                  # terminal 2
```

Each step prints `ok` or `FAIL` with what was missing; a failure saves a screenshot to
`%TEMP%\fillkill-smoke` (or `--out <folder>`). `--base` points it at another address. It exits with
1 if a step failed.

Run it after changing the pages' scripts (`app/static/js/fillkill/`) or the routes behind them,
and before a deploy. When the pages change what a step looks for, change the step with them.

## Notes

- The server handles one request at a time: an in-memory SQLite database lives on one shared
  connection.
- The sample data's dates follow today (New York time), so Main opens on today.
- `tests/conftest.py` imports pytest, so the server needs the test requirements installed.
