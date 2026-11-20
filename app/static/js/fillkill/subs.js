/* Fill/Kill Subs page: every sub on file, from /fillkill/api/subs, with filters and a CSV export
 * of everything they match, a Medline item's subs together. Read-only: a row's Medline item opens
 * its drawer here (2026-11-20), every sub on it; subs are changed in its panel on Main.
 */

import {
  $, STATUS_ORDER, alertBox, config, debounce, enteredBy, esc, fmtDate, fmtDateTime, fmtNumber, getJSON, itemLink,
  needsDetails, noQoeBadge, shiftDay, statusBadge, uomQoe, url, vendorText,
} from './common.js';

$('fk-subs-status').innerHTML += config.statuses.map(([code, label]) => `<option value="${code}">${esc(label)}</option>`).join('');
$('fk-subs-source').innerHTML += config.sources.map(([code, label]) => `<option value="${code}">${esc(label)}</option>`).join('');
const periods = config.fillkillPeriods;
$('fk-subs-period').innerHTML = periods.choices.map((p) => `<option value="${p.period}"${p.period === periods.default
  ? ' selected' : ''}>Last ${esc(p.label)}</option>`).join('');

// The Days or Weeks on Fill/Kill header says the period's unit and length (2026-11-19), and what a
// stick is: a day, or a calendar week, Monday to Sunday (2026-11-20).
function periodHeads(p) {
  const words = {
    Unit: `${p.unit[0].toUpperCase()}${p.unit.slice(1)}s`,
    label: p.label,
    stick: p.unit === 'week' ? 'A stick a week (Mon–Sun), this week at right' : 'A stick a day, today at right',
  };
  document.querySelectorAll('[data-period-head]').forEach((el) => { el.textContent = words[el.dataset.periodHead]; });
}
periodHeads(periods.choices.find((p) => p.period === periods.default));

function filters() {
  const found = { q: $('fk-subs-q').value.trim(), status: $('fk-subs-status').value, source: $('fk-subs-source').value };
  if ($('fk-subs-needs').checked) found.needs_details = '1';
  if ($('fk-subs-deleted').checked) found.deleted = '1';
  if ($('fk-subs-period').value !== periods.default) found.fillkill_period = $('fk-subs-period').value;
  return found;
}

const COLUMNS = 9;

function message(html) {
  $('fk-subs-rows').innerHTML = `<tr><td colspan="${COLUMNS}" class="small p-3">${html}</td></tr>`;
}

// The Medline item's days or weeks on Fill/Kill in the period chosen (2026-11-19, the user): how many
// and its latest day, then a stick for each (``fillkill_recent``, oldest first, from ``p.start``; a
// week is a calendar week, Monday to Sunday, the last this week so far, 2026-11-20), lit when it was
// killed, so its pattern shows at a glance. The sticks fill about the same width whatever the period.
function fillkillCell(s, p) {
  if (!s.fillkill_last_seen) return '<span class="small text-muted" title="No kill lines for this Medline item">Never</span>';
  const recent = s.fillkill_recent || '';
  const days = p.unit === 'week' ? 7 : 1;
  const sticks = [...recent].map((c, i) => {
    const first = shiftDay(p.start, i * days);
    const last = shiftDay(first, days - 1);
    const when = days > 1 ? `${fmtDate(first)}–${fmtDate(last)}${last > p.today ? ' (this week, so far)' : ''}` : fmtDate(first);
    return `<span class="fk-stick${c === '1' ? ' fk-stick-on' : ''}" title="${when}${c === '1' ? ': on Fill/Kill' : ''}"></span>`;
  }).join('');
  const said = `On Fill/Kill ${fmtNumber(s.fillkill_count)} of the last ${p.label}`;
  const width = Math.max(3, Math.floor((120 - (recent.length - 1)) / recent.length));
  return `<div class="small text-nowrap"><span class="fw-semibold">${fmtNumber(s.fillkill_count)}</span>
      <span class="text-muted">·</span> ${fmtDate(s.fillkill_last_seen)}</div>
    <span class="fk-sticks" role="img" aria-label="${said}" title="${said}" style="--fk-stick-width: ${width}px">${sticks}</span>`;
}

let ticket = 0;

// What the server sent last: the subs, the Medline items with no sub, and what they cover.
let shown = null;

