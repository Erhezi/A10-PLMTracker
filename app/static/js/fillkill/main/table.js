/* Main: the table. Each Infor item is a <tbody> of its own, so its UOMs highlight together, with a
 * <tr> per Medline item (UOM) and, with several, a last <tr> adding them up in eaches.
 */

import {
  $, REASON_LABEL, STATUS_ORDER, alertBox, esc, fmtDate, fmtDateTime, fmtNumber, getJSON, needsDetails,
  statusBadge, subText, vendorText,
} from '../common.js';
import { renderNeeds } from './controls.js';
import { openOrderForm } from './forms.js';
import { openPanel } from './panel.js';
import { api, can, scopeParams, state, syncLink } from './state.js';

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

export function renderRows() {
  syncLink();
  const rows = state.rows.filter((row) => (state.needs === 'all' || row.needs.includes(state.needs)) && matchesSearch(row));
  if (!rows.length) {
    const why = state.rows.length ? 'No item matches these filters.' : 'No kill lines for these dates and sites.';
    setRows(`<tbody><tr><td colspan="12" class="text-muted small p-3">${why}</td></tr></tbody>`);
    return;
  }
  setRows(rows.map(itemRows).join(''));
}

function setRows(html) {
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
  const subs = approved.map((a) => `${subText(a)} on ${a.medline_item}`).join('\n');
  return `<div class="small text-success mt-1" title="${esc(subs)}"><i class="bi bi-box-seam"></i>
    ${approved.length} approved for another UOM: ${esc(items.join(', '))}</div>`;
}

function picksCell(picks) {
  if (!picks.length) return '<span class="text-muted small">—</span>';
  return picks.map((pick) => {
    const vendor = vendorText(pick);
    const label = `${esc(pick.vendor_part)}${vendor ? ` <span class="text-muted">· ${esc(vendor)}</span>` : ''}${needsDetails(pick)
      ? ' <i class="bi bi-pencil-square text-warning" title="Vendor details to fill in"></i>' : ''}`;
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

// Orders placed since the first selected day: quantity, UOM and date, newest first.
const ORDERS_SHOWN = 3;

function orderingCell(row) {
  if (!row.orders.length) return '<span class="badge text-bg-light border">No order</span>';
  const lines = row.orders.slice(0, ORDERS_SHOWN).map((o) => `<div class="small text-nowrap">${fmtNumber(o.quantity)}
    <span class="text-muted">${esc(o.uom)}</span> · ${fmtDate(o.ordered_dt)}</div>`).join('');
  const more = row.orders.length > ORDERS_SHOWN ? `<div class="small text-muted">+${row.orders.length - ORDERS_SHOWN} more</div>` : '';
  return `<span class="badge text-bg-success">Ordered</span>${lines}${more}`;
}

// --- rows ------------------------------------------------------------------------------------

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

export function setupTable() {
  mainTable.addEventListener('click', (event) => {
    const orderButton = event.target.closest('[data-order-sub]');
    if (orderButton) {
      openOrderForm(Number(orderButton.dataset.orderSub), orderButton.dataset.item);
      return;
    }
    const opener = event.target.closest('[data-open]');
    if (opener) openPanel(opener.dataset.open, opener.dataset.tab || null, opener.dataset.scope);
  });
}
