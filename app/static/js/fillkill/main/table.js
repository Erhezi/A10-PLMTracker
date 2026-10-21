/* Main: the table. Each Infor item is a <tbody> of its own, so its UOMs highlight together, with a
 * <tr> per Medline item (UOM) and, with several, a last <tr> adding them up in eaches.
 */

import {
  $, NO_VENDOR, REASON_LABEL, STATUS_ORDER, alertBox, esc, fmtDate, fmtDateTime, fmtNumber, getJSON, needsDetails,
  statusBadge, uomQoe, vendorItemText,
} from '../common.js';
import { renderNeeds } from './controls.js';
import { openOrderForm, openVendorItemForm } from './forms.js';
import { openPanel } from './panel.js';
import { api, can, historyUrl, scopeParams, state, syncLink } from './state.js';

const mainTable = $('fk-main');
let mainRequest = 0;

export async function loadMain() {
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
    setRows(`<tbody><tr><td colspan="15" class="p-3">${alertBox(error.message)}</td></tr></tbody>`);
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

export function renderRows() {
  syncLink();
  const rows = state.rows.filter((row) => (state.needs === 'all' || row.needs.includes(state.needs)) && matchesSearch(row));
  if (!rows.length) {
    const why = state.rows.length ? 'No item matches these filters.' : 'No kill lines for these dates and sites.';
    setRows(`<tbody><tr><td colspan="15" class="text-muted small p-3">${why}</td></tr></tbody>`);
    return;
  }
  setRows(rows.map(itemRows).join(''));
}

function setRows(html) {
  closeComments();  // its button is about to go
  mainTable.querySelectorAll(':scope > tbody').forEach((body) => body.remove());
  mainTable.tHead.insertAdjacentHTML('afterend', html);
}

// --- cells -----------------------------------------------------------------------------------

function qtyLines(quantities, key) {
  return quantities.map((q) => `<div>${fmtNumber(q[key])} <span class="text-muted small">${esc(q.uom)}</span></div>`).join('');
}

// Eaches per unit, from Infor's UOM conversion for the Infor item: one per UOM line.
function qoeLines(quantities) {
  return quantities.map((q) => `<div>${q.each != null ? fmtNumber(q.each)
    : '<span class="text-muted" title="Infor has no conversion for this UOM of the Infor item">—</span>'}</div>`).join('');
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
  const subs = approved.map((a) => `${a.reference_sku} on ${a.medline_item}`).join('\n');
  return `<div class="small text-success mt-1" title="${esc(subs)}"><i class="bi bi-box-seam"></i>
    ${approved.length} approved for another UOM: ${esc(items.join(', '))}</div>`;
}

// Picked for Ordering (named so 2026-10-21; "Approver's Pick" before) is always the Reference SKU
// nursing entered (2026-10-20). With no vendor item yet there's nothing to order: a pencil says so,
// and for whoever adds them it opens the form.
function pickCell(pick) {
  if (!pick) return '<span class="text-muted small">—</span>';
  const title = `No vendor item yet: nothing to order for ${pick.reference_sku}`;
  const pencil = !needsDetails(pick) ? ''
    : can.details
      ? ` <button type="button" class="btn btn-link btn-sm p-0 align-baseline" data-add-vi="${pick.sub_id}"
           title="${esc(title)}. Add one." aria-label="Add a vendor item for ${esc(pick.reference_sku)}"><i
           class="bi bi-pencil-square text-warning"></i></button>`
      : ` <i class="bi bi-pencil-square text-warning" title="${esc(title)}" role="img" aria-label="${esc(title)}"></i>`;
  // Its comments, in a popover (2026-10-21): filled with a count when there are some.
  const n = pick.comments || 0;
  const latest = pick.latest_comment;
  const about = n ? `${n} comment${n > 1 ? 's' : ''}; the latest, by ${latest.actor}: ${latest.comment}` : 'No comments yet';
  const chat = ` <button type="button" class="btn btn-link btn-sm p-0 align-baseline${n ? '' : ' text-muted'}" data-comments="${pick.sub_id}"
      title="${esc(about)}" aria-label="Comments on ${esc(pick.reference_sku)}"><i
      class="bi ${n ? 'bi-chat-left-text-fill' : 'bi-chat-left'}"></i>${n ? `<span class="small ms-1">${n}</span>` : ''}</button>`;
  return `<div class="text-nowrap"><span class="fw-semibold">${esc(pick.reference_sku)}</span>${pencil}${chat}</div>`;
}

// --- a pick's comments -----------------------------------------------------------------------

// A pick's comments, newest first, in a popover beside it (2026-10-21), so they can be read
// without opening the item's panel. One is open at a time; a click elsewhere or Escape closes it.
// They're read first and the popover shown with them: Bootstrap hides a manual popover whose
// content is changed while it shows.
let openComments = null;  // { button, popover }
let loadingComments = null;  // the button whose comments are on their way

function closeComments() {
  loadingComments = null;
  if (!openComments) return;
  openComments.popover.dispose();
  openComments = null;
}

function commentList(history) {
  const found = history.filter((h) => h.entity === 'sub' && h.action === 'comment');
  if (!found.length) return '<div class="text-muted">No comments yet.</div>';
  return `<ul class="list-unstyled mb-0">${found.map((h) => `<li class="mb-2">
    <div class="text-muted">${esc(fmtDateTime(h.acted_at))} · ${esc(h.actor)}</div><div>${esc(h.comment)}</div></li>`).join('')}</ul>`;
}

async function toggleComments(button) {
  const again = (openComments && openComments.button === button) || loadingComments === button;
  closeComments();
  if (again || !window.bootstrap) return;
  loadingComments = button;
  let content;
  try {
    content = commentList((await getJSON(historyUrl('sub', button.dataset.comments))).history);
  } catch (error) {
    content = alertBox(error.message);
  }
  // Closed, another opened, or the table redrawn while they were on their way.
  if (loadingComments !== button || !button.isConnected) return;
  loadingComments = null;
  const pick = state.rows.flatMap((row) => row.picks).find((s) => s.sub_id === Number(button.dataset.comments));
  const popover = window.bootstrap.Popover.getOrCreateInstance(button, {
    trigger: 'manual', html: true, placement: 'left', customClass: 'fk-comments-popover',
    title: `Comments · ${esc(pick ? pick.reference_sku : '')}`, content,
  });
  openComments = { button, popover };
  popover.show();
}

// Vendor Item Detail: a tile per vendor ID, vendor part and UOM of the pick beside it (2026-10-20).
// A Materials Manager records an order from one; whoever adds vendor items can add another here.
// ``several``: the UOM has more than one pick, so the add button names its pick.
function vendorItemsCell(pick, several) {
  if (!pick) return '<span class="text-muted small">—</span>';
  const items = (pick.vendor_items || []).map((v) => {
    // The vendor ID first: a long vendor name is cut short, never the ID.
    const id = v.vendor_id === NO_VENDOR.id ? 'Not in Infor' : v.vendor_id;
    const body = `<div><span class="fw-semibold">${esc(v.vendor_part)}</span> ${esc(uomQoe(v))}</div>
      <div class="fk-vi-vendor text-truncate">${esc(id)} · ${esc(v.vendor)}</div>`;
    const title = [vendorItemText(v), v.description, several ? `For ${pick.reference_sku}` : '']
      .filter(Boolean).join('\n');
    return can.order
      ? `<button type="button" class="btn btn-sm btn-outline-primary fk-vi-tile" data-order-vi="${v.vendor_item_id}"
           title="${esc(`${title}\nRecord an order for it`)}">${body}</button>`
      : `<div class="fk-vi-tile" title="${esc(title)}">${body}</div>`;
  });
  if (can.details) {
    items.push(`<button type="button" class="btn btn-link btn-sm p-0 text-decoration-none d-block" data-add-vi="${pick.sub_id}"><i
      class="bi bi-plus-lg"></i> Vendor item${several ? ` for ${esc(pick.reference_sku)}` : ''}</button>`);
  }
  return items.join('') || '<span class="text-muted small">—</span>';
}

function reasonCell(reason) {
  if (!reason) return '<span class="text-muted small">—</span>';
  const date = reason.reason_date ? ` <span class="text-muted">${fmtDate(reason.reason_date)}</span>` : '';
  return `<div class="small" title="${esc(reason.comment)}"><span class="badge text-bg-light border">`
    + `${esc(REASON_LABEL[reason.reason] || reason.reason)}</span>${date}</div>`;
}

// Medline's customer item isn't always the Infor item (it can be the Medline item itself, or
// 1296-<Medline item>): a warning beside the Medline item, naming Medline's customer item on hover.
export function customerFlag(p) {
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

// Orders recorded in these Fill/Kill dates (2026-10-20; any since the first day before), so
// Ordered and No order are about these dates: quantity, UOM and date, newest first.
const ORDERS_SHOWN = 3;

function orderingCell(row) {
  if (!row.orders.length) return '<span class="badge text-bg-light border">No order</span>';
  const lines = row.orders.slice(0, ORDERS_SHOWN).map((o) => `<div class="small text-nowrap">${fmtNumber(o.quantity)}
    <span class="text-muted">${esc(o.uom)}</span> · ${fmtDate(o.ordered_dt)}</div>`).join('');
  const more = row.orders.length > ORDERS_SHOWN ? `<div class="small text-muted">+${row.orders.length - ORDERS_SHOWN} more</div>` : '';
  return `<span class="badge text-bg-success">Ordered</span>${lines}${more}`;
}

// Killed and ordered in these dates, in eaches, for the Infor item (2026-10-21). Kill lines come in
// through the day, so an item ordered for 10 EA in the morning may need more once 30 EA are killed.
const eachesUnknown = (why) => `<span class="text-muted" title="${esc(why)}">—</span>`;
const eachesText = (n) => `${fmtNumber(n)} <span class="text-muted small">EA</span>`;

function killedEachCell(row) {
  return row.killed_each == null ? eachesUnknown("A UOM killed has no QOE in Infor, so it can't be counted in eaches")
    : eachesText(row.killed_each);
}

// With orders that fall short of what was killed, how many eaches short.
function subOrderedEachCell(row) {
  if (!row.orders.length) return `<span class="text-muted">${eachesText(0)}</span>`;
  if (row.sub_ordered_each == null) {
    return eachesUnknown("An order's UOM has no QOE, so it can't be counted in eaches. Correct the order to add its QOE.");
  }
  const short = row.killed_each != null && row.sub_ordered_each < row.killed_each - 1e-9
    ? `<div class="small text-danger fw-semibold">${fmtNumber(row.killed_each - row.sub_ordered_each)} EA short</div>` : '';
  return `${eachesText(row.sub_ordered_each)}${short}`;
}

// --- rows ------------------------------------------------------------------------------------

// A line per pick (2026-10-21), so each pick's vendor items sit beside it; a UOM's other cells span
// its picks' lines, and the Infor item's span them all. A cell that reaches the item's last line has
// data-to-end: no dashed line under it (app.css).
function itemRows(row) {
  const packs = row.packagings;
  const many = packs.length > 1;
  const lines = packs.map((p) => Math.max(1, p.picks.length));
  const span = (n) => (n > 1 ? ` rowspan="${n}"` : '');
  const all = span(lines.reduce((sum, n) => sum + n, 0) + (many ? 1 : 0));
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
  const trs = [];
  packs.forEach((p, i) => {
    const picks = p.picks.length ? p.picks : [null];
    const own = span(lines[i]) + (many ? '' : ' data-to-end');
    picks.forEach((pick, j) => {
      const first = i === 0 && j === 0;
      // Between two picks of a UOM, a lighter line than between UOMs.
      const split = j < picks.length - 1 ? ' class="fk-pick-split"' : '';
      trs.push(`<tr>
        ${first ? `<td data-to-end${all}>${infor}${count}</td>` : ''}
        ${j ? '' : `<td${own}>${packagingCell(p)}</td>`}
        ${first ? `<td class="fk-desc" data-to-end${all}><div class="text-truncate" title="${esc(row.description)}">${esc(row.description)}</div>${inforDesc}</td>` : ''}
        ${j ? '' : `<td class="text-end"${own}>${qoeLines(p.quantities)}</td>
        <td class="text-end"${own}>${qtyLines(p.quantities, 'ordered')}</td>
        <td class="text-end fw-semibold"${own}>${qtyLines(p.quantities, 'killed')}</td>
        <td class="text-end"${own}>${qtyLines(p.quantities, 'filled')}</td>
        <td class="text-end"${own}>${fmtNumber(p.lines)}</td>
        <td${own}>${reasonCell(p.latest_reason)}</td>
        <td role="button" data-open="${esc(p.medline_item)}"${own}>${subsStatusCell(p.subs_status)}${many ? '' : note}</td>`}
        <td${split}>${pickCell(pick)}</td>
        <td${split}>${vendorItemsCell(pick, picks.length > 1)}</td>
        ${first ? `<td data-to-end${all} role="button" data-open="${esc(packs[0].medline_item)}" data-scope="infor" data-tab="orders"
            title="Orders recorded in these Fill/Kill dates. Click for all of its orders">${ordering}</td>
          <td class="text-end" data-to-end${all}>${killedEachCell(row)}</td>
          <td class="text-end" data-to-end${all}>${subOrderedEachCell(row)}</td>` : ''}
      </tr>`);
    });
  });
  if (many) trs.push(totalRow(row, note));
  return `<tbody class="fk-item">${trs.join('')}</tbody>`;
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
    <td></td>
  </tr>`;
}

export function setupTable() {
  // A pick's comments close on a click outside them, or Escape.
  document.addEventListener('click', (event) => {
    if ((openComments || loadingComments) && !event.target.closest('.fk-comments-popover, [data-comments]')) closeComments();
  });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeComments(); });
  mainTable.addEventListener('click', (event) => {
    const commentsButton = event.target.closest('[data-comments]');
    if (commentsButton) {
      toggleComments(commentsButton);
      return;
    }
    const orderButton = event.target.closest('[data-order-vi]');
    if (orderButton) {
      openOrderForm(Number(orderButton.dataset.orderVi));
      return;
    }
    const addButton = event.target.closest('[data-add-vi]');
    if (addButton) {
      const subId = Number(addButton.dataset.addVi);
      openVendorItemForm(state.rows.flatMap((row) => row.picks).find((s) => s.sub_id === subId));
      return;
    }
    const opener = event.target.closest('[data-open]');
    if (opener) openPanel(opener.dataset.open, opener.dataset.tab || null, opener.dataset.scope);
  });
}
