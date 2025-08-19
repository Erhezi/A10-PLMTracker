# Inventory Conversion Tracker — Function Modules (No Alembic, Barebones Auth)

> Purpose: Flask app organized by **functions** instead of datasets. Three modules:
>
> 1. **Auth** (register/login/logout)
> 2. **Item Relation Collection** (collect Item → Replace Item links, auto‑assign/merge groups, flag conflicts)
> 3. **Conversion Tracking** (reporting dashboard over Item Groups joined with UOM, Item Location, Burn Rate, and last‑90‑day PO history)
>
> **No Alembic/migrations** for MVP — we bootstrap schema/tables with `db.create_all()` after ensuring `PLM` schema exists.

---

## 0) System Overview

- **Backend**: Flask Blueprints (`auth`, `collector`, `dashboard`), SQLAlchemy ORM, Flask‑Login; SQL Server via `mssql+pyodbc`.
- **DB init**: `db.create_all()` at startup; create `PLM` schema if missing.
- **Frontend**: Jinja templates + HTMX (progressive enhancement), Chart.js for charts.
- **Security (MVP)**: Password hash only; session login; restrict mutating routes to authenticated users.

---

## 1) Directory Layout (by Function)

```
app/
  __init__.py            # create_app(); ensure PLM schema; db.create_all()
  config.py
  db.py                  # (optional) hold db = SQLAlchemy(metadata=MetaData(schema="PLM"))
  models/
    __init__.py
    auth.py              # User
    inventory.py         # UOM, Item, ItemLocation, BurnRateDaily, PoLine (or PoLine90 view)
    relations.py         # ItemGroup, ItemGroupMember, ItemLink, GroupAlert
  auth/
    routes.py            # register/login/logout
    templates/
      auth/login.html
      auth/register.html
  collector/             # Item Relation Collection
    routes.py            # form pages + APIs to add link, merge groups, review conflicts
    services.py          # grouping/merge logic, conflict detection
    templates/
      collector/collect.html         # dual picker form (Item & Replace Item)
      collector/groups.html          # list groups (filter/search)
      collector/group_detail.html    # group members, merge/split actions
      collector/conflicts.html       # many-to-many alerts & resolution UI
  dashboard/             # Conversion Tracking (reports)
    routes.py            # dashboards + JSON APIs
    queries.py           # SQL/ORM queries for joins & rollups
    templates/
      dashboard/index.html           # overview (active groups, KPIs)
      dashboard/group.html           # group-level charts & KPIs
      dashboard/item.html            # item-level lens (optional)
  templates/
    base.html
    partials/_toasts.html
    partials/_confirm.html
  static/
    app.css
```

---

## 2) Front‑End Pages (MVP)

### 2.1 Auth

- **/register** — email, password, (name optional); auto-login on success.
- **/login** — email + password login; set `last_login_at`.
- **/logout** — end session.

### 2.2 Item Relation Collection

- **/collect** —
  - Dual search inputs: **Item** and **Replace Item** (typeahead pickers).
  - Show existing group memberships for both; preview **resulting group**.
  - Submit to create link; auto‑assign group (create/attach/merge); inline success toast.
  - HTMX snippets for: link preview, existing neighbors, conflict warnings.
- **/groups** — paged list, filters: `status`, `owner`, `updated_since`, text search.
- **/groups/\<group\_id>** — members (original/replacement), sequence editing, promote/demote, remove link; merge/split actions.
- **/conflicts** — list many‑to‑many hotspots with counts: OutDeg, InDeg; actions: keep as M\:N or split/resolve.

### 2.3 Conversion Tracking (Dashboard)

- **/dashboard** — overview cards:
  - Active groups, items impacted, replacement readiness %, total on‑hand EA (orig vs repl), coverage days.
  - Table of top groups by impact; link to details.
- **/dashboard/groups/\<group\_id>** — group KPIs & charts:
  - Join **ItemGroup** → Items → UOM → ItemLocation → BurnRateDaily → **PO lines last 90 days**.
  - KPIs: On‑hand EA (orig/repl), Burn EA/day (orig/repl), Coverage Days (on‑hand / burn), 90‑day PO\$ and PO qty.
  - Charts: On‑hand trend, Burn‑rate trend, 90‑day PO histogram.
