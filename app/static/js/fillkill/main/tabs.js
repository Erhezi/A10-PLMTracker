/* Main: the item panel's tabs: Subs, Kill lines, Sub History and Orders. Each draws the panel's
 * view (panel.js): the Medline items shown and what belongs to them.
 */

import {
  NO_VENDOR, REASON_LABEL, config, esc, fmtDate, fmtDateTime, fmtNumber, needsDetails, noQoeBadge, statusBadge, uomQoe,
  vendorText,
} from '../common.js';
import { can, siteName, state } from './state.js';
import { customerFlag } from './table.js';

export function renderPanelTab(tab, view) {
  if (tab === 'lines') return linesTab(view.lines, view.many);
  if (tab === 'picks') return picksTab(view.history, view.many);
  if (tab === 'orders') return ordersTab(view.orders, view.many);
  return subsTab(view);
}

// --- Subs ------------------------------------------------------------------------------------

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
  return `<div class="small text-muted mb-1">On other UOMs, not on ${esc(p.medline_item)} yet. Add one to review and prefer it here:</div>
    <ul class="list-group list-group-flush small mb-2">${p.other_subs.map((o) => `
      <li class="list-group-item px-0 d-flex flex-wrap gap-2 align-items-center">
        <span class="fw-semibold">${esc(o.reference_sku)}</span>
        ${statusBadge(o.status)}
        <span class="text-muted">on ${esc(o.medline_item)}${o.um ? ` (${esc(o.um)})` : ''}${o.approved_by
          ? `, approved by ${esc(o.approved_by)} ${fmtDateTime(o.approved_at)}` : ''}</span>
        ${can.add_sub ? `<button type="button" class="btn btn-sm btn-outline-primary ms-auto py-0" data-act="copy-sub"
            data-sub="${o.sub_id}" data-item="${esc(p.medline_item)}">Add to ${esc(p.medline_item)}</button>` : ''}
      </li>`).join('')}</ul>`;
}

// A sub's vendor items (2026-10-20): each a way to order it, the Materials Manager's or a Sub
// Finder's. A Materials Manager records an order for one of the pick's.
function vendorItemList(sub) {
  const items = sub.vendor_items || [];
  if (!items.length) return '';
  return `<ul class="list-unstyled small mb-0 mt-1 fk-vendor-items">${items.map((v) => {
    const facts = [
      v.manufacturer_part ? `Mfr part ${esc(v.manufacturer_part)}` : '',
      v.infor_item ? `Infor item ${esc(v.infor_item)}` : '',
      `added by ${esc(v.entered_by)} ${fmtDateTime(v.create_dt)}`,
    ].filter(Boolean).join(' · ');
    const actions = [];
    if (can.order && sub.is_picked) {
      actions.push(`<button type="button" class="btn btn-sm btn-primary py-0" data-act="order" data-vi="${v.vendor_item_id}">Record order</button>`);
    }
    if (can.details) {
      actions.push(`<button type="button" class="btn btn-sm btn-outline-secondary py-0" data-act="edit-vi" data-sub="${sub.sub_id}"
        data-vi="${v.vendor_item_id}">Correct</button>`);
      actions.push(`<button type="button" class="btn btn-sm btn-outline-danger py-0" data-act="delete-vi" data-sub="${sub.sub_id}"
        data-vi="${v.vendor_item_id}">Delete</button>`);
    }
    return `<li class="d-flex flex-wrap gap-2 align-items-center py-1">
      <div class="me-auto"><span class="fw-semibold">${esc(v.vendor_part)}</span> <span class="text-muted">${esc(vendorText(v))}</span>
        · ${esc(uomQoe(v))}${noQoeBadge(v)}${v.description ? ` <span class="text-muted">· ${esc(v.description)}</span>` : ''}
        <div class="text-muted">${facts}</div></div>
      ${actions.join('')}
    </li>`;
  }).join('')}</ul>`;
}

