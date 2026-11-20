# Order Timing database script

Run by hand on O2 (`YNBBSTVWP02\PROCDATASRVPROD`), database `PLM`, with sqlcmd or SSMS. Safe to
re-run. It has no tables: the module only reads Medline's feed, which A13 loads.

| Script | What it does |
| --- | --- |
| `01_views.sql` | Schema `OrderTiming`; `vw_MedlineOrderLine` (Medline's order lines, each step's date and time as one value, **Line Status** and **Short Qty**), Short Ships' `vw_ShortShipLine` (with each line's QOE from Infor since 2026-11-18) and `vw_ItemKillDay` (2026-11-17), and `vw_OrderTimingLastLoad` (the app's "Data as of" and "last loaded"; `last_file` since 2026-11-17). It ends by listing the lines per status, the short lines in Fill/Kill and with a QOE, and the freshness row. |

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
`earliest_day` in `app/ordertiming/routes.py`). Main and Short Ships open on today (Short Ships on the last 7 days until 2026-11-18).
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
status), one row per Medline item. It reads two views, which join this feed to Fill/Kill's
`FillKill.vw_MedlineFillKill` (db/fillkill/10, already on O2 and granted for Fill/Kill) in SQL; the
app filters them by days, sites and search, groups the lines per item and pages them (the user,
2026-11-17: the logic in the query, not the code).

- **`vw_ShortShipLine`**: each short line with all of `vw_MedlineOrderLine`'s columns, its PO's
  total lines that day (`PO Total Lines`), and its Fill/Kill line, found by Medline order and line
  (`Sales Order #` = `Order #`, `Order Line #` = `Order Line`, which both feeds write alike since
  A13's fix of 11/17): `In Fill/Kill`, Medline's reason (`Fill/Kill Reason`) and `Est Avail Date`.
  A line just shorted may not be in Fill/Kill yet ("Not in Fill/Kill yet"): the feeds come in
  their own files. Since 2026-11-18 it also has the line's `QOE` (eaches in one of its UM) and its
  `Order Qty EA` and `Short Qty EA`: Infor's UOM conversion for the Medline item's Infor item,
  found by Medline vendor item (`MDM_VENDORITEM`, vendor like Medline, active) as Fill/Kill's
  item view finds it, never by manufacturer part. For the UM as Infor calls it (`InforUOM`, made
  as `FillKill.vw_MedlineFillKill` makes it since 2026-11-18: through `MDM_EDI_SUB_UOM`, CS is CA,
  BT is BO, TR is TY, else as Medline writes it); an EA without one is 1; none when Infor has none
  or two Infor items disagree. On O2 (11/18) every one of the last 30 days' 185 short lines had
  one, the same as Fill/Kill's item view gives their items; the query took 0.1 s. It reads Infor's
  tables, not that view: the view knows only items that have been in Fill/Kill's feed (a line
  shorted before its kill line comes in, or on an STD order, would have none), and has a row per
  sub.
  Short Ships shows Qty short and Qty ordered in the UM with eaches below, and the QOE; an item
  in two UMs, in eaches when every line has a QOE. The app's account already reads those Infor
  tables (Fill/Kill's go-live).
- **`vw_ItemKillDay`**: Fill/Kill's kill lines per Medline item, Sold-To and `Order Date`, for how
  often each item was killed today, in the last 7 days and in the last 30 (the app adds up the
  days) at the sites chosen. A count of lines, not a quantity: each row of Fill/Kill's feed is one
  Medline order line (its key is `Sales Order #`, `Order Line #`) that Medline killed all or part
  of (on O2, 11/18: 272 all, 21 part, none filled). Fill/Kill's Sold-Tos have no leading zeros (2159659) and this feed's
  do (0002159659): the view pads Fill/Kill's to ten digits, so one site code filters both.

The PO total is a count over each line's day, Sold-To and order, so the app's day and site filters
still reach the source table's key: on O2 (11/17), with the days as parameters as the app sends
them, a range with no lines was a seek that read none. Fill/Kill's table has no index on
`Order Date` or `Item`, so the kill counts read all of it; at about 200 kill lines a day that's
small for a long while.

On O2's data of 11/17, these views gave Short Ships exactly what the app's own join had (24 items,
111 short lines, 106 of them in Fill/Kill; every site the same). The other 5 came in an Order
Detail file newer than Fill/Kill's last. Every Fill/Kill line on an order in this feed is short in
it. Medline's Order Detail feed starts on 11/17: 11/16's orders (129 kill lines) aren't in it,
which stops mattering once 11/16 is past the 30 days.

## Dashboard (2026-11-20)

The Dashboard reads only `vw_MedlineOrderLine`, in the same days and sites as Main (no search, no
status), so it needs nothing new here: no script to run before the release that adds it. Its SQL
groups the lines per PO, per day and status, and per reject code and item (`dashboard_*` in
`app/ordertiming/queries.py`); `app/ordertiming/dashboard.py` makes the figures.

What O2 showed when it was built (11/17 to 11/19: 748 POs, 8,264 lines):

- **Time to confirm.** Mins to Confirm is the same on every line of a PO, and equals the minutes from
  `Received At` to `Confirmed At`, and from `Received At` to `Order Created At`: Medline sends its 855
  as it creates its order. The median PO took 3 minutes. The 38 that took over an hour were all
  received between 19:00 and 22:00 (Medline's clock), mostly Einstein's 21:00 batch, and their orders
  were created between 2 and 5 AM: 5 to 8 hours.
- **ASNs come in waves**, at about 11:00 to 12:00 and 15:00, and only POs whose order was created by
  about 9 AM had one. **The feed sees same-day ASNs only:** `Report Date` is the day Medline created
  the order, each day's lines are as of that day's last file (about 11 PM), and no later file carries
  an earlier Report Date. So an ASN sent the day after never reaches this table (every ASN on O2 was
  dated its line's Report Date). The Dashboard says "ASN the same day" for that reason. Seeing later
  ASNs would take a report from Medline that covers more than one order day.
- **Rejected:** 38 lines, X1 (RESTRICTVENDR: "restricted vendor, please contact the division"), E1
  (INVALID PART: "invalid material") and S5. Every line had its 855, rejected ones included.

## Before the deploy

1. On O2: `01_views.sql` (after Fill/Kill's `10`, which its Short Ships views read). Its last
   result sets list the lines per status, the short lines in Fill/Kill, and the freshness row.
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

**QOE (2026-11-18): re-run `01_views.sql` on O2 BEFORE deploying the release that shows it.** That
release reads `vw_ShortShipLine`'s new `QOE`, `Order Qty EA` and `Short Qty EA`; the release before
it doesn't read them, so the new view is safe under it. No new grant: the app's account reads
`MDM_VENDORITEM`, `MDM_ITEMUOM` and `MDM_EDI_SUB_UOM` for Fill/Kill already.

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