- **/dashboard/items/\<item\_id>** (optional) — per‑item view used by the group page.

---

## 3) Endpoints (HTML + JSON APIs)

### Auth

- `GET  /register` → form
- `POST /register` → create user, login
- `GET  /login` → form
- `POST /login` → authenticate, set `last_login_at`
- `POST /logout`

### Collector (Item Relations)

- `GET  /collect` → form page (HTMX supports snippets below)
- `GET  /api/collect/preview?item=&replace=` → JSON: predicted group, neighbors, warnings
- `POST /api/collect/link` (body: `{ item, replace, reason? }`) → create edge; auto‑group/merge
- `POST /api/collect/bulk` (CSV/XLSX) → batch insert links (optional MVP+)
- `GET  /groups` → list groups
- `POST /groups` → create group (rare; normally created by first link)
- `GET  /groups/<group_id>` → group detail (members, edges)
- `POST /groups/<group_id>/merge` (form: `target_group_id`)
- `POST /groups/<group_id>/split` (form: member ids)
- `DELETE /links/<item>/<replace>` → remove a link
- `GET  /conflicts` → list alerts
- `POST /conflicts/<item>/resolve` → mark resolved / split action

### Dashboard (Tracking)

- `GET  /dashboard` → overview (HTML)
- `GET  /dashboard/groups/<group_id>` → detail (HTML)
- `GET  /api/groups/<group_id>/kpis?as_of=YYYY-MM-DD&location_id=ALL` → JSON
- `GET  /api/groups/<group_id>/timeseries?days=180&location_id=ALL` → JSON
- `GET  /api/items/<item_id>/kpis?as_of=YYYY-MM-DD&location_id=ALL` → JSON
- `GET  /api/items/<item_id>/timeseries?days=180&location_id=ALL` → JSON

---

## 4) Basic Data Models (MVP)

> All tables in schema **PLM**. Prefer DB‑side defaults like `SYSUTCDATETIME()`.

### 4.1 Auth

- **users**
  - `user_id` INT PK
  - `email` VARCHAR(255) UNIQUE NOT NULL
  - `name` VARCHAR(120) NULL
  - `pw_hash` VARCHAR(255) NOT NULL
  - `is_active` BIT NOT NULL DEFAULT 1
  - `created_at` DATETIME NOT NULL DEFAULT `SYSUTCDATETIME()`
  - `last_login_at` DATETIME NULL

### 4.2 Inventory Primitives

- **uom**
  - `uom_id` INT PK
  - `code` VARCHAR(20) UNIQUE NOT NULL
  - `description` VARCHAR(120) NULL
- **items**
  - `item_id` INT PK
  - `erp_item_code` VARCHAR(64) UNIQUE NOT NULL
  - `description` VARCHAR(500) NULL
  - `base_uom_id` INT FK→uom
  - `active_flag` BIT NOT NULL DEFAULT 1
  - `created_at` DATETIME NOT NULL DEFAULT `SYSUTCDATETIME()`
  - `updated_at` DATETIME NULL
- **item\_location** (per‑location snapshot/setup)
  - PK (`item_id`,`location_id`)
  - `location_name` VARCHAR(120)
  - `location_type` VARCHAR(10) CHECK in (`main`,`sat`,`par`,`bin`,`dept`)
  - Setup: `stock_uom_id` FK→uom, `reorder_point`, `reorder_unit`, `reorder_upto_qty`
  - State: `on_hand_ea` DECIMAL(18,2), `on_order_ea` DECIMAL(18,2) NULL, `last_counted_at` DATETIME NULL
  - Audit: `created_at`, `updated_at`
- **item\_uom\_conversion**
  - PK (`item_id`,`from_uom_id`,`to_uom_id`)
  - `factor` DECIMAL(18,6) NOT NULL
- **burnrate\_daily**
  - PK (`as_of_date`,`item_id`,`location_id`)
  - `burnrate_ea_per_day` DECIMAL(18,6) NOT NULL
  - `signal_source` VARCHAR(10) CHECK in (`L10`,`L60`,`L90`,`L365`,`BLEND`,`OVERRIDE`,`NONE`)
  - `created_at` DATETIME NOT NULL DEFAULT `SYSUTCDATETIME()`
