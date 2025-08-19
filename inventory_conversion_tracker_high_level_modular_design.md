# Inventory Conversion Tracker — White Pages (High‑Level Modular Design)

> Purpose: Flask web app to track item replacement (conversion) relationships, expose per‑item/location attributes, and visualize original vs. replacement on‑hand over time. Designed for 4–5 users now; production‑sane, extensible, and Copilot‑friendly.

---

## 0) System Overview

- **Backend**: Flask (Blueprints), SQLAlchemy, Alembic; SQL Server via `mssql+pyodbc`.
- **Frontend**: Jinja + HTMX (progressive enhancement). Chart.js for charts.
- **Data**: Item Master + ItemLocation, Contract Lines, EA‑normalized daily archives, burn‑rate selection.
- **Auth**: Self‑registration (domain allowlist), email verification, RBAC (Admin/Analyst/Viewer).
- **Ops**: Daily archival endpoints (inv balances, rollups, burnrate). Optionally chained by a “close day” endpoint.

---

## 1) Data Model (Tables & Keys)

### 1.1 Users & RBAC

- **users**
  - `user_id` (PK), `email` (unique), `name`, `pw_hash`, `is_active` (bool), `email_verified_at` (datetime), `created_at`, `last_login_at`
- **roles**
  - `role_id` (PK), `name` (unique: `admin|analyst|viewer`)
- **user\_roles**
  - `user_id` (FK→users), `role_id` (FK→roles)  — PK(`user_id`,`role_id`)
- **email\_verification\_tokens** / **password\_reset\_tokens**
  - `(id PK, user_id FK, token_hash, expires_at, used_at)`
- **audit\_log**
  - `audit_id` (PK), `user_id` (nullable), `action`, `entity`, `entity_id`, `payload_json`, `ts`

### 1.2 Item Master & UOM

- **uom**
  - `uom_id` (PK), `code` (unique), `description`
- **items**
  - `item_id` (PK), `erp_item_code` (unique), `manufacturer_id` (nullable), `manufacturer_part_number`, `vendor_part_number` (nullable), `description`, `base_uom_id` (FK→uom), `active_flag` (bool), `created_at`, `updated_at`
- **item\_uom\_conversion** *(normalize quantities → base/EA)*
  - `item_id` (FK), `from_uom_id` (FK), `to_uom_id` (FK), `factor` (DECIMAL(18,6)) — PK(`item_id`,`from_uom_id`,`to_uom_id`)

### 1.3 ItemLocation (per‑item per‑location)

- **item\_location** *(replaces separate locations & reorder settings)*
  - **Key**: PK(`item_id`,`location_id`)
  - Identity: `item_id` (FK→items), `location_id` (string), `location_name`, `location_type` (`main|sat|par|bin|dept`), `is_active` (bool)
  - Setups: `stock_uom_id` (FK→uom), `auto_reorder` (bool), `reorder_point`, `reorder_unit`, `reorder_upto_qty`
  - State: `on_hand_qty`, `on_order_qty` (nullable), `last_counted_at` (datetime)
  - Audit: `created_at`, `updated_at`

### 1.4 Contract Lines (search source for replacements)

- **contract\_line**
  - `contract_line_id` (PK)
  - `contract_number`, `manufacturer`, `vendor_id`, `vendor_name`
  - `manufacturer_part_number`, `vendor_part_number`
  - `buy_uom_id` (FK→uom), `conversion_factor` (DECIMAL(18,6))  *(to base/EA if known)*
  - `contract_price` (nullable), `item_description`
  - `effective_start` (nullable), `effective_end` (nullable)
  - **Indexes**: `(manufacturer_part_number)`, `(vendor_part_number)`, `(vendor_id, vendor_part_number)`, `(contract_number)`

### 1.5 Conversion Relationships

- **item\_replacement\_group**
  - `group_id` (PK), `status` (`draft|active|retired`), `reason`, `start_date`, `end_date` (nullable), `owner_user_id` (FK→users)
- **item\_replacement\_link** *(polymorphic target; exactly one identifier)*
  - `member_id` (PK)
  - `group_id` (FK→item\_replacement\_group)
  - `role` (`original|replacement`), `sequence` (INT)
  - One of: `item_id` (FK→items) **or** `contract_line_id` (FK→contract\_line) **or** `manual_json` (JSON)
  - **Constraint**: only one of the three ref columns may be non‑NULL
  - **Business rule**: Originals must be `item_id`; replacements may be item/contract/manual; promotion path contract/manual → item is supported by update

