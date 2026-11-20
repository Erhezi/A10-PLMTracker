/* What Order Timing's pages share (2026-11-17): Main and Short Ships. Formatting, fetching, the
 * filters both have (the search, the order days, their quick ranges and the sites menu, with the
 * same element IDs on each page), the page link, the pager above the table and "Data as of".
 * ("Data as of" and "last loaded" are static/js/freshness.js, which Fill/Kill's Main shows too.)
 *
 * Each page's settings are JSON in #ot-config.
 */

import { freshnessHtml } from '../freshness.js';

export const $ = (id) => document.getElementById(id);
export const config = JSON.parse($('ot-config').textContent);

// --- formatting ------------------------------------------------------------------------------

export const esc = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (ch) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
));
export const plural = (n, word) => `${Number(n).toLocaleString()} ${word}${n === 1 ? '' : 's'}`;
// A status label inside a sentence: "not confirmed", but "ASN sent" stays as it is.
export const inSentence = (label) => String(label).replace(/^[A-Z](?=[a-z])/, (ch) => ch.toLowerCase());

export function fmtDate(iso) {
  if (!iso) return '';
  const [y, m, d] = String(iso).slice(0, 10).split('-');
  return `${m}/${d}/${y}`;
}
export const fmtTime = (iso) => (iso ? String(iso).slice(11, 16) : '');
export const fmtDateTime = (iso) => (iso ? `${fmtDate(iso)} ${fmtTime(iso)}`.trim() : '');
// A later step's time: just the time when it's the same day as ``since``.
export const fmtAfter = (iso, since) => (iso && since && String(iso).slice(0, 10) === String(since).slice(0, 10)
  ? fmtTime(iso) : fmtDateTime(iso));
export const fmtNumber = (value) => (value == null || value === '' ? '' : Number(value).toLocaleString());

export function shiftDays(iso, days) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export const alertBox = (message, kind) => `<div class="alert alert-${kind || 'danger'} py-2 small mb-3" role="alert">${esc(message)}</div>`;

// --- fetching ---------------------------------------------------------------------------------

export function url(path, params) {
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

export async function getJSON(path, params) {
  const response = await window.appFetch(url(path, params));
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || `The server answered ${response.status}.`);
  return data;
}

export function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

// --- the filters both pages have ------------------------------------------------------------------

export const fromUrl = new URLSearchParams(window.location.search);
const validDate = (value) => (/^\d{4}-\d{2}-\d{2}$/.test(value || '') ? value : null);
// The pages reach the last 30 days only, and not before Medline's LUM go-live (config.earliest to
// today); the server holds the days to them too.
export const inWindow = (iso) => (iso < config.earliest ? config.earliest : (iso > config.today ? config.today : iso));

// The search, days, sites and page as the link gives them.
export function filterState() {
  const state = {
    q: fromUrl.get('q') || '',
    start: validDate(fromUrl.get('start')) || config.default.start,
    end: validDate(fromUrl.get('end')) || config.default.end,
    sites: (fromUrl.get('sites') || '').split(',').filter(Boolean),
    page: Math.max(1, parseInt(fromUrl.get('page'), 10) || 1),
  };
  if (state.start > state.end) [state.start, state.end] = [state.end, state.start];
  state.start = inWindow(state.start);
  state.end = inWindow(state.end);
  return state;
}

