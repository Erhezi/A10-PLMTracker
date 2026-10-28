/* Main: the table. Each Infor item is a <tbody> of its own, so its UOMs highlight together, with a
 * <tr> per Medline item (UOM) and, with several, a last <tr> adding them up in eaches.
 */

import {
  $, NO_VENDOR, REASON_LABEL, STATUS_ORDER, alertBox, config, esc, fmtDate, fmtDateTime, fmtNumber, getJSON, needsDetails,
  noQoeBadge, shortName, statusBadge, uomQoe, vendorItemText,
} from '../common.js';
import { renderNeeds } from './controls.js';
import { openAddSubForm, openInstructionForm, openOrderForm, openVendorItemForm } from './forms.js';
import { openPanel } from './panel.js';
import { api, can, historyUrl, scopeParams, siteName, state, syncLink } from './state.js';

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
    setRows(`<tbody><tr><td colspan="16" class="p-3">${alertBox(error.message)}</td></tr></tbody>`);
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
    setRows(`<tbody><tr><td colspan="16" class="text-muted small p-3">${why}</td></tr></tbody>`);
    return;
  }
  setRows(rows.map(itemRows).join(''));
}

function setRows(html) {
  closePopover();  // its button is about to go
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

// Nursing's Pick (named so 2026-10-28; "Picked for Ordering" from 2026-10-21, "Approver's Pick"
// before) is always the Reference SKU
// nursing entered (2026-10-20). With no vendor item yet there's nothing to order: for whoever adds
// them, a pencil says so and opens the form.
function pickCell(pick) {
  if (!pick) return '<span class="text-muted small">—</span>';
  const title = `No vendor item yet: nothing to order for ${pick.reference_sku}`;
  // Only for those who can add a vendor item, whom it takes to the form (2026-10-21): to others it
  // looked like a button that didn't work. Everyone has the Needs details filter.
  const pencil = needsDetails(pick) && can.details
    ? ` <button type="button" class="btn btn-link btn-sm p-0 align-baseline" data-add-vi="${pick.sub_id}"
         title="${esc(title)}. Add one." aria-label="Add a vendor item for ${esc(pick.reference_sku)}"><i
         class="bi bi-pencil-square text-warning"></i></button>`
    : '';
  // Its comments, in a popover (2026-10-21): filled with a count when there are some.
  const n = pick.comments || 0;
  const latest = pick.latest_comment;
  const about = n ? `${n} comment${n > 1 ? 's' : ''}; the latest, by ${latest.actor}: ${latest.comment}` : 'No comments yet';
  const chat = ` <button type="button" class="btn btn-link btn-sm p-0 align-baseline${n ? '' : ' text-muted'}" data-comments="${pick.sub_id}"
      title="${esc(about)}" aria-label="Comments on ${esc(pick.reference_sku)}"><i
      class="bi ${n ? 'bi-chat-left-text-fill' : 'bi-chat-left'}"></i>${n ? `<span class="small ms-1">${n}</span>` : ''}</button>`;
  // The latest, as text under it (2026-10-27): nursing's word reads on the table, without a click.
  const said = n ? `<div class="fk-pick-comment" title="${esc(`${latest.comment}\n${latest.actor}, ${fmtDateTime(latest.acted_at)}`)}">
      <div class="fk-clamp-2">${esc(latest.comment)}</div>
      <div class="text-muted text-nowrap">${esc(shortName(latest.actor))} · ${fmtDate(latest.acted_at)}</div></div>` : '';
  return `<div class="text-nowrap"><span class="fw-semibold">${esc(pick.reference_sku)}</span>${pencil}${chat}</div>${said}`;
}

// --- a pick's comments, an item's instructions ----------------------------------------------

// A pick's comments (2026-10-21), or the item's instructions (2026-10-27), newest first, in a
// popover beside them, so they can be read without opening the item's panel. One is open at a time;
// a click elsewhere or Escape closes it. They're read first and the popover shown with them:
// Bootstrap hides a manual popover whose content is changed while it shows.
let openPopover = null;  // { button, popover }
let loadingPopover = null;  // the button whose list is on its way

function closePopover() {
  loadingPopover = null;
  if (!openPopover) return;
  openPopover.popover.dispose();
  openPopover = null;
}

function commentList(history) {
  const found = history.filter((h) => h.entity === 'sub' && h.action === 'comment');
  if (!found.length) return '<div class="text-muted">No comments yet.</div>';
  return `<ul class="list-unstyled mb-0">${found.map((h) => `<li class="mb-2">
    <div class="text-muted">${esc(fmtDateTime(h.acted_at))} · ${esc(h.actor)}</div><div>${esc(h.comment)}</div></li>`).join('')}</ul>`;
}

// The instructions (Will's Comments on the page, 2026-10-27), newest first: the first is the one in
// force. In the item panel too.
export function instructionList(instructions) {
  if (!instructions.length) return '<div class="text-muted">No comments yet.</div>';
  return `<ul class="list-unstyled mb-0">${instructions.map((i, n) => `<li class="mb-2">
    <div class="text-muted">${esc(fmtDateTime(i.written_at))} · ${esc(i.written_by)}${n === 0 ? ' · latest' : ''}</div>
    <div class="fk-instruction-text">${esc(i.instruction)}</div></li>`).join('')}</ul>`;
}

// ``load`` returns the popover's HTML; ``title`` is already escaped.
async function togglePopover(button, title, load) {
  const again = (openPopover && openPopover.button === button) || loadingPopover === button;
  closePopover();
  if (again || !window.bootstrap) return;
  loadingPopover = button;
  let content;
  try {
    content = await load();
  } catch (error) {
    content = alertBox(error.message);
  }
  // Closed, another opened, or the table redrawn while they were on their way.
  if (loadingPopover !== button || !button.isConnected) return;
  loadingPopover = null;
  const popover = window.bootstrap.Popover.getOrCreateInstance(button, {
    trigger: 'manual', html: true, placement: 'left', customClass: 'fk-comments-popover', title, content,
  });
  openPopover = { button, popover };
  popover.show();
}

function toggleComments(button) {
  const pick = state.rows.flatMap((row) => row.picks).find((s) => s.sub_id === Number(button.dataset.comments));
  return togglePopover(button, `Comments · ${esc(pick ? pick.reference_sku : '')}`,
    async () => commentList((await getJSON(historyUrl('sub', button.dataset.comments))).history));
}

function toggleInstructions(button) {
  const item = button.dataset.instructions;
  const row = state.rows.find((r) => r.medline_items.includes(item));
  return togglePopover(button, `${esc(config.instructionLabel)} · ${esc(row && row.infor_item ? `Infor item ${row.infor_item}` : item)}`,
    async () => instructionList((await getJSON(api.instructions, { item })).instructions));
}

// Vendor Item Detail: a tile per vendor ID, vendor part and UOM of the pick beside it (2026-10-20).
// A Materials Manager records an order from one; whoever adds vendor items can add another here.
// ``several``: the UOM has more than one pick, so the add button names its pick.
function vendorItemsCell(pick, several) {
  if (!pick) return '<span class="text-muted small">—</span>';
  const items = (pick.vendor_items || []).map((v) => {
    // The vendor ID first: a long vendor name is cut short, never the ID.
    const id = v.vendor_id === NO_VENDOR.id ? 'Not in Infor' : v.vendor_id;
    const body = `<div><span class="fw-semibold">${esc(v.vendor_part)}</span> ${esc(uomQoe(v))}${noQoeBadge(v)}</div>
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

// Will's Comments (2026-10-27; "MM Instruction" at first): the MM Lead's latest instruction to the
// sites, the one in force, its first lines (the whole on hover) with who and when. Its icon lists them
// all. An MM Lead adds one by double-clicking the cell (instructionTd), or from the item panel. Not
// tied to the Fill/Kill dates: its date says how old it is.
function instructionCell(row) {
  const info = row.instruction;
  if (!info) return '<span class="text-muted small">—</span>';
  const { latest, count } = info;
  const all = `<button type="button" class="btn btn-link btn-sm p-0 align-baseline" data-instructions="${esc(row.packagings[0].medline_item)}"
      title="${count > 1 ? `All ${count} comments, newest first` : 'The comment, with who wrote it and when'}"
      aria-label="All comments"><i class="bi bi-chat-square-text"></i>${count > 1 ? `<span class="small ms-1">${count}</span>` : ''}</button>`;
  return `<div class="fk-instruction">
    <div class="fk-instruction-text fk-clamp-3" title="${esc(latest.instruction)}">${esc(latest.instruction)}</div>
    <div class="text-muted text-nowrap" title="${esc(latest.written_by)}">${esc(shortName(latest.written_by))} · ${fmtDateTime(latest.written_at)}
      ${all}</div></div>`;
}

// Double-click a cell to write in it (the user, 2026-10-27), for those who may: Will's Comments for
// an MM Lead, Nursing's Pick for whoever adds subs (a new sub for that line's Medline item).
const dblClickTd = (attrs, title) => `<td ${attrs} data-dblclick title="${esc(title)}"`;

function instructionTd(row, all) {
  if (!can.instruct) return `<td data-to-end${all}>`;
  return `${dblClickTd(`data-to-end${all} data-instruct="${esc(row.packagings[0].medline_item)}"`,
    `Double-click to add a comment for the sites' Materials Managers`)}>`;
}

function pickTd(p, split) {
  if (!can.add_sub) return `<td${split}>`;
  return `${dblClickTd(`${split.trim()} data-add-sub="${esc(p.medline_item)}"`, `Double-click to add a sub for ${p.medline_item}`)}>`;
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
  // Each with its site (2026-10-27): each site orders for itself.
  const lines = row.orders.slice(0, ORDERS_SHOWN).map((o) => `<div class="small text-nowrap">${fmtNumber(o.quantity)}
    <span class="text-muted">${esc(o.uom)}</span> · <span class="fk-site${o.site ? '' : ' text-muted'}" title="${esc(siteName(o.site))}${o.po_number
      ? ` · PO ${esc(o.po_number)}` : ''}">${esc(o.site ? siteName(o.site) : 'no site')}</span> · ${fmtDate(o.ordered_dt)}</div>`).join('');
  const more = row.orders.length > ORDERS_SHOWN ? `<div class="small text-muted">+${row.orders.length - ORDERS_SHOWN} more</div>` : '';
  return `<span class="badge text-bg-success">Ordered</span>${lines}${more}`;
}

// Killed and ordered in these dates, in eaches, for the Infor item (2026-10-21). Kill lines come in
// through the day, so an item ordered for 10 EA in the morning may need more once 30 EA are killed.
const eachesUnknown = (why) => `<span class="text-muted" title="${esc(why)}">—</span>`;
const eachesText = (n) => `${fmtNumber(n)} <span class="text-muted small">EA</span>`;

// The sites that killed the item in these dates (2026-10-27): each orders for itself.
const killedSites = (row) => (row.sites || []).filter((s) => s.site && s.kills.some((k) => k.killed > 0));
const eachesOrUnknown = (n) => (n == null ? "can't be counted" : `${fmtNumber(n)} EA`);

function killedEachCell(row) {
  if (row.killed_each == null) return eachesUnknown("A UOM killed has no QOE in Infor, so it can't be counted in eaches");
  const sites = killedSites(row);
  if (sites.length < 2) return eachesText(row.killed_each);
  const each = sites.map((s) => `${siteName(s.site)}: ${eachesOrUnknown(s.killed_each)}`).join('\n');
  return `<span title="${esc(each)}">${eachesText(row.killed_each)}</span><div class="small text-muted">${sites.length} sites</div>`;
}

// With orders that fall short of what was killed, how many eaches short: with kills at several
// sites, each site that's short (2026-10-27), since each orders for itself.
function subOrderedEachCell(row) {
  if (!row.orders.length) return `<span class="text-muted">${eachesText(0)}</span>`;
  if (row.sub_ordered_each == null) {
    return eachesUnknown("An order's UOM has no QOE, so it can't be counted in eaches. Correct the order to add its QOE.");
  }
  const shortBy = (killed, ordered) => (killed != null && ordered != null && ordered < killed - 1e-9 ? killed - ordered : 0);
  const sites = killedSites(row);
  let short;
  if (sites.length > 1) {
    short = sites.filter((s) => shortBy(s.killed_each, s.sub_ordered_each)).map((s) => `<div class="small text-danger fw-semibold
      text-nowrap"><span class="fk-site" title="${esc(siteName(s.site))}">${esc(siteName(s.site))}</span>:
      ${fmtNumber(shortBy(s.killed_each, s.sub_ordered_each))} EA short</div>`).join('');
  } else {
    const by = shortBy(row.killed_each, row.sub_ordered_each);
    short = by ? `<div class="small text-danger fw-semibold">${fmtNumber(by)} EA short</div>` : '';
  }
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
        ${pickTd(p, split)}${pickCell(pick)}</td>
        ${first ? `${instructionTd(row, all)}${instructionCell(row)}</td>` : ''}
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
  // A pick's comments, or an item's instructions, close on a click outside them, or Escape.
  document.addEventListener('click', (event) => {
    if ((openPopover || loadingPopover) && !event.target.closest('.fk-comments-popover, [data-comments], [data-instructions]')) {
      closePopover();
    }
  });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closePopover(); });
  mainTable.addEventListener('click', (event) => {
    const commentsButton = event.target.closest('[data-comments]');
    if (commentsButton) {
      toggleComments(commentsButton);
      return;
    }
    const instructionsButton = event.target.closest('[data-instructions]');
    if (instructionsButton) {
      toggleInstructions(instructionsButton);
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
  // A cell's buttons keep their own click: double-clicking one doesn't open the form too.
  mainTable.addEventListener('dblclick', (event) => {
    const cell = event.target.closest('td[data-dblclick]');
    if (!cell || event.target.closest('button, a')) return;
    window.getSelection()?.removeAllRanges();  // the word the double-click selected
    closePopover();
    if (cell.dataset.instruct) openInstructionForm(state.rows.find((row) => row.medline_items.includes(cell.dataset.instruct)));
    else if (cell.dataset.addSub) openAddSubForm(cell.dataset.addSub);
  });
}
