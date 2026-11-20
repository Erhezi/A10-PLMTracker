/* Order Timing Main (2026-11-16): our orders in Medline's feed, from /ordertiming/api/orders, to see
 * whether Medline received and confirmed them. One row per order (a PO), its lines below it.
 * Read-only. The search, days, sites and status tab are kept in the URL, so a view can be shared.
 *
 * An ES module, loaded with <script type="module">: it runs once the page is parsed, after
 * base.html has defined appFetch. The page's settings are JSON in #ot-config; what Short Ships
 * shares with it is in common.js.
 */

import {
  $, alertBox, asOfText, asOfWhen, config, drawPager, esc, filterState, fmtAfter, fmtDateTime, fmtNumber, fromUrl,
  furtherBack, getJSON, inSentence, keepInUrl, plural, rangeText, setupFilters, setupPager, showDays, toggleRow, url,
} from './common.js';

const STATUS_LABEL = Object.fromEntries(config.statuses);
// The tabs (2026-11-17, in the user's order): every order, each status, then short shipped, which
// isn't a status (a line with an ASN can be short too) but picks lines the same way (?status=short).
const TABS = [['', 'All orders'], ...config.statuses, config.short_tab];
const TAB_LABEL = Object.fromEntries(TABS);
// Bootstrap's colours, and app.css's orange for short shipped.
const STATUS_CLASS = {
  not_confirmed: 'warning', rejected: 'danger', short: 'orange', confirmed: 'primary', asn: 'success',
};
const STATUS_HINT = {
  not_confirmed: "Medline hasn't sent its order confirmation (855) for it yet.",
  rejected: "Medline rejected this line (a bad line, with Medline's reject code): it won't be filled.",
  short: 'Medline is shipping fewer than ordered, whatever its status: on a FILL-KILL line it ships what it has and kills the rest.',
  confirmed: "Medline confirmed it (855); it hasn't shipped yet.",
  asn: 'Medline sent the ship notice (ASN, 856): it shipped.',
};

function badge(status, extra) {
  return `<span class="badge text-bg-${STATUS_CLASS[status] || 'secondary'}" title="${esc(STATUS_HINT[status] || '')}">`
    + `${esc(STATUS_LABEL[status] || status)}${extra ? ` ${esc(extra)}` : ''}</span>`;
}

// --- state, from the URL --------------------------------------------------------------------

const state = {
  ...filterState(),
  status: TAB_LABEL[fromUrl.get('status')] && fromUrl.get('status') ? fromUrl.get('status') : '',
  allOpen: false,
  open: new Set(),  // the orders whose lines show
};

// --- controls ---------------------------------------------------------------------------------

const { setDays } = setupFilters(state, reload);

// The tabs above the table (2026-11-17): every order, or those with a line in one status or short
// shipped. Each says how many orders the days, sites and search find (the API's status_counts); an
// order with lines in two statuses is under both tabs. No counts until loaded.
const tabList = $('ot-tabs');
function tabsHtml(counts) {
  return TABS.map(([code, label]) => {
    const active = code === state.status;
    const n = counts ? counts[code || 'all'] : null;
    const tone = code && n ? STATUS_CLASS[code] : 'secondary';
    const count = n == null ? ''
      : ` <span class="badge rounded-pill bg-${tone}-subtle text-${tone}-emphasis ot-tab-count">${fmtNumber(n)}</span>`;
    const title = code ? `Orders with a line that's ${inSentence(label)}: ${STATUS_HINT[code]}` : 'Every order, whatever its lines';
    return `<li class="nav-item"><button type="button" class="nav-link${active ? ' active' : ''}" data-status="${esc(code)}"
      aria-pressed="${active}" title="${esc(title)}">${esc(label)}${count}</button></li>`;
  }).join('');
}
let lastCounts = null;
function drawTabs(counts) {
  if (counts !== undefined) lastCounts = counts;
  tabList.innerHTML = tabsHtml(lastCounts);
}
drawTabs(null);
tabList.addEventListener('click', (event) => {
  const tab = event.target.closest('[data-status]');
  if (!tab || tab.dataset.status === state.status) return;
  state.status = tab.dataset.status;
  drawTabs();
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
  const row = event.target.closest('.ot-order-row');
  if (row) toggleRow(row, state.open);
});
rows.addEventListener('keydown', (event) => {
  const row = event.target.closest('.ot-order-row');
  if (row && (event.key === 'Enter' || event.key === ' ')) {
    event.preventDefault();
    toggleRow(row, state.open);
  }
});

setupPager((page) => {
  state.page = page;
  load();
});

// --- loading ------------------------------------------------------------------------------------

