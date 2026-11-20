/* Order Timing's Short Ships (2026-11-17): the items Medline short shipped, from
 * /ordertiming/api/shortships. One row per Medline item, its short lines below it, with how often
 * Medline's Fill/Kill feed killed the item today, in the last 7 days and in the last 30 (at the
 * sites chosen), so items killed again and again stand out. Read-only. The search, days, sites,
 * sort and page are kept in the URL.
 *
 * An ES module, loaded with <script type="module">; the page's settings are JSON in #ot-config, and
 * what it shares with Main is in common.js.
 */

import {
  $, alertBox, asOfHtml, asOfWhen, config, drawPager, esc, filterState, fmtAfter, fmtDate, fmtDateTime, fmtNumber, fromUrl,
  furtherBack, getJSON, keepInUrl, plural, rangeText, setupFilters, setupPager, showDays, toggleRow, url,
} from './common.js';

const SORTS = Array.from(document.querySelectorAll('#ot-head [data-sort]')).map((th) => th.dataset.sort);
// A header's first click: the item number A to Z, a count or date the most first.
const firstDir = (key) => (key === 'medline_item' ? 'asc' : 'desc');

const state = {
  ...filterState(),
  sort: SORTS.includes(fromUrl.get('sort')) ? fromUrl.get('sort') : config.sort[0],
  dir: fromUrl.get('dir') === 'asc' ? 'asc' : (fromUrl.get('dir') === 'desc' ? 'desc' : null),
  allOpen: false,
  open: new Set(),  // the items whose lines show
};
if (!state.dir) state.dir = state.sort === config.sort[0] ? config.sort[1] : firstDir(state.sort);
let windows = config.kill_windows;
let fillkillData = null;

// --- controls ---------------------------------------------------------------------------------

const { setDays } = setupFilters(state, reload);

// The headers that sort: each one's label becomes a button, with an arrow on the one in use.
const head = $('ot-head');
head.querySelectorAll('[data-sort]').forEach((th) => {
  const sub = th.querySelector('div');
  const label = th.firstChild.textContent.trim();
  th.innerHTML = `<button type="button" class="btn btn-link p-0 ot-sort" data-sort-key="${esc(th.dataset.sort)}">${esc(label)}
      <i class="bi" aria-hidden="true"></i>${sub ? `<span class="d-block fw-normal small text-muted">${esc(sub.textContent)}</span>` : ''}</button>`;
});
function drawSort() {
  head.querySelectorAll('[data-sort]').forEach((th) => {
    const on = th.dataset.sort === state.sort;
    th.setAttribute('aria-sort', on ? (state.dir === 'asc' ? 'ascending' : 'descending') : 'none');
    th.querySelector('.bi').className = `bi ${on ? (state.dir === 'asc' ? 'bi-caret-up-fill' : 'bi-caret-down-fill') : ''}`;
  });
  // A count of lines, not a quantity: each line in Medline's Fill/Kill feed is one PO line Medline
  // killed all or part of. By Fill/Kill's order date, so they don't follow the order days.
  const what = 'PO lines Medline killed (all or part) for this item, in its Fill/Kill feed, at the sites chosen';
  const titles = {
    kills_today: `${what}: today (${fmtDate(windows.today)})`,
    kills_7: `${what}: in the last 7 days (${fmtDate(windows.week)} to ${fmtDate(windows.today)})`,
    kills_30: `${what}: in the last 30 days (${fmtDate(windows.month)} to ${fmtDate(windows.today)})`,
  };
  Object.entries(titles).forEach(([key, title]) => { head.querySelector(`[data-sort="${key}"]`).title = title; });
}
drawSort();
head.addEventListener('click', (event) => {
  const button = event.target.closest('[data-sort-key]');
  if (!button) return;
  const key = button.dataset.sortKey;
  state.dir = key === state.sort ? (state.dir === 'asc' ? 'desc' : 'asc') : firstDir(key);
  state.sort = key;
  drawSort();
  reload();
});

