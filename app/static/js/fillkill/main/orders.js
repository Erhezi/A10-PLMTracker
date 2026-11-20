/* Main: Sub Orders Recorded (2026-11-19; "Orders Recorded" before), under the table: the orders by
 * their own date, with dates of their own (the table's dates don't change them), so a Materials
 * Manager can look up past orders right here. Default: today (2026-11-19; the last 30 days before).
 * The table's sites do apply (2026-10-27): a site sees its own orders. A search box narrows them by
 * number (2026-10-20). Every sub is on the Subs page.
 */

import { $, NO_VENDOR, alertBox, config, debounce, esc, fmtDateTime, fmtNumber, getJSON, markQuickDays, shiftDay } from '../common.js';
import { openPanel } from './panel.js';
import { api, siteName, state } from './state.js';

function setOrdersDays(days) {
  state.ordersEnd = config.today;
  state.ordersStart = shiftDay(config.today, 1 - days);
}

export function setupOrders() {
  const startInput = $('fk-orders-start');
  const endInput = $('fk-orders-end');
  const quick = $('fk-orders-quick');
  if (!state.ordersStart || !state.ordersEnd) setOrdersDays(config.ordersDays);
  [startInput, endInput].forEach((input) => { input.max = config.today; });
  const show = () => {
    startInput.value = state.ordersStart;
    endInput.value = state.ordersEnd;
    markQuickDays(quick, state.ordersStart, state.ordersEnd);
  };
  const fromInputs = () => {
    if (!startInput.value || !endInput.value) return;
    [state.ordersStart, state.ordersEnd] = startInput.value <= endInput.value
      ? [startInput.value, endInput.value] : [endInput.value, startInput.value];
    show();
    loadOrders();
  };
  startInput.addEventListener('change', fromInputs);
  endInput.addEventListener('change', fromInputs);
  quick.querySelectorAll('[data-days]').forEach((button) => button.addEventListener('click', () => {
    setOrdersDays(Number(button.dataset.days));
    show();
    loadOrders();
  }));
  show();

  $('fk-orders-q').addEventListener('input', debounce(renderOrders, 150));
  $('fk-orders-rows').addEventListener('click', (event) => {
    const opener = event.target.closest('[data-open]');
    if (opener) openPanel(opener.dataset.open, 'orders', opener.dataset.scope);
  });
}

export async function loadOrders() {
  try {
    const data = await getJSON(api.orders, { start: state.ordersStart, end: state.ordersEnd, sites: state.sites });
    state.orders = data.orders;
    renderOrders();
  } catch (error) {
    state.orders = [];
    $('fk-orders-rows').innerHTML = `<tr><td colspan="12">${alertBox(error.message)}</td></tr>`;
  }
}

// Every word must be one of the order's numbers, or part of one: the Medline item, its Infor item,
// the vendor part ordered, the sub's Reference SKU, the vendor item's manufacturer part or Infor item,
// the PO number (2026-10-27). Dashes, spaces, dots and slashes don't count, so "bd930" finds B-D930299Z.
const compact = (value) => String(value || '').toLowerCase().replace(/[\s\-./]/g, '');
const ORDER_NUMBERS = ['medline_item', 'medline_infor_item', 'vendor_part', 'reference_sku', 'manufacturer_part', 'infor_item',
  'po_number'];

function matches(order, words) {
  const numbers = ORDER_NUMBERS.map((key) => compact(order[key])).join(' ');
  return words.every((word) => numbers.includes(word));
}

function renderOrders() {
  const body = $('fk-orders-rows');
  const words = $('fk-orders-q').value.split(/\s+/).map(compact).filter(Boolean);
  const orders = (state.orders || []).filter((o) => matches(o, words));
  if (!orders.length) {
    const why = state.orders && state.orders.length ? 'No order in these dates matches.'
      : `No orders recorded in these dates${state.sites.length ? ' for these sites' : ''}.`;
    body.innerHTML = `<tr><td colspan="12" class="text-muted small">${why}</td></tr>`;
    return;
  }
  body.innerHTML = orders.map((o) => {
    const voided = Boolean(o.voided_at);
    const vendorId = o.vendor_id === NO_VENDOR.id
      ? `${esc(o.vendor_id)}<div class="small text-muted">not in Infor</div>` : esc(o.vendor_id || '');
    return `<tr class="${voided ? 'text-muted' : ''}">
      <td class="text-nowrap">${fmtDateTime(o.ordered_dt)}</td>
      <td>${o.site ? esc(siteName(o.site)) : '<span class="text-muted">—</span>'}</td>
      <td><button type="button" class="btn btn-link btn-sm p-0" data-open="${esc(o.medline_item)}">${esc(o.medline_item)}</button></td>
      <td>${o.medline_infor_item ? `<button type="button" class="btn btn-link btn-sm p-0" data-open="${esc(o.medline_item)}"
          data-scope="infor" title="All UOMs of this Infor item">${esc(o.medline_infor_item)}</button>` : '<span class="text-muted">—</span>'}</td>
      <td class="fw-semibold">${esc(o.vendor_part)}</td>
      <td class="text-end">${o.qoe != null ? fmtNumber(o.qoe) : '<span class="text-muted">—</span>'}</td>
      <td class="text-end text-nowrap ${voided ? 'text-decoration-line-through' : ''}">${fmtNumber(o.quantity)}
        <span class="text-muted small">${esc(o.uom)}</span></td>
      <td class="text-nowrap">${esc(o.po_number || '')}</td>
      <td class="text-nowrap">${vendorId}</td>
      <td>${esc(o.vendor)}</td>
      <td>${esc(o.ordered_by)}${voided ? ' <span class="badge text-bg-secondary">Voided</span>' : ''}</td>
      <td>${o.latest_comment ? esc(o.latest_comment.comment) : ''}</td>
    </tr>`;
  }).join('');
}