// Wires the search box (when the page has one: the Dashboard hasn't), the days, the quick ranges and
// the sites menu to ``state``; ``reload`` runs when one changes. Returns setDays, for the "Search the
// last 30 days" link.
export function setupFilters(state, reload) {
  const qInput = $('ot-q');
  const startInput = $('ot-start');
  const endInput = $('ot-end');
  const siteMenu = $('ot-sites');
  if (qInput) qInput.value = state.q;
  startInput.value = state.start;
  endInput.value = state.end;
  [startInput, endInput].forEach((input) => {
    input.min = config.earliest;
    input.max = config.today;
  });

  siteMenu.innerHTML = (config.sites || []).map((site, i) => `
    <div class="form-check">
      <input class="form-check-input" type="checkbox" value="${esc(site.code)}" id="ot-site-${i}"
        ${state.sites.includes(site.code) ? 'checked' : ''}>
      <label class="form-check-label text-nowrap" for="ot-site-${i}">${esc(site.name || site.code)}</label>
    </div>`).join('') || '<div class="small text-muted">No sites yet</div>';
  const siteLabel = () => {
    const boxes = Array.from(siteMenu.querySelectorAll('input'));
    const picked = boxes.filter((b) => b.checked);
    $('ot-sites-button').textContent = !picked.length || picked.length === boxes.length ? 'All sites'
      : (picked.length === 1 ? picked[0].nextElementSibling.textContent : `${picked.length} sites`);
  };
  siteLabel();

  // ``days``: the quick range asked for (a button's, or the whole window's), so it's the one pressed
  // when another one's days are the same.
  const setDays = (start, end, days = null) => {
    state.start = start;
    state.end = end;
    startInput.value = start;
    endInput.value = end;
    pickedDays = days == null ? null : String(days);
    markQuickDays(start, end);
    reload();
  };
  if (qInput) qInput.addEventListener('input', debounce(() => { state.q = qInput.value.trim(); reload(); }, 300));
  [startInput, endInput].forEach((input) => input.addEventListener('change', () => {
    if (!startInput.value || !endInput.value) return;
    const [start, end] = startInput.value <= endInput.value ? [startInput.value, endInput.value] : [endInput.value, startInput.value];
    setDays(inWindow(start), inWindow(end));  // a day typed past the last 30 comes back to them
  }));
  document.querySelectorAll('[data-days]').forEach((button) => button.addEventListener('click', () => {
    setDays(inWindow(shiftDays(config.today, 1 - Number(button.dataset.days))), config.today, button.dataset.days);
  }));
  siteMenu.addEventListener('change', () => {
    state.sites = Array.from(siteMenu.querySelectorAll('input:checked')).map((b) => b.value);
    siteLabel();
    reload();
  });
  markQuickDays(state.start, state.end);
  return { setDays };
}

// The quick range pressed (2026-11-20, as on Fill/Kill's Main): the button of Today, the last 7 or the
// last 30 days (each ending today, and starting no earlier than the pages reach) that start..end is,
// and none for any other days. Until the go-live is 30 days old, the last 7 and the last 30 days can
// be the same days: then the one asked for is pressed, or else the shorter, so a page opening on its
// last 7 days shows Last 7 days.
let pickedDays = null;
function markQuickDays(start, end) {
  const buttons = Array.from(document.querySelectorAll('[data-days]'));
  const fits = buttons.filter((button) => end === config.today
    && start === inWindow(shiftDays(config.today, 1 - Number(button.dataset.days))));
  const on = fits.find((button) => button.dataset.days === pickedDays) || fits[0];
  buttons.forEach((button) => {
    button.classList.toggle('active', button === on);
    button.setAttribute('aria-pressed', String(button === on));
  });
}

// The days the server took (held to the last 30, which can move at midnight), shown in the inputs.
export function showDays(state, { start, end }) {
  state.start = start;
  state.end = end;
  $('ot-start').value = start;
  $('ot-end').value = end;
  markQuickDays(start, end);
}

// Whether the days are already all the pages can reach.
export const isWholeWindow = (state) => state.start <= config.earliest && state.end >= config.today;

// The page link keeps what's chosen; the default days and page 1 are left out, so a bookmark opens
// on the latest days.
export function keepInUrl(kept) {
  const params = { ...kept };
  if (params.start === config.default.start && params.end === config.default.end) {
    delete params.start;
    delete params.end;
  }
  if (params.page === 1) delete params.page;
  window.history.replaceState(null, '', url(window.location.pathname, params));
}

