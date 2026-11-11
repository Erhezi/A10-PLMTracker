# Fill/Kill Management — design notes

Living draft. Last updated 2026-10-27.

**Revamped 2026-10-08 after meeting users and stakeholders.** The workflow is now **per Medline
item, with no site distinction**: sites are only a filter, and subs, picks and orders belong to the
item. This replaces the per-site, per-line design of 2026-10-06; what was dropped is listed at the
end of section 5.

**Business model renewed 2026-10-27** after a review with the users and stakeholders (section 1b):
the app is the **central hub** where nursing, the Materials Management lead and the sites' Materials
Managers coordinate their decisions. Subs and picks still belong to the Medline item, for every
site; **orders now record the site they were placed for**, and their PO number when the site
gives it.

Decisions are marked **Decided**. Items to take to stakeholders are in section 8; the design
questions in section 9 were answered on 2026-10-13.

**Words used here**

- **Medline item** = the file's `Item` (e.g. `MDS2585H`), Medline's catalog number. From our side
  it is the vendor part number. It is the key for everything in this module.
- **Site** = a Medline Sold-To account. There are 10 Montefiore accounts (LUM, BULK, EVS, LAB), and
  `FillKill.Site` assigns each to its campus (Moses, Wakefield, Einstein) (2026-10-30, `15_sites.sql`).
- **Department** = a Medline Ship-To under a site (4E, ICU, ED…).
- **Kill line** = one row of the Medline file (a partial fill counts as a kill).
- **Sub** = a substitute recorded for a Medline item: its Reference SKU, with vendor items to order
  it by (section 5).
- **Instruction** = SCM's word to the sites' Materials Managers on how to order an item
  (2026-10-27).
- **SCM** = the role coded `scm` (`mm_lead` until 2026-11-02), shown as MM Lead until 2026-10-28
  and MM/SCM until 2026-11-02.
- **Approved** = approved by nursing: clinically acceptable, and so it can be ordered. From
  2026-10-28 every approved sub can be ordered; **picking** among them (2026-10-20 to 10-28) is
  gone (section 1b). Dated passages below that still speak of picks describe that time.

## 1. Scope

- A second module in the app, alongside **PLM Tracker**. The app is now called **Item
  Management**, with PLM Tracker and Fill/Kill Management as its modules. Same Flask app, same
  `/plm` mount on the server's IIS, same users and login. New pages live under
  `/plm/fillkill/...`; existing PLM URLs do not change.
- Tracks Medline's fill/kill exceptions on company 3000 requisitions, rolled up per Infor item.
  Nursing approves substitutes and picks them, SCM tells the sites how to order, and each
  site's Materials Managers order and record what they ordered (section 1b).
- **v1 is functional but simple.**
  - The main table rolls up the kill lines for a chosen date range (default: today) and the chosen
    sites, one row per Infor item.
  - Subs and picks belong to the Medline item, for every site. Orders belong to the Medline item
    and, since 2026-10-27, to the site they were placed for; the site filter applies to them too.
  - Earlier days stay in the database untouched. Nothing is closed or carried over.

  **Decided** (2026-10-08; sites on orders 2026-10-27).

## 1b. Business model — the app as the coordination hub (renewed 2026-10-27)

**What changed.** The user reviewed the app with the stakeholders. The Materials Management manager
(Will) won't usually order himself: he guides the Materials Managers at each site on how they
should order. The nursing manager (Josh) wants his latest comment readable on the table without
opening anything. So the app is no longer one team's worklist. It is the **central hub** where the
parties who decide and the people who order coordinate, and where everyone sees the latest word on
each item.

**The parties**

| Party | Fill/Kill role | Decides | What Main shows of it |
|---|---|---|---|
| Nursing (the nursing manager and nurses) | Sub Approver | What is clinically acceptable: enters and approves subs, holds or rejects them (which stops them being ordered), comments on subs | **Sub Approved by Nursing** (2026-11-02; Approved by Nursing before): every approved sub, each with its latest comment, as text (new) |
| Materials Management lead (MM manager) | **SCM** (new; "MM Lead" until 2026-10-28, "MM/SCM" until 11-02) | How the sites should order: which approved sub and vendor item, how much, for which sites. Adds vendor items, with no approved sub too (2026-11-02). Usually doesn't order | **SCM Comments** column ("MM Instruction" at first, "Will's Comments" until 2026-11-02): the item's latest instruction (new) |
| Each site's Materials Managers | Materials Manager | Carry the instruction out: order for their site and record it: the sub's vendor item and how much, with the PO number if they have it | **Ordering Status**: each order with its site; **Total Sub Ordered (EA)** with what each site is short (new) |
| Everyone else | Viewer | Nothing; sees everything | |
| A future AI finder | Sub Finder | Proposes subs for nursing to review | |

**The flow, per item**

1. Medline kills lines at one or more sites. Main shows them per Infor item, with Medline's reasons.
2. Nursing enters subs (approved on entry) or reviews proposed ones. Every approved sub can be
   ordered (2026-10-28; nursing picked one before), and its latest comment reads on the table.
3. SCM adds the vendor items to order it by and writes the **instruction**, e.g. "Moses and
   Wakefield: 2 CA of B-D930103CS each. Einstein: use stock until Friday."
4. Each site's Materials Manager reads the instruction, orders for their site, and records the order:
   the vendor item, the quantity and the **site**, with the **PO number** if they have it.
5. Main shows each site's orders and shortfall at once, so SCM sees which sites have
   recorded and which are short, and writes a new instruction when the situation changes.

**Principles**

- **One latest word per party, on the table.** Main shows nursing's latest comment on each approved sub and
  SCM's latest instruction on each item. The full threads open from them, so nobody needs
  the panel to know where things stand.
- **Nothing is overwritten.** Instructions are kept like comments: who, when, every one of them. The
  newest is the one in force.
- **Responsibilities stay separate.** Nursing decides what is acceptable; SCM decides how to
  order it; the site Materials Managers order. The app records who decided what.
- **Sites order separately.** An order belongs to one site. The Materials Manager is responsible
  for choosing the right one; the form starts on their site when they've filtered Main to it.
  Killed and ordered quantities compare like with like for the sites shown, and the order form's
  recommendation is for the order's site.