const expandButton = $('ot-expand');
function showAll(open) {
  state.allOpen = open;
  expandButton.textContent = open ? 'Hide all lines' : 'Show all lines';
  document.querySelectorAll('#ot-rows .ot-order-row').forEach((row) => toggleRow(row, state.open, open));
}
expandButton.addEventListener('click', () => showAll(!state.allOpen));

const rows = $('ot-rows');
rows.addEventListener('click', (event) => {
  if (event.target.closest('[data-search-window]')) {
    setDays(config.earliest, config.today, config.max_days);
    return;
  }
  if (event.target.closest('a')) return;  // Open in Fill/Kill
  const row = event.target.closest('.ot-order-row');
  if (row) toggleRow(row, state.open);
});
rows.addEventListener('keydown', (event) => {
  const row = event.target.closest('.ot-order-row');
  if (row && event.target === row && (event.key === 'Enter' || event.key === ' ')) {
    event.preventDefault();
    toggleRow(row, state.open);
  }
});

setupPager((page) => {
  state.page = page;
  load();
});

// --- loading ------------------------------------------------------------------------------------

function params() {
  return { q: state.q, start: state.start, end: state.end, sites: state.sites };
}

function reload() {
  state.page = 1;
  load();
}

function message(html) {
  rows.innerHTML = `<tr><td colspan="13" class="small p-3">${html}</td></tr>`;
}

const sortParams = () => ({ sort: state.sort, dir: state.dir });
// The link leaves out the sort Short Ships opens on.
const linkSort = () => (state.sort === config.sort[0] && state.dir === config.sort[1] ? {} : sortParams());

let ticket = 0;

async function load() {
  const mine = ++ticket;
  $('ot-export').href = url(config.api.export, params());
  keepInUrl({ ...params(), ...linkSort(), page: state.page });
  try {
    const data = await getJSON(config.api.items, { ...params(), ...sortParams(), page: state.page });
    if (mine === ticket) render(data);
  } catch (error) {
    if (mine === ticket) {
      $('ot-pager').hidden = true;
      message(alertBox(error.message));
    }
  }
}

function asOfText(data) {
  $('ot-as-of').innerHTML = [asOfHtml(data), asOfHtml(fillkillData, 'Fill/Kill')].filter(Boolean).join('');
}

// --- drawing ------------------------------------------------------------------------------------

function render(data) {
  windows = data.kill_windows || windows;
  fillkillData = data.fillkill_data;
  asOfText(data.data);
  if (data.page !== state.page || data.filters.start !== state.start || data.filters.end !== state.end
      || data.sort !== state.sort || data.dir !== state.dir) {
    state.page = data.page;
    state.sort = data.sort;
    state.dir = data.dir;
    showDays(state, data.filters);
    keepInUrl({ ...params(), ...linkSort(), page: state.page });
  }
  drawSort();
  $('ot-count').textContent = data.total ? plural(data.total, 'item') : '';
  drawPager(data, 'Items');
  if (!data.items.length) {
    message(notFound());
    return;
  }
  // As Main: a search opens every item it finds; otherwise a click, or "Show all lines".
  state.open = new Set(state.q || state.allOpen ? data.items.map((it) => it.medline_item) : []);
  rows.innerHTML = data.items.map(itemHtml).join('');
}

function notFound() {
  const more = furtherBack(state);
  if (!state.q) return `<span class="text-muted">Medline short shipped nothing in its data for ${esc(rangeText(state))}.</span>${more}`;
  return `<span class="text-muted">No short-shipped line in Medline's data for ${esc(rangeText(state))} matches “${esc(state.q)}”.</span>${more}`;
}

// Fill/Kill's Main on this item: its last 30 days, searched for it, its panel open.
const fillkillUrl = (item) => url(config.api.fillkill, { start: windows.month, end: windows.today, q: item, item });

