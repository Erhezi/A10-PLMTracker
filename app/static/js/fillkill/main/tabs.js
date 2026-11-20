/* Main: the item panel's tabs: Subs, Kill lines, Sub History and Orders. Each draws the panel's
 * view (panel.js): the Medline items shown and what belongs to them.
 */

import {
  NO_VENDOR, REFERENCE_SKU_HINT, SUB_NOTE_HINT, config, enteredBy, esc, fmtDate, fmtDateTime, fmtNumber, needsDetails,
  noQoeBadge, statusBadge, uomQoe, vendorText,
} from '../common.js';
import { can, siteName, state } from './state.js';
import { customerFlag } from './table.js';

export function renderPanelTab(tab, view) {
  if (tab === 'lines') return linesTab(view);
  if (tab === 'history') return historyTab(view.history, view.many);
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
    return head + own + withoutSub(p) + otherSubs(p);
  }).join('');
}

// Vendor items without a sub (2026-11-02, the user): what SCM directs the sites to order for the
// Medline item when no sub nursing approved is available, e.g. the same item from another vendor.
// Materials Managers and SCM add them; they're ordered like a sub's.
function withoutSub(p) {
  const items = p.vendor_items || [];
  if (!items.length && !can.direct) return '';
  const add = can.direct ? `<button type="button" class="btn btn-sm btn-outline-primary py-0" data-act="add-item-vi"
      data-item="${esc(p.medline_item)}"><i class="bi bi-plus-lg"></i> Vendor item</button>` : '';
  return `<div class="card mb-2"><div class="card-body p-2 small">
    <div class="d-flex flex-wrap gap-2 align-items-center"><span class="fw-semibold me-auto">Vendor items without a sub</span>${add}</div>
    <div class="text-muted">As SCM directs when no sub nursing approved is available, e.g. the same item from another vendor.
      They can be ordered as they are.</div>
    ${items.length ? vendorItemList(items, null) : ''}
  </div></div>`;
}