- **Keep it all in one place.** The least a site records is the sub's vendor item and the quantity
  (its UOM comes with the vendor item): that is what tracks the order. The PO number is optional,
  and kept so orders can later be linked back to each day's killed items. In practice a site may
  order as SCM says and record nothing; the app can't make them, so users are asked to
  record every sub order here, and Main shows SCM which sites haven't.

**Decided** (2026-10-27, the user): a new SCM role writes the instructions (site Materials
Managers can't); Josh's latest comment is the pick's latest sub comment, shown inline, with no new
nursing note; orders record their site, chosen by the Materials Manager; the Record order form gets
an optional PO number. An order recorded by PO number alone (a "+ PO" on the row, checked against
Infor's PO lines the next day) was drafted the same day and dropped by the user: the quantity is the
record, and nothing is matched against Infor in this deploy.

**Decided after trying it** (2026-10-27, the user; the open items of 8.13):
- The instructions' column is called **SCM Comments** (2026-11-02; Will's Comments until then; one label in the code,
  `rules.INSTRUCTION_LABEL`), and sits **before Vendor Item Detail**: read before ordering from the tiles.
- **Double-click to write.** SCM double-clicks the SCM Comments cell to add one; nursing
  (Sub Approvers, Sub Finders) double-click a Sub Approved by Nursing cell to add a sub for its Medline item.
  Both open a small modal. The item panel has an **Add comment** button too, like its Add sub.
- **One free-text comment per item**, not one per site: it names the sites it speaks to.
- **Nobody is emailed.** The sites' Materials Managers open Main, or refresh it, to read the latest.
- **No home site.** A Materials Manager picks their sites with the site filter, which reveals their
  site's figures (and keeps them in the page link); with every site chosen, the totals show. Main and
  the Dashboard alike.

**Simplified** (2026-10-28, the user):
- **Approved by nursing means clinically approved, and every approved sub can be ordered.** Picking
  among the approved subs is gone: no Pick or Unpick (called Prefer and Unprefer for a morning), no
  *Needs pick*, no automatic picks, nothing about picks on orders or deletes. A Sub Approver's entry
  is approved on entry; a Sub Finder's, and Medline's PBO subs, wait for a Sub Approver's review.
- **To stop a sub being ordered**, the Sub Approver puts it on **Hold** or **Rejects** it, with a
  reason if they like. The reason is kept as the sub's comment ("Hold: ..."), so it reads on its
  card. The sub leaves Main's column and can't be ordered until it's approved again; its orders so
  far stay.
- Main's pick column is **Approved by Nursing** (**Sub Approved by Nursing** from 2026-11-02; "Picked for Ordering" before; "Nursing's Pick" and
  "Nursing's Recommendation" for a morning): every approved sub, a line each, with its latest
  comment and its vendor items beside it.
- *Needs details* now means no approved sub has a vendor item yet, so nothing can be ordered.
- The code keeps `Sub.is_picked` (always 0; the table's CHECKs name it) and the History actions
  `pick` and `unpick` the table allows; none is written. No database change.
- The role shows as **SCM** (2026-11-02; MM/SCM from 10-28, MM Lead before), for the function rather
  than a rank above the sites' Materials Managers. Its code is `scm` too (2026-11-02, the user: one
  name, no confusion later; `mm_lead` before): `02_user_module_role.sql` renames the rows, so
  nobody's roles change.