### 1.6 Inventory Archives & Burn‑Rate

- **inv\_balance\_daily** *(EA‑normalized balance snapshot)*
  - PK(`as_of_date`,`item_id`,`location_id`)
  - `on_hand_ea`, `on_order_ea` (nullable), `calc_version` (tinyint), `created_at`
- **inv\_usage\_rollups** *(EA team’s precomputed windows)*
  - PK(`as_of_date`,`item_id`,`location_id`)
  - `consumed_10d_ea`, `consumed_60d_ea`, `consumed_90d_ea`, `consumed_365d_ea`
  - Optional: `receipts_10d_ea`, `receipts_60d_ea`, `receipts_90d_ea`, `receipts_365d_ea`
  - `calc_version`, `created_at`
- **burnrate\_daily** *(selected daily burn signal)*
  - PK(`as_of_date`,`item_id`,`location_id`)
  - `burnrate_ea_per_day` (DECIMAL(18,6)), `signal_source` (`L10|L60|L90|L365|BLEND|OVERRIDE|NONE`), `created_at`
- *(optional)* **group\_view\_cache**
  - `as_of_date`, `group_id`, `original_on_hand_ea`, `replacement_on_hand_ea`, `total_on_hand_ea`, `original_burn_ea_d`, `replacement_burn_ea_d`

---

## 2) Endpoints (Routes & Functions)

### 2.1 Auth & Session

- `GET /register` → show registration form
- `POST /register` → create Viewer (domain allowlist); send email verification; audit
- `GET /verify-email?token=...` → mark verified; audit; redirect login
- `GET /login` → show login
- `POST /login` → authenticate (Flask‑Login); block if not verified/active (policy)
- `POST /logout` → end session
- `GET /forgot` / `POST /forgot` → request password reset; email token
- `GET /reset?token=...` / `POST /reset` → set new password; audit
- Admin: `GET /admin/users` (list/search), `PATCH /admin/users/<id>` (activate/deactivate, set roles)

### 2.2 Items & ItemLocation

- `GET /items` → search items by `q` (item\_id/code/MPN/desc), `active`, pagination
- `GET /items/<item_id>` → item header
- `GET /items/<item_id>/locations?active_only=&location_type=&include_uom_conversions=` → all itemLocation rows (+ optional conversions)
- `PATCH /items/<item_id>/locations/<location_id>` → update setups: `auto_reorder`, `reorder_point`, `reorder_unit`, `reorder_upto_qty`, `stock_uom_id`, `is_active`
- Admin ingest: `POST /admin/import/item-locations` → upsert from CSV/XLSX/JSON

### 2.3 Contract Lines

- Search pickers:
  - `GET /search/contract-lines?mpn=&vpn=&vendor_id=&contract_number=&q=&limit=`
- Admin ingest:
  - `POST /admin/import/contract-lines` → upsert
  - `GET /admin/contract-lines/<id>` → debug detail

### 2.4 Conversion Groups & Links

- Groups CRUD:
  - `GET /groups` (filters: status, owner, date)
  - `POST /groups` (create draft)
  - `GET /groups/<group_id>` (detail + members)
  - `PATCH /groups/<group_id>` (update reason/start\_date/owner)
  - `POST /groups/<group_id>/activate` (validate + set active)
  - `POST /groups/<group_id>/retire` (set retired + end\_date)
- Members CRUD (polymorphic):
  - `POST /groups/<group_id>/items` with `item_ref`:
    - `{ "role":"original", "item_ref": {"type":"item", "item_id": 123 } }`
    - `{ "role":"replacement", "item_ref": {"type":"contract_line", "contract_line_id": 987 } }`
    - `{ "role":"replacement", "item_ref": {"type":"manual", "data": {"manufacturer_part_number":"ABC","vendor_part_number":"V-1","item_description":"...","buy_uom":"BOX","conversion_factor":10} } }`
  - `PATCH /groups/<group_id>/items/<member_id>` → change role/sequence; **promote** `{ "promote_to_item_id": 456 }`
  - `DELETE /groups/<group_id>/items/<member_id>` → remove