- **po\_line** *(or a view limited to last 90 days)*
  - `po_line_id` BIGINT PK
  - `po_date` DATE NOT NULL
  - `item_id` INT FK→items
  - `vendor_id` INT NULL, `vendor_name` VARCHAR(200) NULL
  - `qty_ea` DECIMAL(18,2) NOT NULL, `price` DECIMAL(18,4) NULL
  - Useful index: (`po_date` DESC, `item_id`)
  > In queries, filter `po_date >= DATEADD(DAY, -90, @as_of)`.

### 4.3 Relations (Grouping)

- **item\_group**
  - `group_id` INT IDENTITY PK
  - `status` VARCHAR(10) CHECK in (`draft`,`active`,`retired`) DEFAULT `draft`
  - `reason` VARCHAR(200) NULL
  - `start_date` DATE NULL, `end_date` DATE NULL
  - `owner_user_id` INT NULL FK→users
  - `created_at` DATETIME DEFAULT `SYSUTCDATETIME()`
- **item\_group\_member**
  - PK (`item_id`)
  - `group_id` INT NOT NULL FK→item\_group
  - `role` VARCHAR(12) CHECK in (`original`,`replacement`) NULL
  - `sequence` INT NULL  -- display/promote order
  - `added_at` DATETIME DEFAULT `SYSUTCDATETIME()`
- **item\_link**  *(edge list from the collection form)*
  - PK (`item_id`,`replace_item_id`)
  - `created_at` DATETIME DEFAULT `SYSUTCDATETIME()`
- **group\_alert** *(optional, for conflict monitoring)*
  - `alert_id` INT IDENTITY PK
  - `item_id` INT NOT NULL
  - `alert_type` VARCHAR(40) in (`OUT_DEG_GT1`,`IN_DEG_GT1`,`MANY_TO_MANY`)
  - `degree_out` INT NULL, `degree_in` INT NULL
  - `noted_at` DATETIME DEFAULT `SYSUTCDATETIME()`
  - `details` VARCHAR(400) NULL

---

## 5) Core Flows (Service Logic)

### Add a relation (CollectorService)

1. Insert `item_link (item_id, replace_item_id)` if missing.
2. Ensure both items exist in `item_group_member`:
   - If neither in a group → create new `item_group`, attach both.
   - If one has group → attach the other to same group.
   - If both in different groups → **merge groups** (winner by smaller `group_id`).
3. Compute degrees for both nodes and insert `group_alert` rows if `OutDeg>1` / `InDeg>1` / both.

### Merge groups

- Reassign all members from loser → winner; log reason (optional table); preserve sequences when possible.

### Dashboard queries

- For a `group_id`, gather member items and left‑join:
  - `item_location` (aggregate across or per‑location)
  - `burnrate_daily` (choose latest as\_of or param)
  - `po_line` filtered to last 90 days
- Compute KPIs: on‑hand EA (orig/repl), burn EA/day, coverage days, PO\$ / PO qty (90d).

---

## 6) App Bootstrap (no Alembic)

```python
# app/__init__.py (excerpt)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData, text

db = SQLAlchemy(metadata=MetaData(schema="PLM"))

with app.app_context():
    with db.engine.begin() as conn:
        conn.execute(text("""
            IF SCHEMA_ID('PLM') IS NULL EXEC('CREATE SCHEMA PLM AUTHORIZATION dbo;')
        """))
    db.create_all()
```

---

## 7) MVP Milestones (by Function)

1. **Auth** — register/login/logout; guard collector & dashboard routes.
2. **Collector** — collect form, auto‑group service, groups list/detail, conflicts page.
3. **Dashboard** — overview and group page (KPIs + charts); item lens optional.
4. **Data Imports** — seed Items/UOM/ItemLocation/BurnRate; PO lines feed (daily).
5. **Polish (Later)** — roles/RBAC, CSRF/forms, email verification, password reset, audit log; consider Alembic once the schema stabilizes.

