# Order Timing database script

Run by hand on O2 (`YNBBSTVWP02\PROCDATASRVPROD`), database `PLM`, with sqlcmd or SSMS. Safe to
re-run. It has no tables: the module only reads Medline's feed, which A13 loads.

| Script | What it does |
| --- | --- |
| `01_views.sql` | Schema `OrderTiming`; `vw_MedlineOrderLine` (Medline's order lines, each step's date and time as one value, **Line Status** and **Short Qty**) and `vw_OrderTimingLastLoad` (the app's "Data as of" and "last loaded"; `last_file` since 2026-11-17). It ends by listing the lines per status. |

## Where the data comes from

A13's `reports/medline_ordertiming` pipeline loads Medline's "MHS - ORDER DETAIL REPORT" mail into
`SCSFileIngestor.MedlineOrderTiming.MedlineOrderTiming`, one row per order line, keyed on
(Report Date, Order #, Order Line). Each load replaces its Report Date, so a day's lines are as of
that day's latest file. Until LUM go-live Medline sends one test file a day; then hourly.

## How much Main reads

Main shows 20 POs a page and reaches the last 30 days only, today included (the user, 2026-11-16,
expecting a large volume), and nothing before Medline's LUM go-live on 2026-11-16 (the user,
2026-11-17; `ORDERTIMING_FIRST_DAY` in `app/config.py`, which an environment variable of that name
can change, empty for none): the app holds every search and export to them (`MAX_DAYS` and
`earliest_day` in `app/ordertiming/routes.py`). Main opens on today, Short Ships on the last 7 days.
The table's clustered key leads with Report Date, so those days are a range seek. The sites list
reads the same days, and `vw_OrderTimingLastLoad` reads only the newest day, so neither scans the
whole table. Main's tabs (2026-11-17) count the orders per Line Status, and with a Short Qty, in one
more pass over the days searched.

## Line Status and Short Qty

Worked out in the view, so they can change without an app deploy. Line Status is checked in this
order:

| Status | When |
| --- | --- |
| `rejected` | `Bad Line` = YES, or a `Rej Code` (E1, S1, X1 seen) |
| `not_confirmed` | no `855 Date` |
| `asn` | an `ASN Creation Date` |
| `confirmed` | anything else: confirmed, not shipped yet |

**Short Qty** (2026-11-17) is what a line is short shipped, apart from its status: `Order Qty` less
`Shipped Qty` and `Open Qty`, when that's more than 0, on a line that isn't rejected and has a
`SAP Delv Doc #`; NULL otherwise. The user: ASN sent wins over short shipped in the status, and short
shipped is tallied on its own (a column on Main's PO rows, and Main's last tab). For one day it was a
status (`short`, between not_confirmed and asn); it never reached O2.

Medline's SAP delivery document (`SAP Delv Doc #`) is not a status (the user, 2026-11-16): it only
means the line reached Medline's SAP. The view still carries the column, but the app doesn't show it.
Short Qty reads it only as the sign that Medline has set `Shipped Qty`: before the delivery, a line
just confirmed would otherwise look short.

**Short shipped, on O2 on 2026-11-17** (Medline's LUM orders, 1,552 lines on 112 POs): 1,536 lines
are Line Type `FILL-KILL` (Medline ships what it has and kills the rest), 16 `STD`. 67 lines were
short, all with a delivery document; 58 of them were already in Fill/Kill's feed
(`SCSFileIngestor.MedlineFillKill`) on the same Medline order and line, the same item and the same
filled quantity, and no fully shipped line was. The other 9 were waiting on Fill/Kill's next load.
Four short lines that day had their ASN, having shipped none: ASN sent, with a Short Qty.

The app labels them (`app/ordertiming/queries.py`, `STATUSES`): a new status needs a label there,
which does need a deploy. An order shows as confirmed when every line has its 855.

The app also shows Medline's `PO Type` on the PO's row, and each line's `Line Type`, `Bad Line` and
`Rej Code`. On every line seen so far PO Type is EDI; Line Type was STD on the 10/07 sample and is
FILL-KILL on almost every LUM line since go-live (see above). A Rej Code always came with Bad Line = YES.

On the 2026-10-07 sample (257 lines, 70 orders), tested on LocalDB: 17 rejected, 239 confirmed,
1 ASN, none not confirmed. Every order was confirmed within 6 minutes.

## Short Ships (2026-11-17)

Order Timing's second page lists the items with a short-shipped line (a Short Qty, whatever the
status), one row per Medline item. It also
reads Fill/Kill's `FillKill.vw_MedlineFillKill` (db/fillkill/10, already on O2 and granted for
Fill/Kill), for:

- **each short line's Fill/Kill line**, found by Medline order (`Sales Order #` = `Order #`) and
  line (Fill/Kill's `Order Line #` 210 is this feed's `Order Line` 000210): Medline's reason and
  Est Avail Date (the view's `Reason` and `Reason Date`), or "Not in Fill/Kill yet";
- **how often each item was killed**: Fill/Kill's lines for the item today, in the last 7 days and
  in the last 30, by its `Order Date`, at the sites chosen. Fill/Kill's Sold-Tos have no leading
  zeros on O2 (2159659) and this feed's do (0002159659): the app matches both forms.

Fill/Kill's table has no index on `Order Date` or `Item`, so the kill counts read all of it; at
about 200 kill lines a day that's small for a long while.

## Before the deploy

1. On O2: `01_views.sql`. Its last result sets list the lines per status and the freshness row.
2. Grant the app's account `SELECT` on `SCSFileIngestor.MedlineOrderTiming.MedlineOrderTiming`
   (Fill/Kill's go-live already granted `MedlineReport.ETLHealth`). A view in PLM doesn't carry
   permissions into another database.
3. Locally, `tools/fillkill_ui/smoke.mjs` passes (its Order Timing step searches the sample orders).

Until both are done, Order Timing's Main tells admins what's missing and others to ask an admin;
nothing else in the app is affected.

**Short shipped (2026-11-17): re-run `01_views.sql` on O2 BEFORE deploying the release with Short
Ships.** That release reads the view's new `Short Qty` column; without it, Order Timing's pages say
they can't read Medline's data. The release before it reads the new view fine (the same four
statuses; it doesn't read the new column). Its last result set gives each status's short-shipped
lines.

**Data as of (2026-11-17):** what the pages called "Data as of" was when A13 loaded the feed; it's
now "last loaded", and "Data as of" is when Medline made the file loaded. `vw_OrderTimingLastLoad`
gives that file (`last_file`: the last good run's, else the newest day's lines'), and
`app/utility/freshness.py` reads the time in its name: `MHS - ORDER DETAIL REPORT-2026-11-17-01-02-15.xls`
is 1:02 PM Central (Medline's names use a 12-hour clock without AM or PM; the reading not after the
load is taken), 2:02 PM here. The app reads `last_file` when the view has it, so the deploy order
above doesn't change.

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
