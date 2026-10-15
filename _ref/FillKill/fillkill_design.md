# Fill/Kill Management — design notes

Living draft. Last updated 2026-10-13.

**Revamped 2026-10-08 after meeting users and stakeholders.** The workflow is now **per Medline
item, with no site distinction**: sites are only a filter, and subs, picks and orders belong to the
item. This replaces the per-site, per-line design of 2026-10-06; what was dropped is listed at the
end of section 5.

Decisions are marked **Decided**. Items to take to stakeholders are in section 8; the design
questions in section 9 were answered on 2026-10-13.

**Words used here**

- **Medline item** = the file's `Item` (e.g. `MDS2585H`), Medline's catalog number. From our side
  it is the vendor part number. It is the key for everything in this module.
- **Site** = a Medline Sold-To account (Moses, Wakefield, Einstein).
- **Department** = a Medline Ship-To under a site (4E, ICU, ED…).
- **Kill line** = one row of the Medline file (a partial fill counts as a kill).
- **Sub** = a substitute recorded for a Medline item: a vendor plus that vendor's part number.

## 1. Scope

- A second module in the app, alongside **PLM Tracker**. The app is now called **Item
  Management**, with PLM Tracker and Fill/Kill Management as its modules. Same Flask app, same
  `/plm` mount on the server's IIS, same users and login. New pages live under
  `/plm/fillkill/...`; existing PLM URLs do not change.
- Tracks Medline's fill/kill exceptions on company 3000 requisitions, rolled up per Medline item.
  Sub Finders record substitutes, a Sub Approver reviews and picks them, and a Materials Manager
  records what was ordered.
- **v1 is functional but simple.**
  - The main table rolls up the kill lines for a chosen date range (default: today) and the chosen
    sites, one row per Medline item.
  - Sites are only a filter. Subs, picks and orders belong to the Medline item, not to a site.
  - Earlier days stay in the database untouched. Nothing is closed or carried over.

  **Decided** (2026-10-08).

## 2. Source file — Medline "LUM Fill-Kill Report v2"

Facts from the 11 White Plains samples in this folder (2026-09-20 → 09-30), checked against O2:

- One sheet, 23 columns, one row per Medline order line, then three footer rows
  (`Medline Insight: LUM Fill-Kill Report v2 - SAP Data Direct`, `Date Range: Last 24 Hours`,
  `Run Date: m/d/yyyy`).
- **Exceptions only**: 285 kills + 6 partial fills, no fully filled lines. Partial fill counts as a
  kill (kill qty = Order Qty − Filled Qty). **Decided.**