// A not-found sentence's days and sites: "11/10/2026 to 11/17/2026 at those sites".
export function rangeText(state) {
  const range = state.start === state.end ? fmtDate(state.start) : `${fmtDate(state.start)} to ${fmtDate(state.end)}`;
  const where = state.sites.length ? ` at ${state.sites.length === 1 ? 'that site' : 'those sites'}` : '';
  return `${range}${where}`;
}

// After a not-found sentence: how to look further back, unless the days already go back that far
// (the last 30 days, and not before Medline's LUM go-live: config.earliest).
export const furtherBack = (state) => (isWholeWindow(state)
  ? ` <span class="text-muted">Order Timing looks back to ${esc(fmtDate(config.earliest))}.</span>`
  : ` <button type="button" class="btn btn-link btn-sm p-0 align-baseline" data-search-window>Search from ${esc(fmtDate(config.earliest))}</button>`);

// --- the pager above the table ------------------------------------------------------------------------

// Which rows these are, and the pages (the first, the last, and two either side of this one).
// Hidden when everything fits on one page. ``noun`` names the rows ("Orders", "Items"), and
// ``titles`` the previous and next buttons.
export function drawPager({ total, page, pages, per_page: perPage }, noun, titles = ['Previous page', 'Next page']) {
  $('ot-pager').hidden = pages <= 1;
  if (pages <= 1) return;
  const first = (page - 1) * perPage + 1;
  $('ot-range').textContent = `${noun} ${fmtNumber(first)}–${fmtNumber(Math.min(page * perPage, total))} of ${fmtNumber(total)}`;
  const shown = [...new Set([1, pages, ...[-2, -1, 0, 1, 2].map((d) => page + d)])]
    .filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  const item = (label, to, { active = false, disabled = false, title = '' } = {}) => (
    `<li class="page-item${active ? ' active' : ''}${disabled ? ' disabled' : ''}">
       <button type="button" class="page-link" data-page="${to}"${disabled ? ' disabled' : ''}
         ${active ? 'aria-current="page"' : ''}${title ? ` aria-label="${title}" title="${title}"` : ''}>${label}</button></li>`);
  const gap = '<li class="page-item disabled"><span class="page-link">…</span></li>';
  let html = item('&lsaquo;', page - 1, { disabled: page === 1, title: titles[0] });
  shown.forEach((n, i) => {
    if (i && n - shown[i - 1] > 1) html += gap;
    html += item(fmtNumber(n), n, { active: n === page });
  });
  html += item('&rsaquo;', page + 1, { disabled: page === pages, title: titles[1] });
  $('ot-pages').innerHTML = html;
}

// A page button clicked: ``go(page)``, back to the top of the table.
export function setupPager(go) {
  $('ot-pages').addEventListener('click', (event) => {
    const button = event.target.closest('[data-page]');
    if (!button || button.disabled) return;
    go(Number(button.dataset.page));
    document.querySelector('.ot-scroll').scrollTop = 0;
  });
}

// --- "Data as of" -------------------------------------------------------------------------------------

// As Fill/Kill's Main shows it: "Data as of" (Medline's file) · "last loaded" (static/js/freshness.js).
export { freshnessHtml as asOfHtml, freshnessWhen as asOfWhen } from '../freshness.js';
export const asOfText = (data) => { $('ot-as-of').innerHTML = freshnessHtml(data); };

// Rows that open to their lines: a click or Enter/Space on a row toggles it; ``open`` keeps which
// are open by ``key`` (data-key).
export function toggleRow(row, openSet, show) {
  const key = row.dataset.key;
  const open = show == null ? !openSet.has(key) : show;
  if (open) openSet.add(key); else openSet.delete(key);
  row.setAttribute('aria-expanded', String(open));
  row.querySelector('.ot-caret i').className = `bi bi-chevron-${open ? 'down' : 'right'}`;
  row.nextElementSibling.hidden = !open;
}
