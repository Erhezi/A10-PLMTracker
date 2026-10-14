/* Fill/Kill Dashboard (plan v2 §5.4): draws /fillkill/api/dashboard with Chart.js.
 * Chart.js is loaded with `defer` in base.html, so everything starts on DOMContentLoaded.
 */
document.addEventListener('DOMContentLoaded', () => {
  'use strict';

  const config = JSON.parse(document.getElementById('fk-config').textContent);
  const statusLabels = Object.fromEntries(config.statuses);
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
  const fmtDate = (iso) => {
    if (!iso) return '';
    const [y, m, d] = String(iso).slice(0, 10).split('-');
    return `${m}/${d}/${y}`;
  };
  const fmtDateTime = (iso) => (iso ? `${fmtDate(iso)} ${String(iso).slice(11, 16)}` : '');
  const REASON_LABEL = {
    ALLOCATION: 'Allocation', MBO: 'Manufacturer backorder', OUT_OF_STOCK: 'Out of stock',
    NONSTOCK_UOM: 'Non-stock UOM', NONSTOCK: 'Non-stock', DISCONTINUED: 'Discontinued', SPIKE: 'Spike', OTHER: 'Other',
  };
  const SOURCE_LABEL = { manual: 'Entered by a Sub Finder', medline_pbo: 'Medline PBO', llm: 'AI (future)' };
  const STATUS_COLOR = { approved: '#198754', hold: '#ffc107', pending_review: '#0dcaf0', rejected: '#dc3545' };
  const PALETTE = ['#003769', '#d6336c', '#2a9d8f', '#e9c46a', '#f4a261', '#6c757d', '#7b2cbf', '#0d6efd'];

  const state = { start: config.default.start, end: config.default.end, sites: [] };
  const charts = {};

  // --- controls --------------------------------------------------------------------------

  const startInput = $('fk-dash-start');
  const endInput = $('fk-dash-end');
  startInput.value = state.start || '';
  endInput.value = state.end || '';
  [startInput, endInput].forEach((input) => {
    if (config.bounds.first) input.min = config.bounds.first;
    if (config.bounds.last) input.max = config.bounds.last;
    input.addEventListener('change', () => {
      if (!startInput.value || !endInput.value) return;
      [state.start, state.end] = startInput.value <= endInput.value
        ? [startInput.value, endInput.value] : [endInput.value, startInput.value];
      load();
    });
  });

  document.querySelectorAll('[data-days]').forEach((button) => button.addEventListener('click', () => {
    const last = config.bounds.last;
    if (!last) return;
    if (button.dataset.days === 'all') {
      state.start = config.bounds.first;
    } else {
      const d = new Date(`${last}T00:00:00Z`);
      d.setUTCDate(d.getUTCDate() - Number(button.dataset.days) + 1);
      const start = d.toISOString().slice(0, 10);
      state.start = start < config.bounds.first ? config.bounds.first : start;
    }
    state.end = last;
    startInput.value = state.start;
    endInput.value = state.end;
    load();
  }));

  const menu = $('fk-dash-sites');
  menu.innerHTML = (config.sites || []).map((site, i) => `
    <div class="form-check">
      <input class="form-check-input" type="checkbox" value="${esc(site.code)}" id="fk-dash-site-${i}">
      <label class="form-check-label text-nowrap" for="fk-dash-site-${i}">${esc(site.name || site.code)}</label>
    </div>`).join('') || '<div class="small text-muted">No sites yet</div>';
  menu.addEventListener('change', () => {
    const boxes = Array.from(menu.querySelectorAll('input'));
    const picked = boxes.filter((b) => b.checked);
    state.sites = picked.map((b) => b.value);
    $('fk-dash-sites-button').textContent = !picked.length || picked.length === boxes.length ? 'All sites'
      : (picked.length === 1 ? picked[0].nextElementSibling.textContent : `${picked.length} sites`);
    load();
  });

  // --- drawing ------------------------------------------------------------------------------

  function draw(id, type, labels, datasets, options) {
    if (!window.Chart) return;
    if (charts[id]) charts[id].destroy();
    // Nothing to show: say so instead of drawing empty axes.
    const total = datasets.reduce((sum, d) => sum + d.data.reduce((a, b) => a + (Number(b) || 0), 0), 0);
    const box = $(id).parentElement;
    let note = box.querySelector('.fk-chart-note');
    if (!note) {
      note = document.createElement('div');
      note.className = 'fk-chart-note small text-muted position-absolute top-50 start-50 translate-middle';
      note.textContent = 'Nothing in these dates.';
      box.appendChild(note);
    }
    note.classList.toggle('d-none', total > 0);
    $(id).classList.toggle('invisible', total === 0);
    charts[id] = new window.Chart($(id), {
      type,
      data: { labels, datasets },
      options: Object.assign({ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }, options || {}),
    });
  }

  const stacked = { scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } } };

  function seriesDatasets(series, label) {
    return Object.entries(series).map(([name, values], i) => ({
      label: label(name), data: values, backgroundColor: PALETTE[i % PALETTE.length],
    }));
  }

  function headline(h) {
    const cards = [
      ['Items killed', h.items, ''],
      ['Kill lines', h.lines, ''],
      ['Items with an approved sub', h.items_with_approved_sub, h.share_with_approved_sub != null ? `${h.share_with_approved_sub}% of items` : ''],
      ['Items ordered', h.items_ordered, h.share_ordered != null ? `${h.share_ordered}% of items` : ''],
      ['Subs added', h.subs_added, ''],
      ['Median time to review', h.median_review_hours != null ? `${h.median_review_hours} h` : '—',
        h.subs_reviewed ? `${h.subs_reviewed} subs reviewed` : 'no subs reviewed yet'],
    ];
    $('fk-dash-headline').innerHTML = cards.map(([label, value, note]) => `
      <div class="col-6 col-md-4 col-xl-2"><div class="card shadow-sm border-0 h-100"><div class="card-body py-2">
        <div class="small text-muted">${esc(label)}</div>
        <div class="fs-4 fw-semibold">${esc(value)}</div>
        <div class="small text-muted">${esc(note)}</div>
      </div></div></div>`).join('');
  }

  function topItems(rows) {
    $('fk-dash-top').innerHTML = rows.length ? rows.map((row) => {
      const subs = Object.entries(row.subs_status).filter(([, n]) => n)
        .map(([s, n]) => `<span class="badge" style="background:${STATUS_COLOR[s]}">${esc(statusLabels[s])} ${n}</span>`).join(' ');
      // Several UOMs: their kills added up in eaches, when Infor converts every one.
      const killed = row.packagings.length > 1 && row.quantities_each
        ? `${Number(row.quantities_each.killed).toLocaleString()} EA`
        : row.packagings.flatMap((p) => p.quantities).map((q) => `${q.killed} ${esc(q.uom)}`).join('<br>');
      return `<tr>
        <td><a href="${esc(config.api.main)}" class="fw-semibold">${esc(row.infor_item || row.medline_items[0])}</a>
          <div class="small text-muted">${row.infor_item ? esc(row.medline_items.join(', ')) : 'Not in Infor'}</div></td>
        <td class="small">${esc(row.description)}</td>
        <td class="text-end">${row.lines}</td>
        <td class="text-end small">${killed}</td>
        <td>${subs || '<span class="small text-muted">No subs</span>'}</td>
        <td>${row.ordering_status === 'ordered' ? '<span class="badge text-bg-success">Ordered</span>' : '<span class="badge text-bg-light border">No order</span>'}</td>
      </tr>`;
    }).join('') : '<tr><td colspan="6" class="small text-muted">No kill lines for these dates and sites.</td></tr>';
  }

  function rejected(groups) {
    $('fk-dash-rejected').innerHTML = groups.length ? groups.map((g) => `
      <div class="mb-3">
        <div class="fw-semibold">${esc(g.vendor)} <span class="badge text-bg-danger">${g.count}</span></div>
        <ul class="list-unstyled small mb-0 ms-2">${g.subs.map((s) => `
          <li class="mb-1"><span class="fw-semibold">${esc(s.vendor_part)}</span> for ${esc(s.medline_item)}
            <span class="text-muted">· rejected${s.rejected_by ? ` by ${esc(s.rejected_by)}` : ''}${s.rejected_at ? ` ${fmtDateTime(s.rejected_at)}` : ''}</span>
            ${s.comments.map((c) => `<div class="border-start border-2 ps-2 text-muted">${esc(c.actor)}: ${esc(c.comment)}</div>`).join('')}
          </li>`).join('')}
        </ul>
      </div>`).join('') : '<p class="small text-muted mb-0">No rejected subs.</p>';
  }

  // --- loading -----------------------------------------------------------------------------

  let ticket = 0;

  async function load() {
    const mine = ++ticket;
    const params = new URLSearchParams({ start: state.start || '', end: state.end || '' });
    if (state.sites.length) params.set('sites', state.sites.join(','));
    try {
      const response = await window.appFetch(`${config.api.dashboard}?${params}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || `The server answered ${response.status}.`);
      if (mine !== ticket) return;
      $('fk-dash-error').innerHTML = '';
      $('fk-dash-range').textContent = `${fmtDate(data.scope.start)} to ${fmtDate(data.scope.end)}`;
      headline(data.headline);
      draw('fk-chart-reason', 'bar', data.by_reason.days.map(fmtDate),
        seriesDatasets(data.by_reason.series, (name) => REASON_LABEL[name] || name), stacked);
      draw('fk-chart-site', 'bar', data.by_site.days.map(fmtDate),
        seriesDatasets(data.by_site.series, (name) => name), stacked);
      const statuses = Object.keys(data.subs_by_status);
      draw('fk-chart-status', 'doughnut', statuses.map((s) => statusLabels[s] || s),
        [{ data: statuses.map((s) => data.subs_by_status[s]), backgroundColor: statuses.map((s) => STATUS_COLOR[s]) }]);
      draw('fk-chart-new-subs', 'bar', data.new_subs.weeks.map((w) => `Week of ${fmtDate(w)}`),
        seriesDatasets(data.new_subs.series, (name) => SOURCE_LABEL[name] || name), stacked);
      topItems(data.top_items);
      rejected(data.rejected);
    } catch (error) {
      if (mine !== ticket) return;
      $('fk-dash-error').innerHTML = `<div class="alert alert-danger py-2 small">${esc(error.message)}</div>`;
    }
  }

  load();
});