- **Primary key**: (Sales Order #, Order Line #), as built in the ingestion. Unique within and
  across all 11 files, and no sales order spans more than one Sold-To. **Decided.**
- **Join to Infor**: `PO` = the first 10 digits of `PO #`, `POLine` = `PO Line` without leading
  zeros (both added by the ingestion) → `PLMPreprocessorShared.infor.PURCHASEORDER_LINE (PO, POLine)`.
  - Matched 291/291 sample lines, and (PO, POLine) is unique there.
  - `Customer Item #` equals the Infor item on 291/291 lines.
- **Per Medline item, in the sample:** one UOM and one Infor item each; one item's description
  changes over time.
- **Reading**: openpyxl cannot open these files (the generator writes an out-of-range font value
  in styles.xml). pandas with the calamine engine reads them correctly.
- **Refresh**: hourly 8am–11pm. A line repeats across the day's files and its comment may be filled
  in or changed later; ingestion upserts by the primary key. Each day's files hold only that day's
  orders (sites stop ordering by 4–5 PM), so there is no cross-midnight case. **Decided.**
- The filename timestamp appears to be a 12-hour clock without AM/PM (`…-01-02-06` holds orders up
  to 12:25). Don't use it for ordering; use the file's arrival time.
- The sample is company 2600 (Medline vendor 1037888, JIT tote program). Production will be
  company 3000 with three Sold-To accounts.

The comment column (`Internal Order Comments from SAP (Z106)`) is the kill reason. All users should
be able to see it. **Decided.** The main table shows it as Latest Reason (section 5).

| Comment | Sample lines | Meaning |
|---|---|---|
| Allocation limit has been reached (incl. 1 SPIKE) | 118 | Medline is rationing |
| MBO – ERD is *date* | 94 | Manufacturer backorder, expected release date |
| OUT OF STOCK – ETA is *date* | 27 | Medline warehouse out, ETA |
| SPIKE MBO – Forecast x, Usage y; ERD *date* | 4 | Ordered above forecast |
| NONSTOCK UOM – Item stocked by CS/BX UOM | 28 | Ordered in a UOM Medline doesn't stock |
| NONSTOCK (MBO) – needs a stock request | 11 | Not stocked on fill/kill accounts |
| DISCONTINUED ITEM | 9 | Permanent |

## 3. Ingestion — A13 pipeline (**Built** 2026-10-06)

Ingestion is the `medline_fillkill` report in the Medline pipeline repo
([A13-MedlinePBO](https://github.com/Erhezi/A13-MedlinePBO)), run hourly by Windows Task Scheduler.
The web app never ingests; it only reads.

**Why not inside the app**

- The app runs under IIS FastCGI on the web server. IIS starts Python processes on the first
  request, recycles them when idle (20 minutes by default) and may run more than one at a time. A
  timer inside the app would skip runs when nobody has used the site and could run twice with two
  processes. Making it reliable needs IIS app-pool changes on the server's IIS.
- The feed (email vs SFTP) is undecided; every fetch/parse change would be another deploy on the
  web server, plus new packages there (pandas + calamine, paramiko for SFTP).
- The app's Microsoft Graph credentials are used only to send mail; reading the mailbox may need
  extra permission. A13 already reads that mailbox.

**What's built** (`reports/medline_fillkill/` in A13)

- **Hourly run (7:00–23:00).** Each run:
  - downloads the newest matching mail attachment
  - validates the 23 headers and drops the footer rows
  - checks the primary key; a missing or repeated key fails the run before anything is written
  - adds `PO` and `POLine`, and types Order Date, Order Time and the quantities
- **Load:** truncate and reload the staging table, then MERGE into the target in one transaction.
  - A matched line is updated only when a value actually changed.
  - New lines are inserted, and nothing is ever deleted.
- **Tables**, in the `SCSFileIngestor` database on O2:
  - `MedlineFillKill.MedlineFillKill`: every line ever received, keyed on (Sales Order #, Order
    Line #).
  - `MedlineFillKill.medlinefillkill_stg`: the last file loaded.
- **Run health:** written to `SCSFileIngestor.MedlineReport.ETLHealth` (process "Medline
  Fill-Kill"). Failures send email; successes don't.
- **Backfill:** `python -m reports.medline_fillkill.backfill <folder>`. The 11 samples are loaded:
  291 lines, 2026-09-20 → 09-30.

**Still to do in A13**

- **Mail matching.** The keyword ("FILL KILL") and file prefix ("WPH - FILL KILL REPORT") come from
  the samples; confirm them once the hourly mail starts. If each of the three Sold-To accounts gets
  its own file, take the newest file per prefix.
- **Backfill order.** Backfill sorts files by name. If hourly filenames use a 12-hour clock with no
  AM/PM, a 1 PM file sorts before an 8 AM file and could overwrite newer comments. Sort by mail
  received time or file modified time instead. The hourly run is unaffected.
- **Scheduling and feed:** set up the Task Scheduler trigger, and add an SFTP fetch if that becomes
  the feed.

**How the app reads it**

- **Through views in the PLM database** (section 6). Kill lines come only from
  `FillKill.vw_MedlineFillKill`, which combines `SCSFileIngestor.MedlineFillKill.MedlineFillKill`
  with the test lines. Nothing else names the `SCSFileIngestor` table, so if the source moves, only
  that view changes. The main table reads the item and quantity views built on top of it.
- **"Data as of"** comes from the latest successful `ETLHealth` run. The app warns when it is more
  than ~90 minutes old between 8am and 11pm.
- **No references to individual lines.** Subs and orders are keyed on the Medline item, so no
  workflow table points at a kill line.
- **Prerequisite: read access for the app's account.** The account the web app runs as needs
  read access to:
  - `SCSFileIngestor.MedlineFillKill.MedlineFillKill`
  - `SCSFileIngestor.MedlineReport.ETLHealth`
  - `SCSFileIngestor.MedlinePBO.MedlineSubCollection`
  - `PLMPreprocessorShared.infor`: `MDM_ITEMUOM`, `CONTRACTLINE`, `MDM_VENDORITEM` (read by the
    item view). Probably already granted: PLM views the app uses today, such as `vw_ItemUOM` and
    `vw_ContractItem`, read the same database.

  A view in PLM doesn't carry permissions into another database, so these must be granted directly.
  So far access has only been checked with a personal account.
- **Go-live order:** the pipeline can run before the app module ships, so real history starts
  accumulating early.

## 4. Roles

**Login.** Shared users and login. Every login, PLM included, ends at 2:30 AM New York time each day;
the next click sends the user to the login page with an "expired" message, then back to where they
were. **Decided.**

**One account, access per module** (unified 2026-10-12). **Decided.**

- **Registering:** people register once for Item Management. The form asks which modules they need;
  that request grants nothing by itself.
- **Approving:** an admin approves the account and sets access in User Control. Each user has one
  row with an Admin box, a PLM Tracker role and Fill/Kill roles, saved together.
- **Storage:**
  - App level: `users.user_role` is `admin` (approves accounts, assigns module roles) or `user`.
  - Module level: each role inside a module is a row in `PLM.UserModuleRole`:

    | Module | Roles |
    |---|---|
    | `plm` | `viewer` or `editor` (one at most) |
    | `fillkill` | `viewer` alone, or any of `sub_finder`, `sub_approver`, `materials_manager` |
- **PLM on the server:**
  - Viewers can open PLM pages and read data, including the dashboard filters and exports.
  - Editors can also change data.
  - Clearing deleted rows and archiving completed ones need admin and Editor.
  - Before this change, view-only was only hidden in the page.
- **No access yet:** a user without any module role lands on a "no module access yet" page; an
  admin without one lands in User Control.
- **Migration:** the previous release's `view-only` became a PLM Viewer role. The value itself
  stays in `users.user_role` until the new release is live, because the old release reads it;
  `04_after_deploy.sql` then renames it to `user`. Rolling back runs `rollback_deploy1.sql`, which
  sets `user_role` back from each person's PLM role.

Fill/Kill roles (named 2026-10-13; earlier drafts called them A, B and C):

| Role | Code | Responsible for |
|---|---|---|
| Viewer | `viewer` | Seeing everything in the module, without changing anything |
| Sub Finder | `sub_finder` | Adding subs to a Medline item |
| Sub Approver | `sub_approver` | Setting each sub's status (approve / hold / reject); picking approved subs for ordering; adding comments to subs |
| Materials Manager | `materials_manager` | Recording orders against the picks; adding comments to orders |

- **The Sub Approver decides what is clinically acceptable and which sub to use; the Materials
  Manager records what was ordered.** Today the Sub Approver is usually nursing. **Decided.**
- **Combinations:**
  - Viewer is held alone: it can't be combined with the other roles, which can all view.
    **Decided** (2026-10-13).
  - In practice people hold **Sub Finder + Sub Approver** (nursing today), **Sub Finder +
    Materials Manager**, or **Viewer**. Sub Finder on its own is kept for a future AI agent that
    finds subs. **Decided** (9.7).
  - Only Sub Finders add subs; a Materials Manager without Sub Finder can't. **Decided** (9.7).
  - Sub Approver and Materials Manager may not be the same person; User Control refuses the
    combination. **Decided for now** (stakeholder item 8.3).
- **Admins** approve accounts and assign module roles. Being an admin grants nothing inside a
  module: admins hold module roles like anyone else, with no defaults (revised 2026-10-13; this
  replaces "admins hold every role by default"). Clearing deleted rows and archiving completed
  ones in PLM need both admin and PLM Editor. The Sub Approver + Materials Manager rule doesn't
  apply to admins, so an admin can test both sides; the Viewer-alone rule does. They can't remove
  their own admin access; another admin has to. **Decided.**
- Roles are not scoped by site. **Decided.**

## 5. Workflow

**One operating page for every role** (2026-10-13). **Decided.** Everyone works on the Main page
and sees the same thing; what they can do on it follows their roles. Sub Finders add subs and Sub
Approvers set status and pick right there, and Materials Managers record orders from the picks.
The full sub list and the order log are tables (or cards) on the same page, not pages of their own.
Trends and analytics live on a separate Dashboard page (section 7).

### Main table — one row per Infor item

**Controls**

- **Date range slider:** pick the start and end order date. Default: today to today; the slider
  spans the first to the last date in the data.
- **Site filter:** one or more sites. Default: all.
- **Needs filter:** All · Needs subs · Needs review · Needs pick · Needs order · Ordered (9.8):
  - *needs subs*: no sub that is pending review, approved or on hold
  - *needs review*: at least one sub pending review
  - *needs pick*: at least one approved sub, none picked
  - *needs order*: at least one pick, and no order in the range
  - *ordered*: an order in the range
- **Search:** every word typed must appear in the Infor item, a packaging's Medline or customer
  item, Medline's description, Infor's long description, or the commodity code or its description (the commodity
  isn't shown in the table). Item numbers also match without dashes, spaces, dots or slashes:
  "BD930" finds B-D930299Z. **Decided** (2026-10-14). A meaning-based "advanced" search was
  evaluated and parked (section 11).
- **Data as of:** with a stale warning.

**One row per Infor item** (Materials Managers' choice, 2026-10-14; was one per Medline item). Its
Medline items in the range are its **UOMs** (e.g. JLCSFTP22A5SH by the each and JLCSFTP22A5S by
the box, both 111848; called "packagings" in the code), one line each inside the row. Subs, picks
and orders still belong to a Medline item, so the per-UOM columns stay per Medline item.

**Which Infor item.** Medline's `Customer Item #` isn't always an Infor item number: it can be the
Medline item itself (B-D930299H), or Infor's contract-only "Special" number, a 4-digit manufacturer
code plus the Medline item (1296-DYNJAA04), or another number (198765 for B-D367344, Infor item
102205). So the Infor item comes from `vw_MedlineFillKillItemCollection.[Infor Item]`: Infor's
**Medline vendor item** for the Medline item (script 11, CTE f, vendors limited to Medline). A
Medline item that isn't one is a row of its own, *Not in Infor*. **Never by manufacturer part
alone** (2026-10-14, the user): different manufacturers share simple part numbers (e.g. 0104), so
it gives false matches. A manufacturer-part fallback was tried and removed the same day.

**Columns**, sorted by Infor Item (none last), then Medline Item, then Item Description, then the
rest:

| Column | Meaning |
|---|---|
| Infor Item | the Infor item, with *Inactive* when it is; "N UOMs" when more than one |
| Medline Item | one line per UOM: the file's `Item`, the key for subs and orders. A yellow **⚠ superscript** when Medline's customer item isn't the Infor item (or there is no Infor item); hovering says "Medline Customer Item listed as <customer item>" |
| Item Description | Medline's latest description in the range, with the Infor item's long description under it (its short description isn't used) |
| QOE | per UOM: eaches per unit, `MDM_ITEMUOM.UOMConversion` for the Infor item and that UOM ("—" if none) (2026-10-14) |
| Total Ordered / Killed / Filled | per UOM. With several, a last line "All UOMs, in EA" adds them up by the QOE; "—" if a UOM has none |
| PO Lines | per UOM, and their total |
| Latest Reason | per UOM: the latest Medline comment in the range, with its reason category (9.5) |
| Subs Status | per UOM: *approved / hold / pending review / rejected* counts. Subs approved on another UOM not killed in the range are noted |
| Approver's Pick | per UOM. A Materials Manager clicks one to record an order |
| Ordering Status | for the Infor item: *ordered* when a non-voided order for any of its Medline items has an Ordered DT inside the selected range (9.3) |

The **Needs filter** counts Infor items, over all their Medline items' subs, picks and orders.

Clicking the Infor item or a Medline item opens the **item panel** for the whole Infor item.

**Signals between UOMs** (2026-10-14): a sub approved on one Medline item is flagged on the
Infor item's others ("Approved for JLCSFTP22A5S (BX)"); nursing still approves it per Medline item.
The order form shows the combined need ("All 2 UOMs of Infor item 111848 killed 486 EA").

- **Sources:** totals and PO line counts sum `vw_MedlineFillKillQtyAgg` over the chosen dates and
  sites; description, Infor item and UOM conversions come from `vw_MedlineFillKillItemCollection`.
- The three totals sum only lines inside the chosen date range and sites.
- **Quantities are shown with their UOM** (e.g. "10 BX"). If an item appears in more than one UOM
  in the range, the totals are shown per UOM rather than added together. The sample has one UOM
  per item, so this is a guard, not the normal case.
- The table is **Decided** (2026-10-08; Latest Reason and the Needs filter added 2026-10-13).

### Item panel

The panel covers the Infor item: every Medline item (UOM) Medline has killed under it, those
killed in the range first (2026-10-14).

- **Item details** at the top: the Infor item and whether it's active (or *not found*), its long
  description, its commodity code and description, and the manufacturer (2026-10-14).
- **UOMs:** each Medline item with its UOM and QOE, the ⚠ where Medline's customer item isn't the
  Infor item, and *not killed in these dates*.
- **Subs:** one section per Medline item, with status, pick and comments; under each, the other
  UOMs' subs not on it yet, with "Add to <Medline item>". Add a sub, choosing the Medline item
  (the one clicked by default); click a sub for its timeline.
- **Pick history:** every pick, unpick and status change on the item's subs, across all days, so
  the Sub Approver sees what they decided before (9.2).
- **Order history:** every order for the item across all days and subs, with edits and voids
  (9.3).

**Decided** (2026-10-13).

### Subs — per Medline item, across all sites

**Fields**

| Field | Notes |
|---|---|
| Vendor | |
| Vendor Part | the vendor's part number; searchable, and what future LLM sub-finding will use |
| Description | optional; pre-filled for PBO subs from contract data when found (9.4) |
| Status | *Pending Review* when added; the Sub Approver sets *Approved*, *Hold* or *Rejected* |
| Entered By | email, `Medline` for PBO subs, or `system` (reserved for future LLM subs) |
| Create DT, Update DT | |
| Comments | entries of up to 400 characters each, with who and when; none is ever overwritten. The Sub Finder can add one when adding the sub; Sub Approvers add more later (9.7). |

**Rules**

- **Keyed on the Medline item**, not the Infor item: Medline's substitute data uses that key, and
  the Infor number is meaningless outside Infor. **Decided.**
- An item can have any number of subs. There is one sub per (Medline item, vendor, vendor part).
- **Every sub needs the Sub Approver's approval**, including the same product from another vendor
  or in another UOM. Those usually mean buying on a different contract, so the Sub Approver should
  see that even though they judge only item equivalence. **Decided.**
- **Statuses** (9.1): new subs start as *Pending Review*. *Hold* is the Sub Approver's deliberate
  "not now", so it's told apart from subs nobody has looked at yet. Rejecting needs no comment; the
  history records who rejected it and when (9.9). **Decided.**
- **History:** clicking a sub shows its history as an audit-log timeline, with who and when:
  creation, every status change, pick and unpick, and comments. **Decided.**
- **Picking:** approved subs light up a **Pick** button. The Sub Approver can pick one or more
  (usually one), and picked subs appear under Approver's Pick. A pick stays, across days, until the
  Sub Approver unpicks it or changes the sub's status (9.2); a sub that stops being *approved* is
  unpicked automatically. **Decided.**
- **Other packagings** (2026-10-14): a sub approved for another Medline item of the same Infor item
  is flagged, but not approved automatically. Clinically the substitution was already judged; the
  packaging differs, which matters for ordering. So:
  - the main table's Subs Status says "N approved for other packaging: <Medline item> (<UOM>)";
  - the item panel lists the other packagings' subs, with who approved them and when, and a Sub
    Finder can add one to this item in one click. It starts as *Pending Review* and is badged
    "Approved for <Medline item> (<UOM>)", so the Sub Approver can approve it quickly.
  - Suggesting the other packaging itself as a sub was considered and not done: whether it helps
    depends on why it's killed too (e.g. it may be on backorder or allocation as well), which
    nursing and the Materials Manager judge from the reasons. **Decided.**
- **Contract search** (9.4): when adding a sub, a search over Infor's active contract lines, like
  PLM's contract-item search, fills vendor, vendor part, description, UOM and QOE. **Decided.**
- **Where subs come from:**
  - **Medline PBO** substitutes (`SCSFileIngestor.MedlinePBO.MedlineSubCollection`) are added
    automatically: Vendor *Medline*, Vendor Part = the substitute number, Entered By *Medline*,
    status *Pending Review*.
  - **Manual entry** by Sub Finders is the main source. PBO coverage is expected to stay low; only
    1 of the 31 killed White Plains items has one.
  - Subs persist, so the library builds up through daily work: when an item is killed again, its
    subs are already there. **Decided.**

### Ordering (Materials Manager)

- **Recording an order:** the Materials Manager clicks a sub under Approver's Pick and enters:

  | Field | Notes |
  |---|---|
  | Quantity, UOM | UOM pre-filled from the sub when known |
  | QOE | quantity of each: eaches per UOM, e.g. a BX of 100 → 100 (9.6); pre-filled from the sub when known |
  | Vendor | pre-filled from the sub |
  | Ordered By | the user |
  | Ordered DT | defaults to now; editable |
  | Comments | entries of up to 400 characters each, with who and when; Materials Managers add more later (9.7) |

  **Decided.**
- **More than one order per item** is allowed, e.g. 10 from one pick and the remaining 5 from
  another, when one alternative can't cover the need. **Decided.**
- **UOM-mismatch kills** (NONSTOCK UOM): ordering the same item in Medline's stocked UOM goes
  through a sub like everything else, e.g. Medline + the same or the case-pack part number. The
  Sub Approver approves it, and the Materials Manager records the order with the new UOM and QOE.
- **Corrections:** the Materials Manager can correct or void an order. Every change is kept in
  the same audit-log history.
- **Period:** not recorded (stakeholder item 8.5).

### Dropped from the 2026-10-06 design

- per-site approvals, and the "apply to all sites" option
- line-level decisions and the five line stages. The three item-level columns now show the same
  progress: subs → approved → picked → ordered.
- the four option types; a sub is now just a vendor + vendor part
- orders made of entries and covered lines, and "link to an existing order"
- the `Site` table; the site filter uses the Sold-To names in Medline's file

## 6. Tables

**Read from `SCSFileIngestor`** (written by A13 and the PBO pipeline; the app only reads):

| Table | One row per |
|---|---|
| `MedlineFillKill.MedlineFillKill` | Medline order line |
| `MedlineReport.ETLHealth` | pipeline run |
| `MedlinePBO.MedlineSubCollection` | Medline item × PBO substitute |

**Owned by the app: the `PLM` database, schema `FillKill`.** **Decided.** Everything is created by
DDL scripts kept in this repo (`db/fillkill/`) and run on O2 before the app deploy.

| Object | One row per | Notes |
|---|---|---|
| `vw_MedlineFillKill` (view) | kill line | Medline's lines plus the test lines, with an `Is Test` flag. The only reader of Medline's table. (`10_kill_lines.sql`) |
| `vw_MedlineFillKillItemCollection` (view) | Medline item (and UM) | description, Infor UOM conversion for the item and for the contract vendor item, Medline PBO sub, Infor item matched through vendor items, and a consistency flag. Written by the module owner. (`11_item_qty_views.sql`) |
| `vw_MedlineFillKillQtyAgg` (view) | order date × Sold-To × Medline item | ordered, filled and killed quantities, PO line count. Written by the module owner. (`11_item_qty_views.sql`) |
| `TestFillKillLine` | test line | copies of real lines under Sold-To `test site`; emptied at go-live (`10_kill_lines.sql`) |
| `Sub` | sub of a Medline item | medline_item, vendor, vendor_part, description, uom, qoe, status (pending_review / approved / hold / rejected), is_picked, source (manual / medline_pbo; llm reserved), entered_by, create_dt, update_dt |
| `SubOrder` | order recorded by a Materials Manager | medline_item, sub_id, quantity, uom, qoe, vendor, ordered_by, ordered_dt, voided by/at/reason |
| `History` | change or comment on a sub or an order | entity, id, medline_item, action, from → to, comment (≤400), by, at; drives the timelines and the pick and order histories. Comments are rows here, so none is ever overwritten. |

**Notes on the item and quantity views**

- **One row per item is not guaranteed.** `vw_MedlineFillKillItemCollection` has one row per item
  today (31 of 31), but an item gets several rows when it has more than one contract UOM, PBO sub
  or Infor item (the `*_VARS` columns), or appears in the lines with more than one UM, customer
  item or manufacturer. The main table must not add quantities across those rows; it joins on
  item and UM and shows "varies" where the values differ.
- **`Infor Item Consistency` is 0 in two cases:** the matched Infor item differs, or Medline's item
  has no active Medline vendor-item record in Infor. Telling them apart (e.g. NULL for no match)
  would make the flag clearer.
- **Kill reasons aren't in either view.** The Latest Reason column and reason trends on
  the Dashboard read the comment from `vw_MedlineFillKill`.
- **PBO subs:** `Medline.Sub` in the item view is where Medline's PBO substitutes enter `Sub`.

In the PLM schema: `UserModuleRole` (user, module, role, granted by/at); admin is `users.user_role`.

## 7. App pages (under `/plm/fillkill/`)

- **Main** (`/`): the one operating page for every role (section 5).
  - The main table with its controls. **View subs** opens a panel for that item: the sub list, add
    sub, status, pick, history, and recording orders against picks.
  - **All subs:** a table (or cards) of every sub across all items, filterable by status, vendor and
    item. This is the reference library.
  - **Orders:** a table (or cards) of the orders Materials Managers recorded, with their history.
- **Dashboard** (`/dashboard`): trends and analytics, e.g. kills over time by reason and site, sub
  coverage, time to review, and rejected subs with their comments, grouped by vendor and item. Read-only for every Fill/Kill role. Separate from
  PLM Tracker's dashboard.

`/subs` and `/orders` are no longer pages (2026-10-13).

**Navigation:** a top row switches between PLM Tracker and Fill/Kill Management; a second row shows
the active module's pages (Fill/Kill: Main, Dashboard). PLM pages and URLs are unchanged.

## 8. For stakeholders

1. **What to display.** **Answered 2026-10-08:** a date range slider plus a site filter, rolled up
   per Medline item.
2. **Lifecycle beyond today.** Nothing closes, and any date range can be reviewed. Is any analysis
   wanted on history?
3. **Separating approval and ordering.** One person can't currently be both Sub Approver and
   Materials Manager. Confirm that is wanted.
4. **Approval level.** **Answered 2026-10-08:** per Medline item, for all sites.
5. **Ordering level and coverage** (for the director).
   - **Level:** answered 2026-10-08, per Medline item.
   - **Still open:** if the Materials Manager orders ahead (e.g. two weeks), how is that coverage
     tracked, and who keeps count of the substitute stock on hand? No period is recorded in v1.
6. **Auto sub.**
   - What exactly is an auto sub, and is it set up on Medline's side or in our Infor?
   - Who enters and maintains it, and how does nursing learn that one exists?
   - Is the substitute in Medline's Proactive BackOrder (PBO) report the same thing?
   - Could we get it as a lookup view, or as a column in a later version of Medline's report?
7. **Where subs come from.** PBO coverage is low (1 of 31 sample items), so manual entry is the main
   source.
   - Are we expecting new files, e.g. a Medline auto-sub list, or extra columns in the fill/kill
     report?
   - Should other existing data suggest subs? Candidates: PLM conversion pairs (`ItemLink`), other
     contracts carrying the same item (`vw_ContractItem`).
8. **UOM-mismatch kills.** Handled as a sub for the stocked UOM, approved by the Sub Approver and
   ordered by the Materials Manager with the new UOM and QOE. Confirm that matches practice.
9. **Critical tag.** Per Medline item, set by the Sub Approver (nursing). Deferred from v1.
10. **PLM conversion.** Approved subs (especially for discontinued items) feeding PLM conversion
    pairs. Future goal.
11. **Order confirmation and fill rate.** Checking recorded orders against `PURCHASEORDER_LINE`,
    and a fill-rate measure (needs Infor PO lines as the denominator). Later.
12. **Feed.** Email vs SFTP; one file per site or one combined file.

## 9. Design questions — answered 2026-10-13

1. **Statuses.** New subs start as *Pending Review*. *Hold* (renamed from *wait*) is a status the
   Sub Approver chooses, meaning held on purpose.
2. **Picks persist.** Yes, until unpicked or the sub's status changes. The item panel shows the
   item's pick history.
3. **Ordering Status.** *Ordered* when an order for the item has an Ordered DT inside the selected
   range. The item panel shows the item's whole order history.
4. **Sub description.** Yes, optional, pre-filled for PBO subs from contract data. A contract
   search, like PLM's, helps fill in a sub.
5. **Latest Reason column.** Yes.
6. **QOE.** Quantity of each: eaches per UOM.
7. **Who adds and comments.** Only Sub Finders add subs. Sub Approvers add comments to subs;
   Materials Managers add comments to orders. Typical role sets: Sub Finder + Sub Approver, Sub
   Finder + Materials Manager, or Viewer; Sub Finder alone is kept for a future AI agent.
8. **Needs filter.** Yes (section 5).
9. **Comment on reject.** Not required; the history records who rejected and when.

## 9b. Ordering on the combined quantity (2026-10-14) — B chosen

**Decided:** B. Materials Managers chose the Infor item as the main row (section 5). Orders still
belong to a pick of one Medline item; the Infor item's row is *Ordered* when any of its packagings
has an order in the range, so ordering the combined need once clears *Needs order*. Questions 2 and
3 below are still open. The original question:


Materials Managers may order an Infor item's combined need once, rather than per packaging. Today
an order belongs to a pick of one Medline item, so after ordering the combined 486 EA through
JLCSFTP22A5S, JLCSFTP22A5SH would still say *No order* and stay under *Needs order*.

- **A. An order can cover the whole Infor item** (proposed). The order form gets "Covers all
  packagings of 111848"; the other packagings in the range then count as ordered ("Ordered via
  JLCSFTP22A5S") and leave *Needs order*. Small change: one column on `SubOrder`. Rows, subs and picks
  stay per Medline item.
- **B. The Infor item becomes the main row**, with its Medline items under it. Closer to how
  ordering may really work, but it changes the roll-up everywhere: the Needs filter, Subs Status, the
  Dashboard's counts.

Questions:

1. A now, and B only if UAT shows Materials Managers think in Infor items?
2. Should "covers all packagings" be ticked by default when the Infor item has several packagings?
3. Pre-fill the quantity with the combined need converted to the pick's UOM (rounded up), when the
   pick has a QOE?

## 10. Phases

1. **App shell**: navigation, `UserModuleRole`, User Control column, CSRF, daily login reset.
   Web-server deploy #1. Not affected by the 2026-10-08 revamp.
2. **Data**:
   - Done: ingestion built in A13, with the 11 samples loaded; the item and quantity views.
   - Run on O2: `10`–`14` (kill-line view with reasons, test lines, item and quantity views,
     workflow tables, contract search, PBO sync).
   - Remaining: read grants for the app's account, the Task Scheduler trigger.

   No web-server deploy needed.
3. **Workflow**: the Main page (with its subs and orders tables) and the Dashboard. Web-server
   deploy #2. **Built** 2026-10-13 (plan v2 W1–W5); next is UAT, then the deploy.

## 11. Advanced (semantic) search — evaluated 2026-10-14, parked

**Parked** 2026-10-14 to focus on the current design; revisit after go-live, or with the AI Sub
Finder (plan v2 §10). An idea, not a requirement: a toggle on the search box that matches by **meaning** across
Medline's description, Infor's long description and the commodity description. For example,
"pulse ox sensor for babies" would find *SENSOR INFANT OXIMETER*, though no word matches.

**Trial on 2026-10-14** (local, nothing deployed): `fastembed` (ONNX) with the small
`BAAI/bge-small-en-v1.5` model, over the 11,562 active Infor items (long description + commodity
description).

| | Result |
|---|---|
| Python packages | `fastembed`, `onnxruntime`, `tokenizers`, `numpy`: 165 MB. Windows wheels for Python 3.13; no PyTorch. |
| Model | 64 MB on disk |
| Quality | Good on everyday words, where keyword search finds nothing: "pulse ox sensor for babies" → infant oximeter sensors; "exam gloves without latex" → latex-free nitrile exam gloves; "iv catheter 24 gauge" → 24GA IV catheters; "ecg leads" → EKG leadwires. Looser phrases ("tape for sensitive skin") come back mixed. |
| Vectors | 11,562 × 384 numbers = 17 MB |
| Embedding every item | 5 minutes on a laptop CPU, 1.2 GB memory at peak, so done offline (e.g. nightly in A13), not by the web app |
| Cost to the web app | about 220 MB more memory per Python process, 1.5–2 s to load the model the first time, then about 10 ms per search |
| Network | Downloading the model failed: the network re-signs HTTPS, and Python doesn't trust that certificate. The model files would be copied to the server with the app; nothing is downloaded at run time. |

**Ways to deploy it on the web server** (IIS FastCGI on Windows; O2 is SQL Server 2019):

| Option | What it needs there | Verdict |
|---|---|---|
| A. Vectors in a PLM table, model in the app | `pip install fastembed`; the model folder copied with the app; a nightly A13 step that embeds new or changed items into a `FillKill` table | **Recommended, if we do it.** No new server or service. |
| B. Chroma | Its built-in mode isn't safe with several IIS processes sharing one folder; its server mode is another always-on service on the web server, with more dependencies | Not worth it for about 12,000 vectors |
| C. Postgres + pgvector | A new database server to install, secure and back up | Not justified at this size |
| D. Hosted embeddings (e.g. Azure OpenAI, if Montefiore has an approved tenant) | An API key and outbound HTTPS; approval | Lightest on the server, but depends on approval and the network |
| E. SQL Server full-text search (installed on O2) | A full-text index on an item-text table; synonyms need a thesaurus file on the SQL Server host | Smarter keywords (word forms, ranking), not meaning. A cheap middle step. |
| F. Native vectors in SQL Server 2025 | An O2 upgrade | Not available on 2019 |

**Why no vector database:** 12,000 vectors are 17 MB; comparing a search against all of them in
memory takes milliseconds. A vector database earns its keep at millions of vectors, for example if
the future AI Sub Finder searches all 632,000 contract lines.

**To ask Abdallah** before choosing A:

- The Python version on the server, and whether he can `pip install` packages.
- How much memory the server has, and how many FastCGI processes the app pool runs: each one would
  load the model.
- The app pool's idle timeout: a recycled process reloads the model (about 2 s on its first
  search).

**Suggested path:**

1. Done: keyword search over the item numbers, both descriptions and the commodity.
2. If wanted: option A behind an "Advanced" toggle, loading the model only when someone uses it.
3. The same vectors can later suggest subs ("items like this one"), which is the groundwork for the
   AI Sub Finder.