// What the filters pick: the export takes these; Main's API also the page.
function params() {
  return { q: state.q, status: state.status, start: state.start, end: state.end, sites: state.sites };
}

// A filter changed: back to the first page.
function reload() {
  state.page = 1;
  load();
}

function message(html) {
  rows.innerHTML = `<tr><td colspan="9" class="small p-3">${html}</td></tr>`;
}

let ticket = 0;

async function load() {
  const mine = ++ticket;
  $('ot-export').href = url(config.api.export, params());
  keepInUrl({ ...params(), page: state.page });
  try {
    const data = await getJSON(config.api.orders, { ...params(), page: state.page });
    if (mine === ticket) render(data);
  } catch (error) {
    if (mine === ticket) {
      $('ot-pager').hidden = true;
      message(alertBox(error.message));
    }
  }
}

// --- drawing ------------------------------------------------------------------------------------

function render(data) {
  asOfText(data.data);
  drawTabs(data.status_counts || null);
  const { orders, total } = data;
  const picks = data.filters.picks_lines;
  // The page and days the server gave (one past the last page is the last; the days held to the
  // last 30, which can move at midnight); the URL keeps them.
  if (data.page !== state.page || data.filters.start !== state.start || data.filters.end !== state.end) {
    state.page = data.page;
    showDays(state, data.filters);
    keepInUrl({ ...params(), page: state.page });
  }
  $('ot-count').textContent = total ? plural(total, 'order') : '';
  drawPager(data, 'Orders', ['Newer orders', 'Older orders']);
  if (!orders.length) {
    message(notFound(data));
    return;
  }
  // A search opens every order it finds, to show the lines it found; a status tab doesn't (the
  // user, 2026-11-17: a click opens the order). Otherwise orders open when clicked, or all with
  // "Show all lines".
  state.open = new Set(state.q || state.allOpen ? orders.map((o) => o.order_no) : []);
  rows.innerHTML = orders.map((o) => orderHtml(o, picks)).join('');
}

function notFound(data) {
  const more = furtherBack(state);
  if (!state.q) {
    const status = state.status ? ` with a line that's ${esc(inSentence(TAB_LABEL[state.status]))}` : '';
    return `<span class="text-muted">No orders in Medline's data for ${esc(rangeText(state))}${status}.</span>${more}`;
  }
  const words = state.q.split(/[\s,;]+/).filter(Boolean);
  // When Medline made the file loaded: a PO received since isn't in it (2026-11-17).
  const asOf = asOfWhen(data.data);
  const po = words.every((word) => /^\d+$/.test(word))
    ? ` If you sent ${words.length === 1 ? 'that PO' : 'those POs'} to Medline on these days, Medline hasn't reported
       receiving ${words.length === 1 ? 'it' : 'them'}${asOf ? ` (data ${esc(asOf)})` : ''}.` : '';
  return `<span class="text-muted">No order in Medline's data for ${esc(rangeText(state))} matches “${esc(state.q)}”.${po}</span>${more}`;
}

function orderHtml(o, picks) {
  const open = state.open.has(o.order_no);
  const confirmed = o.status === 'confirmed'
    ? `<span class="badge text-bg-success" title="Medline sent its order confirmation (855)">Confirmed</span>
       <span class="text-nowrap">${esc(fmtAfter(o.confirmed_at, o.received_at))}</span>
       ${o.mins_to_confirm != null ? `<div class="small text-muted">${fmtNumber(o.mins_to_confirm)} min after Medline received it</div>` : ''}`
    : `<span class="badge text-bg-warning" title="${esc(STATUS_HINT.not_confirmed)}">Not confirmed</span>`;
  const chips = config.statuses.filter(([code]) => o.counts[code]).map(([code, label]) => (
    `<span class="badge rounded-pill bg-${STATUS_CLASS[code]}-subtle text-${STATUS_CLASS[code]}-emphasis border border-${STATUS_CLASS[code]}-subtle"
       title="${esc(STATUS_HINT[code])}">${o.counts[code]} ${esc(inSentence(label))}</span>`)).join(' ');
  // How many lines the search or status found, when it's not all of them (as the highlight).
  const found = picks && o.matched < o.line_count
    ? `<div class="small text-muted text-nowrap">${fmtNumber(o.matched)} found</div>` : '';
  const shipTo = [o.ship_to_name, o.buyer].filter(Boolean).map(esc).join(' · ');
  return `<tbody class="ot-order">
    <tr class="ot-order-row" data-key="${esc(o.order_no)}" tabindex="0" role="button" aria-expanded="${open}">
      <td class="ot-caret text-muted"><i class="bi bi-chevron-${open ? 'down' : 'right'}" aria-hidden="true"></i></td>
      <td><div class="fw-semibold" title="${esc(o.po_raw || '')}">${esc(o.po || o.po_raw || '—')}</div>
        <div class="small text-muted">${esc(o.order_no)}</div></td>
      <td class="ot-po-type">${esc(o.po_type || '')}</td>
      <td><div title="Sold-To ${esc(o.site)}">${esc(o.site_name || o.site)}</div>
        <div class="small text-muted" title="Ship-To ${esc(o.ship_to)}">${shipTo}</div></td>
      <td class="text-nowrap">${esc(fmtDateTime(o.received_at))}</td>
      <td>${confirmed}</td>
      <td class="text-end ot-total" title="${esc(plural(o.line_count, 'line'))} on this PO">
        <span class="fw-semibold">${fmtNumber(o.line_count)}</span>${found}</td>
      <td>${chips}</td>
      <td class="text-center ot-short-tally" title="${esc(STATUS_HINT.short)}">${o.short_lines
        ? `<span class="fw-semibold ot-short-note">${fmtNumber(o.short_lines)}</span>` : '<span class="text-muted">0</span>'}</td>
    </tr>
    <tr class="ot-lines-row"${open ? '' : ' hidden'}>
      <td></td>
      <td colspan="8" class="pt-0 pb-2">${linesHtml(o, picks)}</td>
    </tr>
  </tbody>`;
}

