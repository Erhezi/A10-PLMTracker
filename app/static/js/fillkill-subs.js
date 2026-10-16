/* Fill/Kill Subs page: every sub on file, from /fillkill/api/subs, with filters and a CSV export
 * of everything they match. Read-only: a row's Medline item opens that item's panel on Main, where
 * subs are changed.
 */
(function () {
  'use strict';

  const config = JSON.parse(document.getElementById('fk-config').textContent);
  const statusLabels = Object.fromEntries(config.statuses);
  const sourceLabels = Object.fromEntries(config.sources);
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
  const fmtNumber = (value) => (value == null ? '' : Number(value).toLocaleString(undefined, { maximumFractionDigits: 4 }));
  const STATUS_CLASS = {
    approved: 'text-bg-success', hold: 'text-bg-warning', pending_review: 'text-bg-info', rejected: 'text-bg-danger',
  };
  const statusBadge = (status) => `<span class="badge ${STATUS_CLASS[status] || 'text-bg-secondary'}">${esc(statusLabels[status] || status)}</span>`;

  function debounce(fn, ms) {
    let timer = null;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), ms);
    };
  }

  $('fk-subs-status').innerHTML += config.statuses.map(([code, label]) => `<option value="${code}">${esc(label)}</option>`).join('');
  $('fk-subs-source').innerHTML += config.sources.map(([code, label]) => `<option value="${code}">${esc(label)}</option>`).join('');

  function filters() {
    const found = { q: $('fk-subs-q').value.trim(), status: $('fk-subs-status').value, source: $('fk-subs-source').value };
    if ($('fk-subs-needs').checked) found.needs_details = '1';
    if ($('fk-subs-deleted').checked) found.deleted = '1';
    return found;
  }

  function withQuery(path, params) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => { if (value) query.set(key, value); });
    const text = query.toString();
    return text ? `${path}?${text}` : path;
  }

  // The item's panel on Main.
  const itemLink = (item) => withQuery(config.api.main, { item });

  function message(html) {
    $('fk-subs-rows').innerHTML = `<tr><td colspan="9" class="small p-3">${html}</td></tr>`;
  }

  let ticket = 0;

  async function load() {
    const mine = ++ticket;
    const params = filters();
    $('fk-subs-export').href = withQuery(config.api.export, params);
    try {
      const response = await window.appFetch(withQuery(config.api.subs, params));
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.message || `The server answered ${response.status}.`);
      if (mine === ticket) render(data.subs, data.limit, Boolean(params.deleted));
    } catch (error) {
      if (mine === ticket) message(`<div class="alert alert-danger py-2 mb-0">${esc(error.message)}</div>`);
    }
  }

  function render(subs, limit, deleted) {
    $('fk-subs-count').textContent = subs.length >= limit
      ? `The ${limit} most recently changed: narrow the filters, or export them all`
      : `${subs.length} sub${subs.length === 1 ? '' : 's'}${deleted ? ' deleted' : ''}`;
    if (!subs.length) { message('<span class="text-muted">No subs match.</span>'); return; }
    $('fk-subs-rows').innerHTML = subs.map((s) => {
      const vendor = s.vendor ? esc(s.vendor)
        : '<span class="badge text-bg-warning" title="The Materials Manager fills in the vendor details">Vendor details needed</span>';
      const unit = s.uom ? `<div class="text-muted">${esc(s.uom)}${s.qoe ? ` · QOE ${fmtNumber(s.qoe)}` : ''}</div>` : '';
      const removed = deleted
        ? `<div class="small text-danger">Deleted by ${esc(s.deleted_by)} ${fmtDateTime(s.deleted_at)}: ${esc(s.delete_reason)}</div>` : '';
      const entered = s.source === 'manual' ? esc(s.entered_by) : esc(sourceLabels[s.source] || s.source);
      return `<tr>
        <td><a href="${esc(itemLink(s.medline_item))}" title="Open the item on Main">${esc(s.medline_item)}</a>
          ${s.infor_item ? `<div class="small text-muted">${esc(s.infor_item)}</div>` : ''}</td>
        <td class="fw-semibold">${esc(s.vendor_part)}</td>
        <td>${vendor}${s.vendor_id ? `<div class="small text-muted">${esc(s.vendor_id)}</div>` : ''}</td>
        <td class="small">${esc(s.description || '')}${unit}</td>
        <td>${statusBadge(s.status)}${s.is_picked ? ' <span class="badge text-bg-success">Picked</span>' : ''}${removed}</td>
        <td class="small text-nowrap">${s.orders ? `${s.orders} · last ${fmtDate(s.last_ordered)}` : '<span class="text-muted">—</span>'}</td>
        <td class="small">${entered}<div class="text-muted text-nowrap">${fmtDateTime(s.create_dt)}</div></td>
        <td class="small">${s.approved_by ? `${esc(s.approved_by)}<div class="text-muted text-nowrap">${fmtDateTime(s.approved_at)}</div>`
          : '<span class="text-muted">—</span>'}</td>
        <td class="small">${s.latest_comment ? `${esc(s.latest_comment.comment)}<div class="text-muted">${esc(s.latest_comment.actor)}</div>` : ''}</td>
      </tr>`;
    }).join('');
  }

  $('fk-subs-q').addEventListener('input', debounce(load, 300));
  ['fk-subs-status', 'fk-subs-source', 'fk-subs-needs', 'fk-subs-deleted'].forEach((id) => $(id).addEventListener('change', load));
  load();
})();