const killCell = (n, key) => `<td class="text-end ot-kills ot-${key}">${n
  ? `<span class="fw-semibold">${fmtNumber(n)}</span>` : '<span class="text-muted">0</span>'}</td>`;

const isEach = (uom) => String(uom || '').trim().toUpperCase() === 'EA';

// Qty short or ordered (2026-11-18): in the item's UM, and in eaches below when that isn't EA. Lines
// in more than one UM have no one total in a UM: then it's in eaches, when every line has a QOE.
function qtyHtml(it, qty, each, strong) {
  const uoms = it.qoes.map((u) => u.uom).join(', ');
  if (qty != null) {
    const eaches = each != null && !isEach(it.um) ? `<div class="small text-muted">${fmtNumber(each)} EA</div>` : '';
    return `<span class="${strong}">${fmtNumber(qty)}</span> ${esc(it.um || '')}${eaches}`;
  }
  if (each != null) return `<span class="${strong}" title="${esc(`Its lines are in ${uoms}: in eaches, by the QOE`)}">${fmtNumber(each)}</span> EA`;
  return `<span class="text-muted" title="${esc(`Its lines are in ${uoms}, and Infor has no QOE for one: see each line`)}">mixed UMs</span>`;
}

// Eaches in one of the item's UM, from Infor; one per UM when it has several ("BX/100").
function qoeHtml(it) {
  const none = (u) => `<span class="text-muted" title="${esc(`Infor has no QOE for ${it.medline_item}'s ${u.uom}`)}">—</span>`;
  if (it.qoes.length === 1) return it.qoes[0].qoe != null ? fmtNumber(it.qoes[0].qoe) : none(it.qoes[0]);
  return it.qoes.map((u) => `<div class="text-nowrap">${esc(u.uom)}/${u.qoe != null ? fmtNumber(u.qoe) : none(u)}</div>`).join('');
}

function itemHtml(it) {
  const open = state.open.has(it.medline_item);
  const sites = it.site_names.length === 1 ? esc(it.site_names[0])
    : `<span title="${esc(it.site_names.join('\n'))}">${esc(plural(it.sites, 'site'))}</span>`;
  const maker = [it.manufacturer, it.mfr_item].filter(Boolean).map(esc).join(' · ');
  return `<tbody class="ot-order">
    <tr class="ot-order-row" data-key="${esc(it.medline_item)}" tabindex="0" role="button" aria-expanded="${open}">
      <td class="ot-caret text-muted"><i class="bi bi-chevron-${open ? 'down' : 'right'}" aria-hidden="true"></i></td>
      <td><div class="fw-semibold ot-item">${esc(it.medline_item)}</div><div class="small text-muted">${esc(it.cust_item || '')}</div></td>
      <td><div>${esc(it.description || '')}</div><div class="small text-muted">${maker}</div></td>
      <td class="text-end ot-short-lines"><span class="fw-semibold">${fmtNumber(it.short_lines)}</span>
        <div class="small text-muted text-nowrap">${esc(plural(it.pos, 'PO'))}</div></td>
      <td class="text-end text-nowrap ot-qty-short">${qtyHtml(it, it.short_qty, it.short_qty_each, 'ot-short-note fw-semibold')}</td>
      <td class="text-end text-nowrap ot-qty-ordered">${qtyHtml(it, it.qty, it.qty_each, '')}</td>
      <td class="text-end pe-3 ot-qoe">${qoeHtml(it)}</td>
      <td class="ot-sites">${sites}</td>
      <td class="text-nowrap">${esc(fmtDateTime(it.last_short))}</td>
      ${killCell(it.kills_today, 'kills-today')}${killCell(it.kills_7, 'kills-7')}${killCell(it.kills_30, 'kills-30')}
      <td class="text-nowrap"><a class="btn btn-sm btn-outline-secondary py-0" href="${esc(fillkillUrl(it.medline_item))}"
        title="This item on Fill/Kill's Main: its kills in the last 30 days, its subs and orders">Fill/Kill <i class="bi bi-arrow-right-short" aria-hidden="true"></i></a></td>
    </tr>
    <tr class="ot-lines-row"${open ? '' : ' hidden'}>
      <td></td>
      <td colspan="12" class="pt-0 pb-2">${linesHtml(it)}</td>
    </tr>
  </tbody>`;
}

