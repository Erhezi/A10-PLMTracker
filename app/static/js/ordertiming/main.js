/* Order Timing Main (2026-11-16): our orders in Medline's feed, from /ordertiming/api/orders, to see
 * whether Medline received and confirmed them. One row per order (a PO), its lines below it.
 * Read-only. The search, days, sites and status are kept in the URL, so a view can be shared.
 *
 * An ES module, loaded with <script type="module">: it runs once the page is parsed, after
 * base.html has defined appFetch. The page's settings are JSON in #ot-config.
 */

const $ = (id) => document.getElementById(id);
const config = JSON.parse($('ot-config').textContent);
const STATUS_LABEL = Object.fromEntries(config.statuses);
const STATUS_CLASS = {
  not_confirmed: 'warning', rejected: 'danger', confirmed: 'primary', asn: 'success',
};
const STATUS_HINT = {
  not_confirmed: "Medline hasn't sent its order confirmation (855) for it yet.",
  rejected: "Medline rejected this line (a bad line, with Medline's reject code): it won't be filled.",
  confirmed: "Medline confirmed it (855); it hasn't shipped yet.",
  asn: 'Medline sent the ship notice (ASN, 856): it shipped.',
};

// --- helpers -------------------------------------------------------------------------------

const esc = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (ch) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
));
const plural = (n, word) => `${Number(n).toLocaleString()} ${word}${n === 1 ? '' : 's'}`;
// A status label inside a sentence: "not confirmed", but "ASN sent" stays as it is.
const inSentence = (label) => String(label).replace(/^[A-Z](?=[a-z])/, (ch) => ch.toLowerCase());

function fmtDate(iso) {
  if (!iso) return '';
  const [y, m, d] = String(iso).slice(0, 10).split('-');
  return `${m}/${d}/${y}`;
}
const fmtTime = (iso) => (iso ? String(iso).slice(11, 16) : '');
const fmtDateTime = (iso) => (iso ? `${fmtDate(iso)} ${fmtTime(iso)}`.trim() : '');
// A later step's time: just the time when it's the same day as ``since``.
const fmtAfter = (iso, since) => (iso && since && String(iso).slice(0, 10) === String(since).slice(0, 10)
  ? fmtTime(iso) : fmtDateTime(iso));
const fmtNumber = (value) => (value == null || value === '' ? '' : Number(value).toLocaleString());

function url(path, params) {
  const query = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      if (value.length) query.set(key, value.join(','));
    } else if (value != null && value !== '') {
      query.set(key, value);
    }
  });
  const qs = query.toString();
  return qs ? `${path}?${qs}` : path;
}

async function getJSON(path, params) {
  const response = await window.appFetch(url(path, params));
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || `The server answered ${response.status}.`);
  return data;
}

function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

const alertBox = (message, kind) => `<div class="alert alert-${kind || 'danger'} py-2 small mb-3" role="alert">${esc(message)}</div>`;

function badge(status, extra) {
  return `<span class="badge text-bg-${STATUS_CLASS[status] || 'secondary'}" title="${esc(STATUS_HINT[status] || '')}">`
    + `${esc(STATUS_LABEL[status] || status)}${extra ? ` ${esc(extra)}` : ''}</span>`;
}

// --- state, from the URL --------------------------------------------------------------------

const fromUrl = new URLSearchParams(window.location.search);
const validDate = (value) => (/^\d{4}-\d{2}-\d{2}$/.test(value || '') ? value : null);
// Main reaches the last 30 days only (config.earliest to today); the server holds the days to them too.
const inWindow = (iso) => (iso < config.earliest ? config.earliest : (iso > config.today ? config.today : iso));
const state = {
  q: fromUrl.get('q') || '',
  status: STATUS_LABEL[fromUrl.get('status')] ? fromUrl.get('status') : '',
  start: validDate(fromUrl.get('start')) || config.default.start,
  end: validDate(fromUrl.get('end')) || config.default.end,
  sites: (fromUrl.get('sites') || '').split(',').filter(Boolean),
  page: Math.max(1, parseInt(fromUrl.get('page'), 10) || 1),
  allOpen: false,
  open: new Set(),  // the orders whose lines show
};
if (state.start > state.end) [state.start, state.end] = [state.end, state.start];
state.start = inWindow(state.start);
state.end = inWindow(state.end);

