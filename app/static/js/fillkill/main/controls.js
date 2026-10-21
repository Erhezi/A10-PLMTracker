/* Main: the controls above the table: dates, sites, search and the Needs chips. */

import { $, config, debounce, esc, fmtDate } from '../common.js';
import { linked, state } from './state.js';
import { reloadAll } from './refresh.js';
import { renderRows } from './table.js';

// Two ways to choose the Fill/Kill dates (the kill lines' order dates; named so 2026-10-20, apart
// from our orders' dates): today only, or a range in the two date boxes. The button beside them
// switches. The live server opens on today; locally, on the newest day with kill lines
// (FILLKILL_OPEN_ON), today when that's today.
export function setupDates() {
  const startInput = $('fk-start');
  const endInput = $('fk-end');
  const modeButton = $('fk-date-mode');
  const first = config.bounds && config.bounds.first;
  const today = config.today;
  [startInput, endInput].forEach((input) => {
    if (first) input.min = first;
    if (today) input.max = today;
  });
  state.dateMode = today && state.start === today && state.end === today ? 'today' : 'range';

  const showMode = () => {
    const onToday = state.dateMode === 'today';
    startInput.value = state.start || '';
    endInput.value = state.end || '';
    startInput.disabled = onToday;
    endInput.disabled = onToday;
    modeButton.textContent = onToday ? 'Select a range' : 'View today';
    modeButton.title = onToday ? 'Choose the first and last Fill/Kill dates'
      : `Show only today's kill lines (${fmtDate(today)})`;
  };

  modeButton.addEventListener('click', () => {
    if (state.dateMode === 'today') {
      state.dateMode = 'range';  // the same dates until the range changes
      showMode();
      startInput.focus();
      return;
    }
    state.dateMode = 'today';
    state.start = today;
    state.end = today;
    showMode();
    reloadAll();
  });

  const fromInputs = () => {
    if (!startInput.value || !endInput.value) return;
    [state.start, state.end] = startInput.value <= endInput.value
      ? [startInput.value, endInput.value] : [endInput.value, startInput.value];
    showMode();
    reloadAll();
  };
  startInput.addEventListener('change', fromInputs);
  endInput.addEventListener('change', fromInputs);
  showMode();
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
  const update = debounce(() => {
    state.sites = boxes.filter((b) => b.checked).map((b) => b.value);
    label();
    reloadAll();
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