// Subs on the Infor item's other UOMs, not on this one yet.
function otherSubs(p) {
  if (!p.other_subs.length) return '';
  return `<div class="small text-muted mb-1">On other UOMs, not on ${esc(p.medline_item)} yet. Add one to review it here:</div>
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
// Finder's. A Materials Manager records an order for one of an approved sub's, or for one without a
// sub (``sub`` null, 2026-11-02), whose vendor items only Materials Managers and SCM change.
function vendorItemList(items, sub) {
  if (!items.length) return '';
  const orderable = !sub || sub.status === 'approved';
  const changes = sub ? can.details : can.direct;
  const subId = sub ? sub.sub_id : '';
  return `<ul class="list-unstyled small mb-0 mt-1 fk-vendor-items">${items.map((v) => {
    const facts = [
      v.manufacturer_part ? `Mfr part ${esc(v.manufacturer_part)}` : '',
      v.infor_item ? `Infor item ${esc(v.infor_item)}` : '',
      `added by ${esc(v.entered_by)} ${fmtDateTime(v.create_dt)}`,
    ].filter(Boolean).join(' · ');
    const actions = [];
    if (can.order && orderable) {
      actions.push(`<button type="button" class="btn btn-sm btn-primary py-0" data-act="order" data-vi="${v.vendor_item_id}">Record order</button>`);
    }
    if (changes) {
      actions.push(`<button type="button" class="btn btn-sm btn-outline-secondary py-0" data-act="edit-vi" data-sub="${subId}"
        data-vi="${v.vendor_item_id}">Correct</button>`);
      actions.push(`<button type="button" class="btn btn-sm btn-outline-danger py-0" data-act="delete-vi" data-sub="${subId}"
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
  const source = esc(enteredBy(sub));
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
  if (can.details) {
    actions.push(`<button type="button" class="btn btn-sm btn-outline-primary" data-act="add-vi" data-sub="${sub.sub_id}"><i
      class="bi bi-plus-lg"></i> Vendor item</button>`);
  }
  if (can.add_sub) {
    actions.push(`<button type="button" class="btn btn-sm btn-outline-secondary" data-act="edit-sub" data-sub="${sub.sub_id}">Correct Reference SKU</button>`);
    actions.push(`<button type="button" class="btn btn-sm btn-outline-danger" data-act="delete-sub" data-sub="${sub.sub_id}">Delete</button>`);
  }
  actions.push(`<button type="button" class="btn btn-sm btn-link" data-act="history" data-entity="sub" data-id="${sub.sub_id}">History</button>`);

  const commentBox = can.review ? `
    <form class="input-group input-group-sm mt-2" data-act="comment-sub" data-sub="${sub.sub_id}">
      <input type="text" class="form-control" name="comment" maxlength="400" placeholder="Add a comment" aria-label="Comment on this sub">
      <button class="btn btn-outline-secondary" type="submit">Add</button>
    </form>` : '';

  return `<div class="card mb-2 ${sub.status === 'approved' ? 'border-success' : ''}">
    <div class="card-body p-2">
      <div class="d-flex flex-wrap gap-2 align-items-center">
        <span><span class="fw-semibold">${esc(sub.reference_sku)}</span> <span class="small text-muted">Reference SKU</span></span>
        ${statusBadge(sub.status)}${detailsNeeded}
        ${(sub.approved_elsewhere || []).map((o) => `<span class="badge text-success border border-success bg-white"
            title="Approved by ${esc(o.approved_by || '')} ${fmtDateTime(o.approved_at)}"><i class="bi bi-box-seam"></i>
            Approved for ${esc(o.medline_item)}${o.um ? ` (${esc(o.um)})` : ''}</span>`).join(' ')}
      </div>
      <div class="small text-muted">Added by ${source}, ${fmtDateTime(sub.create_dt)} · updated ${fmtDateTime(sub.update_dt)}</div>
      ${vendorItemList(sub.vendor_items || [], sub)}
      ${comment}
      <div class="d-flex flex-wrap gap-2 align-items-center mt-2">${actions.join('')}</div>
      ${commentBox}
      <div class="fk-history small mt-2" id="fk-history-sub-${sub.sub_id}"></div>
    </div>
  </div>`;
}

// Nursing enters the Reference SKU, and a note if they like (2026-10-15, 10-20). A Sub Approver's
// entry is approved on entry, so it can be ordered; the Materials Manager adds its vendor items.
function addSubForm(packs) {
  // Several UOMs: which Medline item the sub is for (the one clicked, unless changed).
  const target = packs.length > 1 ? `
        <div class="col-12"><label class="form-label small mb-0" for="fk-add-item">For Medline item *</label>
          <select class="form-select form-select-sm" id="fk-add-item" name="medline_item">${packs.map((p) => `
            <option value="${esc(p.medline_item)}" ${p.medline_item === state.panelItem ? 'selected' : ''}>${esc(p.medline_item)} (${esc(p.um)})</option>`).join('')}
          </select></div>` : '';
  const what = can.review
    ? "It's approved as soon as it's added, so it can be ordered: the Materials Manager adds its vendor items."
    : "It waits for a Sub Approver's review.";
  return `
    <div class="border rounded p-2 bg-light">
      <form id="fk-add-form" class="row g-2" novalidate>${target}
        <div class="col-6"><label class="form-label small mb-0" for="fk-add-sku">Reference SKU *</label>
          <input class="form-control form-control-sm" id="fk-add-sku" name="reference_sku" maxlength="100" required
                 placeholder="${esc(REFERENCE_SKU_HINT)}"></div>
        <div class="col-12"><label class="form-label small mb-0" for="fk-add-comment">Note</label>
          <input class="form-control form-control-sm" id="fk-add-comment" name="comment" maxlength="400"
                 placeholder="${esc(SUB_NOTE_HINT)}"></div>
        <div class="col-12 small text-muted">${what}</div>
        <div class="col-12"><button type="submit" class="btn btn-sm btn-primary">Add sub</button>
          <button type="button" class="btn btn-sm btn-link" data-act="hide-add">Cancel</button></div>
      </form>
    </div>`;
}

// --- Kill lines, Sub History, Orders ---------------------------------------------------------

// The ship-to: its location code first (Ship-To Name 2 without "- UBOAT", e.g. PWLREICU: the name
// Materials Managers know, 2026-11-16), then Medline's Ship-To Name.
function shipTo(l) {
  const code = l.ship_to_code ? `<span class="fw-semibold">${esc(l.ship_to_code)}</span>` : '';
  return [code, esc(l.department || '')].filter(Boolean).join(' · ');
}

// The kill lines by site (2026-11-20, the user; as Order Timing's orders and their lines, instead of
// switching between each line and by site): a row per site with what it killed, per UOM (in eaches
// too with several UOMs, when each has a QOE), its kill lines and how many locations requested them,
// each listed on hover; most lines first, then "All sites". Every site starts folded, a single one
// too (the user, 2026-11-20); a click on a site (or Enter) shows its lines under it. Which are open
// is kept while the item is open.
function linesTab(view) {
  const { lines, many } = view;
  if (!lines.length) return '<p class="text-muted small">No kill lines for these dates and sites.</p>';
  const qoe = new Map(view.packs.flatMap((p) => (p.uom_qoes || []).map((u) => [`${p.medline_item}|${u.uom}`, u.qoe])));
  const rollUp = (group) => {
    const units = new Map();
    let each = 0;
    const locations = new Map();
    group.forEach((l) => {
      units.set(l.um || '', (units.get(l.um || '') || 0) + (l.killed || 0));
      const q = qoe.get(`${l.medline_item}|${l.um}`);
      each = each == null || q == null ? null : each + (l.killed || 0) * q;
      const where = locationOf(l);
      if (where) {
        const found = locations.get(where) || { name: l.department, lines: 0 };
        found.lines += 1;
        locations.set(where, found);
      }
    });
    return { units, each, locations, lines: group };
  };
  const killed = (r) => [...r.units].map(([um, n]) => `<div>${fmtNumber(n)} <span class="text-muted small">${esc(um)}</span></div>`).join('')
    + (r.units.size > 1 && r.each != null ? `<div class="text-muted small">${fmtNumber(r.each)} EA</div>` : '');
  const places = (r) => {
    const list = [...r.locations].sort(([a], [b]) => a.localeCompare(b))
      .map(([code, l]) => `${code}${l.name && l.name !== code ? ` · ${l.name}` : ''}: ${l.lines} line${l.lines > 1 ? 's' : ''}`).join('\n');
    return `<span title="${esc(list)}">${fmtNumber(r.locations.size)}</span>`;
  };
  const cells = (r) => `<td class="text-end text-nowrap">${killed(r)}</td><td class="text-end">${fmtNumber(r.lines.length)}</td>
    <td class="text-end">${places(r)}</td>`;
  const groups = new Map();
  lines.forEach((l) => groups.set(l.site || '', [...(groups.get(l.site || '') || []), l]));  // newest first, as sent
  const sites = [...groups].map(([site, group]) => ({ site, ...rollUp(group) }))
    .sort((a, b) => b.lines.length - a.lines.length || a.site.localeCompare(b.site));
  const one = sites.length === 1;
  const isOpen = (site) => state.linesOpen.has(site);
  const body = sites.map((r) => {
    const open = isOpen(r.site);
    const name = r.site ? esc(r.site) : '<span class="text-muted">No site</span>';
    return `<tbody class="fk-site-group">
      <tr class="fk-site-row" data-site="${esc(r.site)}" tabindex="0" role="button" aria-expanded="${open}"
          title="${open ? 'Hide' : 'Show'} its kill lines">
        <td class="fk-caret text-muted"><i class="bi bi-chevron-${open ? 'down' : 'right'}" aria-hidden="true"></i></td>
        <td class="fw-semibold">${name}</td>${cells(r)}
      </tr>
      <tr class="fk-site-lines-row"${open ? '' : ' hidden'}><td></td><td colspan="4" class="pt-0 pb-2">${siteLines(r.lines, many)}</td></tr>
    </tbody>`;
  }).join('');
  const total = one ? '' : `<tbody class="fk-site-total"><tr class="fw-semibold"><td></td><td>All sites</td>${cells(rollUp(lines))}</tr></tbody>`;
  const allOpen = sites.every((r) => isOpen(r.site));
  const showAll = one ? '' : `<button type="button" class="btn btn-sm btn-link p-0 ms-auto" data-lines-all="${allOpen ? 'open' : 'closed'}">${allOpen
    ? 'Hide all lines' : 'Show all lines'}</button>`;
  return `<div class="d-flex flex-wrap gap-2 align-items-center mb-2">
      <span class="small text-muted">${plural(lines.length, 'kill line')} at ${plural(sites.length, 'site')} · click a site for its lines</span>${showAll}</div>
    <div class="table-responsive"><table class="table table-sm align-middle fk-panel-table">
      <thead class="table-light"><tr><th class="fk-caret"><span class="visually-hidden">Lines</span></th><th>Site</th>
        <th class="text-end">Killed</th><th class="text-end">Kill lines</th>
        <th class="text-end" title="Requesting locations: the ship-tos, by their code (Ship-To Name 2)">Locations</th></tr></thead>
      ${body}${total}</table></div>`;
}

const plural = (n, word) => `${fmtNumber(n)} ${word}${n === 1 ? '' : 's'}`;

// A line's requesting location: its ship-to code (Ship-To Name 2 up to its hyphen, e.g. PMOSK6), or
// Medline's Ship-To Name when it has none.
const locationOf = (l) => l.ship_to_code || l.department || '';

// A site's kill lines, newest first, under its row.
function siteLines(lines, many) {
  return `<table class="table table-sm mb-0 fk-panel-table fk-site-lines">
    <thead class="text-nowrap"><tr><th>Ordered</th>${many ? '<th>Medline Item</th>' : ''}<th>Ship-To</th><th>PO</th><th class="text-end">Killed</th><th>Reason</th></tr></thead>
    <tbody>${lines.map((l) => `<tr class="fk-kill-line">
      <td class="text-nowrap">${fmtDate(l.order_date)} ${esc(String(l.order_time || '').slice(0, 5))}</td>
      ${many ? `<td class="text-nowrap">${esc(l.medline_item)}</td>` : ''}
      <td>${shipTo(l)}</td>
      <td class="text-nowrap">${esc(l.po)}${l.po_line != null ? `-${esc(l.po_line)}` : ''}</td>
      <td class="text-end text-nowrap">${fmtNumber(l.killed)} / ${fmtNumber(l.ordered)} ${esc(l.um)}</td>
      <td>${[l.reason ? `<span class="badge text-bg-light border">${esc(l.reason)}</span>` : '',
        l.comment ? `<span class="text-muted">${esc(l.comment)}</span>` : ''].filter(Boolean).join(' ')}</td>
    </tr>`).join('')}</tbody></table>`;
}

// Open or close a site's kill lines (``show`` true or false; a click toggles), in place, so the
// keyboard keeps its place; "Show all lines" follows.
export function toggleSite(row, show) {
  const open = show == null ? row.getAttribute('aria-expanded') !== 'true' : show;
  if (open) state.linesOpen.add(row.dataset.site); else state.linesOpen.delete(row.dataset.site);
  row.setAttribute('aria-expanded', String(open));
  row.title = `${open ? 'Hide' : 'Show'} its kill lines`;
  row.querySelector('.fk-caret i').className = `bi bi-chevron-${open ? 'down' : 'right'}`;
  row.nextElementSibling.hidden = !open;
  const all = row.closest('#fk-panel-content')?.querySelector('[data-lines-all]');
  if (all) {
    const allOpen = [...row.closest('table').querySelectorAll('.fk-site-row')].every((r) => r.getAttribute('aria-expanded') === 'true');
    all.dataset.linesAll = allOpen ? 'open' : 'closed';
    all.textContent = allOpen ? 'Hide all lines' : 'Show all lines';
  }
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

function historyTab(history, many) {
  return `<p class="small text-muted mb-2">Every sub added, reviewed or deleted for ${many ? 'these Medline items' : 'this Medline item'},
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
      <td><span class="fw-semibold">${esc(o.vendor_part)}</span><div class="text-muted">${o.reference_sku
        ? `for ${esc(o.reference_sku)}` : 'no sub, as SCM directs'}</div></td>
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