// --- controls ---------------------------------------------------------------------------------

const qInput = $('ot-q');
const startInput = $('ot-start');
const endInput = $('ot-end');
const statusSelect = $('ot-status');
const siteMenu = $('ot-sites');

qInput.value = state.q;
startInput.value = state.start;
endInput.value = state.end;
[startInput, endInput].forEach((input) => {
  input.min = config.earliest;
  input.max = config.today;
});
statusSelect.innerHTML += config.statuses.map(([code, label]) => `<option value="${esc(code)}">${esc(label)}</option>`).join('');
statusSelect.value = state.status;

siteMenu.innerHTML = (config.sites || []).map((site, i) => `
  <div class="form-check">
    <input class="form-check-input" type="checkbox" value="${esc(site.code)}" id="ot-site-${i}"
      ${state.sites.includes(site.code) ? 'checked' : ''}>
    <label class="form-check-label text-nowrap" for="ot-site-${i}">${esc(site.name || site.code)}</label>
  </div>`).join('') || '<div class="small text-muted">No sites yet</div>';

function siteLabel() {
  const boxes = Array.from(siteMenu.querySelectorAll('input'));
  const picked = boxes.filter((b) => b.checked);
  $('ot-sites-button').textContent = !picked.length || picked.length === boxes.length ? 'All sites'
    : (picked.length === 1 ? picked[0].nextElementSibling.textContent : `${picked.length} sites`);
}
siteLabel();

function setDays(start, end) {
  state.start = start;
  state.end = end;
  startInput.value = start;
  endInput.value = end;
  reload();
}

function shiftDays(iso, days) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

// Whether the days are already all Main can reach.
const isWholeWindow = () => state.start <= config.earliest && state.end >= config.today;

qInput.addEventListener('input', debounce(() => { state.q = qInput.value.trim(); reload(); }, 300));
statusSelect.addEventListener('change', () => { state.status = statusSelect.value; reload(); });
[startInput, endInput].forEach((input) => input.addEventListener('change', () => {
  if (!startInput.value || !endInput.value) return;
  const [start, end] = startInput.value <= endInput.value ? [startInput.value, endInput.value] : [endInput.value, startInput.value];
  setDays(inWindow(start), inWindow(end));  // a day typed past the last 30 comes back to them
}));
document.querySelectorAll('[data-days]').forEach((button) => button.addEventListener('click', () => {
  setDays(shiftDays(config.today, 1 - Number(button.dataset.days)), config.today);
}));
siteMenu.addEventListener('change', () => {
  state.sites = Array.from(siteMenu.querySelectorAll('input:checked')).map((b) => b.value);
  siteLabel();
  reload();
});

const expandButton = $('ot-expand');
function showAll(open) {
  state.allOpen = open;
  expandButton.textContent = open ? 'Hide all lines' : 'Show all lines';
  document.querySelectorAll('#ot-rows .ot-order-row').forEach((row) => toggle(row, open));
}
expandButton.addEventListener('click', () => showAll(!state.allOpen));

function toggle(row, open) {
  const number = row.dataset.order;
  const show = open == null ? !state.open.has(number) : open;
  if (show) state.open.add(number); else state.open.delete(number);
  row.setAttribute('aria-expanded', String(show));
  row.querySelector('.ot-caret i').className = `bi bi-chevron-${show ? 'down' : 'right'}`;
  row.nextElementSibling.hidden = !show;
}

const rows = $('ot-rows');
rows.addEventListener('click', (event) => {
  if (event.target.closest('[data-search-window]')) {
    setDays(config.earliest, config.today);
    return;
  }
  const row = event.target.closest('.ot-order-row');
  if (row) toggle(row);
});
rows.addEventListener('keydown', (event) => {
  const row = event.target.closest('.ot-order-row');
  if (row && (event.key === 'Enter' || event.key === ' ')) {
    event.preventDefault();
    toggle(row);
  }
});