**Considered, not planned: finding orders in Infor that nobody recorded.** The app could search
Infor's PO lines for the subs' vendor items after each kill and show "Found in Infor". The user
decided against it (2026-10-27): searching that way is inefficient and error-prone (routine orders
of the same item would look like sub orders, and Infor's ship-to locations would have to be mapped
to Medline's sites). Whether an order happened is tracked through what the sites record.

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
  company 3000. As of 2026-10-30 it has ten Sold-To accounts across three campuses (`FillKill.Site`).

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
  the samples; confirm them once the hourly mail starts. If each Sold-To account gets
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
    | `fillkill` | `viewer` alone, or any of `sub_finder`, `sub_approver`, `materials_manager`, `scm` |
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
| Sub Approver | `sub_approver` | Nursing. Entering a sub's Reference SKU (approved on entry, so it can be ordered); approving, holding and rejecting subs (a reason optional, 2026-10-28); comments on subs; correcting a Reference SKU; deleting a sub |
| Materials Manager | `materials_manager` | A site's buyer. Adding each sub's vendor items (vendor part, vendor, vendor ID, UOM, QOE, ...), with the contract search; recording orders for approved subs' vendor items, each for a site; comments on orders |
| SCM | `scm` | (2026-10-27; coded `mm_lead` until 2026-11-02, shown "MM Lead" until 2026-10-28, "MM/SCM" until 11-02) Coordinating how the sites order. Writing each item's instruction to the sites' Materials Managers; adding vendor items. Doesn't record orders unless also given Materials Manager |
| Sub Finder | `sub_finder` | Proposing subs, pending review; adding vendor items. Kept for a future AI finder |

**Revised 2026-10-15 after the stakeholder review.** Nursing should do as little as possible, and
there is no team to collect and enter every candidate: nursing, supply chain and Materials Managers
gather options from suppliers by email and phone, and nursing filters them. So:

1. Nursing (Sub Approver) enters only the vendor part, with a note if they like; it's **approved on
   entry**, so it can be ordered (2026-10-28; until then it was also picked if it was the Medline
   item's only approved sub). They can still Hold or Reject it later, which stops it being ordered.
   The Sub Approver's comments stay.
2. The **Materials Manager** adds the sub's **vendor items**, each a way to order it: a vendor
   part, its vendor, Infor's vendor ID and a UOM (required), with QOE, manufacturer part, Infor item
   and description, from the contract search if they like. Then they record orders against them.
   **What nursing enters is the Reference SKU** (2026-10-20; "vendor part" until then, and
   2026-10-19's "approved reference"): often the manufacturer's part (e.g. BD's 930103), which
   several vendors sell in several UOMs (Medline's B-D930103CSZ, a box of 40, and B-D930103CS, a
   case of 400). The Reference SKU never changes with the vendor items, so who decided what stays
   clear: the Sub Approver approved the Reference SKU; the Materials Manager chose what to order.
   Each vendor ID, vendor part and UOM is a vendor item of its own, as many as a sub needs. Until
   2026-10-20 a sub had one set of vendor details, and setting the vendor part ordered replaced
   what was entered ("Entered as"); entering the same part twice was the only way to a second
   vendor part. `12`'s step 2 turned those into vendor items, merging such subs.
3. Subs proposed by the system (Medline PBO, a future AI agent) stay **pending review**; the Sub
   Approver approves, holds or rejects them.
4. A sub is one Reference SKU per Medline item; its vendor items can wait for the Materials Manager.

Capabilities: `add_sub` = Sub Approver, Sub Finder (enter, correct the Reference SKU, delete);
`review` = Sub Approver (status, with an optional reason, and comments on subs); `pick` (2026-10-21
to 10-28: Sub Approver, Materials Manager, SCM) is gone; `details` = Materials Manager, Sub Finder, SCM (add, correct
and delete vendor items, with the contract and vendor searches); `order` = Materials Manager;
`instruct` = SCM (write an item's instruction, 2026-10-27).

**Renewed 2026-10-27** (section 1b). The Materials Management lead guides the sites' Materials
Managers rather than ordering, so they get a role of their own, **SCM** (MM Lead at first). It writes the item's
instruction, which the sites' Materials Managers can read but not write, and it can pick and add
vendor items, since choosing what to order is part of guiding how to order. It can't record orders:
a lead who also orders is given Materials Manager as well.

- **The Sub Approver decides what is clinically acceptable and which sub to use; the Materials
  Manager records what was ordered.** Today the Sub Approver is usually nursing. **Decided.**
- **Combinations:**
  - Viewer is held alone: it can't be combined with the other roles, which can all view.
    **Decided** (2026-10-13).
  - In practice nursing holds **Sub Approver**, the sites' Materials Managers **Materials
    Manager**, the Materials Management lead **SCM** (2026-10-27), and others **Viewer**. Sub
    Finder is kept for a future AI agent that finds subs.
  - SCM combines with Materials Manager (a lead who also orders). It isn't refused with Sub
    Approver: the rule below separates approving from ordering, and SCM doesn't order.
  - Sub Approvers and Sub Finders add subs; a Materials Manager doesn't (revised 2026-10-15; was
    "only Sub Finders", 9.7).
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
and sees the same thing; what they can do on it follows their roles. Nursing enters subs (approved
on entry) and reviews and picks right there, SCM writes each item's instruction, and the
sites' Materials Managers add vendor items and record orders for their site from the picks' vendor
items (revised 2026-10-15, 2026-10-20 and 2026-10-27, sections 1b and 4).
The full sub list and the order log are tables (or cards) on the same page, not pages of their own.
Trends and analytics live on a separate Dashboard page (section 7).

### Main table — one row per Infor item

**Controls**

- **Fill/Kill dates** (2026-10-15; the slider was dropped; called "Order dates" until 2026-10-20,
  renamed so they aren't taken for our orders' dates): the kill lines' order dates. Two date boxes,
  and a button beside them that switches between **View today** (today only, the boxes locked) and
  **Select a range** (the boxes open). Default (2026-10-20): **today** on the live server
  (`ProductionConfig.FILLKILL_OPEN_ON`); locally the newest day with lines, since O2's data can end
  days ago.
- **Site filter:** one or more sites. Default: all. It applies to the kill lines and, since
  2026-10-27, to the orders: with sites chosen, only their orders count in Ordering Status, Total Sub
  Ordered (EA), the Needs filter and the orders under the table. Orders recorded before sites were
  (no site) count only when every site is shown.
- **Needs filter:** All · Needs subs · Needs review · Needs details · Needs order · Ordered (9.8;
  *Needs pick* until 2026-10-28):
  - *needs subs*: no sub that is pending review, approved or on hold
  - *needs review*: at least one sub pending review
  - *needs details*: approved subs, none with a vendor item yet, so nothing to order, and not
    ordered yet (2026-10-19; 2026-10-28: none of the approved, rather than a pick without): the
    Materials Manager's to-do list
  - *needs order*: at least one approved sub, and no order in the range for the sites shown
  - *ordered*: an order in the range for the sites shown (2026-10-27: an order for another site
    doesn't count)
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
| Sub Approved by Nursing | ("Approved by Nursing" from 2026-10-28 until the user renamed it on 2026-11-02; 2026-10-28: every approved sub, since every one can be ordered; before, the picks: "Approver's Pick" until 2026-10-21, "Picked for Ordering" until 2026-10-28) per UOM: each approved sub's **Reference SKU**, as entered (2026-10-20), on a line of its own (2026-10-21; oldest first), the UOM's other cells spanning its subs' lines. A sub put on hold or rejected leaves it. A pencil when it has no vendor item yet, so nothing can be ordered, shown only to those who add vendor items, for whom it opens the vendor item form (2026-10-21: to Viewers and Sub Approvers it looked like a button that didn't work). A comments icon beside each (2026-10-21, the user) counts its comments and opens them all, newest first, in a popover, for everyone, without the panel. **Under the Reference SKU, its latest comment as text** (2026-10-27, for the nursing manager): up to two lines (the whole on hover), with who wrote it and when. **Double-click the cell** (Sub Approvers and Sub Finders, 2026-10-27, the user): a modal adds a sub for that line's Medline item (Reference SKU and note, the panel's Add sub), showing the subs on file and the approved ones |
| SCM Comments | (2026-10-27; "MM Instruction" until the user renamed it and moved it before Vendor Item Detail the same day, "Will's Comments" until 2026-11-02) for the Infor item: SCM's latest instruction to the sites' Materials Managers, up to three lines (the whole on hover), with who and when. Its icon counts them and opens them all, newest first, in a popover. SCM **double-clicks the cell** to write a new one (no button in the cell; the cell is outlined under the pointer, and says so on hover), or uses the panel's Add comment. It isn't tied to the Fill/Kill dates: the latest stays in force until a newer one replaces it, and its date shows how old it is |
| Vendor Item Detail | per approved sub, on its line (2026-10-20; beside it from 2026-10-21): a tile for each of its vendor items (vendor part, UOM/QOE as in `CA/400`, vendor ID and name). A Materials Manager clicks one to record an order; "+ Vendor item" adds another. **Without a sub** (2026-11-02, the user): on the UOM's line with no approved sub (the only line when none is approved, an extra one once it has vendor items without a sub), the tiles of its vendor items without a sub, and, for Materials Managers and SCM, "+ Vendor item" to add one (section Ordering) |
| Ordering Status | for the Infor item: *ordered* when a non-voided order for any of its Medline items, for a site shown (2026-10-27), has an Ordered DT inside the Fill/Kill dates (9.3; 2026-10-20, back from "on or after the first day"), otherwise *no order*; it lists each order's quantity, UOM, **site** (2026-10-27) and date, newest first (three, then "+N more"); click for the Orders tab, which has all of them |
| Total Killed (EA) | (2026-10-21, the user) for the Infor item: killed in the Fill/Kill dates at the sites shown, all its UOMs, in eaches by Infor's QOE (an EA without one counts 1); "—" when a UOM has no QOE. Killed at several sites: each site's eaches on hover |
| Total Sub Ordered (EA) | (2026-10-21) for the Infor item: its subs' orders in the Fill/Kill dates for the sites shown, in eaches, each order's quantity times its own QOE; "—" when an order's UOM has none. Fewer than killed: "N EA short" in red. Killed at several sites (2026-10-27): a red line per site that's short ("Moses: 20 EA short"), since each site orders for itself. Why: kill lines keep coming in through the day, so an item ordered for 10 EA at 11:00 may have 30 EA killed by 2:15 |

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

**Scope** (2026-10-15): clicking the **Infor item** shows all its UOMs (subs, kill lines, Sub
History and orders of every Medline item); clicking a **Medline item** shows only that Medline item
(one UOM), with "Show all N UOMs of Infor item X" to widen. In the all-UOMs view, clicking a Medline
item in the UOM list narrows to it. A Medline item's subs section still lists subs on the other UOMs
not on it yet. The API returns the whole Infor item either way; the page filters.

- **Item details** at the top: the Infor item and whether it's active (or *not found*), its long
  description, its commodity code and description, and the manufacturer (2026-10-14).
- **SCM Comments** (2026-10-27): SCM's latest instruction, with who and when; *All N*
  lists them all under it. SCM gets **Add comment** (the user: a button like the subs' Add sub),
  which opens the same modal as a double-click on the column.
- **UOMs:** each Medline item with its UOM and QOE, the ⚠ where Medline's customer item isn't the
  Infor item, and *not killed in these dates*.
- **Subs:** one section per Medline item; each sub's card has its Reference SKU, status,
  comments and its vendor items (each with Record order, Correct, Delete), and "+ Vendor item".
  Under each section, the other UOMs' subs not on it yet, with "Add to <Medline item>" (the
  Reference SKU only: vendor items are per UOM). Add a sub, choosing the Medline item (the one
  clicked by default); a sub's History includes its vendor items'.
- **Sub History** (was "Pick history"; renamed 2026-10-15, since "pick" means something specific to
  Materials Managers): every sub added, every status change and deletion on the item's subs,
  and every vendor item added and deleted (2026-10-20), across all days, so the Sub Approver sees
  what they decided before (9.2).
- **Width:** drag the panel's left edge (or arrow keys on it) to resize; remembered per browser,
  double-click resets (2026-10-15).
- **Order history:** every order for the item across all days and subs, with edits and voids
  (9.3). A table like the kill lines (2026-10-20; cards before): ordered, site (2026-10-27),
  vendor part (for its Reference SKU), quantity with UOM/QOE, vendor and ID, who, the latest
  comment; Correct, Void, Comment and History open from icons, the last two in a line under the row.
  Every site's orders, whatever the site filter: it is the item's whole history.

**Decided** (2026-10-13).

### Subs — per Medline item, across all sites

**Fields of a sub** (2026-10-20: what the Sub Approver or a Sub Finder enters, and its review)

| Field | Notes |
|---|---|
| Reference SKU | what was entered: nursing's approved reference, often the manufacturer's part, or Medline's PBO number; searchable, and what future LLM sub-finding will use. It doesn't change with the vendor items; nursing can correct it until the sub has an order |
| Status | *Pending Review* when added; the Sub Approver sets *Approved*, *Hold* or *Rejected* |
| Entered By | email, `Medline` for PBO subs, or `system` (reserved for future LLM subs) |
| Create DT, Update DT | a vendor item added, corrected or deleted updates its sub too |
| Comments | entries of up to 400 characters each, with who and when; none is ever overwritten. The Sub Finder can add one when adding the sub; Sub Approvers add more later (9.7). |

**Fields of a vendor item** (2026-10-20: what can be ordered for the sub, the Materials Manager's or
a Sub Finder's; until then these were the sub's own "vendor details", one set per sub)

| Field | Notes |
|---|---|
| Vendor | the vendor's **name**, required. Picking a contract line fills it with Infor's name. Typing it searches Infor's vendors (2026-10-19): every word anywhere in the vendor name, legal name or search name (`MDM_VENDOR`'s VendorName, LegalName, VendorSearchName, through `vw_Vendor`), `*` inside a word for anything, digits also matching IDs; active vendors first, at most 20. Choosing one fills in its vendor ID and Infor's name |
| Vendor ID | Infor's vendor ID (e.g. 1000931), **required** (2026-10-19; optional from 10-15): a vendor item can't be saved without it. When Infor has no such vendor, the Materials Manager says so on purpose with **0000000**, "Vendor not available in system" (seven digits like Infor's vendor IDs, 0000000 from 2026-10-20; Infor has no vendor 0000000): choosing it clears the vendor name and asks for the one they know, which isn't looked up in Infor (2026-10-20). Filled in from a contract line or the vendor search; typed by hand, it must be one Infor knows (`vw_Vendor`). **The vendor name follows the ID** (2026-10-21, the user): whenever the ID changes, typed, chosen or from a contract line, Infor's name for it replaces whatever name was there, and a name box left after a search nobody chose from goes back to the ID's vendor; the server saves Infor's name for an Infor ID too, and refuses a correction that changes only the name (change the ID instead). Only 0000000's name is typed. Medline PBO vendor items get 1000931 (MEDLINE INDUSTRIES INC) |
| Vendor Part | the vendor's part number, required: the one ordered (e.g. B-D930103CSZ for the Reference SKU 930103) |
| UOM, QOE | the UOM, required, and its eaches (QOE, optional). The same vendor part in another UOM is another vendor item |
| Manufacturer Part | the manufacturer's part number (2026-10-19), from the contract line's manufacturer number or typed |
| Infor Item | Infor's item number for it (2026-10-19), when it has one: item-master contract lines only ("Special" lines have none) |
| Description | optional; from the contract line when chosen (9.4) |
| Entered By, Create DT, Update DT | who added it and when; corrections are in its History |

**Rules**

- **Keyed on the Medline item**, not the Infor item: Medline's substitute data uses that key, and
  the Infor number is meaningless outside Infor. **Decided.**
- An item can have any number of subs. There is one live sub per (Medline item, Reference SKU)
  (2026-10-20; per vendor part from 2026-10-15). A sub can have any number of vendor items, one
  live one per (vendor ID, vendor part, UOM).
- **Vendor items** (2026-10-20) can be added to any sub, whatever its status, by Materials Managers
  and Sub Finders. Correcting one never changes its orders, which keep what they were placed with.
  Deleting one needs a reason and is refused while it has orders that aren't voided; its row stays.
  Main's Needs details counts items whose approved subs have no vendor item yet.
- **Not the killed item itself** (2026-10-20, the user): a vendor item whose vendor part is the sub's
  Medline item (ignoring case) under one of Medline's vendor IDs, 1000931, 1017968, 1017969 or
  1037888 (`rules.MEDLINE_VENDOR_IDS`), is the item that was killed, not a sub. It's refused when
  added or corrected, with a message saying so; the contract search lists such a line but it can't
  be chosen, and the form flags it as typed. The same number from another vendor is allowed.
  Medline's PBO data had no item listed as its own substitute on 10/20, so 14 is unchanged.
- **UOMs as Infor has them** (2026-10-20): a UOM typed into a vendor item or an order correction is
  saved as Infor's (Lawson's) when it's one of `MDM_EDI_SUB_UOM`'s external values (CS is CA, VL is
  VI; `vw_UomAlias`, 13), and as typed otherwise; the form changes it as the box is left. PH is
  listed as PK there, though one Infor item has a PH UOM: 109889 (Raney scalp clip), whose PH and PK
  are both 200 EA. Checked with the user 2026-10-21: PH is converted to PK like the rest.
- **Spaces** (2026-10-20): every box loses leading and trailing spaces when it's left, and the
  server drops them too.
- **Deleting a sub** (2026-10-15): a Sub Finder can delete one, with a required reason. It leaves the
  item, the library, the counts and the Dashboard, but its row stays (who, when, why) and Sub History
  shows "Deleted: <reason>"; Medline's PBO sync doesn't add a deleted PBO sub back, and the same
  Reference SKU can be added again as a new sub. Refused for a sub with orders that aren't voided
  (and, until 2026-10-28, for a picked one).
- **Every sub needs the Sub Approver's approval**, including the same product from another vendor
  or in another UOM. Those usually mean buying on a different contract, so the Sub Approver should
  see that even though they judge only item equivalence. **Decided.** **Changed 2026-11-02 (the
  user):** when SCM directs the sites to order something no sub nursing approved covers (e.g. "order
  the same original item 345678 from BD", or a sub item nursing hasn't approved), ordering doesn't
  wait for one: see *Vendor items without a sub* under Ordering.
- **Statuses** (9.1): new subs start as *Pending Review*. *Hold* is the Sub Approver's deliberate
  "not now", so it's told apart from subs nobody has looked at yet. Rejecting needs no comment; the
  history records who rejected it and when (9.9). **Decided.**
- **History:** clicking a sub shows its history as an audit-log timeline, with who and when:
  creation, every status change, pick and unpick, comments, and its vendor items added, corrected
  and deleted (2026-10-20). **Decided.**
- **Every approved sub can be ordered** (2026-10-28, the user). Until then approved subs were
  *picked* (by the Sub Approver, a Materials Manager or SCM) and only picks could be
  ordered. Now nursing's approval is the decision: the sites' Materials Managers order any approved
  sub, as SCM Comments guides them, and nursing stops one by putting it on **Hold** or
  **Rejecting** it, with an optional reason kept as its comment. **Decided.**
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
- **Contract search** (9.4): in the vendor item form (Materials Managers and Sub Finders; it was in
  "Add sub" before 2026-10-15), a search over Infor's active contract lines, like PLM's
  contract-item search, starting from the Reference SKU, fills the vendor item: vendor part,
  vendor ID and name, manufacturer part, Infor item, description, UOM and QOE. **Decided.** One word is
  a part number (vendor item or manufacturer number, without dashes) or an Infor item number, or
  description words; several words (2026-10-19, e.g. "930103 chloraprep") must each be somewhere in
  the line: part number, Infor item, description or vendor name (descriptions often run words
  together, so a word matches anywhere). At most 15 lines, in a list about 3-4 lines tall that
  scrolls, with "add a word" when there are more.
  Each result also shows the vendor ID next to the vendor name, the 6-digit Infor item number when
  the line is an item-master line ("Special" lines have none), and **MHS / Non-MHS**: whether any of
  its contracts is MHS's (`[Contract.MMAHSOrganizationEID] = '105188574'`). Non-MHS lines can still
  be chosen (2026-10-15). These aren't stored on the sub.
- **Where subs come from:**
  - **Medline PBO** substitutes (`SCSFileIngestor.MedlinePBO.MedlineSubCollection`) are added
    automatically: Reference SKU = the substitute number, Entered By *Medline*, status *Pending
    Review*; and a vendor item (Medline 1000931, the substitute number as the vendor part) when
    Medline's contract lines for it agree on one UOM and QOE (2026-10-20).
  - **Manual entry** by Sub Finders is the main source. PBO coverage is expected to stay low; only
    1 of the 31 killed White Plains items has one.
  - Subs persist, so the library builds up through daily work: when an item is killed again, its
    subs are already there. **Decided.**

### Ordering (Materials Manager)

- **Recording an order** (2026-10-20): the Materials Manager clicks a vendor item tile under Vendor
  Item Detail (or Record order on the vendor item in the panel). The order keeps the vendor item's
  vendor part, vendor, vendor ID, UOM and QOE (9.6: QOE is eaches per UOM, e.g. a BX of 100 →
  100), and they enter:

  | Field | Notes |
  |---|---|
  | Site | (2026-10-27) the Medline Sold-To the order is for, **required** on new orders. The Materials Manager is responsible for choosing the right one (the user: per-site ordering works only if they do). It starts on the site the filter shows when it shows just one, as when a Materials Manager has filtered Main to their own site; otherwise it's blank until chosen, never guessed from where the item was killed. The recommendation below is for this site, and follows it when it's changed. Orders recorded before 2026-10-27 have none ("Site not recorded"); a correction can add it |
  | PO number | (2026-10-27) **optional**: Infor's PO number, digits only (company 3000's are 10, e.g. 3000564756), kept so orders can later be linked back to the day's killed items. Shown with the order and found by the orders' search; not checked against Infor in this deploy (Infor's PO data loads overnight, a day behind) |
  | Quantity | in the vendor item's UOM. **Recommended** (2026-10-21, the user; 10-20 used the kills alone; per site from 2026-10-27): what's still needed **at the order's site**, the Infor item's eaches killed there less its sub orders for that site in these dates, over the vendor item's QOE, rounded up to whole units (1,300 EA still needed for a CA/1000: 1.3, so 2 CA; 10 EA for a CA/50: 1 CA). Pre-filled with it only when this Medline item was killed in one UOM, the vendor item has that UOM (CS read as CA) and QOE (an EA without a QOE is 1), and it comes out whole (killed 30 EA, 10 EA ordered: 20). Otherwise blank, with the recommendation as the box's hint, and a red box shows what was killed (each UOM with its QOE), what's been ordered, what's still needed and the recommendation. Already covered: a yellow box says nothing more is needed. A QOE missing on the vendor item, a UOM killed or an order already placed: a red **No QOE** warning says which, and there's no recommendation. Vendor items without a QOE (other than EA) carry a *no QOE* badge on Main and in the panel |
  | Ordered By | the user |
  | Ordered DT | defaults to now; editable |
  | Comments | entries of up to 400 characters each, with who and when; Materials Managers add more later (9.7) |

  **Decided.**
- **More than one order per item** is allowed, e.g. 10 from one pick and the remaining 5 from
  another, when one alternative can't cover the need. **Decided.**
- **UOM-mismatch kills** (NONSTOCK UOM): ordering the same item in Medline's stocked UOM goes
  through a sub like everything else, e.g. Medline + the same or the case-pack part number. The
  Sub Approver approves it, and the Materials Manager adds a vendor item in the new UOM and records
  the order with it.
- **Corrections:** the Materials Manager can correct or void an order, its site, vendor part,
  vendor, vendor ID, UOM and QOE included. Every change is kept in the same audit-log history.
- **Any site** (2026-10-27): a Materials Manager can record orders for any site. Roles aren't scoped
  by site (section 4); the site says who the order is for, not who may place it.
- **Vendor items without a sub** (2026-11-02, the user): when SCM's instruction is to order from an
  alternative vendor (e.g. "order same original item 345678 from BD") or a sub item nursing hasn't
  approved (e.g. "order sub item MDS12345 from Medline"), there may be no approved sub to hang a
  vendor item on. So a vendor item can belong to the **Medline item itself**, with no sub, and it can
  be ordered as it is (no nursing approval, no status). **Built:**
  - Who: Materials Managers and SCM (capability `direct`). Not Sub Finders, kept for a future AI
    finder, whose finds should go through nursing.
  - Where: on Main, "+ Vendor item" under Vendor Item Detail on the UOM's line without an approved
    sub; in the item panel, a *Vendor items without a sub* block per Medline item (also when it has
    approved subs). The form is the usual vendor item form; its contract search starts from the
    Infor item, to find the same item from other vendors. The Medline item itself from Medline is
    still refused.
  - Orders of one have no sub (`SubOrder.sub_id` empty) and count like any other: Ordering, Total
    Sub Ordered (EA), the recommendation. The panel's Orders tab says "no sub, as SCM directs".
  - Needs: such a vendor item makes the item *Needs order* (until ordered) and never *Needs
    details*; *Needs subs* still shows while it has no live sub. Dashboard: it counts in kill to
    order, not in sub to order.
  - Not on the Subs page or its export, which list subs.
  - Database: `12`'s step 4 (`SubVendorItem.medline_item`, `sub_id` may be empty on `SubVendorItem`
    and `SubOrder`, a unique index and two CHECKs).

### Instructions (SCM, 2026-10-27; "SCM Comments" on the page)

SCM's word to the sites' Materials Managers on how to order an item: which sub and vendor
item, how much, which sites, until when. Free text, so one instruction can speak to every site.

- **Per Infor item**, the main table's row: SCM orders against the Infor item's combined need
  (Total Killed (EA)). A Medline item not in Infor has its own, like its row. Stored with the Infor
  item and the Medline item it was written from; when a Medline item without an Infor item gets one
  later, its instructions move to the Infor item's row.
- **Kept like comments:** up to 1,000 characters each (instructions name several sites, so more
  than a comment's 400), with who and when; none is changed or deleted. The newest is the one in
  force; to lift one, SCM writes a new one (e.g. "No special instruction: order the pick as
  usual").
- **Not tied to the Fill/Kill dates**, like picks: an instruction stays until replaced, and shows its
  date.
- **Who:** written by SCM only (`instruct`); read by everyone, on Main, in the item panel, and in
  the popover listing them all.
- **Where it's written:** a double-click on the item's SCM Comments cell, or Add comment in its
  panel, opens a modal: each site's killed and sub-ordered eaches in these dates and the latest
  comment above a box for the new one, labelled *Comment from SCM* (2026-11-02; "Comment for the
  sites' Materials Managers" before), whose hint shows the kind of thing it says (the user, 2026-11-02):
  "Comments from SCM (Will), e.g. autosub in place, scan again; order sub item MDS12345 from Medline;
  order same original item 345678 from BD."
- **Nobody is notified** (the user, 2026-10-27): no email. The sites' Materials Managers open Main, or
  refresh it, to read the latest.

### Dropped from the 2026-10-06 design

- per-site approvals, and the "apply to all sites" option
- line-level decisions and the five line stages. The three item-level columns now show the same
  progress: subs → approved → ordered (→ picked → between them until 2026-10-28).
- the four option types; a sub is now just a vendor + vendor part
- orders made of entries and covered lines, and "link to an existing order"
- the `Site` table; the site filter uses the Sold-To names in Medline's file. (`Site` came back on
  2026-10-30 as a lookup from a Sold-To account to its campus. Nothing reads it yet.)

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
| `Site` | Medline Sold-To account (2026-10-30) | sold_to (Medline's code, leading zeros kept, the same value as SubOrder.site), sold_to_name, site_short_name (Moses / Wakefield / Einstein). 10 Montefiore accounts. Kept by `15_sites.sql`. The app doesn't read it yet |
| `Sub` | sub of a Medline item | medline_item, reference_sku, status (pending_review / approved / hold / rejected), is_picked, source (manual / medline_pbo; llm reserved), entered_by, create_dt, update_dt, deleted by/at/reason; one live per (medline_item, reference_sku) |
| `SubVendorItem` | way to order a sub (2026-10-20), or a Medline item without a sub (2026-11-02) | sub_id, or none and then **medline_item** (exactly one of the two, `CK_SubVendorItem_sub_or_item`), vendor_part, vendor, vendor_id, uom, qoe, manufacturer_part, infor_item, description, entered_by, create_dt, update_dt, deleted by/at/reason; one live per (sub_id, vendor_id, vendor_part, uom), and without a sub per (medline_item, vendor_id, vendor_part, uom) |
| `SubOrder` | order recorded by a Materials Manager | medline_item, sub_id (none for a vendor item without a sub, 2026-11-02; then it has its vendor_item_id), vendor_item_id, **site** (Medline's Sold-To code, 2026-10-27; none on older orders), **po_number** (Infor's, optional, 2026-10-27), quantity, and what it was placed with: vendor_part, uom, qoe, vendor, vendor_id; ordered_by, ordered_dt, voided by/at/reason. Orders recorded before vendor items have a vendor item only when the sub's details were what they were placed with |
| `ItemInstruction` | instruction by SCM (2026-10-27) | infor_item (none for a Medline item not in Infor), medline_item (written from), instruction (≤1,000), written_by, written_at. Never changed or deleted; the newest per row is in force |
| `History` | change or comment on a sub, a vendor item or an order | entity (sub / vendoritem / order), id, medline_item, action, from → to, comment (≤400), by, at; drives the timelines and the pick and order histories. Comments are rows here, so none is ever overwritten. |

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
  - **Orders:** the orders recorded, voided ones included, by their own date, with **date controls of
    their own** (default: the last 30 days; Today / 7 / 30 days), independent of the table's, so a
    Materials Manager can look up past orders on the fly (2026-10-19; the user kept it on Main
    rather than a page). Before, it followed the table's dates and was empty whenever orders were
    recorded after the kills shown. It follows the table's site filter (2026-10-27), so a site's
    Materials Manager sees their site's orders. Columns (2026-10-20): Order Date, Site (2026-10-27),
    Medline Item, its Infor Item, Sub (the vendor part ordered), QOE, Ordered (`21 BX`, the UOM grey
    as in the main table), PO (2026-10-27: the PO number, when given), Vendor (its
    vendor ID), Vendor Name, Ordered By, Latest Comment. A search box keeps the orders whose numbers
    have every word typed: the Medline item, its Infor item, the vendor part ordered, the sub's
    Reference SKU, the vendor item's manufacturer part or Infor item, or the PO number (2026-10-27)
    (dashes optional). An order keeps what it was placed with (vendor part, vendor ID, vendor
    name, UOM, QOE); a correction can change them.
  - **Sizes** (2026-10-20): the tables' text is a little smaller, Infor's long descriptions smaller
    still. The main table and the orders scroll inside 450px, the Subs page's table inside 600px,
    each with its header in view. The vendor item and order forms open wide, in sections: the sub
    (and vendor item) they're for, the contract search, the vendor item, the order.
  - **The page link keeps the view** (2026-10-19): `?dates=today` or `?start=&end=`, `?sites=a,b`,
    `?q=`, `?needs=`, and the open panel's `?item=<Medline item>[&scope=infor][&tab=…]`, updated as
    the user works (no new history entries), so a copied link reopens the same view. Subs and the
    Dashboard link to `?item=`.
- **Subs** (`/subs`, 2026-10-16; it was the "All subs" tab on Main): every sub on file, as a data
  asset. Filters: text (item, Reference SKU, or a vendor item's vendor part, manufacturer part,
  Infor item, vendor, vendor ID or description), status, source, "no vendor item yet", and deleted
  subs (with who, when, why). Columns: the Medline item and its Infor item, the **Reference SKU**,
  the **Vendor Items** (each: vendor part, UOM/QOE, vendor and vendor ID, with manufacturer part,
  Infor item and description under it; 2026-10-20), status, orders (count, last date), who entered
  and approved it, and the latest comment. **Export CSV** gives everything the filters match, **one
  row per vendor item** (a sub without one has a row of its own): Reference SKU, then the vendor
  item's columns, which all start with "Sub" (Sub Vendor Part, Sub Manufacturer Part, Sub Infor
  Item, Sub Vendor ID, Sub Vendor Name, Sub Description, Sub UOM, Sub QOE), apart from the Medline
  item's; Orders and Last Ordered are the sub's. Read-only; a row's Medline item opens the panel on
  Main.
- **Dashboard** (`/dashboard`): trends and analytics, e.g. kills over time by reason and site, sub
  coverage, time to review, and the most killed items with their subs. Read-only for every Fill/Kill
  role. Separate from PLM Tracker's dashboard. Quick dates: Today, Last 7 days, Last 30 days, All
  (2026-10-21: Today added; the 7 and 30 days end on the latest day with kill lines).
  **Off for now** (the user, 2026-10-21): subs added per week by source, rejected subs by vendor,
  and the Ordering column of the most killed items (over a period it added nothing and could
  mislead). `dashboard.weekly_new_subs` and `rejected_groups` stay, to bring the first two back.
  **Flow** (2026-10-19): for the Medline items killed in the dates, the median time from the first
  kill to a sub (0 when one was already on file), from that sub to the first order since the kill,
  and from the kill to that order, each with how many items it covers; the share of killed items
  with an order is the "Items ordered" card.
  **Sites** (2026-10-27, the user): the orders follow the site filter like the kills, so a site's
  Materials Manager picks their sites to see their figures: "Items ordered", how many of them are
  **short** (fewer eaches ordered than killed, as on Main; on that card) and the flow medians count
  only orders for the sites chosen. With every site, the totals (orders without a site included).
  No per-site breakdown.

**Reset data, on the development server only** (2026-11-02, the user). Main has a **Reset data** button
beside the latest line update, for admins, that empties the workflow as `90_reset_workflow.sql`
does: every sub, vendor item, order, history row and SCM comment, numbered from 1 again (on SQL
Server, given ALTER on the tables). The kill lines stay, and PBO subs come back on Main's next load.
It asks for RESET typed and names the database; on O2 it warns that the live app's data goes too,
since a local `run.py` reads O2 by default. Only `DevelopmentConfig` offers it (`FILLKILL_RESET`;
`FILLKILL_RESET=0` hides it); the live server (`ProductionConfig`) never does, and its route answers 404.

**Order Timing is a module of its own, not a Fill/Kill page** (2026-10-30, the user). It sits beside
PLM Tracker and Fill/Kill in the module row, under `/ordertiming/`, with its own **Main** and
**Dashboard** and its docs at `/doc/ordertiming`. Medline also sends a feed of the EDI orders it
received from us, which it fills through the day (the user doesn't know why the ERP can't easily pass
this on). Order Timing will show that feed, for display only. Its data isn't ready, so both pages only
say so: no data is read, and there are no tables and no JavaScript.

Access: it has **no roles of its own**, and every Fill/Kill role can view it. In code that's
`Module.roles_from = FILLKILL`. User Control and registration don't offer it, and their Fill/Kill
column says "includes Order Timing". No database change.

`/orders` is not a page (2026-10-13); `/subs` came back as the Subs page (2026-10-16).

**Navigation:** a top row switches between PLM Tracker and Fill/Kill Management; a second row shows
the active module's pages (Fill/Kill: Main, Subs, Dashboard). PLM pages and URLs are unchanged.

**Code** (2026-10-19): server side in `app/fillkill/` (routes, services, rules, queries, rollup,
dashboard, health). The pages' scripts are ES modules in `app/static/js/fillkill/`: `common.js`,
shared by the three pages (formatting, fetching, status badges, the link to an item on Main);
`subs.js`; `dashboard.js`; and Main in `main/`, started by `main/index.js`, whose header maps its
modules (state and page link, controls, table, panel and its tabs, modal forms, orders, refresh).
To try the pages locally and check them after a change: `tools/fillkill_ui/` (a dev server on
sample or read-only O2 data, and a smoke walkthrough in headless Edge; see its README).

**Speed** (measured 2026-10-21 on O2, 330 kill lines). Main's table took ~0.2 s on the server, 80% of
it reading `vw_MedlineFillKillItemCollection` three times (~100 ms each, ~0.3 s when SQL Server
compiles it; it works over all kill lines and joins CONTRACTLINE, so it grows with the data). Each
app process now keeps that view's rows in memory and reads them again when the kill lines' "as of"
moves, after 10 minutes, or for a Medline item it hasn't got (`queries.item_view_rows`): ~45 ms a
load after the first. The panel, the orders and the Subs page use it too. The PBO sync took 7 ms.
The 2-3 s users saw is a **cold start**: a new app process takes ~2-2.5 s (imports ~1 s, the app's
setup ~0.9 s, `db.create_all` ~0.15 s of it) before its first answer. IIS starts one on the first
request, and stops it after `idleTimeout` (300 s in the repo's `web.config`) without requests, so
the first person after 5 quiet minutes waits. For Abdallah: a longer FastCGI `idleTimeout` (and app
pool idle time-out) keeps processes warm.

**Help page:** "Who can do what" (2026-10-21) lists each function against each role, ticked from
`FILLKILL_FUNCTIONS` and the capabilities in `app/utility/access.py`, so it shows what the app checks.

## 8. For stakeholders

1. **What to display.** **Answered 2026-10-08:** a date range slider plus a site filter, rolled up
   per Medline item.
2. **Lifecycle beyond today.** Nothing closes, and any date range can be reviewed. Is any analysis
   wanted on history?
3. **Separating approval and ordering.** One person can't currently be both Sub Approver and
   Materials Manager. Confirm that is wanted. (2026-10-27: the SCM role isn't part of the rule,
   since it doesn't order.)
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
    and a fill-rate measure (needs Infor PO lines as the denominator). Later. Since 2026-10-27
    orders can carry Infor's PO number, which such a check would join on (`PO`; Infor's PO data
    loads overnight, a day behind). Infor's PO line has the vendor, vendor item, Infor item,
    quantity, buy UOM and its multiplier to eaches, and the ship-to location.
12. **Feed.** Email vs SFTP; one file per site or one combined file.
13. **Coordination hub** (from the 2026-10-27 review; section 1b). **Answered** the same day:
    - A home site for each Materials Manager: no. They pick their sites with the site filter (the
      page link keeps it), and the order form starts on the site when just one is picked.
    - Instructions per site: no, one free-text comment per item ("SCM Comments").
    - Email when SCM writes one: no. The sites read Main, refreshing it.
    - The Dashboard per site: yes, through the site filter; with every site, the totals.

## 9. Design questions — answered 2026-10-13

1. **Statuses.** New subs start as *Pending Review*. *Hold* (renamed from *wait*) is a status the
   Sub Approver chooses, meaning held on purpose.
2. **Picks persist.** Yes, until unpicked or the sub's status changes. The item panel shows the
   item's pick history. (Picking went on 2026-10-28: an approved sub can be ordered until nursing
   holds or rejects it.)
3. **Ordering Status.** *Ordered* when an order for the item has an Ordered DT inside the selected
   range. The item panel shows the item's whole order history.
   **Changed 2026-10-15:** on or after the range's first day, with no end. Orders are placed after
   the kills, so an order recorded today for the 9/30 kills counted as *No order* under the old
   rule whenever the dates ended before today. The "Orders in these dates" table still lists
   orders by their own date.
   **Changed back 2026-10-20 (the user):** inside the Fill/Kill dates again, so *Ordered* and
   *No order* are about the dates chosen; with Main opening on today, today's orders count for
   today's kills. An order recorded on 10/1 for 9/30's kills shows under 9/30 only in a range
   that reaches 10/1. The Dashboard's kill-to-order times still look for the first order after
   each kill, whenever it came.
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
   deploy #2. **Built** 2026-10-13 (plan v2 W1–W5); released with deploy #1 from `main` on
   2026-10-21.
4. **Coordination hub** (2026-10-27, branch `fillkill-deploy2`; section 1b): the SCM role and
   its instructions, sites and PO numbers on orders, and nursing's latest comment on Main. A script
   on O2 (the instructions table, the order's site and PO number, the role) before the app goes out,
   then a web-server deploy.

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
