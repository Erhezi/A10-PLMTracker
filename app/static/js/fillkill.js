/* Fill/Kill Management: the Main page (plan v2 §5.2).
 *
 * Reads the JSON API, draws the main table, the item panel and the tables
 * below, and sends actions through appFetch (CSRF token included). Controls a
 * user's roles don't allow aren't drawn; the server checks every action anyway.
 */
(function () {
  'use strict';

  const config = JSON.parse(document.getElementById('fk-config').textContent);
  const can = config.can || {};
  const api = config.api;
  config.statusLabels = Object.fromEntries(config.statuses);

  const state = {
    start: (config.default && config.default.start) || '',
    end: (config.default && config.default.end) || '',
    sites: [],
    needs: 'all',
    search: '',
    dateMode: 'range',  // 'today' or 'range'
    rows: [],
    counts: {},
    panelItem: null,
    panelTab: 'subs',
    panelScope: 'medline',  // 'infor': the whole Infor item; 'medline': only panelItem (one UOM)
    panelData: null,
  };

  // --- small helpers ----------------------------------------------------------------

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
  const STATUS_CLASS = {
    approved: 'text-bg-success', hold: 'text-bg-warning', pending_review: 'text-bg-info', rejected: 'text-bg-danger',
  };
  const STATUS_ORDER = ['approved', 'hold', 'pending_review', 'rejected'];
  const REASON_LABEL = {
    ALLOCATION: 'Allocation', MBO: 'Manufacturer backorder', OUT_OF_STOCK: 'Out of stock',
    NONSTOCK_UOM: 'Non-stock UOM', NONSTOCK: 'Non-stock', DISCONTINUED: 'Discontinued', SPIKE: 'Spike', OTHER: 'Other',
  };

  function statusBadge(status, extra) {
    return `<span class="badge ${STATUS_CLASS[status] || 'text-bg-secondary'}${extra ? ' ' + extra : ''}">`
      + `${esc(config.statusLabels[status] || status)}</span>`;
  }

  function fmtDate(iso) {
    if (!iso) return '';
    const [y, m, d] = String(iso).slice(0, 10).split('-');
    return `${m}/${d}/${y}`;
  }

  function fmtDateTime(iso) {
    if (!iso) return '';
    const text = String(iso);
    return `${fmtDate(text)} ${text.slice(11, 16)}`.trim();
  }

  function fmtNumber(value) {
    if (value == null || value === '') return '';
    const n = Number(value);
    return Number.isInteger(n) ? n.toLocaleString() : n.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }

  function qtyLines(quantities, key) {
    return quantities.map((q) => `<div>${fmtNumber(q[key])} <span class="text-muted small">${esc(q.uom)}</span></div>`).join('');
  }

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

  function scopeParams() {
    return { start: state.start, end: state.end, sites: state.sites };
  }

  async function getJSON(path, params) {
    const response = await window.appFetch(url(path, params));
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || `The server answered ${response.status}.`);
    return data;
  }

  async function postJSON(path, payload) {
    const response = await window.appFetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.message || `The server answered ${response.status}.`);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  const subUrl = (subId, action) => api.subAction.replace('/0/', `/${subId}/`).replace('ACTION', action);
  const orderUrl = (orderId, action) => api.orderAction.replace('/0/', `/${orderId}/`).replace('ACTION', action);
  const historyUrl = (entity, id) => api.history.replace('ENTITY', entity).replace(/\/0$/, `/${id}`);

  function debounce(fn, ms) {
    let timer = null;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), ms);
    };
  }

  // A sub's vendor: its name, with Infor's vendor ID when it has one.
  function vendorText(s) {
    return `${s.vendor || ''}${s.vendor_id ? ` (${s.vendor_id})` : ''}`;
  }

  function alertBox(message, kind) {
    return `<div class="alert alert-${kind || 'danger'} py-2 small mb-2" role="alert">${esc(message)}</div>`;
  }

  // --- controls: dates, sites, search, needs ----------------------------------------------

  // Two ways to choose the order dates: today only, or a range in the two date boxes. The button
  // beside them switches. The page opens on today when the newest kill lines are today's, and
  // otherwise on the newest day there is (a range of one day).
  function setupDates() {
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
      modeButton.title = onToday ? 'Choose the first and last order dates'
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

  function setupSites() {
    const menu = $('fk-sites');
    const button = $('fk-sites-button');
    menu.innerHTML = (config.sites || []).map((site, i) => `
      <div class="form-check">
        <input class="form-check-input" type="checkbox" value="${esc(site.code)}" id="fk-site-${i}">
        <label class="form-check-label text-nowrap" for="fk-site-${i}">${esc(site.name || site.code)}</label>
      </div>`).join('') || '<div class="small text-muted">No sites yet</div>';
    const boxes = Array.from(menu.querySelectorAll('input'));
    const update = debounce(() => {
      state.sites = boxes.filter((b) => b.checked).map((b) => b.value);
      const names = boxes.filter((b) => b.checked).map((b) => b.nextElementSibling.textContent);
      button.textContent = !names.length || names.length === boxes.length ? 'All sites'
        : (names.length === 1 ? names[0] : `${names.length} sites`);
      reloadAll();
    }, 300);
    boxes.forEach((b) => b.addEventListener('change', update));
  }

  function setupSearch() {
    $('fk-search').addEventListener('input', debounce((event) => {
      state.search = event.target.value.trim().toLowerCase();
      renderRows();
    }, 150));
  }

  function renderNeeds() {
    const chips = [['all', 'All']].concat(config.needs);
    $('fk-needs').innerHTML = chips.map(([key, label]) => `
      <button type="button" class="btn btn-sm ${state.needs === key ? 'btn-primary' : 'btn-outline-secondary'}"
              data-needs="${key}" aria-pressed="${state.needs === key}">
        ${esc(label)} <span class="badge text-bg-light ms-1">${state.counts[key] ?? 0}</span>
      </button>`).join('');
  }

  $('fk-needs').addEventListener('click', (event) => {
    const chip = event.target.closest('[data-needs]');
    if (!chip) return;
    state.needs = chip.dataset.needs;
    renderNeeds();
    renderRows();
  });

  // --- the main table ------------------------------------------------------------------------

  let mainRequest = 0;

  async function loadMain() {
    const ticket = ++mainRequest;
    try {
      const data = await getJSON(api.main, scopeParams());
      if (ticket !== mainRequest) return;  // a newer request is on its way
      state.rows = data.rows;
      state.counts = data.counts;
      renderDataAsOf(data.data);
      renderNeeds();
      renderRows();
    } catch (error) {
      if (ticket !== mainRequest) return;
      setRows(`<tbody><tr><td colspan="12" class="p-3">${alertBox(error.message)}</td></tr></tbody>`);
    }
  }

  function renderDataAsOf(data) {
    const el = $('fk-data-as-of');
    if (!data || !data.as_of) { el.innerHTML = ''; return; }
    const when = fmtDateTime(data.as_of);
    const what = data.source === 'feed' ? 'Data as of' : 'Latest line update';
    el.innerHTML = data.stale
      ? `<span class="badge text-bg-warning">${what} ${esc(when)}: more than 90 minutes old</span>`
      : `<span class="text-muted">${what} ${esc(when)}</span>`;
  }

  // Every word must appear in the Infor item's fields or in one of its packagings' (the commodity
  // code and its description are searchable but not shown in the table). Item numbers also match
  // without their dashes, spaces, dots and slashes, so "BD930" finds B-D930299Z.
  const ROW_SEARCHED = ['infor_item', 'description', 'long_description', 'commodity_code', 'commodity_description'];
  const PACKAGING_SEARCHED = ['medline_item', 'customer_item', 'description'];
  const compact = (value) => String(value || '').toLowerCase().replace(/[\s\-./]/g, '');

  function searchText(row) {
    if (!row.searchText) {
      const values = ROW_SEARCHED.map((key) => row[key])
        .concat(...row.packagings.map((p) => PACKAGING_SEARCHED.map((key) => p[key])));
      const numbers = [row.infor_item].concat(...row.packagings.map((p) => [p.medline_item, p.customer_item]));
      // Joined with spaces: a word has none, so it can't match across two fields.
      row.searchText = {
        text: values.map((value) => String(value || '').toLowerCase()).join(' '),
        numbers: numbers.map(compact).join(' '),
      };
    }
    return row.searchText;
  }

  function matchesSearch(row) {
    if (!state.search) return true;
    const { text, numbers } = searchText(row);
    return state.search.split(/\s+/).every((word) => text.includes(word) || (compact(word) && numbers.includes(compact(word))));
  }

  function subsStatusCell(counts) {
    const parts = STATUS_ORDER.filter((s) => counts[s])
      .map((s) => `${statusBadge(s)} <span class="small">${counts[s]}</span>`);
    return parts.length ? `<div class="d-flex flex-wrap gap-1 align-items-center">${parts.join(' ')}</div>`
      : '<span class="text-muted small">No subs</span>';
  }

  // Subs approved for another Medline item of the same Infor item (another UOM) not killed
  // in these dates: nursing still approves them here, but knows the product was already judged
  // (design §5, 2026-10-14).
  function otherPackagingNote(approved) {
    if (!approved || !approved.length) return '';
    const items = [...new Set(approved.map((a) => `${a.medline_item}${a.um ? ` (${a.um})` : ''}`))];
    const subs = approved.map((a) => `${a.vendor_part} · ${vendorText(a)} on ${a.medline_item}`).join('\n');
    return `<div class="small text-success mt-1" title="${esc(subs)}"><i class="bi bi-box-seam"></i>
      ${approved.length} approved for another UOM: ${esc(items.join(', '))}</div>`;
  }

  function picksCell(picks) {
    if (!picks.length) return '<span class="text-muted small">—</span>';
    return picks.map((pick) => {
      const label = `${esc(pick.vendor_part)} <span class="text-muted">· ${esc(vendorText(pick))}</span>`;
      return can.order
        ? `<button type="button" class="btn btn-sm btn-outline-primary py-0 mb-1 text-start" data-order-sub="${pick.sub_id}"
             data-item="${esc(pick.medline_item)}" title="Record an order for this pick">${label}</button>`
        : `<div class="small">${label}</div>`;
    }).join('');
  }

  function reasonCell(reason) {
    if (!reason) return '<span class="text-muted small">—</span>';
    const date = reason.reason_date ? ` <span class="text-muted">${fmtDate(reason.reason_date)}</span>` : '';
    return `<div class="small" title="${esc(reason.comment)}"><span class="badge text-bg-light border">`
      + `${esc(REASON_LABEL[reason.reason] || reason.reason)}</span>${date}</div>`;
  }

  // Medline's customer item isn't always the Infor item (it can be the Medline item itself, or
  // 1296-<Medline item>): a warning beside the Medline item, naming Medline's customer item on hover.
  function customerFlag(p) {
    if (p.consistent) return '';
    const text = `Medline Customer Item listed as ${p.customer_item || '(blank)'}`;
    return `<sup class="fk-flag" title="${esc(text)}"><i class="bi bi-exclamation-triangle-fill text-warning" role="img"
      aria-label="${esc(text)}"></i></sup>`;
  }

  function packagingCell(p) {
    const varies = p.varies.length ? ` <span class="badge text-bg-light border" title="Medline's lines or Infor disagree on: ${esc(p.varies.join(', '))}">varies</span>` : '';
    return `<button type="button" class="btn btn-link p-0" data-open="${esc(p.medline_item)}">${esc(p.medline_item)}</button>`
      + `${customerFlag(p)}${varies}`;
  }

  // Eaches per unit, from Infor's UOM conversion for the Infor item: one per UOM line.
  function qoeLines(quantities) {
    return quantities.map((q) => `<div>${q.each != null ? fmtNumber(q.each)
      : '<span class="text-muted" title="Infor has no conversion for this UOM of the Infor item">—</span>'}</div>`).join('');
  }

  function renderRows() {
    const rows = state.rows.filter((row) => (state.needs === 'all' || row.needs.includes(state.needs)) && matchesSearch(row));
    if (!rows.length) {
      const why = state.rows.length ? 'No item matches these filters.' : 'No kill lines for these dates and sites.';
      setRows(`<tbody><tr><td colspan="12" class="text-muted small p-3">${why}</td></tr></tbody>`);
      return;
    }
    setRows(rows.map(itemRows).join(''));
  }

  // Each Infor item is a <tbody> of its own, so its UOMs highlight together.
  const mainTable = $('fk-main');

  function setRows(html) {
    mainTable.querySelectorAll(':scope > tbody').forEach((body) => body.remove());
    mainTable.tHead.insertAdjacentHTML('afterend', html);
  }

  // One <tr> per Medline item (UOM); with several, a last <tr> adds them up in eaches.
  function itemRows(row) {
    const packs = row.packagings;
    const many = packs.length > 1;
    const span = many ? ` rowspan="${packs.length + 1}"` : '';
    const inactive = row.infor_active && row.infor_active !== 'Yes'
      ? ' <span class="badge text-bg-secondary" title="The Infor item is not active">Inactive</span>' : '';
    const infor = row.infor_item
      ? `<button type="button" class="btn btn-link p-0 fw-semibold" data-open="${esc(packs[0].medline_item)}" data-scope="infor"
           title="All UOMs of this Infor item">${esc(row.infor_item)}</button>${inactive}`
      : '<span class="text-muted small" title="Not a Medline vendor item in Infor">Not in Infor</span>';
    const count = many ? `<div class="small text-muted">${packs.length} UOMs</div>` : '';
    const inforDesc = row.long_description
      ? `<div class="text-truncate small text-muted" title="Infor: ${esc(row.long_description)}">${esc(row.long_description)}</div>` : '';
    const ordering = orderingCell(row);
    const note = otherPackagingNote(row.approved_other_packagings);
    const trs = packs.map((p, i) => `<tr>
      ${i ? '' : `<td${span}>${infor}${count}</td>`}
      <td>${packagingCell(p)}</td>
      ${i ? '' : `<td class="fk-desc"${span}><div class="text-truncate" title="${esc(row.description)}">${esc(row.description)}</div>${inforDesc}</td>`}
      <td class="text-end">${qoeLines(p.quantities)}</td>
      <td class="text-end">${qtyLines(p.quantities, 'ordered')}</td>
      <td class="text-end fw-semibold">${qtyLines(p.quantities, 'killed')}</td>
      <td class="text-end">${qtyLines(p.quantities, 'filled')}</td>
      <td class="text-end">${fmtNumber(p.lines)}</td>
      <td>${reasonCell(p.latest_reason)}</td>
      <td role="button" data-open="${esc(p.medline_item)}">${subsStatusCell(p.subs_status)}${many ? '' : note}</td>
      <td>${picksCell(p.picks)}</td>
      ${i ? '' : `<td${span} role="button" data-open="${esc(packs[0].medline_item)}" data-scope="infor" data-tab="orders"
          title="Open the orders">${ordering}</td>`}
    </tr>`);
    if (many) trs.push(totalRow(row, note));
    return `<tbody class="fk-item">${trs.join('')}</tbody>`;
  }

  // Orders placed since the first selected day: quantity, UOM and date, newest first.
  const ORDERS_SHOWN = 3;

  function orderingCell(row) {
    if (!row.orders.length) return '<span class="badge text-bg-light border">No order</span>';
    const lines = row.orders.slice(0, ORDERS_SHOWN).map((o) => `<div class="small text-nowrap">${fmtNumber(o.quantity)}
      <span class="text-muted">${esc(o.uom)}</span> · ${fmtDate(o.ordered_dt)}</div>`).join('');
    const more = row.orders.length > ORDERS_SHOWN ? `<div class="small text-muted">+${row.orders.length - ORDERS_SHOWN} more</div>` : '';
    return `<span class="badge text-bg-success">Ordered</span>${lines}${more}`;
  }

  // The UOMs added up in eaches, by Infor's UOM conversion.
  function totalRow(row, note) {
    const each = (key) => (row.quantities_each
      ? `${fmtNumber(row.quantities_each[key])} <span class="text-muted small">EA</span>`
      : '<span class="text-muted" title="A UOM has no Infor conversion, so they can\'t be added up">—</span>');
    return `<tr class="fk-total">
      <td class="small text-muted">All UOMs, in EA</td>
      <td></td>
      <td class="text-end">${each('ordered')}</td>
      <td class="text-end fw-semibold">${each('killed')}</td>
      <td class="text-end">${each('filled')}</td>
      <td class="text-end">${fmtNumber(row.lines)}</td>
      <td></td>
      <td>${note}</td>
      <td></td>
    </tr>`;
  }

  mainTable.addEventListener('click', (event) => {
    const orderButton = event.target.closest('[data-order-sub]');
    if (orderButton) {
      openOrderForm(Number(orderButton.dataset.orderSub), orderButton.dataset.item);
      return;
    }
    const opener = event.target.closest('[data-open]');
    if (opener) openPanel(opener.dataset.open, opener.dataset.tab || null, opener.dataset.scope);
  });

  // --- the item panel -------------------------------------------------------------------------

  const panelEl = $('fk-panel');
  const panel = window.bootstrap ? window.bootstrap.Offcanvas.getOrCreateInstance(panelEl) : null;

  // Drag the panel's left edge (or use the arrow keys on it) to change its width; this browser
  // remembers it. Double-click the edge to go back to the default.
  const PANEL_WIDTH_KEY = 'fk-panel-width';
  const resizer = $('fk-panel-resize');
  const clampWidth = (px) => Math.round(Math.min(Math.max(px, 320), window.innerWidth - 40));

  function setPanelWidth(px, save) {
    const width = clampWidth(px);
    panelEl.style.width = `${width}px`;
    if (save) {
      try { localStorage.setItem(PANEL_WIDTH_KEY, String(width)); } catch (error) { /* not remembered */ }
    }
  }

  try {
    const saved = Number(localStorage.getItem(PANEL_WIDTH_KEY));
    if (saved) setPanelWidth(saved, false);
  } catch (error) { /* default width */ }

  resizer.addEventListener('pointerdown', (event) => {
    event.preventDefault();
    resizer.setPointerCapture(event.pointerId);
    document.body.classList.add('fk-resizing');
    const move = (e) => setPanelWidth(window.innerWidth - e.clientX, false);
    const done = () => {
      resizer.removeEventListener('pointermove', move);
      resizer.removeEventListener('pointerup', done);
      resizer.removeEventListener('pointercancel', done);
      document.body.classList.remove('fk-resizing');
      setPanelWidth(panelEl.getBoundingClientRect().width, true);
    };
    resizer.addEventListener('pointermove', move);
    resizer.addEventListener('pointerup', done);
    resizer.addEventListener('pointercancel', done);
  });

  resizer.addEventListener('keydown', (event) => {
    const step = { ArrowLeft: 32, ArrowRight: -32 }[event.key];
    if (!step) return;
    event.preventDefault();
    setPanelWidth(panelEl.getBoundingClientRect().width + step, true);
  });

  resizer.addEventListener('dblclick', () => {
    panelEl.style.width = '';
    try { localStorage.removeItem(PANEL_WIDTH_KEY); } catch (error) { /* nothing kept */ }
  });

  window.addEventListener('resize', debounce(() => {
    if (panelEl.style.width) setPanelWidth(parseFloat(panelEl.style.width), false);
  }, 150));

  // scope 'infor' shows the whole Infor item (all UOMs); otherwise just this Medline item.
  async function openPanel(item, tab, scope) {
    state.panelItem = item;
    state.panelScope = scope === 'infor' ? 'infor' : 'medline';
    if (tab) state.panelTab = tab;
    $('fk-panel-title').textContent = item;
    $('fk-panel-subtitle').textContent = '';
    $('fk-panel-body').innerHTML = '<div class="text-muted small">Loading…</div>';
    if (panel) panel.show();
    await loadPanel();
  }

  let panelRequest = 0;

  async function loadPanel(message) {
    const item = state.panelItem;
    if (!item) return;
    const ticket = ++panelRequest;
    try {
      const data = await getJSON(api.item, Object.assign({ item }, scopeParams()));
      if (ticket !== panelRequest) return;  // a newer request is on its way
      state.panelData = data;
      renderPanel(message);
    } catch (error) {
      $('fk-panel-body').innerHTML = alertBox(error.message);
    }
  }

  // What the panel shows. The API always returns the whole Infor item; clicked on a Medline item,
  // the panel keeps to that Medline item (one UOM): its subs, kill lines, history and orders.
  function panelView() {
    const data = state.panelData;
    const whole = state.panelScope === 'infor';
    const mine = (x) => whole || x.medline_item === state.panelItem;
    const packs = data.packagings.filter(mine);
    const lines = data.lines.filter(mine);
    return {
      whole,
      packs,
      lines,
      orders: data.orders.filter(mine),
      history: data.pick_history.filter(mine),
      many: packs.length > 1,
      reason: whole ? data.latest_reason : lines[0],  // lines are newest first
    };
  }

  function renderPanel(message) {
    const data = state.panelData;
    const d = data.details || {};
    const view = panelView();
    $('fk-panel-title').textContent = view.whole && data.infor_item ? `Infor item ${data.infor_item}` : state.panelItem;
    $('fk-panel-subtitle').innerHTML = [
      !view.whole && data.infor_item ? `Infor item ${esc(data.infor_item)}` : '',
      esc((view.whole ? d.description : (view.packs[0] || {}).description) || ''),
      view.reason ? esc(view.reason.comment) : '',
    ].filter(Boolean).join(' · ');

    const subs = view.packs.reduce((n, p) => n + p.subs.length, 0);
    const tabs = [
      ['subs', `Subs <span class="badge text-bg-light">${subs}</span>`],
      ['lines', `Kill lines <span class="badge text-bg-light">${view.lines.length}</span>`],
      ['picks', 'Sub History'],
      ['orders', `Orders <span class="badge text-bg-light">${view.orders.length}</span>`],
    ];
    $('fk-panel-body').innerHTML = `
      ${message ? alertBox(message.text, message.kind) : ''}
      ${itemDetails(d)}
      ${packagingList(data, view)}
      <ul class="nav nav-pills nav-fill small mb-3" role="tablist">
        ${tabs.map(([key, label]) => `<li class="nav-item"><button type="button" class="nav-link py-1 ${state.panelTab === key ? 'active' : ''}"
            data-panel-tab="${key}">${label}</button></li>`).join('')}
      </ul>
      <div id="fk-panel-content">${renderPanelTab(state.panelTab)}</div>`;
  }

  function itemDetails(d) {
    const rows = [
      ['Infor item', d.infor_item
        ? [d.infor_item, d.infor_active ? (d.infor_active === 'Yes' ? 'Active' : 'Inactive') : ''].filter(Boolean).join(' · ')
        : 'None: not a Medline vendor item in Infor'],
      ['Long description', d.long_description],
      ['Commodity', [d.commodity_code, d.commodity_description].filter(Boolean).join(' · ')],
      ['Manufacturer', [d.manufacturer, d.mfr_item].filter(Boolean).join(' · ')],
    ].filter(([, value]) => value);
    return `<dl class="row small bg-light border rounded py-2 mx-0 mb-3">${rows.map(([label, value]) => `
      <dt class="col-sm-4 text-muted fw-normal">${esc(label)}</dt><dd class="col-sm-8 mb-1">${esc(value)}</dd>`).join('')}</dl>`;
  }

  // The Medline items (UOMs) shown: those killed in these dates first, then any other Medline has
  // killed under the Infor item. Switch between one Medline item and all of them here.
  function packagingList(data, view) {
    const total = data.packagings.length;
    let label = view.many ? `${view.packs.length} UOMs (Medline items)` : 'Medline item';
    if (view.whole && total > 1) label += ' · click one to see only it';
    const widen = !view.whole && total > 1
      ? `<button type="button" class="btn btn-link btn-sm p-0 ms-2 align-baseline" data-panel-focus="">Show all ${total} UOMs
          of Infor item ${esc(data.infor_item)}</button>` : '';
    return `<div class="small mb-3"><div class="text-muted mb-1">${label}${widen}</div>
      <ul class="list-unstyled mb-0">${view.packs.map((p) => {
        const notes = [
          esc(p.um),
          p.qoe != null ? `QOE ${fmtNumber(p.qoe)}` : '',
          p.killed_in_range ? '' : 'not killed in these dates',
        ].filter(Boolean).join(' · ');
        const name = view.many
          ? `<button type="button" class="btn btn-link btn-sm p-0 align-baseline" data-panel-focus="${esc(p.medline_item)}">${esc(p.medline_item)}</button>`
          : `<span class="fw-semibold">${esc(p.medline_item)}</span>`;
        return `<li class="mb-1">${name}${customerFlag(p)}
          <span class="text-muted">${notes}</span>
          ${p.description ? `<div class="text-muted text-truncate">${esc(p.description)}</div>` : ''}</li>`;
      }).join('')}</ul></div>`;
  }

  function renderPanelTab(tab) {
    const view = panelView();
    if (tab === 'lines') return linesTab(view.lines, view.many);
    if (tab === 'picks') return picksTab(view.history, view.many);
    if (tab === 'orders') return ordersTab(view.orders, view.many);
    return subsTab(view);
  }

  const panelSubs = () => (state.panelData ? state.panelData.packagings.flatMap((p) => p.subs) : []);

  // Subs ----

  // Subs belong to a Medline item: with several UOMs, one section each.
  function subsTab(view) {
    const { packs, many } = view;
    const add = can.add_sub ? `
      <div class="mb-3">
        <button type="button" class="btn btn-sm btn-primary" data-act="show-add"><i class="bi bi-plus-lg"></i> Add sub</button>
        <div id="fk-add-sub" class="d-none mt-2">${addSubForm(packs)}</div>
      </div>` : '';
    return add + packs.map((p) => {
      const head = many ? `<h3 class="h6 fw-semibold mt-3 mb-2">${esc(p.medline_item)}${customerFlag(p)}
          <span class="fw-normal small text-muted">${esc(p.um)}${p.killed_in_range ? '' : ' · not killed in these dates'}</span></h3>` : '';
      const own = p.subs.length ? p.subs.map(subCard).join('')
        : `<p class="text-muted small mb-2">No subs yet for ${many ? esc(p.medline_item) : 'this item'}.</p>`;
      return head + own + otherSubs(p);
    }).join('');
  }

  // Subs on the Infor item's other UOMs, not on this one yet.
  function otherSubs(p) {
    if (!p.other_subs.length) return '';
    return `<div class="small text-muted mb-1">On other UOMs, not on ${esc(p.medline_item)} yet. Add one to review and pick it here:</div>
      <ul class="list-group list-group-flush small mb-2">${p.other_subs.map((o) => `
        <li class="list-group-item px-0 d-flex flex-wrap gap-2 align-items-center">
          <span class="fw-semibold">${esc(o.vendor_part)}</span><span class="text-muted">${esc(vendorText(o))}</span>
          ${statusBadge(o.status)}
          <span class="text-muted">on ${esc(o.medline_item)}${o.um ? ` (${esc(o.um)})` : ''}${o.approved_by
            ? `, approved by ${esc(o.approved_by)} ${fmtDateTime(o.approved_at)}` : ''}</span>
          ${can.add_sub ? `<button type="button" class="btn btn-sm btn-outline-primary ms-auto py-0" data-act="copy-sub"
              data-sub="${o.sub_id}" data-item="${esc(p.medline_item)}">Add to ${esc(p.medline_item)}</button>` : ''}
        </li>`).join('')}</ul>`;
  }

  function subCard(sub) {
    const meta = [
      sub.description ? esc(sub.description) : '',
      sub.uom ? `UOM ${esc(sub.uom)}${sub.qoe ? ` · QOE ${fmtNumber(sub.qoe)}` : ''}` : '',
    ].filter(Boolean).join(' · ');
    const source = sub.source === 'medline_pbo' ? 'Medline PBO' : esc(sub.entered_by);
    const comment = sub.latest_comment
      ? `<div class="small border-start border-3 ps-2 my-2"><span class="text-muted">${esc(sub.latest_comment.actor)},
          ${fmtDateTime(sub.latest_comment.acted_at)}${sub.latest_comment.count > 1 ? ` (${sub.latest_comment.count} comments)` : ''}:</span>
          ${esc(sub.latest_comment.comment)}</div>` : '';

    const actions = [];
    if (can.review) {
      const options = ['approved', 'hold', 'rejected'].map((s) => `<option value="${s}" ${sub.status === s ? 'selected' : ''}>${esc(config.statusLabels[s])}</option>`);
      actions.push(`<select class="form-select form-select-sm w-auto" data-act="status" data-sub="${sub.sub_id}" data-expected="${sub.status}" aria-label="Status">
        ${sub.status === 'pending_review' ? '<option value="" selected disabled>Set status…</option>' : ''}${options.join('')}</select>`);
      if (sub.status === 'approved') {
        actions.push(sub.is_picked
          ? `<button type="button" class="btn btn-sm btn-outline-secondary" data-act="unpick" data-sub="${sub.sub_id}" data-expected="${sub.status}">Unpick</button>`
          : `<button type="button" class="btn btn-sm btn-success" data-act="pick" data-sub="${sub.sub_id}" data-expected="${sub.status}"><i class="bi bi-hand-index-thumb"></i> Pick</button>`);
      }
    }
    if (can.order && sub.is_picked) {
      actions.push(`<button type="button" class="btn btn-sm btn-primary" data-act="order" data-sub="${sub.sub_id}"
        data-item="${esc(sub.medline_item)}">Record order</button>`);
    }
    if (can.add_sub) {
      actions.push(`<button type="button" class="btn btn-sm btn-outline-secondary" data-act="edit-sub" data-sub="${sub.sub_id}">Edit</button>`);
      // The Approver's Pick can't be deleted until it's unpicked (the server refuses it too).
      actions.push(sub.is_picked
        ? `<span class="d-inline-block" tabindex="0" title="It's the Approver's Pick: unpick it first">
             <button type="button" class="btn btn-sm btn-outline-danger" disabled>Delete</button></span>`
        : `<button type="button" class="btn btn-sm btn-outline-danger" data-act="delete-sub" data-sub="${sub.sub_id}">Delete</button>`);
    }
    actions.push(`<button type="button" class="btn btn-sm btn-link" data-act="history" data-entity="sub" data-id="${sub.sub_id}">History</button>`);

    const commentBox = can.review ? `
      <form class="input-group input-group-sm mt-2" data-act="comment-sub" data-sub="${sub.sub_id}">
        <input type="text" class="form-control" name="comment" maxlength="400" placeholder="Add a comment" aria-label="Comment on this sub">
        <button class="btn btn-outline-secondary" type="submit">Add</button>
      </form>` : '';

    return `<div class="card mb-2 ${sub.is_picked ? 'border-success' : ''}">
      <div class="card-body p-2">
        <div class="d-flex flex-wrap gap-2 align-items-center">
          <span class="fw-semibold">${esc(sub.vendor_part)}</span><span class="text-muted">${esc(vendorText(sub))}</span>
          ${statusBadge(sub.status)}${sub.is_picked ? ' <span class="badge text-bg-success"><i class="bi bi-check2"></i> Picked</span>' : ''}
          ${(sub.approved_elsewhere || []).map((o) => `<span class="badge text-success border border-success bg-white"
              title="Approved by ${esc(o.approved_by || '')} ${fmtDateTime(o.approved_at)}"><i class="bi bi-box-seam"></i>
              Approved for ${esc(o.medline_item)}${o.um ? ` (${esc(o.um)})` : ''}</span>`).join(' ')}
        </div>
        ${meta ? `<div class="small text-muted">${meta}</div>` : ''}
        <div class="small text-muted">Added by ${source}, ${fmtDateTime(sub.create_dt)} · updated ${fmtDateTime(sub.update_dt)}</div>
        ${comment}
        <div class="d-flex flex-wrap gap-2 align-items-center mt-2">${actions.join('')}</div>
        ${commentBox}
        <div class="fk-history small mt-2" id="fk-history-sub-${sub.sub_id}"></div>
      </div>
    </div>`;
  }

  function addSubForm(packs) {
    // Several UOMs: which Medline item the sub is for (the one clicked, unless changed).
    const target = packs.length > 1 ? `
          <div class="col-12"><label class="form-label small mb-0" for="fk-add-item">For Medline item *</label>
            <select class="form-select form-select-sm" id="fk-add-item" name="medline_item">${packs.map((p) => `
              <option value="${esc(p.medline_item)}" ${p.medline_item === state.panelItem ? 'selected' : ''}>${esc(p.medline_item)} (${esc(p.um)})</option>`).join('')}
            </select></div>` : '';
    return `
      <div class="border rounded p-2 bg-light">
        <label class="form-label small mb-1" for="fk-contract-q">Search Infor's active contracts</label>
        <input type="search" class="form-control form-control-sm mb-2" id="fk-contract-q" autocomplete="off"
               placeholder="Vendor item, manufacturer number, or description words">
        <div id="fk-contract-results" class="small mb-2"></div>
        <form id="fk-add-form" class="row g-2" novalidate>${target}
          <div class="col-4"><label class="form-label small mb-0" for="fk-add-vendor-id">Vendor ID</label>
            <input class="form-control form-control-sm" id="fk-add-vendor-id" name="vendor_id" maxlength="20"
                   inputmode="numeric" placeholder="Optional" data-vendor-name="fk-add-vendor">
            <div class="form-text small mt-0" id="fk-add-vendor-id-note"></div></div>
          <div class="col-8"><label class="form-label small mb-0" for="fk-add-vendor">Vendor name *</label>
            <input class="form-control form-control-sm" id="fk-add-vendor" name="vendor" maxlength="255" required></div>
          <div class="col-6"><label class="form-label small mb-0" for="fk-add-part">Vendor part *</label>
            <input class="form-control form-control-sm" id="fk-add-part" name="vendor_part" maxlength="100" required></div>
          <div class="col-12"><label class="form-label small mb-0" for="fk-add-desc">Description</label>
            <input class="form-control form-control-sm" id="fk-add-desc" name="description" maxlength="255"></div>
          <div class="col-4"><label class="form-label small mb-0" for="fk-add-uom">UOM</label>
            <input class="form-control form-control-sm" id="fk-add-uom" name="uom" maxlength="10"></div>
          <div class="col-4"><label class="form-label small mb-0" for="fk-add-qoe">QOE</label>
            <input class="form-control form-control-sm" id="fk-add-qoe" name="qoe" inputmode="decimal"></div>
          <div class="col-12"><label class="form-label small mb-0" for="fk-add-comment">Comment</label>
            <input class="form-control form-control-sm" id="fk-add-comment" name="comment" maxlength="400"></div>
          <div class="col-12"><button type="submit" class="btn btn-sm btn-primary">Add sub</button>
            <button type="button" class="btn btn-sm btn-link" data-act="hide-add">Cancel</button></div>
        </form>
      </div>`;
  }

  // Whether the contract line is available for MHS (on a contract of MMAHS organization 105188574).
  // A non-MHS line can still be chosen; the badge only says so.
  function contractMhsBadge(line) {
    return line.is_mhs === 'Yes'
      ? '<span class="badge text-bg-success ms-auto">MHS</span>'
      : '<span class="badge text-bg-warning ms-auto" title="Not on an MHS contract. You can still choose it.">Non-MHS</span>';
  }

  const searchContracts = debounce(async (q) => {
    const box = $('fk-contract-results');
    if (!box) return;
    if (q.replace(/\s/g, '').length < 3) { box.innerHTML = ''; return; }
    box.innerHTML = '<span class="text-muted">Searching…</span>';
    try {
      const data = await getJSON(api.contractLines, { q });
      if (!$('fk-contract-q') || $('fk-contract-q').value !== q) return;
      if (!data.lines.length) { box.innerHTML = '<span class="text-muted">No active contract line found; fill in the sub below.</span>'; return; }
      state.contractLines = data.lines;
      box.innerHTML = `<div class="list-group">${data.lines.map((line, i) => {
        const facts = [
          line.infor_item ? `Infor item ${esc(line.infor_item)}` : 'No Infor item',
          `${esc(line.uom)}${line.qoe ? ` × ${fmtNumber(line.qoe)}` : ''}`,
          line.contracts > 1 ? `${line.contracts} contracts${line.mhs_contracts && line.mhs_contracts < line.contracts
            ? ` (${line.mhs_contracts} MHS)` : ''}` : '',
        ].filter(Boolean).join(' · ');
        return `
        <button type="button" class="list-group-item list-group-item-action py-1" data-contract="${i}">
          <div class="d-flex gap-2 align-items-baseline">
            <span><span class="fw-semibold">${esc(line.vendor_item)}</span> · ${esc(line.vendor_name)}
              <span class="text-muted">(vendor ${esc(line.vendor_id)})</span></span>
            ${contractMhsBadge(line)}
          </div>
          <div class="text-muted">${facts}</div>
          <div class="text-muted text-truncate">${esc(line.description)}</div>
        </button>`;
      }).join('')}</div>`;
    } catch (error) {
      box.innerHTML = alertBox(error.message);
    }
  }, 350);

  function fillFromContract(line) {
    $('fk-add-vendor-id').value = line.vendor_id || '';
    vendorNote($('fk-add-vendor-id'), '');
    $('fk-add-vendor').value = line.vendor_name || '';
    $('fk-add-vendor').dataset.autofilled = '1';
    $('fk-add-part').value = line.vendor_item || '';
    $('fk-add-desc').value = line.description || '';
    $('fk-add-uom').value = line.uom || '';
    $('fk-add-qoe').value = line.qoe != null ? fmtNumber(line.qoe).replace(/,/g, '') : '';
  }

  // Kill lines, pick history, orders ----

  function linesTab(lines, many) {
    if (!lines.length) return '<p class="text-muted small">No kill lines for these dates and sites.</p>';
    return `<div class="table-responsive"><table class="table table-sm small align-middle">
      <thead class="table-light"><tr><th>Ordered</th>${many ? '<th>Medline Item</th>' : ''}<th>Site · Dept</th><th>PO</th><th class="text-end">Killed</th><th>Reason</th></tr></thead>
      <tbody>${lines.map((l) => `<tr>
        <td class="text-nowrap">${fmtDate(l.order_date)} ${esc(String(l.order_time || '').slice(0, 5))}</td>
        ${many ? `<td class="text-nowrap">${esc(l.medline_item)}</td>` : ''}
        <td>${esc(l.site)}${l.is_test ? ` <span class="badge text-bg-warning" title="${esc(l.test_purpose || 'Test line')}">test</span>` : ''}<div class="text-muted">${esc(l.department)}</div>
            ${l.test_purpose ? `<div class="text-muted fst-italic">${esc(l.test_purpose)}</div>` : ''}</td>
        <td class="text-nowrap">${esc(l.po)}${l.po_line != null ? `-${esc(l.po_line)}` : ''}</td>
        <td class="text-end text-nowrap">${fmtNumber(l.killed)} / ${fmtNumber(l.ordered)} ${esc(l.um)}</td>
        <td>${l.reason ? `<span class="badge text-bg-light border">${esc(REASON_LABEL[l.reason] || l.reason)}</span>` : ''}
            <div class="text-muted">${esc(l.comment)}</div></td>
      </tr>`).join('')}</tbody></table></div>`;
  }

  function describe(h) {
    const labels = config.statusLabels;
    switch (h.action) {
      case 'created': return h.entity === 'order' ? 'Recorded the order' : 'Added the sub';
      case 'status': return `Status ${esc(labels[h.from_value] || h.from_value)} → ${statusBadge(h.to_value)}`;
      case 'pick': return 'Picked';
      case 'unpick': return h.comment ? esc(h.comment) : 'Unpicked';
      case 'comment': return `Comment: ${esc(h.comment)}`;
      case 'edit': return `Changed ${esc(String(h.field || '').replace('_', ' '))}: ${esc(h.from_value || '—')} → ${esc(h.to_value || '—')}`;
      case 'void': return `Voided: ${esc(h.comment)}`;
      case 'delete': return `Deleted: ${esc(h.comment)}`;
      default: return esc(h.action);
    }
  }

  function timeline(entries, withLabel, withItem) {
    if (!entries.length) return '<p class="text-muted small">Nothing yet.</p>';
    return `<ul class="list-unstyled small mb-0 fk-timeline">${entries.map((h) => `
      <li class="mb-1"><span class="text-muted text-nowrap">${fmtDateTime(h.acted_at)}</span> ·
        ${esc(h.actor)}${withLabel && h.label ? ` · <span class="fw-semibold">${esc(h.label)}</span>` : ''}${withItem && h.medline_item
          ? ` <span class="text-muted">on ${esc(h.medline_item)}</span>` : ''} · ${describe(h)}</li>`).join('')}</ul>`;
  }

  function picksTab(history, many) {
    return `<p class="small text-muted mb-2">Every sub added, reviewed, picked and unpicked for ${many ? 'these Medline items' : 'this Medline item'}, newest first.</p>
      ${timeline(history, true, many)}`;
  }

  function ordersTab(orders, many) {
    if (!orders.length) return '<p class="text-muted small">No orders recorded for this item.</p>';
    return orders.map((o) => {
      const actions = [];
      if (can.order && !o.voided_at) {
        actions.push(`<button type="button" class="btn btn-sm btn-outline-secondary" data-act="edit-order" data-order="${o.order_id}">Correct</button>`);
        actions.push(`<button type="button" class="btn btn-sm btn-outline-danger" data-act="void-order" data-order="${o.order_id}">Void</button>`);
      }
      actions.push(`<button type="button" class="btn btn-sm btn-link" data-act="history" data-entity="order" data-id="${o.order_id}">History</button>`);
      const commentBox = can.order ? `
        <form class="input-group input-group-sm mt-2" data-act="comment-order" data-order="${o.order_id}">
          <input type="text" class="form-control" name="comment" maxlength="400" placeholder="Add a comment" aria-label="Comment on this order">
          <button class="btn btn-outline-secondary" type="submit">Add</button>
        </form>` : '';
      return `<div class="card mb-2 ${o.voided_at ? 'opacity-75' : ''}"><div class="card-body p-2 small">
        <div class="d-flex flex-wrap gap-2 align-items-center">
          <span class="fw-semibold ${o.voided_at ? 'text-decoration-line-through' : ''}">${fmtNumber(o.quantity)} ${esc(o.uom)}${o.qoe ? ` (QOE ${fmtNumber(o.qoe)})` : ''}</span>
          <span>${esc(o.sub_label)}</span><span class="text-muted">from ${esc(o.vendor)}${many ? ` for ${esc(o.medline_item)}` : ''}</span>
          ${o.voided_at ? `<span class="badge text-bg-secondary">Voided</span>` : ''}
        </div>
        <div class="text-muted">Ordered ${fmtDateTime(o.ordered_dt)} by ${esc(o.ordered_by)}${o.voided_at ? ` · voided by ${esc(o.voided_by)}: ${esc(o.void_reason)}` : ''}</div>
        ${o.latest_comment ? `<div class="border-start border-3 ps-2 my-1">${esc(o.latest_comment.actor)}: ${esc(o.latest_comment.comment)}</div>` : ''}
        <div class="d-flex flex-wrap gap-2 mt-1">${actions.join('')}</div>
        ${commentBox}
        <div class="fk-history mt-2" id="fk-history-order-${o.order_id}"></div>
      </div></div>`;
    }).join('');
  }

  // Panel events ----

  async function act(path, payload, done) {
    try {
      await postJSON(path, payload);
      await afterChange(done);
    } catch (error) {
      // 409: someone changed it meanwhile; the reloaded panel shows the latest next to the message.
      await loadPanel({ text: error.message, kind: error.status === 409 ? 'warning' : 'danger' });
    }
  }

  async function afterChange(message) {
    await Promise.all([loadPanel(message ? { text: message, kind: 'success' } : null), loadMain(), loadLibrary(), loadOrders()]);
  }

  panelEl.addEventListener('click', async (event) => {
    const tab = event.target.closest('[data-panel-tab]');
    if (tab) {
      state.panelTab = tab.dataset.panelTab;
      renderPanel();
      return;
    }
    // One Medline item, or (empty) the whole Infor item: the data is already here.
    const focus = event.target.closest('[data-panel-focus]');
    if (focus) {
      if (focus.dataset.panelFocus) {
        state.panelItem = focus.dataset.panelFocus;
        state.panelScope = 'medline';
      } else {
        state.panelScope = 'infor';
      }
      renderPanel();
      return;
    }
    const contract = event.target.closest('[data-contract]');
    if (contract) {
      fillFromContract(state.contractLines[Number(contract.dataset.contract)]);
      return;
    }
    const button = event.target.closest('button[data-act]');
    if (!button) return;
    const { act: what } = button.dataset;
    const subId = Number(button.dataset.sub);
    if (what === 'show-add') { $('fk-add-sub').classList.remove('d-none'); $('fk-contract-q').focus(); return; }
    if (what === 'hide-add') { $('fk-add-sub').classList.add('d-none'); return; }
    if (what === 'pick' || what === 'unpick') {
      await act(subUrl(subId, what), { expected_status: button.dataset.expected }, what === 'pick' ? 'Picked.' : 'Unpicked.');
      return;
    }
    if (what === 'order') { openOrderForm(subId, button.dataset.item); return; }
    if (what === 'copy-sub') {
      const target = button.dataset.item;
      const pack = state.panelData.packagings.find((p) => p.medline_item === target);
      const o = pack && pack.other_subs.find((x) => x.sub_id === subId);
      if (!o) return;
      await act(api.addSub, {
        medline_item: target, vendor: o.vendor, vendor_part: o.vendor_part, description: o.description || '',
        uom: o.uom || '', qoe: o.qoe != null ? String(o.qoe) : '',
        comment: `Added from ${o.medline_item}${o.um ? ` (${o.um})` : ''}, where it is ${config.statusLabels[o.status]}.`,
      }, `Sub added to ${target} from the other UOM. It is pending review there.`);
      return;
    }
    if (what === 'edit-sub') { openSubEditForm(panelSubs().find((s) => s.sub_id === subId)); return; }
    if (what === 'delete-sub') { openSubDeleteForm(panelSubs().find((s) => s.sub_id === subId)); return; }
    if (what === 'edit-order') { openOrderEditForm(state.panelData.orders.find((o) => o.order_id === Number(button.dataset.order))); return; }
    if (what === 'void-order') { openVoidForm(Number(button.dataset.order)); return; }
    if (what === 'history') {
      const target = $(`fk-history-${button.dataset.entity}-${button.dataset.id}`);
      if (target.innerHTML) { target.innerHTML = ''; return; }
      target.innerHTML = '<span class="text-muted">Loading…</span>';
      try {
        const data = await getJSON(historyUrl(button.dataset.entity, button.dataset.id));
        target.innerHTML = timeline(data.history, false);
      } catch (error) {
        target.innerHTML = alertBox(error.message);
      }
    }
  });

  panelEl.addEventListener('change', async (event) => {
    const select = event.target.closest('select[data-act="status"]');
    if (!select || !select.value) return;
    await act(subUrl(select.dataset.sub, 'status'), { status: select.value, expected_status: select.dataset.expected },
      `Status set to ${config.statusLabels[select.value]}.`);
  });

  panelEl.addEventListener('input', (event) => {
    if (event.target.id === 'fk-contract-q') searchContracts(event.target.value);
    vendorInput(event.target);
  });

  // An optional vendor ID box (data-vendor-name names its vendor name box) is checked against
  // Infor as it's typed. Infor's name goes into the name box when that is empty or was filled in
  // for the Sub Finder (from a contract line or an earlier ID); a name they typed stays.
  function vendorInput(target) {
    if (target.dataset.vendorName) lookupVendor(target);
    else if (target.name === 'vendor') delete target.dataset.autofilled;
  }

  function vendorNote(input, text, problem) {
    const note = $(`${input.id}-note`);
    input.classList.toggle('is-invalid', Boolean(problem));
    if (note) {
      note.textContent = text || '';
      note.classList.toggle('text-danger', Boolean(problem));
    }
  }

  const lookupVendor = debounce(async (input) => {
    const nameBox = $(input.dataset.vendorName);
    const id = input.value.trim();
    if (!id) { vendorNote(input, ''); return; }
    if (!/^\d+$/.test(id)) { vendorNote(input, "Infor's vendor ID is digits only", true); return; }
    try {
      const data = await getJSON(api.vendor, { id });
      if (input.value.trim() !== id) return;  // typed on meanwhile
      const vendor = data.vendor;
      if (!vendor) { vendorNote(input, "Not in Infor's vendor list", true); return; }
      const status = vendor.vendor_status && vendor.vendor_status !== 'Active' ? ` (${vendor.vendor_status})` : '';
      vendorNote(input, `Infor: ${vendor.vendor_name}${status}`);
      if (nameBox && (!nameBox.value.trim() || nameBox.dataset.autofilled)) {
        nameBox.value = vendor.vendor_name || '';
        nameBox.dataset.autofilled = '1';
      }
    } catch (error) {
      vendorNote(input, error.message, true);
    }
  }, 300);

  panelEl.addEventListener('submit', async (event) => {
    const form = event.target;
    event.preventDefault();
    if (form.id === 'fk-add-form') {
      const payload = Object.fromEntries(new FormData(form).entries());
      payload.medline_item = payload.medline_item || state.panelItem;  // the UOM chosen, if several
      await act(api.addSub, payload, 'Sub added. It is pending review.');
      return;
    }
    const comment = form.elements.comment ? form.elements.comment.value.trim() : '';
    if (!comment) return;
    if (form.dataset.act === 'comment-sub') await act(subUrl(form.dataset.sub, 'comments'), { comment }, 'Comment added.');
    if (form.dataset.act === 'comment-order') await act(orderUrl(form.dataset.order, 'comments'), { comment }, 'Comment added.');
  });

  // --- forms in the modal: record, correct and void orders; correct a sub ----------------------

  const modalEl = $('fk-modal');
  const modal = window.bootstrap ? window.bootstrap.Modal.getOrCreateInstance(modalEl) : null;
  const modalForm = $('fk-modal-form');
  let modalSubmit = null;
  // Bootstrap ignores show() while the modal fades out and hide() while it fades in, so a quick
  // "save, then open the next form" would be lost. Track the fade and wait for it to finish.
  let modalPhase = 'hidden';  // hidden | showing | shown | hiding
  modalEl.addEventListener('show.bs.modal', () => { modalPhase = 'showing'; });
  modalEl.addEventListener('shown.bs.modal', () => { modalPhase = 'shown'; });
  modalEl.addEventListener('hide.bs.modal', () => { modalPhase = 'hiding'; });
  modalEl.addEventListener('hidden.bs.modal', () => { modalPhase = 'hidden'; });

  function whenModal(phase, action) {
    if (modalPhase === phase) action();
    else modalEl.addEventListener(`${phase}.bs.modal`, action, { once: true });
  }

  function openModal() {
    if (!modal || modalPhase === 'shown' || modalPhase === 'showing') return;
    whenModal('hidden', () => modal.show());
  }

  function hideModal() {
    if (!modal || modalPhase === 'hidden' || modalPhase === 'hiding') return;
    whenModal('shown', () => modal.hide());
  }

  function showModal(title, fields, submitLabel, onSubmit) {
    modalForm.innerHTML = `
      <div class="modal-header"><h2 class="modal-title h5" id="fk-modal-title">${title}</h2>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>
      <div class="modal-body"><div id="fk-modal-message"></div><div class="row g-2">${fields}</div></div>
      <div class="modal-footer"><button type="button" class="btn btn-sm btn-link" data-bs-dismiss="modal">Cancel</button>
        <button type="submit" class="btn btn-sm btn-primary">${submitLabel}</button></div>`;
    modalSubmit = onSubmit;
    openModal();
  }

  modalForm.addEventListener('input', (event) => vendorInput(event.target));

  modalForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!modalSubmit) return;
    const values = Object.fromEntries(new FormData(modalForm).entries());
    try {
      const message = await modalSubmit(values);
      hideModal();
      await afterChange(message);
    } catch (error) {
      $('fk-modal-message').innerHTML = alertBox(error.message, error.status === 409 ? 'warning' : 'danger');
    }
  });

  const field = (name, label, value, attrs, col) => `
    <div class="col-${col || 6}"><label class="form-label small mb-0" for="fk-m-${name}">${label}</label>
      <input class="form-control form-control-sm" id="fk-m-${name}" name="${name}" value="${esc(value == null ? '' : value)}" ${attrs || ''}></div>`;

  function nowLocal() {
    const d = new Date();
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 16);
  }

  // A pick from the panel (any UOM) or from the main table.
  function findSub(subId) {
    return panelSubs().concat(...state.rows.map((row) => row.picks)).find((s) => s.sub_id === subId) || null;
  }

  function openOrderForm(subId, item) {
    const sub = findSub(subId);
    if (!sub) return;
    const medline = sub.medline_item || item;
    const row = state.rows.find((r) => r.medline_items.includes(medline));
    const pack = row ? row.packagings.find((p) => p.medline_item === medline) : null;
    const killed = pack && pack.quantities.length === 1 ? pack.quantities[0].killed : '';
    // Materials Managers may order for the whole Infor item: its UOMs added up in eaches.
    const combined = row && row.packagings.length > 1 && row.quantities_each
      ? `<div class="col-12 small text-muted">All ${row.packagings.length} UOMs of Infor item ${esc(row.infor_item)} killed
          ${fmtNumber(row.quantities_each.killed)} EA in these dates${sub.qoe ? ` (${fmtNumber(row.quantities_each.killed / sub.qoe)} ×
          ${esc(sub.uom || 'unit')} of ${fmtNumber(sub.qoe)})` : ''}.</div>` : '';
    showModal(`Record an order · ${esc(medline)}`, `
      <div class="col-12 small text-muted">Pick: <span class="fw-semibold">${esc(sub.vendor_part)}</span> · ${esc(vendorText(sub))}
        ${killed ? ` · ${esc(medline)} killed in these dates: ${fmtNumber(killed)} ${esc(pack.quantities[0].uom)}` : ''}</div>${combined}
      ${field('quantity', 'Quantity *', killed, 'type="number" min="1" step="1" required', 4)}
      ${field('uom', 'UOM *', sub.uom, 'maxlength="10" required', 4)}
      ${field('qoe', 'QOE', sub.qoe != null ? fmtNumber(sub.qoe).replace(/,/g, '') : '', 'inputmode="decimal"', 4)}
      ${field('vendor', 'Vendor', sub.vendor, 'maxlength="255"', 6)}
      ${field('ordered_dt', 'Ordered', nowLocal(), 'type="datetime-local"', 6)}
      ${field('comment', 'Comment', '', 'maxlength="400"', 12)}`,
    'Record order', (values) => postJSON(api.recordOrder, Object.assign(values, { sub_id: subId, expected_status: 'approved' }))
      .then(() => 'Order recorded.'));
  }

  function openOrderEditForm(order) {
    if (!order) return;
    showModal(`Correct an order · ${esc(order.sub_label)}`, `
      ${field('quantity', 'Quantity', order.quantity, 'type="number" min="1" step="1"', 4)}
      ${field('uom', 'UOM', order.uom, 'maxlength="10"', 4)}
      ${field('qoe', 'QOE', order.qoe != null ? fmtNumber(order.qoe).replace(/,/g, '') : '', 'inputmode="decimal"', 4)}
      ${field('vendor', 'Vendor', order.vendor, 'maxlength="255"', 6)}
      ${field('ordered_dt', 'Ordered', String(order.ordered_dt || '').slice(0, 16), 'type="datetime-local"', 6)}`,
    'Save correction', (values) => postJSON(orderUrl(order.order_id, 'edit'), values).then(() => 'Order corrected.'));
  }

  // Deleting a sub needs a reason; the sub's row and history stay.
  function openSubDeleteForm(sub) {
    if (!sub) return;
    showModal(`Delete a sub · ${esc(sub.vendor_part)}`, `
      <div class="col-12 small text-muted">${esc(vendorText(sub))} on ${esc(sub.medline_item)}. It leaves the item and the
        library; who deleted it, when and why stay in its history.</div>
      ${field('reason', 'Why? *', '', 'maxlength="400" required', 12)}`,
    'Delete sub', (values) => postJSON(subUrl(sub.sub_id, 'delete'), { reason: values.reason, expected_status: sub.status })
      .then(() => 'Sub deleted.'));
  }

  function openVoidForm(orderId) {
    showModal('Void an order', field('reason', 'Why? *', '', 'maxlength="400" required', 12),
      'Void order', (values) => postJSON(orderUrl(orderId, 'void'), values).then(() => 'Order voided.'));
  }

  function openSubEditForm(sub) {
    if (!sub) return;
    const locked = sub.status !== 'pending_review';
    const lockNote = locked ? '<div class="col-12 small text-muted">Vendor, vendor ID and vendor part are fixed once the sub has been reviewed.</div>' : '';
    showModal(`Correct a sub · ${esc(sub.vendor_part)}`, `${lockNote}
      ${locked ? '' : `<div class="col-4"><label class="form-label small mb-0" for="fk-m-vendor_id">Vendor ID</label>
        <input class="form-control form-control-sm" id="fk-m-vendor_id" name="vendor_id" value="${esc(sub.vendor_id || '')}"
               maxlength="20" inputmode="numeric" placeholder="Optional" data-vendor-name="fk-m-vendor">
        <div class="form-text small mt-0" id="fk-m-vendor_id-note"></div></div>`}
      ${locked ? '' : field('vendor', 'Vendor name *', sub.vendor, 'maxlength="255" required', 8)}
      ${locked ? '' : field('vendor_part', 'Vendor part *', sub.vendor_part, 'maxlength="100" required', 6)}
      ${field('description', 'Description', sub.description, 'maxlength="255"', 12)}
      ${field('uom', 'UOM', sub.uom, 'maxlength="10"', 6)}
      ${field('qoe', 'QOE', sub.qoe != null ? fmtNumber(sub.qoe).replace(/,/g, '') : '', 'inputmode="decimal"', 6)}`,
    'Save correction', (values) => postJSON(subUrl(sub.sub_id, 'edit'), values).then(() => 'Sub corrected.'));
  }

  // --- the tables under the main table ------------------------------------------------------------

  function setupLibrary() {
    const status = $('fk-lib-status');
    status.innerHTML += config.statuses
      .map(([key, label]) => `<option value="${key}">${esc(label)}</option>`).join('');
    status.addEventListener('change', loadLibrary);
    $('fk-lib-source').addEventListener('change', loadLibrary);
    $('fk-lib-q').addEventListener('input', debounce(loadLibrary, 300));
    $('fk-lib-rows').addEventListener('click', (event) => {
      const opener = event.target.closest('[data-open]');
      if (opener) openPanel(opener.dataset.open, 'subs');
    });
    $('fk-orders-rows').addEventListener('click', (event) => {
      const opener = event.target.closest('[data-open]');
      if (opener) openPanel(opener.dataset.open, 'orders');
    });
  }

  async function loadLibrary() {
    const body = $('fk-lib-rows');
    try {
      const data = await getJSON(api.subs, { status: $('fk-lib-status').value, source: $('fk-lib-source').value, q: $('fk-lib-q').value.trim() });
      body.innerHTML = data.subs.length ? data.subs.map((s) => `<tr>
          <td><button type="button" class="btn btn-link p-0" data-open="${esc(s.medline_item)}">${esc(s.medline_item)}</button></td>
          <td>${esc(s.vendor)}${s.vendor_id ? `<div class="small text-muted">${esc(s.vendor_id)}</div>` : ''}</td>
          <td class="fw-semibold">${esc(s.vendor_part)}</td>
          <td class="small">${esc(s.description)}</td>
          <td>${statusBadge(s.status)}${s.is_picked ? ' <span class="badge text-bg-success">Picked</span>' : ''}</td>
          <td class="small">${s.source === 'medline_pbo' ? 'Medline PBO' : esc(s.entered_by)}</td>
          <td class="small text-nowrap">${fmtDateTime(s.update_dt)}</td>
          <td class="small">${s.latest_comment ? esc(s.latest_comment.comment) : ''}</td>
        </tr>`).join('')
        : '<tr><td colspan="8" class="text-muted small">No subs match.</td></tr>';
    } catch (error) {
      body.innerHTML = `<tr><td colspan="8">${alertBox(error.message)}</td></tr>`;
    }
  }

  async function loadOrders() {
    const body = $('fk-orders-rows');
    try {
      const data = await getJSON(api.orders, scopeParams());
      body.innerHTML = data.orders.length ? data.orders.map((o) => `<tr class="${o.voided_at ? 'text-muted' : ''}">
          <td class="small text-nowrap">${fmtDateTime(o.ordered_dt)}</td>
          <td><button type="button" class="btn btn-link p-0" data-open="${esc(o.medline_item)}">${esc(o.medline_item)}</button></td>
          <td>${esc(o.sub_label)}</td>
          <td class="text-end ${o.voided_at ? 'text-decoration-line-through' : ''}">${fmtNumber(o.quantity)} ${esc(o.uom)}</td>
          <td class="small">${esc(o.vendor)}</td>
          <td class="small">${esc(o.ordered_by)}${o.voided_at ? ' <span class="badge text-bg-secondary">Voided</span>' : ''}</td>
          <td class="small">${o.latest_comment ? esc(o.latest_comment.comment) : ''}</td>
        </tr>`).join('')
        : '<tr><td colspan="7" class="text-muted small">No orders recorded with an ordered date in these dates.</td></tr>';
    } catch (error) {
      body.innerHTML = `<tr><td colspan="7">${alertBox(error.message)}</td></tr>`;
    }
  }

  // --- start ---------------------------------------------------------------------------------------

  function reloadAll() {
    loadMain();
    loadOrders();
    if (state.panelItem && panelEl.classList.contains('show')) loadPanel();
  }

  panelEl.addEventListener('hidden.bs.offcanvas', () => {
    state.panelItem = null;
    state.panelData = null;
  });

  setupDates();
  setupSites();
  setupSearch();
  setupLibrary();
  renderNeeds();
  loadMain();
  loadLibrary();
  loadOrders();
})();