async function load() {
  const mine = ++ticket;
  const params = filters();
  $('fk-subs-export').href = url(config.api.export, params);
  try {
    const data = await getJSON(config.api.subs, params);
    if (mine === ticket) {
      periodHeads(data.fillkill);
      shown = { ...data, deleted: Boolean(params.deleted) };
      render();
    }
  } catch (error) {
    if (mine === ticket) message(`<div class="alert alert-danger py-2 mb-0">${esc(error.message)}</div>`);
  }
}

// --- sorting (the user, 2026-11-19) ---------------------------------------------------------------
// Medline Item, Reference SKU and Status, as Main's headers do: the first click sorts A to Z (Status:
// Approved, Hold, Pending Review, Rejected, No sub), the second the other way, the third back to the
// page's own order (subs newest change first, then the items with no sub, latest on Fill/Kill
// first). Blanks stay last either way; ties keep the page's order.

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });
const STATUS_RANK = ['approved', 'hold', 'pending_review', 'rejected', 'no_sub'];
const SORTS = {
  medline_item: (row) => row.medline_item,
  reference_sku: (row) => row.reference_sku,
  status: (row) => (STATUS_RANK.includes(row.status) ? STATUS_RANK.indexOf(row.status) : null),
};
let sort = null;

function sorted(rows) {
  if (!sort) return rows;
  const sign = sort.dir === 'asc' ? 1 : -1;
  const blank = (value) => value == null || value === '';
  return rows.map((row, i) => ({ row, i, value: SORTS[sort.key](row) })).sort((a, b) => {
    if (blank(a.value) || blank(b.value)) return blank(a.value) - blank(b.value) || a.i - b.i;
    const order = typeof a.value === 'number' ? a.value - b.value : collator.compare(a.value, b.value);
    return sign * order || a.i - b.i;
  }).map((keyed) => keyed.row);
}

function showSort() {
  document.querySelectorAll('.fk-table th[data-sort]').forEach((th) => {
    const dir = sort && sort.key === th.dataset.sort ? sort.dir : null;
    if (dir) th.setAttribute('aria-sort', dir === 'asc' ? 'ascending' : 'descending');
    else th.removeAttribute('aria-sort');
    th.querySelector('.fk-sort-icon').className = `bi fk-sort-icon ${{ asc: 'bi-arrow-up', desc: 'bi-arrow-down' }[dir]
      || 'bi-arrow-down-up'}`;
  });
}

// The arrow stays with the label's last word, never on a line of its own.
document.querySelectorAll('.fk-table th[data-sort] .fk-sort').forEach((button) => {
  const words = button.textContent.trim().split(/\s+/);
  const last = words.pop();
  button.innerHTML = `${words.length ? `${esc(words.join(' '))} ` : ''}<span class="text-nowrap">${esc(last)}`
    + '<i class="bi fk-sort-icon" aria-hidden="true"></i></span>';
});
document.querySelector('.fk-table thead').addEventListener('click', (event) => {
  const button = event.target.closest('.fk-sort');
  if (!button) return;
  const key = button.closest('th').dataset.sort;
  if (!sort || sort.key !== key) sort = { key, dir: 'asc' };
  else if (sort.dir === 'asc') sort = { key, dir: 'desc' };
  else sort = null;
  showSort();
  if (shown) render();
});
showSort();

// --- rows ------------------------------------------------------------------------------------------

const plural = (n, word) => `${fmtNumber(n)} ${word}${n === 1 ? '' : 's'}`;
// A click opens the item's drawer; Ctrl+click (or the middle button) still opens it on Main.
const itemCell = (row, note) => `<td class="fk-item-cell"><a href="${esc(itemLink(row.medline_item))}" data-item="${esc(row.medline_item)}"
    title="See the item and all its subs (Ctrl+click: open it on Main)">${esc(row.medline_item)}</a>
  ${row.medline_infor_item ? `<div class="small text-muted">${esc(row.medline_infor_item)}</div>` : ''}
  ${note ? `<div class="small text-muted fk-sub-count">${note}</div>` : ''}</td>`;
const none = '<span class="text-muted">—</span>';

// --- a Medline item's subs together (2026-11-20, the user) ----------------------------------------
// So an item with more than one sub (or sub candidate) can't be missed: in the page's own order and
// by Medline Item, its subs are next to each other, where its newest change puts it; the item and
// its days or weeks on Fill/Kill on the first row only, "Total N subs" under the item, a dashed line
// between its subs. Sorted by Reference SKU or Status, each row is on its own, the total under it.

const grouped = () => !sort || sort.key === 'medline_item';