- Search helpers:
  - `GET /search/items?q=&limit=` → item picker (lightweight projection)

### 2.5 Tracking (Timeseries & KPIs)

- Group level:
  - `GET /api/groups/<group_id>/timeseries?days=200&location_id=ALL` → `[{ date, original_on_hand_ea, replacement_on_hand_ea, total_on_hand_ea }]`
  - `GET /api/groups/<group_id>/kpis?as_of=YYYY-MM-DD&location_id=ALL` → `{ original:{on_hand_ea,burn,dos,source}, replacement:{...}, total:{...} }`
- Item level:
  - `GET /api/items/<item_id>/timeseries?days=200&location_id=ALL` → `[{ date, on_hand_ea }]`
  - `GET /api/items/<item_id>/kpis?as_of=YYYY-MM-DD&location_id=ALL` → `{ on_hand_ea, burnrate_ea_per_day, days_of_supply, signal_source }`

### 2.6 Admin — Archival Jobs

- `POST /admin/archive/today` → read `item_location`, normalize to EA, upsert into `inv_balance_daily (as_of=today)`
- `POST /admin/rollups/today` → load EA lookbacks into `inv_usage_rollups (as_of=today)`
- `POST /admin/burnrate/today` → compute `burnrate_daily` from rollups using heuristic
- *(optional)* `POST /admin/close-day` → run the three in order; respond with summary
- *(optional)* `PATCH /admin/burnrate/override` → manual override for specific `(date,item,location)`

---

## 3) Functions & Business Logic (Brief)

### 3.1 EA Normalization (`to_ea`)

- Convert any qty in `from_uom_id` to EA using `item_uom_conversion` or identity if already base.
- Implement as a SQL UDF or app‑side helper; keep `calc_version` in archives to allow changes later.

### 3.2 Burn‑Rate Heuristic (initial)

- For each `(as_of_date,item_id,location_id)`:
  - `r10 = consumed_10d_ea/10`, `r60 = /60`, `r90 = /90`, `r365 = /365` (conditioned on min counts)
  - If `r10` & `r60` within stability threshold (e.g., 25%), set `burn = (r10+r60)/2`, `source='BLEND'`
  - Else prefer `r60`; else `r90`; else `r10`; else `r365`; else `0 (NONE)`
  - Allow per‑SKU override via admin route

### 3.3 Group Validation (Activate)

- Must have ≥1 `original` (all as `item_id`) and ≥1 `replacement` (item/contract/manual ok)
- `start_date` present; (optional) disallow an `item_id` to appear in >1 **active** group

### 3.4 Promotion (contract/manual → item)

- Single PATCH swaps `contract_line_id`/`manual_json` to `item_id`; keep `member_id` stable; audit change

---

## 4) Front‑End (Pages, Sections, Components)

### 4.1 `base.html`

- Navigation (Groups, Tracking, Admin), flash/toast region, block slots (`head`, `content`, `scripts`), includes HTMX & Chart.js.

### 4.2 Login (`auth/login.html`)

- Clean form (email, password, CSRF). Links to forgot/reset. Show banners for unverified/deactivated.

### 4.3 Relation Entry (`groups/edit.html`)

- **Header**: status chip, reason field, start date picker, owner, Activate/Retire buttons.
- **Originals column**: item picker (search by item\_id/code/MPN via `/search/items`).
- **Replacements column**: tabs → Item (`/search/items`), Contract (`/search/contract-lines`), Manual (inline form).
- **Member cards**: show ERP code/MPN/UOM; actions: remove, reorder (sequence), promote.
- **HTMX flows**: search (GET), add (POST), update (PATCH), delete (DELETE) without full reload.

### 4.4 Tracking (`tracking/group.html`)

- **Toolbar**: Days (90/200/365), Location scope (ALL or site).
- **Chart**: Original vs Replacement on‑hand (EA) line chart.
- **KPI cards**: DoS & burn per role with `source` tag.
- **Fetch**: `/api/groups/<id>/timeseries`, `/api/groups/<id>/kpis` on filter change.

### 4.5 Admin Users (`admin/users.html`)

- **Table**: name, email, verified badge, active toggle, roles multi‑select.
- **Actions**: Inline PATCH to `/admin/users/<id>` for toggles/roles.

### 4.6 Partials

