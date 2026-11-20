/* Main: the controls above the table: dates, sites, search and the Needs chips. */

import { $, config, debounce, esc, markQuickDays, shiftDay } from '../common.js';
import { loadOrders } from './orders.js';
import { linked, state } from './state.js';
import { reloadAll } from './refresh.js';
import { renderRows } from './table.js';

// The Fill/Kill dates (the kill lines' order dates; named so 2026-10-20, apart from our orders'
// dates): Today, the Last 7 or 30 days, or any range in the two date boxes (2026-11-19, as Order
// Timing; a View today / Select a range switch before). Main opens on today, on every server.
export function setupDates() {
  const startInput = $('fk-start');
  const endInput = $('fk-end');
  const quick = $('fk-quick-dates');
  const first = config.bounds && config.bounds.first;
  const today = config.today;
  [startInput, endInput].forEach((input) => {
    if (first) input.min = first;
    if (today) input.max = today;
  });

  const show = () => {
    startInput.value = state.start || '';
    endInput.value = state.end || '';
    markQuickDays(quick, state.start, state.end);
  };

  quick.addEventListener('click', (event) => {
    const button = event.target.closest('[data-days]');
    if (!button || !today) return;
    state.start = shiftDay(today, 1 - Number(button.dataset.days));
    state.end = today;
    show();
    reloadAll();
  });

  const fromInputs = () => {
    if (!startInput.value || !endInput.value) return;
    [state.start, state.end] = startInput.value <= endInput.value
      ? [startInput.value, endInput.value] : [endInput.value, startInput.value];
    show();
    reloadAll();
  };
  startInput.addEventListener('change', fromInputs);
  endInput.addEventListener('change', fromInputs);
  show();
}

export function setupSites() {
  const menu = $('fk-sites');
  const button = $('fk-sites-button');
  menu.innerHTML = (config.sites || []).map((site, i) => `
    <div class="form-check">
      <input class="form-check-input" type="checkbox" value="${esc(site.code)}" id="fk-site-${i}">
      <label class="form-check-label text-nowrap" for="fk-site-${i}">${esc(site.name || site.code)}</label>
    </div>`).join('') || '<div class="small text-muted">No sites yet</div>';
  const boxes = Array.from(menu.querySelectorAll('input'));
  const label = () => {
    const names = boxes.filter((b) => b.checked).map((b) => b.nextElementSibling.textContent);
    button.textContent = !names.length || names.length === boxes.length ? 'All sites'
      : (names.length === 1 ? names[0] : `${names.length} sites`);
  };
  boxes.forEach((b) => { b.checked = state.sites.includes(b.value); });  // from the page link
  label();
  // The orders under the table follow the sites too (2026-10-27), so a site sees its own.
  const update = debounce(() => {
    state.sites = boxes.filter((b) => b.checked).map((b) => b.value);
    label();
    reloadAll();
    loadOrders();
  }, 300);
  boxes.forEach((b) => b.addEventListener('change', update));
}

export function setupSearch() {
  $('fk-search').value = linked.get('q') || '';
  $('fk-search').addEventListener('input', debounce((event) => {
    state.search = event.target.value.trim().toLowerCase();
    renderRows();
  }, 150));
}

// The Needs chips, each with how many items it holds.
export function renderNeeds() {
  const chips = [['all', 'All']].concat(config.needs);
  $('fk-needs').innerHTML = chips.map(([key, label]) => `
    <button type="button" class="btn btn-sm ${state.needs === key ? 'btn-primary' : 'btn-outline-secondary'}"
            data-needs="${key}" aria-pressed="${state.needs === key}">
      ${esc(label)} <span class="badge text-bg-light ms-1">${state.counts[key] ?? 0}</span>
    </button>`).join('');
}

export function setupNeeds() {
  $('fk-needs').addEventListener('click', (event) => {
    const chip = event.target.closest('[data-needs]');
    if (!chip) return;
    state.needs = chip.dataset.needs;
    renderNeeds();
    renderRows();
  });
  renderNeeds();
}