function groupRows(rows) {
  const groups = new Map();
  rows.forEach((row) => {
    const key = `${row.status === 'no_sub' ? 'none' : 'subs'}|${row.medline_item}`;
    groups.set(key, [...(groups.get(key) || []), row]);
  });
  return [...groups.values()];
}

// "Total 3 subs", with "2 shown" when the filters keep fewer of them together here. Deleted subs:
// how many live ones their item has.
function countNote(row, together, deleted) {
  const n = row.item_subs || 0;
  if (deleted) return n ? `${plural(n, 'live sub')}` : '';
  if (n < 2) return '';
  return `Total ${plural(n, 'sub')}${together && together < n ? ` · ${fmtNumber(together)} shown` : ''}`;
}

function subRow(s, scope, deleted, at = { first: true, continues: false, note: '' }) {
  // Its vendor items (2026-10-20): what can be ordered for it, each with the vendor part, vendor
  // (and vendor ID), UOM and QOE; the manufacturer's part, Infor item and description below.
  const items = needsDetails(s) ? `<span class="badge text-bg-warning"
    title="Nothing to order yet: the Materials Manager adds what can be ordered for it">Vendor item needed</span>`
    : s.vendor_items.map((v) => {
      const more = [v.manufacturer_part ? `mfr ${esc(v.manufacturer_part)}` : '', v.infor_item ? `Infor item ${esc(v.infor_item)}` : '',
        esc(v.description || '')].filter(Boolean).join(' · ');
      return `<div class="mb-1"><span class="fw-semibold">${esc(v.vendor_part)}</span> ${esc(uomQoe(v))}
        <span class="text-muted">· ${esc(vendorText(v))}</span>
        ${more ? `<div class="small text-muted">${more}</div>` : ''}</div>`;
    }).join('');
  const removed = deleted
    ? `<div class="small text-danger">Deleted by ${esc(s.deleted_by)} ${fmtDateTime(s.deleted_at)}: ${esc(s.delete_reason)}</div>` : '';
  const own = '<td class="fk-item-cell"></td>';  // the item's, on its first row
  return `<tr${at.continues ? ' class="fk-group-continues"' : ''}>
    ${at.first ? itemCell(s, at.note) : own}
    <td class="fw-semibold">${esc(s.reference_sku)}</td>
    <td>${items}</td>
    <td>${statusBadge(s.status)}${removed}</td>
    <td class="small">${esc(enteredBy(s))}<div class="text-muted text-nowrap">${fmtDateTime(s.create_dt)}</div></td>
    <td class="small">${s.approved_by ? `${esc(s.approved_by)}<div class="text-muted text-nowrap">${fmtDateTime(s.approved_at)}</div>` : none}</td>
    <td class="small">${s.latest_comment ? `${esc(s.latest_comment.comment)}<div class="text-muted">${esc(s.latest_comment.actor)}</div>` : ''}</td>
    ${at.first ? `<td class="fk-item-cell">${fillkillCell(s, scope)}</td>` : own}
    <td class="small text-nowrap">${s.orders ? `${fmtNumber(s.orders)} · ${fmtDate(s.last_ordered)}` : none}</td>
  </tr>`;
}

// A Medline item on Fill/Kill with no sub (2026-11-19, the user): its item, the status and how often
// it's killed; nursing adds a sub in its panel on Main.
function noSubRow(row, scope) {
  return `<tr>
    ${itemCell(row, '')}
    <td>${none}</td><td>${none}</td>
    <td>${statusBadge(row.status)}</td>
    <td></td><td></td><td></td>
    <td>${fillkillCell(row, scope)}</td>
    <td>${none}</td>
  </tr>`;
}

function render() {
  const { subs, no_sub: noSub, limit, deleted, fillkill: scope } = shown;
  const counts = [];
  if (subs.length >= limit) counts.push(`the ${limit} most recently changed subs: narrow the filters, or export them all`);
  else if (subs.length || !noSub.length) counts.push(`${plural(subs.length, 'sub')}${deleted ? ' deleted' : ''}`);
  if (noSub.length) counts.push(`${plural(noSub.length, 'item')} with no sub`);
  const text = counts.join(' · ');
  $('fk-subs-count').textContent = text[0].toUpperCase() + text.slice(1);
  if (!subs.length && !noSub.length) { message('<span class="text-muted">No subs match.</span>'); return; }
  const rows = sorted([...subs, ...noSub]);
  const together = grouped();
  $('fk-subs-rows').innerHTML = (together ? groupRows(rows) : rows.map((row) => [row])).map((group) => group.map((row, i) => {
    if (row.status === 'no_sub') return noSubRow(row, scope);
    return subRow(row, scope, deleted, { first: i === 0, continues: i < group.length - 1, note: countNote(row, together && group.length, deleted) });
  }).join('')).join('');
}

