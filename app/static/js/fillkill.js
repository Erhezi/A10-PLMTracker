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
    rows: [],
    counts: {},
    panelItem: null,
    panelTab: 'subs',
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

  function alertBox(message, kind) {
    return `<div class="alert alert-${kind || 'danger'} py-2 small mb-2" role="alert">${esc(message)}</div>`;
  }

  // --- controls: dates, sites, search, needs ----------------------------------------------

  const DAY = 24 * 60 * 60 * 1000;
  const toDay = (iso) => Math.round(Date.parse(`${iso}T00:00:00Z`) / DAY);
  const fromDay = (n) => new Date(n * DAY).toISOString().slice(0, 10);
  let slider = null;

  function setupDates() {
    const startInput = $('fk-start');
    const endInput = $('fk-end');
    const first = config.bounds && config.bounds.first;
    const last = config.bounds && config.bounds.last;
    startInput.value = state.start || '';
    endInput.value = state.end || '';
    if (first) { startInput.min = first; endInput.min = first; }
    if (last) { startInput.max = last; endInput.max = last; }

    const sliderEl = $('fk-date-slider');
    if (window.noUiSlider && first && last && first !== last) {
      slider = window.noUiSlider.create(sliderEl, {
        start: [toDay(state.start || first), toDay(state.end || last)],
        connect: true,
        step: 1,
        range: { min: toDay(first), max: toDay(last) },
        tooltips: [{ to: (v) => fmtDate(fromDay(Math.round(v))) }, { to: (v) => fmtDate(fromDay(Math.round(v))) }],
      });
      slider.on('change', (values) => {
        state.start = fromDay(Math.round(values[0]));
        state.end = fromDay(Math.round(values[1]));
        startInput.value = state.start;
        endInput.value = state.end;
        reloadAll();
      });
    } else {
      sliderEl.classList.add('d-none');  // the date boxes still work
    }

    const fromInputs = () => {
      if (!startInput.value || !endInput.value) return;
      [state.start, state.end] = startInput.value <= endInput.value
        ? [startInput.value, endInput.value] : [endInput.value, startInput.value];
      if (slider) slider.set([toDay(state.start), toDay(state.end)], false);
      reloadAll();
    };
    startInput.addEventListener('change', fromInputs);
    endInput.addEventListener('change', fromInputs);
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
      $('fk-rows').innerHTML = `<tr><td colspan="11" class="p-3">${alertBox(error.message)}</td></tr>`;
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

  // Every word must appear in one of these (commodity code and its description are searchable
  // but not shown in the table). Item numbers also match without their dashes, spaces, dots and
  // slashes, so "BD930" finds B-D930299Z.
  const SEARCHED = ['customer_item', 'medline_item', 'description', 'infor_item', 'long_description',
    'commodity_code', 'commodity_description'];
  const ITEM_NUMBERS = ['customer_item', 'medline_item', 'infor_item'];
  const compact = (value) => String(value || '').toLowerCase().replace(/[\s\-./]/g, '');

  function matchesSearch(row) {
    if (!state.search) return true;
    // Joined with spaces: a word has none, so it can't match across two fields.
    const text = SEARCHED.map((key) => String(row[key] || '').toLowerCase()).join(' ');
    const numbers = ITEM_NUMBERS.map((key) => compact(row[key])).join(' ');
    return state.search.split(/\s+/).every((word) => text.includes(word) || (compact(word) && numbers.includes(compact(word))));
  }

  function subsStatusCell(row) {
    const parts = STATUS_ORDER.filter((s) => row.subs_status[s])
      .map((s) => `${statusBadge(s)} <span class="small">${row.subs_status[s]}</span>`);
    return parts.length ? `<div class="d-flex flex-wrap gap-1 align-items-center">${parts.join(' ')}</div>`
      : '<span class="text-muted small">No subs</span>';
  }

  function picksCell(row) {
    if (!row.picks.length) return '<span class="text-muted small">—</span>';
    return row.picks.map((pick) => {
      const label = `${esc(pick.vendor_part)} <span class="text-muted">· ${esc(pick.vendor)}</span>`;
      return can.order
        ? `<button type="button" class="btn btn-sm btn-outline-primary py-0 mb-1 text-start" data-order-sub="${pick.sub_id}"
             data-item="${esc(row.medline_item)}" title="Record an order for this pick">${label}</button>`
        : `<div class="small">${label}</div>`;
    }).join('');
  }

  function reasonCell(reason) {
    if (!reason) return '<span class="text-muted small">—</span>';
    const date = reason.reason_date ? ` <span class="text-muted">${fmtDate(reason.reason_date)}</span>` : '';
    return `<div class="small" title="${esc(reason.comment)}"><span class="badge text-bg-light border">`
      + `${esc(REASON_LABEL[reason.reason] || reason.reason)}</span>${date}</div>`;
  }

  function renderRows() {
    const rows = state.rows.filter((row) => (state.needs === 'all' || row.needs.includes(state.needs)) && matchesSearch(row));
    if (!rows.length) {
      const why = state.rows.length ? 'No item matches these filters.' : 'No kill lines for these dates and sites.';
      $('fk-rows').innerHTML = `<tr><td colspan="11" class="text-muted small p-3">${why}</td></tr>`;
      return;
    }
    $('fk-rows').innerHTML = rows.map((row) => {
      const flag = row.infor_consistent === false
        ? ` <i class="bi bi-exclamation-triangle-fill text-warning" title="Differs from Infor, or not found in Infor's vendor items"></i>` : '';
      const infor = row.infor_item && row.infor_item !== row.customer_item
        ? `<div class="small text-muted">${esc(row.infor_item)}</div>` : '';
      const varies = row.varies.length ? ` <span class="badge text-bg-light border" title="Medline's lines or Infor disagree on: ${esc(row.varies.join(', '))}">varies</span>` : '';
      const inactive = row.infor_active && row.infor_active !== 'Yes'
        ? ' <span class="badge text-bg-secondary" title="The Infor item is not active">Inactive</span>' : '';
      const inforDesc = row.long_description
        ? `<div class="text-truncate small text-muted" title="Infor: ${esc(row.long_description)}">${esc(row.long_description)}</div>` : '';
      return `<tr>
        <td><button type="button" class="btn btn-link p-0 fw-semibold" data-open="${esc(row.medline_item)}">${esc(row.customer_item || '—')}</button>${flag}${inactive}${infor}</td>
        <td><button type="button" class="btn btn-link p-0" data-open="${esc(row.medline_item)}">${esc(row.medline_item)}</button>${varies}</td>
        <td class="fk-desc"><div class="text-truncate" title="${esc(row.description)}">${esc(row.description)}</div>${inforDesc}</td>
        <td class="text-end">${qtyLines(row.quantities, 'ordered')}</td>
        <td class="text-end fw-semibold">${qtyLines(row.quantities, 'killed')}</td>
        <td class="text-end">${qtyLines(row.quantities, 'filled')}</td>
        <td class="text-end">${fmtNumber(row.lines)}</td>
        <td>${reasonCell(row.latest_reason)}</td>
        <td role="button" data-open="${esc(row.medline_item)}">${subsStatusCell(row)}</td>
        <td>${picksCell(row)}</td>
        <td>${row.ordering_status === 'ordered' ? '<span class="badge text-bg-success">Ordered</span>' : '<span class="badge text-bg-light border">No order</span>'}</td>
      </tr>`;
    }).join('');
  }

  $('fk-rows').addEventListener('click', (event) => {
    const orderButton = event.target.closest('[data-order-sub]');
    if (orderButton) {
      openOrderForm(Number(orderButton.dataset.orderSub), orderButton.dataset.item);
      return;
    }
    const opener = event.target.closest('[data-open]');
    if (opener) openPanel(opener.dataset.open);
  });

  // --- the item panel -------------------------------------------------------------------------

  const panelEl = $('fk-panel');
  const panel = window.bootstrap ? window.bootstrap.Offcanvas.getOrCreateInstance(panelEl) : null;

  async function openPanel(item, tab) {
    state.panelItem = item;
    if (tab) state.panelTab = tab;
    $('fk-panel-title').textContent = item;
    $('fk-panel-subtitle').textContent = '';
    $('fk-panel-body').innerHTML = '<div class="text-muted small">Loading…</div>';
    if (panel) panel.show();
    await loadPanel();
  }

  async function loadPanel(message) {
    const item = state.panelItem;
    if (!item) return;
    try {
      const data = await getJSON(api.item, Object.assign({ item }, scopeParams()));
      if (item !== state.panelItem) return;
      state.panelData = data;
      renderPanel(message);
    } catch (error) {
      $('fk-panel-body').innerHTML = alertBox(error.message);
    }
  }

  function renderPanel(message) {
    const data = state.panelData;
    const d = data.details || {};
    const reason = data.latest_reason;
    $('fk-panel-subtitle').innerHTML = [
      esc(d.description || ''),
      d.customer_item ? `Customer item ${esc(d.customer_item)}` : '',
      reason ? esc(reason.comment) : '',
    ].filter(Boolean).join(' · ');

    const tabs = [
      ['subs', `Subs <span class="badge text-bg-light">${data.subs.length}</span>`],
      ['lines', `Kill lines <span class="badge text-bg-light">${data.lines.length}</span>`],
      ['picks', 'Pick history'],
      ['orders', `Orders <span class="badge text-bg-light">${data.orders.length}</span>`],
    ];
    $('fk-panel-body').innerHTML = `
      ${message ? alertBox(message.text, message.kind) : ''}
      ${itemDetails(d)}
      <ul class="nav nav-pills nav-fill small mb-3" role="tablist">
        ${tabs.map(([key, label]) => `<li class="nav-item"><button type="button" class="nav-link py-1 ${state.panelTab === key ? 'active' : ''}"
            data-panel-tab="${key}">${label}</button></li>`).join('')}
      </ul>
      <div id="fk-panel-content">${renderPanelTab(state.panelTab)}</div>`;
  }

  function itemDetails(d) {
    const rows = [
      ['Infor item', [d.infor_item || d.customer_item, d.infor_active ? (d.infor_active === 'Yes' ? 'Active' : 'Inactive') : '']
        .filter(Boolean).join(' · ')],
      ['Long description', d.long_description],
      ['Commodity', [d.commodity_code, d.commodity_description].filter(Boolean).join(' · ')],
      ['Manufacturer', [d.manufacturer, d.mfr_item].filter(Boolean).join(' · ')],
    ].filter(([, value]) => value);
    if (!rows.length) return '';
    return `<dl class="row small bg-light border rounded py-2 mx-0 mb-3">${rows.map(([label, value]) => `
      <dt class="col-sm-4 text-muted fw-normal">${esc(label)}</dt><dd class="col-sm-8 mb-1">${esc(value)}</dd>`).join('')}</dl>`;
  }

  function renderPanelTab(tab) {
    const data = state.panelData;
    if (tab === 'lines') return linesTab(data.lines);
    if (tab === 'picks') return picksTab(data.pick_history);
    if (tab === 'orders') return ordersTab(data.orders);
    return subsTab(data.subs);
  }

  // Subs ----

  function subsTab(subs) {
    const add = can.add_sub ? `
      <div class="mb-3">
        <button type="button" class="btn btn-sm btn-primary" data-act="show-add"><i class="bi bi-plus-lg"></i> Add sub</button>
        <div id="fk-add-sub" class="d-none mt-2">${addSubForm()}</div>
      </div>` : '';
    if (!subs.length) return `${add}<p class="text-muted small">No subs yet for this item.</p>`;
    return add + subs.map(subCard).join('');
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
      actions.push(`<button type="button" class="btn btn-sm btn-primary" data-act="order" data-sub="${sub.sub_id}">Record order</button>`);
    }
    if (can.add_sub) {
      actions.push(`<button type="button" class="btn btn-sm btn-outline-secondary" data-act="edit-sub" data-sub="${sub.sub_id}">Edit</button>`);
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
          <span class="fw-semibold">${esc(sub.vendor_part)}</span><span class="text-muted">${esc(sub.vendor)}</span>
          ${statusBadge(sub.status)}${sub.is_picked ? ' <span class="badge text-bg-success"><i class="bi bi-check2"></i> Picked</span>' : ''}
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

  function addSubForm() {
    return `
      <div class="border rounded p-2 bg-light">
        <label class="form-label small mb-1" for="fk-contract-q">Search Infor's active contracts</label>
        <input type="search" class="form-control form-control-sm mb-2" id="fk-contract-q" autocomplete="off"
               placeholder="Vendor item, manufacturer number, or description words">
        <div id="fk-contract-results" class="small mb-2"></div>
        <form id="fk-add-form" class="row g-2" novalidate>
          <div class="col-6"><label class="form-label small mb-0" for="fk-add-vendor">Vendor *</label>
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
      box.innerHTML = `<div class="list-group">${data.lines.map((line, i) => `
        <button type="button" class="list-group-item list-group-item-action py-1" data-contract="${i}">
          <span class="fw-semibold">${esc(line.vendor_item)}</span> · ${esc(line.vendor_name)}
          <span class="text-muted">· ${esc(line.uom)}${line.qoe ? ` × ${fmtNumber(line.qoe)}` : ''}${line.contracts > 1 ? ` · ${line.contracts} contracts` : ''}</span>
          <div class="text-muted text-truncate">${esc(line.description)}</div>
        </button>`).join('')}</div>`;
    } catch (error) {
      box.innerHTML = alertBox(error.message);
    }
  }, 350);

  function fillFromContract(line) {
    $('fk-add-vendor').value = line.vendor_name || '';
    $('fk-add-part').value = line.vendor_item || '';
    $('fk-add-desc').value = line.description || '';
    $('fk-add-uom').value = line.uom || '';
    $('fk-add-qoe').value = line.qoe != null ? fmtNumber(line.qoe).replace(/,/g, '') : '';
  }

  // Kill lines, pick history, orders ----

  function linesTab(lines) {
    if (!lines.length) return '<p class="text-muted small">No kill lines for these dates and sites.</p>';
    return `<div class="table-responsive"><table class="table table-sm small align-middle">
      <thead class="table-light"><tr><th>Ordered</th><th>Site · Dept</th><th>PO</th><th class="text-end">Killed</th><th>Reason</th></tr></thead>
      <tbody>${lines.map((l) => `<tr>
        <td class="text-nowrap">${fmtDate(l.order_date)} ${esc(String(l.order_time || '').slice(0, 5))}</td>
        <td>${esc(l.site)}${l.is_test ? ' <span class="badge text-bg-warning">test</span>' : ''}<div class="text-muted">${esc(l.department)}</div></td>
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
      default: return esc(h.action);
    }
  }

  function timeline(entries, withLabel) {
    if (!entries.length) return '<p class="text-muted small">Nothing yet.</p>';
    return `<ul class="list-unstyled small mb-0 fk-timeline">${entries.map((h) => `
      <li class="mb-1"><span class="text-muted text-nowrap">${fmtDateTime(h.acted_at)}</span> ·
        ${esc(h.actor)}${withLabel && h.label ? ` · <span class="fw-semibold">${esc(h.label)}</span>` : ''} · ${describe(h)}</li>`).join('')}</ul>`;
  }

  function picksTab(history) {
    return `<p class="small text-muted mb-2">Every sub added, reviewed, picked and unpicked for this item, newest first.</p>
      ${timeline(history, true)}`;
  }

  function ordersTab(orders) {
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
          <span>${esc(o.sub_label)}</span><span class="text-muted">from ${esc(o.vendor)}</span>
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
    if (what === 'order') { openOrderForm(subId, state.panelItem); return; }
    if (what === 'edit-sub') { openSubEditForm(state.panelData.subs.find((s) => s.sub_id === subId)); return; }
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
  });

  panelEl.addEventListener('submit', async (event) => {
    const form = event.target;
    event.preventDefault();
    if (form.id === 'fk-add-form') {
      const payload = Object.fromEntries(new FormData(form).entries());
      payload.medline_item = state.panelItem;
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

  async function findSub(subId, item) {
    if (state.panelData && state.panelItem === item) {
      const sub = state.panelData.subs.find((s) => s.sub_id === subId);
      if (sub) return sub;
    }
    const row = state.rows.find((r) => r.medline_item === item);
    return row ? row.picks.find((p) => p.sub_id === subId) : null;
  }

  async function openOrderForm(subId, item) {
    const sub = await findSub(subId, item);
    if (!sub) return;
    const row = state.rows.find((r) => r.medline_item === item);
    const killed = row && row.quantities.length === 1 ? row.quantities[0].killed : '';
    showModal(`Record an order · ${esc(item)}`, `
      <div class="col-12 small text-muted">Pick: <span class="fw-semibold">${esc(sub.vendor_part)}</span> · ${esc(sub.vendor)}
        ${killed ? ` · killed in these dates: ${fmtNumber(killed)} ${esc(row.quantities[0].uom)}` : ''}</div>
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

  function openVoidForm(orderId) {
    showModal('Void an order', field('reason', 'Why? *', '', 'maxlength="400" required', 12),
      'Void order', (values) => postJSON(orderUrl(orderId, 'void'), values).then(() => 'Order voided.'));
  }

  function openSubEditForm(sub) {
    if (!sub) return;
    const locked = sub.status !== 'pending_review';
    const lockNote = locked ? '<div class="col-12 small text-muted">Vendor and vendor part are fixed once the sub has been reviewed.</div>' : '';
    showModal(`Correct a sub · ${esc(sub.vendor_part)}`, `${lockNote}
      ${locked ? '' : field('vendor', 'Vendor', sub.vendor, 'maxlength="255"', 6)}
      ${locked ? '' : field('vendor_part', 'Vendor part', sub.vendor_part, 'maxlength="100"', 6)}
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
          <td>${esc(s.vendor)}</td><td class="fw-semibold">${esc(s.vendor_part)}</td>
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