// --- loading ------------------------------------------------------------------------------------

// What the filters pick: the export takes these; Main's API also the page.
function params() {
  return { q: state.q, status: state.status, start: state.start, end: state.end, sites: state.sites };
}

// The URL keeps what's chosen; the default days and page 1 are left out, so a bookmark opens on the
// latest days.
function keepInUrl() {
  const kept = { ...params(), page: state.page > 1 ? state.page : null };
  if (kept.start === config.default.start && kept.end === config.default.end) {
    delete kept.start;
    delete kept.end;
  }
  window.history.replaceState(null, '', url(window.location.pathname, kept));
}

// A filter changed: back to the first page.
function reload() {
  state.page = 1;
  load();
}

const pageList = $('ot-pages');
pageList.addEventListener('click', (event) => {
  const button = event.target.closest('[data-page]');
  if (!button || button.disabled) return;
  state.page = Number(button.dataset.page);
  load();
  document.querySelector('.ot-scroll').scrollTop = 0;
});

function message(html) {
  rows.innerHTML = `<tr><td colspan="8" class="small p-3">${html}</td></tr>`;
}

let ticket = 0;

async function load() {
  const mine = ++ticket;
  $('ot-export').href = url(config.api.export, params());
  keepInUrl();
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

// The top right, as Fill/Kill's Main shows it (static/js/fillkill/main/table.js, renderDataAsOf).
function asOfText(data) {
  const el = $('ot-as-of');
  if (!data || !data.as_of) { el.innerHTML = ''; return; }
  const when = fmtDateTime(data.as_of);
  const what = data.source === 'feed' ? 'Data as of' : 'Latest line update';
  el.innerHTML = data.stale
    ? `<span class="badge text-bg-warning">${what} ${esc(when)}: more than 90 minutes old</span>`
    : `<span class="text-muted">${what} ${esc(when)}</span>`;
}

// --- drawing ------------------------------------------------------------------------------------

function render(data) {
  asOfText(data.data);
  const { orders, total } = data;
  const picks = data.filters.picks_lines;
  // The page and days the server gave (one past the last page is the last; the days held to the
  // last 30, which can move at midnight); the URL keeps them.
  const { start, end } = data.filters;
  if (data.page !== state.page || start !== state.start || end !== state.end) {
    Object.assign(state, { page: data.page, start, end });
    startInput.value = start;
    endInput.value = end;
    keepInUrl();
  }
  $('ot-count').textContent = total ? plural(total, 'order') : '';
  pagerHtml(data);
  if (!orders.length) {
    message(notFound(data));
    return;
  }
  // The search or a status opens every order, to show the lines they found; otherwise orders open
  // when clicked, or all with "Show all lines".
  state.open = new Set(picks || state.allOpen ? orders.map((o) => o.order_no) : []);
  rows.innerHTML = orders.map((o) => orderHtml(o, picks)).join('');
}

// The pager above the table: which orders these are, and the pages (the first, the last, and two
// either side of this one). Hidden when everything fits on one page.
function pagerHtml({ total, page, pages, per_page: perPage }) {
  $('ot-pager').hidden = pages <= 1;
  if (pages <= 1) return;
  const first = (page - 1) * perPage + 1;
  $('ot-range').textContent = `Orders ${fmtNumber(first)}–${fmtNumber(Math.min(page * perPage, total))} of ${fmtNumber(total)}`;
  const shown = [...new Set([1, pages, ...[-2, -1, 0, 1, 2].map((d) => page + d)])]
    .filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  const item = (label, to, { active = false, disabled = false, title = '' } = {}) => (
    `<li class="page-item${active ? ' active' : ''}${disabled ? ' disabled' : ''}">
       <button type="button" class="page-link" data-page="${to}"${disabled ? ' disabled' : ''}
         ${active ? 'aria-current="page"' : ''}${title ? ` aria-label="${title}" title="${title}"` : ''}>${label}</button></li>`);
  const gap = '<li class="page-item disabled"><span class="page-link">…</span></li>';
  let html = item('&lsaquo;', page - 1, { disabled: page === 1, title: 'Newer orders' });
  shown.forEach((n, i) => {
    if (i && n - shown[i - 1] > 1) html += gap;
    html += item(fmtNumber(n), n, { active: n === page });
  });
  html += item('&rsaquo;', page + 1, { disabled: page === pages, title: 'Older orders' });
  pageList.innerHTML = html;
}

function notFound(data) {
  const range = state.start === state.end ? fmtDate(state.start) : `${fmtDate(state.start)} to ${fmtDate(state.end)}`;
  const where = state.sites.length ? ` at ${state.sites.length === 1 ? 'that site' : 'those sites'}` : '';
  const more = isWholeWindow()
    ? ` <span class="text-muted">Order Timing looks back ${config.max_days} days.</span>`
    : ` <button type="button" class="btn btn-link btn-sm p-0 align-baseline" data-search-window>Search the last ${config.max_days} days</button>`;
  if (!state.q) {
    const status = state.status ? ` with a line that's ${esc(inSentence(STATUS_LABEL[state.status]))}` : '';
    return `<span class="text-muted">No orders in Medline's data for ${esc(range)}${where}${status}.</span>${more}`;
  }
  const words = state.q.split(/[\s,;]+/).filter(Boolean);
  const asOf = data.data && data.data.as_of;
  const po = words.every((word) => /^\d+$/.test(word))
    ? ` If you sent ${words.length === 1 ? 'that PO' : 'those POs'} to Medline on these days, Medline hasn't reported
       receiving ${words.length === 1 ? 'it' : 'them'}${asOf ? ` as of ${esc(fmtDateTime(asOf))}` : ''}.` : '';
  return `<span class="text-muted">No order in Medline's data for ${esc(range)}${where} matches “${esc(state.q)}”.${po}</span>${more}`;
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
    <tr class="ot-order-row" data-order="${esc(o.order_no)}" tabindex="0" role="button" aria-expanded="${open}">
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
    </tr>
    <tr class="ot-lines-row"${open ? '' : ' hidden'}>
      <td></td>
      <td colspan="7" class="pt-0 pb-2">${linesHtml(o, picks)}</td>
    </tr>
  </tbody>`;
}

function linesHtml(o, picks) {
  // The lines found stand out only when the others weren't (a PO's search finds them all).
  const some = picks && o.matched < o.line_count;
  const body = o.lines.map((l) => {
    const cls = some ? (l.matched ? 'ot-match' : 'ot-other') : '';
    const onPo = l.item_on_po && l.item_on_po !== l.medline_item
      ? `<div class="small text-muted">on PO: ${esc(l.item_on_po)}</div>` : '';
    // Short: fewer shipped and still open than ordered, on a line Medline didn't reject.
    const short = l.status !== 'rejected' && l.qty != null
      ? Number(l.qty) - Number(l.shipped_qty || 0) - Number(l.open_qty || 0) : 0;
    const when = l.status === 'asn' ? `ASN ${fmtAfter(l.asn_at, o.received_at)}` : '';
    return `<tr class="${cls}">
      <td class="text-nowrap" title="Medline order line ${esc(l.order_line)}">${esc(l.po_line || l.order_line)}</td>
      <td class="ot-line-type">${esc(l.line_type || '')}</td>
      <td><span class="fw-semibold">${esc(l.medline_item)}</span>${onPo}</td>
      <td>${esc(l.cust_item)}</td>
      <td>${esc(l.description)}</td>
      <td class="ot-manufacturer">${esc(l.manufacturer || '')}</td>
      <td class="ot-mfr-item text-nowrap">${esc(l.mfr_item || '')}</td>
      <td class="text-end text-nowrap">${fmtNumber(l.qty)} ${esc(l.um)}</td>
      <td class="text-end">${fmtNumber(l.shipped_qty)}${short > 0 ? `<div class="small text-danger" title="Ordered, less shipped and still open">${fmtNumber(short)} short</div>` : ''}</td>
      <td class="text-end">${fmtNumber(l.open_qty)}</td>
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
      <th scope="col" class="text-end">Shipped</th><th scope="col" class="text-end">Open</th><th scope="col" class="ps-3">Status</th>
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