function linesHtml(o, picks) {
  // The lines found stand out only when the others weren't (a PO's search finds them all).
  const some = picks && o.matched < o.line_count;
  // On a tab, its lines come first (the user, 2026-11-17: the rejected, short-shipped... lines at
  // the top of the PO), each group in line order.
  const lines = state.status && some ? [...o.lines].sort((a, b) => Number(b.matched) - Number(a.matched)) : o.lines;
  const body = lines.map((l) => {
    const cls = some ? (l.matched ? 'ot-match' : 'ot-other') : '';
    const onPo = l.item_on_po && l.item_on_po !== l.medline_item
      ? `<div class="small text-muted">on PO: ${esc(l.item_on_po)}</div>` : '';
    const when = l.asn_at ? `ASN ${fmtAfter(l.asn_at, o.received_at)}` : '';
    return `<tr class="${cls}">
      <td class="text-nowrap" title="Medline order line ${esc(l.order_line)}">${esc(l.po_line || l.order_line)}</td>
      <td class="ot-line-type">${esc(l.line_type || '')}</td>
      <td><span class="fw-semibold">${esc(l.medline_item)}</span>${onPo}</td>
      <td>${esc(l.cust_item)}</td>
      <td>${esc(l.description)}</td>
      <td class="ot-manufacturer">${esc(l.manufacturer || '')}</td>
      <td class="ot-mfr-item text-nowrap">${esc(l.mfr_item || '')}</td>
      <td class="text-end text-nowrap">${fmtNumber(l.qty)} ${esc(l.um)}</td>
      <td class="text-end">${fmtNumber(l.shipped_qty)}</td>
      <td class="text-end">${fmtNumber(l.open_qty)}</td>
      <td class="text-end ot-line-short">${l.short_qty > 0 ? `<span class="fw-semibold ot-short-note">${fmtNumber(l.short_qty)}</span>` : ''}</td>
      <td class="ps-3">${badge(l.status)}${when ? `<div class="small text-muted text-nowrap">${esc(when)}</div>` : ''}</td>
      <td class="ot-bad-line text-danger fw-semibold">${esc(l.bad_line || '')}</td>
      <td class="ot-rej-code text-danger fw-semibold">${esc(l.rej_code || '')}</td>
    </tr>`;
  }).join('');
  return `<table class="table table-sm mb-0 ot-lines">
    <thead><tr>
      <th scope="col">PO line</th><th scope="col" title="Medline's Line Type">Line type</th><th scope="col">Medline item</th>
      <th scope="col" title="Medline's Cust Item #: our item number for it, usually Infor's">Customer item</th>
      <th scope="col">Description</th><th scope="col">Manufacturer</th>
      <th scope="col" title="Medline's Mfr Item #: the manufacturer's part number">Mfr part #</th>
      <th scope="col" class="text-end">Ordered</th>
      <th scope="col" class="text-end">Shipped</th><th scope="col" class="text-end">Open</th>
      <th scope="col" class="text-end" title="Short shipped: ordered, less shipped and still open, whatever the status">Short</th>
      <th scope="col" class="ps-3">Status</th>
      <th scope="col" title="Medline's Bad Line flag">Bad line</th>
      <th scope="col" title="Medline's reject code (E1, S1, X1…)">Rej code</th>
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