function reasonHtml(l) {
  if (!l.in_fillkill) {
    const asOf = asOfWhen(fillkillData) ? `Fill/Kill's data ${asOfWhen(fillkillData)}.` : '';
    return `<span class="text-muted fst-italic" title="${esc(`Not in Medline's Fill/Kill feed yet. ${asOf}`.trim())}">Not in Fill/Kill yet</span>`;
  }
  const avail = l.kill_reason_date ? `<div class="small text-muted text-nowrap">Est avail ${esc(fmtDate(l.kill_reason_date))}</div>` : '';
  return `${esc(l.kill_reason || '—')}${avail}`;
}

// An item's short lines (the user, 2026-11-18: the PO, its line and line type first, then when the
// PO was created and its total lines).
function linesHtml(it) {
  const body = it.lines.map((l) => `<tr>
      <td><div class="fw-semibold ot-line-po" title="${esc(l.po_raw || '')}">${esc(l.po || l.po_raw || '—')}</div>
        <div class="small text-muted">${esc(l.order_no)}</div></td>
      <td class="text-nowrap ot-po-line" title="Medline order line ${esc(l.order_line)}">${esc(l.po_line || l.order_line)}</td>
      <td class="ot-line-type">${esc(l.line_type || '')}</td>
      <td class="text-nowrap ot-po-created">${esc(fmtDateTime(l.created_at))}</td>
      <td class="text-end ot-po-lines">${fmtNumber(l.po_lines)}</td>
      <td><div title="Sold-To ${esc(l.site)}">${esc(l.site_name || l.site)}</div>
        <div class="small text-muted" title="Ship-To ${esc(l.ship_to)}">${esc(l.ship_to_name || '')}</div></td>
      <td class="text-end text-nowrap">${fmtNumber(l.qty)} ${esc(l.um)}</td>
      <td class="text-end">${fmtNumber(l.shipped_qty)}</td>
      <td class="text-end ot-short-note fw-semibold">${fmtNumber(l.short_qty)}</td>
      <td class="ot-reason">${reasonHtml(l)}</td>
      <td class="text-nowrap small text-muted">${l.asn_at ? esc(`ASN ${fmtAfter(l.asn_at, l.created_at)}`) : ''}</td>
    </tr>`).join('');
  return `<table class="table table-sm mb-0 ot-lines">
    <thead><tr>
      <th scope="col">PO<div class="fw-normal">Medline order</div></th>
      <th scope="col" title="The line's number on our PO">PO line #</th>
      <th scope="col" title="Medline's Line Type">Line type</th>
      <th scope="col" title="Medline's Order Create Date and Time: when Medline created its order for the PO">PO created</th>
      <th scope="col" class="text-end" title="Every line of the PO in Medline's data">Total lines</th>
      <th scope="col">Site<div class="fw-normal">Ship-to</div></th>
      <th scope="col" class="text-end">Ordered</th>
      <th scope="col" class="text-end">Shipped</th>
      <th scope="col" class="text-end" title="Ordered, less shipped and still open">Short</th>
      <th scope="col" title="Medline's reason in its Fill/Kill feed, and its estimated available date">Fill/Kill reason</th>
      <th scope="col"><span class="visually-hidden">ASN</span></th>
    </tr></thead>
    <tbody>${body}</tbody>
  </table>`;
}

// --- start --------------------------------------------------------------------------------------

asOfText(config.data);
if (config.problem) {
  $('ot-problem').innerHTML = alertBox(config.problem, 'warning');
  message('<span class="text-muted">Nothing to show until Medline\'s order data can be read.</span>');
} else {
  load();
}