// --- a Medline item's drawer (2026-11-20, the user) -----------------------------------------------
// A click on a row's Medline item opens it here instead of on Main: the Medline item, its Infor item
// and descriptions, and every live sub on it (whatever the filters show), approved first, each with
// its vendor items, who entered and approved it, its latest comment and its orders; then its vendor
// items without a sub. Read-only, as the page is: "Open on Main" to change them. From the item
// panel's API, the whole Infor item's, kept to this Medline item.

const drawerEl = $('fk-item-drawer');
const drawer = window.bootstrap ? window.bootstrap.Offcanvas.getOrCreateInstance(drawerEl) : null;
let drawerTicket = 0;

async function openDrawer(item) {
  const mine = ++drawerTicket;
  // The row's own facts: its Infor item until the drawer's load, its days or weeks on Fill/Kill.
  const row = shown ? [...shown.subs, ...shown.no_sub].find((r) => r.medline_item === item) : null;
  $('fk-item-drawer-title').textContent = item;
  $('fk-item-drawer-subtitle').textContent = row && row.medline_infor_item ? `Infor item ${row.medline_infor_item}` : '';
  $('fk-item-drawer-body').innerHTML = '<div class="text-muted small">Loading…</div>';
  if (drawer) drawer.show();
  try {
    const data = await getJSON(config.api.item, { item });
    if (mine === drawerTicket) drawItem(item, data, row);
  } catch (error) {
    if (mine === drawerTicket) $('fk-item-drawer-body').innerHTML = alertBox(error.message);
  }
}

function drawItem(item, data, row) {
  const pack = data.packagings.find((p) => p.medline_item === item) || { subs: [], vendor_items: [] };
  const d = data.details || {};
  $('fk-item-drawer-subtitle').textContent = [data.infor_item ? `Infor item ${data.infor_item}` : 'Not in Infor',
    pack.description].filter(Boolean).join(' · ');
  const rank = (s) => (STATUS_ORDER.includes(s.status) ? STATUS_ORDER.indexOf(s.status) : STATUS_ORDER.length);
  const subs = [...pack.subs].sort((a, b) => rank(a) - rank(b) || String(a.create_dt).localeCompare(String(b.create_dt)));
  // Each sub's orders, voided ones left out, as the table's Orders column counts them.
  const orders = new Map();
  data.orders.filter((o) => !o.voided_at && o.sub_id).forEach((o) => {
    const seen = orders.get(o.sub_id) || { count: 0, last: null };
    orders.set(o.sub_id, { count: seen.count + 1, last: !seen.last || o.ordered_dt > seen.last ? o.ordered_dt : seen.last });
  });
  const statuses = STATUS_ORDER.map((status) => [status, subs.filter((s) => s.status === status).length]).filter(([, n]) => n);
  const total = subs.length
    ? `Total ${plural(subs.length, 'sub')}${statuses.length > 1 ? ` · ${statuses.map(([status, n]) => `${n} ${esc(config.statusLabels[status])}`).join(' · ')}` : ''}`
    : '';
  $('fk-item-drawer-body').innerHTML = `
    ${itemFacts(item, pack, d, row)}
    <div class="d-flex flex-wrap align-items-baseline gap-2 mb-2">
      <h3 class="h6 fw-semibold mb-0">Subs</h3><span class="small text-muted fk-sub-count">${total}</span>
      <a class="btn btn-sm btn-outline-primary ms-auto" href="${esc(itemLink(item))}" title="Subs are added, reviewed and changed in the item's panel on Main">Open on Main</a>
    </div>
    ${subs.length ? subs.map((s) => subCard(s, orders.get(s.sub_id))).join('')
      : '<p class="text-muted small">No subs yet: nursing adds them in the item\'s panel on Main.</p>'}
    ${(pack.vendor_items || []).length ? `<div class="card mb-2"><div class="card-body p-2 small">
      <div class="fw-semibold">Vendor items without a sub</div>
      <div class="text-muted">As SCM directs when no sub nursing approved is available, e.g. the same item from another vendor.</div>
      ${vendorItems(pack.vendor_items)}</div></div>` : ''}`;
}