function subCard(sub) {
  const detailsNeeded = needsDetails(sub)
    ? ' <span class="badge text-bg-warning" title="Nothing to order yet: the Materials Manager adds what can be ordered for it">Vendor item needed</span>' : '';
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
  }
  // Sub Approvers and Materials Managers pick among the approved subs (2026-10-21), MM/SCM too: "Prefer"
  // on the page from 2026-10-28 (the user: it means preferred), pick in the code and its URLs.
  if (can.pick && sub.status === 'approved') {
    actions.push(sub.is_picked
      ? `<button type="button" class="btn btn-sm btn-outline-secondary" data-act="unpick" data-sub="${sub.sub_id}" data-expected="${sub.status}">Unprefer</button>`
      : `<button type="button" class="btn btn-sm btn-success" data-act="pick" data-sub="${sub.sub_id}" data-expected="${sub.status}"><i class="bi bi-star"></i> Prefer</button>`);
  }
  if (can.details) {
    actions.push(`<button type="button" class="btn btn-sm btn-outline-primary" data-act="add-vi" data-sub="${sub.sub_id}"><i
      class="bi bi-plus-lg"></i> Vendor item</button>`);
  }
  if (can.add_sub) {
    actions.push(`<button type="button" class="btn btn-sm btn-outline-secondary" data-act="edit-sub" data-sub="${sub.sub_id}">Correct Reference SKU</button>`);
    // The preferred sub can't be deleted until it's unpreferred (the server refuses it too).
    actions.push(sub.is_picked
      ? `<span class="d-inline-block" tabindex="0" title="It's preferred: unprefer it first">
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
        <span><span class="fw-semibold">${esc(sub.reference_sku)}</span> <span class="small text-muted">Reference SKU</span></span>
        ${statusBadge(sub.status)}${sub.is_picked ? ' <span class="badge text-bg-success"><i class="bi bi-star-fill"></i> Preferred</span>' : ''}${detailsNeeded}
        ${(sub.approved_elsewhere || []).map((o) => `<span class="badge text-success border border-success bg-white"
            title="Approved by ${esc(o.approved_by || '')} ${fmtDateTime(o.approved_at)}"><i class="bi bi-box-seam"></i>
            Approved for ${esc(o.medline_item)}${o.um ? ` (${esc(o.um)})` : ''}</span>`).join(' ')}
      </div>
      <div class="small text-muted">Added by ${source}, ${fmtDateTime(sub.create_dt)} · updated ${fmtDateTime(sub.update_dt)}</div>
      ${vendorItemList(sub)}
      ${comment}
      <div class="d-flex flex-wrap gap-2 align-items-center mt-2">${actions.join('')}</div>
      ${commentBox}
      <div class="fk-history small mt-2" id="fk-history-sub-${sub.sub_id}"></div>
    </div>
  </div>`;
}

// Nursing enters the Reference SKU, and a note if they like (2026-10-15, 10-20). A Sub Approver's
// entry is approved on entry, and picked when it's the only approved sub; the Materials Manager adds
// its vendor items.
function addSubForm(packs) {
  // Several UOMs: which Medline item the sub is for (the one clicked, unless changed).
  const target = packs.length > 1 ? `
        <div class="col-12"><label class="form-label small mb-0" for="fk-add-item">For Medline item *</label>
          <select class="form-select form-select-sm" id="fk-add-item" name="medline_item">${packs.map((p) => `
            <option value="${esc(p.medline_item)}" ${p.medline_item === state.panelItem ? 'selected' : ''}>${esc(p.medline_item)} (${esc(p.um)})</option>`).join('')}
          </select></div>` : '';
  const what = can.review
    ? "It's approved as soon as it's added, and preferred if it's the only approved sub. The Materials Manager adds what can be ordered for it."
    : "It waits for a Sub Approver's review.";
  return `
    <div class="border rounded p-2 bg-light">
      <form id="fk-add-form" class="row g-2" novalidate>${target}
        <div class="col-6"><label class="form-label small mb-0" for="fk-add-sku">Reference SKU *</label>
          <input class="form-control form-control-sm" id="fk-add-sku" name="reference_sku" maxlength="100" required
                 placeholder="The part you approved, e.g. the manufacturer's"></div>
        <div class="col-12"><label class="form-label small mb-0" for="fk-add-comment">Note</label>
          <input class="form-control form-control-sm" id="fk-add-comment" name="comment" maxlength="400"
                 placeholder="Optional: what you know about it, e.g. from the supplier"></div>
        <div class="col-12 small text-muted">${what}</div>
        <div class="col-12"><button type="submit" class="btn btn-sm btn-primary">Add sub</button>
          <button type="button" class="btn btn-sm btn-link" data-act="hide-add">Cancel</button></div>
      </form>
    </div>`;
}

// --- Kill lines, Sub History, Orders ---------------------------------------------------------

function linesTab(lines, many) {
  if (!lines.length) return '<p class="text-muted small">No kill lines for these dates and sites.</p>';
  return `<div class="table-responsive"><table class="table table-sm align-middle fk-panel-table">
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

const FIELD_LABELS = { reference_sku: 'Reference SKU', vendor_part: 'vendor part', vendor_id: 'vendor ID', uom: 'UOM', qoe: 'QOE',
  manufacturer_part: 'manufacturer part', infor_item: 'Infor item', entered_part: 'part as entered', ordered_dt: 'ordered date',
  po_number: 'PO number' };

function describe(h) {
  const labels = config.statusLabels;
  const vendorItem = h.entity === 'vendoritem';
  // An order's site is kept as Medline's Sold-To code (2026-10-27): shown by its name.
  const value = (v) => esc(h.field === 'site' && v ? siteName(v) : (v || '—'));
  switch (h.action) {
    case 'created': return { order: 'Recorded the order', vendoritem: 'Added the vendor item' }[h.entity] || 'Added the sub';
    case 'status': return `Status ${esc(labels[h.from_value] || h.from_value)} → ${statusBadge(h.to_value)}`;
    case 'pick': return h.comment ? esc(h.comment) : 'Preferred';
    case 'unpick': return h.comment ? esc(h.comment) : 'No longer preferred';
    case 'comment': return `Comment: ${esc(h.comment)}`;
    case 'edit': return `Changed ${vendorItem ? "the vendor item's " : ''}${esc(FIELD_LABELS[h.field] || String(h.field || '').replace(/_/g, ' '))}:
      ${value(h.from_value)} → ${value(h.to_value)}`;
    case 'void': return `Voided: ${esc(h.comment)}`;
    case 'delete': return `Deleted${vendorItem ? ' the vendor item' : ''}: ${esc(h.comment)}`;
    default: return esc(h.action);
  }
}

// History entries, newest first; a sub's or an order's own History button shows them too. A vendor
// item's entries always say which vendor item.
export function timeline(entries, withLabel, withItem) {
  if (!entries.length) return '<p class="text-muted small">Nothing yet.</p>';
  return `<ul class="list-unstyled small mb-0 fk-timeline">${entries.map((h) => `
    <li class="mb-1"><span class="text-muted text-nowrap">${fmtDateTime(h.acted_at)}</span> ·
      ${esc(h.actor)}${(withLabel || h.entity === 'vendoritem') && h.label ? ` · <span class="fw-semibold">${esc(h.label)}</span>` : ''}${withItem && h.medline_item
        ? ` <span class="text-muted">on ${esc(h.medline_item)}</span>` : ''} · ${describe(h)}</li>`).join('')}</ul>`;
}

function picksTab(history, many) {
  return `<p class="small text-muted mb-2">Every sub added, reviewed, preferred and unpreferred for ${many ? 'these Medline items' : 'this Medline item'},
    and every vendor item added and deleted, newest first.</p>
    ${timeline(history, true, many)}`;
}

// Every order for the item, every site's (whatever the site filter: it's the item's history), as a
// table like the kill lines (2026-10-20; cards before), newest first. A voided one is greyed, its
// quantity struck through. A row's History and Comment open a line under it.
function ordersTab(orders, many) {
  if (!orders.length) return '<p class="text-muted small">No orders recorded for this item.</p>';
  const columns = many ? 9 : 8;
  return `<div class="table-responsive"><table class="table table-sm align-middle fk-panel-table fk-orders-tab">
    <thead class="table-light text-nowrap"><tr><th>Ordered</th>${many ? '<th>Medline Item</th>' : ''}<th>Site · PO</th><th>Vendor Part</th>
      <th class="text-end">Quantity</th><th>Vendor</th><th>Ordered By</th><th>Latest Comment</th>
      <th><span class="visually-hidden">Actions</span></th></tr></thead>
    <tbody>${orders.map((o) => orderRows(o, many, columns)).join('')}</tbody></table></div>`;
}

function orderRows(o, many, columns) {
  const voided = Boolean(o.voided_at);
  const button = (act, icon, label) => `<button type="button" class="btn btn-sm btn-link p-0 ms-2" data-act="${act}"
    data-order="${o.order_id}" title="${label}" aria-label="${label}"><i class="bi ${icon}"></i></button>`;
  const actions = [];
  if (can.order && !voided) actions.push(button('edit-order', 'bi-pencil', 'Correct'), button('void-order', 'bi-x-circle text-danger', 'Void'));
  if (can.order) actions.push(button('comment-order-open', 'bi-chat-left-text', 'Add a comment'));
  actions.push(`<button type="button" class="btn btn-sm btn-link p-0 ms-2" data-act="history" data-entity="order" data-id="${o.order_id}"
    title="History" aria-label="History"><i class="bi bi-clock-history"></i></button>`);
  const vendorId = o.vendor_id === NO_VENDOR.id ? 'not in Infor' : (o.vendor_id || '');
  const c = o.latest_comment;
  const commentBox = can.order ? `
    <form class="input-group input-group-sm mb-1 d-none" data-act="comment-order" data-order="${o.order_id}">
      <input type="text" class="form-control" name="comment" maxlength="400" placeholder="Add a comment" aria-label="Comment on this order">
      <button class="btn btn-outline-secondary" type="submit">Add</button>
    </form>` : '';
  return `<tr class="${voided ? 'text-muted' : ''}">
      <td class="text-nowrap">${fmtDateTime(o.ordered_dt)}</td>
      ${many ? `<td class="text-nowrap">${esc(o.medline_item)}</td>` : ''}
      <td>${o.site ? esc(siteName(o.site)) : '<span class="text-muted">Site not recorded</span>'}${o.po_number
        ? `<div class="text-muted text-nowrap">PO ${esc(o.po_number)}</div>` : ''}</td>
      <td><span class="fw-semibold">${esc(o.vendor_part)}</span><div class="text-muted">for ${esc(o.reference_sku)}</div></td>
      <td class="text-end text-nowrap"><span class="${voided ? 'text-decoration-line-through' : ''}">${fmtNumber(o.quantity)}</span>
        <span class="text-muted">${esc(uomQoe(o))}</span></td>
      <td>${esc(o.vendor)}${vendorId ? `<div class="text-muted">${esc(vendorId)}</div>` : ''}</td>
      <td>${esc(o.ordered_by)}${voided ? `<div><span class="badge text-bg-secondary">Voided</span> by ${esc(o.voided_by)}:
        ${esc(o.void_reason)}</div>` : ''}</td>
      <td>${c ? `${esc(c.comment)}<div class="text-muted">${esc(c.actor)}, ${fmtDateTime(c.acted_at)}${c.count > 1
        ? ` · ${c.count} comments` : ''}</div>` : ''}</td>
      <td class="text-end text-nowrap">${actions.join('')}</td>
    </tr>
    <tr class="fk-order-more d-none"><td colspan="${columns}">${commentBox}
      <div class="fk-history" id="fk-history-order-${o.order_id}"></div></td></tr>`;
}