- `_toasts.html`, `_confirm.html`, `_item_picker.html`, `_contract_picker.html`, `_manual_entry.html`, `_member_card.html`, `_kpis.html`

---

## 5) Directory Structure

```
app/
  __init__.py
  config.py
  models.py
  auth/
    routes.py
    forms.py
  items/
    routes.py
    services.py
  contracts/
    routes.py
    services.py
  groups/
    routes.py
    services.py
  tracking/
    routes.py
    queries.py
  admin/
    routes.py
  templates/
    base.html
    auth/login.html
    groups/edit.html
    tracking/group.html
    admin/users.html
    partials/_toasts.html
    partials/_confirm.html
    partials/_item_picker.html
    partials/_contract_picker.html
    partials/_manual_entry.html
    partials/_member_card.html
    partials/_kpis.html
  static/
    app.css
migrations/
scripts/
```

---

## 6) API Contracts (Selected Schemas)

### 6.1 Search — Items

`GET /search/items?q=abc&limit=20`

```json
[
  {"item_id":123, "erp_item_code":"A-001", "manufacturer_part_number":"MPN-001", "vendor_part_number":"VP-9", "description":"Catheter 5F", "base_uom":{"id":1,"code":"EA"}}
]
```

### 6.2 Search — Contract Lines

`GET /search/contract-lines?mpn=ABC&vendor_id=V01&limit=20`

```json
[
  {"contract_line_id":987, "contract_number":"CN-2025-01", "vendor_id":"V01", "vendor_name":"Acme", "manufacturer":"AcmeBio", "manufacturer_part_number":"ABC", "vendor_part_number":"V-123", "buy_uom":{"id":2,"code":"BOX"}, "conversion_factor":10, "item_description":"Catheter 5F", "contract_price": 12.34}
]
```

### 6.3 Add Group Member (polymorphic)

`POST /groups/42/items`

```json
{ "role": "replacement", "item_ref": { "type": "contract_line", "contract_line_id": 987 } }
```

### 6.4 Promote Member to Item

`PATCH /groups/42/items/7`

```json
{ "promote_to_item_id": 456 }
```

### 6.5 Group Timeseries

`GET /api/groups/42/timeseries?days=200&location_id=ALL`

```json
[
  {"date":"2025-02-24","original_on_hand_ea":120,"replacement_on_hand_ea":0,"total_on_hand_ea":120}
]
```

### 6.6 Group KPIs

`GET /api/groups/42/kpis?as_of=2025-08-12&location_id=ALL`

```json
{
  "original": {"on_hand_ea": 480, "burn": 12.5, "dos": 38.4, "source": "L60"},
  "replacement": {"on_hand_ea": 210, "burn": 9.0,  "dos": 23.3, "source": "BLEND"},
  "total": {"on_hand_ea": 690, "burn": 21.5, "dos": 32.1}
}
```

---

## 7) Security & Operational Notes

- CSRF on all forms; rate‑limit `POST /login|/register|/forgot`.
- Domain allowlist for registration; email verification required before login (configurable).
- Parameterized queries; server‑side validation on all mutating routes.
- Audit every write (who/what/when/payload). Retain audit ≥ 1–2 years.
- Archives retention: ≥ 400 days for balances & burn; enables 200‑day charts from any past “today”.

---

## 8) Config & Environment

- `DATABASE_URL` (SQL Server), `SECRET_KEY`, `SMTP_*` for email, `ALLOWED_EMAIL_DOMAINS`.
- Optional: `RATE_LIMITS`, `SECURITY_PASSWORD_POLICY`, `FEATURE_FLAGS`.

---

## 9) MVP Milestones

1. **Skeleton + Auth** — blueprints, DB init, register/verify/login/logout, admin user table.
2. **Items & ItemLocation API** — `/items`, `/items/<id>/locations`, batch import.
3. **Conversion Relationships** — contract\_line ingest, search pickers, groups CRUD, polymorphic links, promotion.
4. **Inventory/Burn/Tracking** — archival endpoints, group/item timeseries & KPIs, tracking page.
5. **Polish & AI hooks (optional)** — summaries/anomalies, UI touch‑ups.

---

*This white paper is the single source of truth for Copilot/agentic scaffolding: precise tables, routes, functions, and UI surfaces to generate a working project skeleton quickly.*