function itemFacts(item, pack, d, row) {
  const scope = shown && shown.fillkill;
  const onFillKill = !row ? '' : row.fillkill_last_seen
    ? `${fmtNumber(row.fillkill_count)} of the last ${scope ? scope.label : ''} · last ${fmtDate(row.fillkill_last_seen)}` : 'Never';
  const facts = [
    ['Medline item', [item, pack.um, pack.qoe != null ? `QOE ${fmtNumber(pack.qoe)}` : ''].filter(Boolean).join(' · ')],
    ['Description', pack.description],
    ['Infor item', d.infor_item
      ? [d.infor_item, d.infor_active ? (d.infor_active === 'Yes' ? 'Active' : 'Inactive') : ''].filter(Boolean).join(' · ')
      : 'None: not a Medline vendor item in Infor'],
    ['Long description', d.long_description],
    ['Commodity', [d.commodity_code, d.commodity_description].filter(Boolean).join(' · ')],
    ['Manufacturer', [d.manufacturer, d.mfr_item].filter(Boolean).join(' · ')],
    ['On Fill/Kill', onFillKill],
  ].filter(([, value]) => value);
  return `<dl class="row small bg-light border rounded py-2 mx-0 mb-3">${facts.map(([label, value]) => `
    <dt class="col-sm-4 text-muted fw-normal">${esc(label)}</dt><dd class="col-sm-8 mb-1">${esc(value)}</dd>`).join('')}</dl>`;
}

// Its vendor items: the vendor part, UOM and QOE, vendor; the manufacturer's part, Infor item and
// description below.
function vendorItems(items) {
  return items.map((v) => {
    const more = [v.manufacturer_part ? `mfr ${esc(v.manufacturer_part)}` : '', v.infor_item ? `Infor item ${esc(v.infor_item)}` : '',
      esc(v.description || '')].filter(Boolean).join(' · ');
    return `<div class="mt-1"><span class="fw-semibold">${esc(v.vendor_part)}</span> ${esc(uomQoe(v))}${noQoeBadge(v)}
      <span class="text-muted">· ${esc(vendorText(v))}</span>${more ? `<div class="text-muted">${more}</div>` : ''}</div>`;
  }).join('');
}

function subCard(s, ordered) {
  const elsewhere = (s.approved_elsewhere || []).map((o) => `<span class="badge text-success border border-success bg-white"
    title="Approved by ${esc(o.approved_by || '')} ${fmtDateTime(o.approved_at)}"><i class="bi bi-box-seam"></i>
    Approved for ${esc(o.medline_item)}${o.um ? ` (${esc(o.um)})` : ''}</span>`).join(' ');
  const c = s.latest_comment;
  return `<div class="card mb-2 fk-drawer-sub${s.status === 'approved' ? ' border-success' : ''}"><div class="card-body p-2 small">
    <div class="d-flex flex-wrap gap-2 align-items-center">
      <span><span class="fw-semibold fs-6">${esc(s.reference_sku)}</span> <span class="text-muted">Reference SKU</span></span>
      ${statusBadge(s.status)} ${elsewhere}
    </div>
    <div class="text-muted">Entered by ${esc(enteredBy(s))}, ${fmtDateTime(s.create_dt)}${s.approved_by
      ? ` · approved by ${esc(s.approved_by)}, ${fmtDateTime(s.approved_at)}` : ''}</div>
    ${needsDetails(s) ? `<div class="mt-1"><span class="badge text-bg-warning"
      title="Nothing to order yet: the Materials Manager adds what can be ordered for it">Vendor item needed</span></div>`
      : vendorItems(s.vendor_items)}
    ${c ? `<div class="border-start border-3 ps-2 mt-2"><span class="text-muted">${esc(c.actor)}, ${fmtDateTime(c.acted_at)}${c.count > 1
      ? ` (${c.count} comments)` : ''}:</span> ${esc(c.comment)}</div>` : ''}
    <div class="mt-1 text-muted">${ordered ? `${plural(ordered.count, 'order')} · last ordered ${fmtDate(ordered.last)}` : 'No orders'}</div>
  </div></div>`;
}

$('fk-subs-rows').addEventListener('click', (event) => {
  const link = event.target.closest('a[data-item]');
  if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  openDrawer(link.dataset.item);
});

$('fk-subs-q').addEventListener('input', debounce(load, 300));
['fk-subs-status', 'fk-subs-source', 'fk-subs-period', 'fk-subs-needs', 'fk-subs-deleted'].forEach((id) => $(id).addEventListener('change', load));
load();
