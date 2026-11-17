# Order Timing database script

Run by hand on O2 (`YNBBSTVWP02\PROCDATASRVPROD`), database `PLM`, with sqlcmd or SSMS. Safe to
re-run. It has no tables: the module only reads Medline's feed, which A13 loads.

| Script | What it does |
| --- | --- |
| `01_views.sql` | Schema `OrderTiming`; `vw_MedlineOrderLine` (Medline's order lines, each step's date and time as one value, and **Line Status**) and `vw_OrderTimingLastLoad` (the app's "Medline data as of"). It ends by listing the lines per status. |

## Where the data comes from

A13's `reports/medline_ordertiming` pipeline loads Medline's "MHS - ORDER DETAIL REPORT" mail into
`SCSFileIngestor.MedlineOrderTiming.MedlineOrderTiming`, one row per order line, keyed on
(Report Date, Order #, Order Line). Each load replaces its Report Date, so a day's lines are as of
that day's latest file. Until LUM go-live Medline sends one test file a day; then hourly.

## How much Main reads

Main shows 20 POs a page and reaches the last 30 days only, today included (the user, 2026-11-16,
expecting a large volume): the app holds every search and export to them (`MAX_DAYS` in
`app/ordertiming/routes.py`). The table's clustered key leads with Report Date, so those days are a
range seek. The sites list reads the same 30 days, and `vw_OrderTimingLastLoad` reads only the newest
day, so neither scans the whole table.

## Line Status

Worked out in the view, so it can change without an app deploy. Checked in this order:

| Status | When |
| --- | --- |
| `rejected` | `Bad Line` = YES, or a `Rej Code` (E1, S1, X1 seen) |
| `not_confirmed` | no `855 Date` |
| `asn` | an `ASN Creation Date` |
| `confirmed` | anything else: confirmed, not shipped yet |

Medline's SAP delivery document (`SAP Delv Doc #`) is not a status (the user, 2026-11-16): it only
means the line reached Medline's SAP. The view still carries the column, but the app doesn't show it.

The app labels them (`app/ordertiming/queries.py`, `STATUSES`): a new status needs a label there,
which does need a deploy. An order shows as confirmed when every line has its 855.

The app also shows Medline's `PO Type` on the PO's row, and each line's `Line Type`, `Bad Line` and
`Rej Code`. On every line seen so far PO Type is EDI and Line Type STD; a Rej Code always came with
Bad Line = YES.

On the 2026-10-07 sample (257 lines, 70 orders), tested on LocalDB: 17 rejected, 239 confirmed,
1 ASN, none not confirmed. Every order was confirmed within 6 minutes.

## Before the deploy

1. On O2: `01_views.sql`. Its last result sets list the lines per status and the freshness row.
2. Grant the app's account `SELECT` on `SCSFileIngestor.MedlineOrderTiming.MedlineOrderTiming`
   (Fill/Kill's go-live already granted `MedlineReport.ETLHealth`). A view in PLM doesn't carry
   permissions into another database.
3. Locally, `tools/fillkill_ui/smoke.mjs` passes (its Order Timing step searches the sample orders).

Until both are done, Order Timing's Main tells admins what's missing and others to ask an admin;
nothing else in the app is affected.

```bash
sqlcmd -S "YNBBSTVWP02\PROCDATASRVPROD" -d PLM -b -i "db/ordertiming/01_views.sql"
```

## Open questions

- **Time zone.** The file's "Dates & Times Time Zone:" line is blank, and A13 finds its file stamps
  look like Central time. The page shows Medline's times as sent. Ask Medline.
- **A PO Medline never received** isn't in the feed at all, so the page can only say it isn't
  there. Comparing against the POs Infor sent would show them as missing, but Infor's PO tables
  load overnight, a day late.
- **Lines crossing a day.** If a line ever appears under two Report Dates (A13's open question 1),
  Main counts it once in its PO's total, as of its latest day; the export has a row for each day.
