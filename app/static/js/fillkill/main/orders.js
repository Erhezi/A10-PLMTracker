/* Main: the orders under the table, by their own date, with dates of their own (the table's dates
 * don't change them), so a Materials Manager can look up past orders right here. Default: the
 * last 30 days. A search box narrows them by number (2026-10-20). Every sub is on the Subs page.
 */

import { $, NO_VENDOR, alertBox, config, debounce, esc, fmtDateTime, fmtNumber, getJSON } from '../common.js';
import { openPanel } from './panel.js';
import { api, state } from './state.js';

const shiftDay = (iso, days) => {
  const day = new Date(`${iso}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() + days);
  return day.toISOString().slice(0, 10);
};

function setOrdersDays(days) {
  state.ordersEnd = config.today;
  state.ordersStart = shiftDay(config.today, 1 - days);
}

export function setupOrders() {
  const startInput = $('fk-orders-start');
  const endInput = $('fk-orders-end');
  if (!state.ordersStart || !state.ordersEnd) setOrdersDays(config.ordersDays);
  [startInput, endInput].forEach((input) => { input.max = config.today; });
  const show = () => {
    startInput.value = state.ordersStart;
    endInput.value = state.ordersEnd;
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
  document.querySelectorAll('[data-orders-days]').forEach((button) => button.addEventListener('click', () => {
    setOrdersDays(Number(button.dataset.ordersDays));
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
    const data = await getJSON(api.orders, { start: state.ordersStart, end: state.ordersEnd });
    state.orders = data.orders;
    renderOrders();
  } catch (error) {
    state.orders = [];
    $('fk-orders-rows').innerHTML = `<tr><td colspan="10">${alertBox(error.message)}</td></tr>`;
  }
}

// Every word must be one of the order's numbers, or part of one: the Medline item, its Infor item,
// the sub's vendor part (and as entered), manufacturer part or Infor item. Dashes, spaces, dots and
// slashes don't count, so "bd930" finds B-D930299Z.
const compact = (value) => String(value || '').toLowerCase().replace(/[\s\-./]/g, '');
const ORDER_NUMBERS = ['medline_item', 'medline_infor_item', 'sub_label', 'sub_entered_part', 'sub_manufacturer_part', 'sub_infor_item'];

function matches(order, words) {
  const numbers = ORDER_NUMBERS.map((key) => compact(order[key])).join(' ');
  return words.every((word) => numbers.includes(word));
}

function renderOrders() {
  const body = $('fk-orders-rows');
  const words = $('fk-orders-q').value.split(/\s+/).map(compact).filter(Boolean);
  const orders = (state.orders || []).filter((o) => matches(o, words));
  if (!orders.length) {
    const why = state.orders && state.orders.length ? 'No order in these dates matches.' : 'No orders recorded in these dates.';
    body.innerHTML = `<tr><td colspan="10" class="text-muted small">${why}</td></tr>`;
    return;
  }
  body.innerHTML = orders.map((o) => {
    const voided = Boolean(o.voided_at);
    const entered = o.sub_entered_part && o.sub_entered_part !== o.sub_label
      ? `<div class="small text-muted">entered as ${esc(o.sub_entered_part)}</div>` : '';
    const vendorId = o.vendor_id === NO_VENDOR.id
      ? `${esc(o.vendor_id)}<div class="small text-muted">not in Infor</div>` : esc(o.vendor_id || '');
    return `<tr class="${voided ? 'text-muted' : ''}">
      <td class="text-nowrap">${fmtDateTime(o.ordered_dt)}</td>
      <td><button type="button" class="btn btn-link btn-sm p-0" data-open="${esc(o.medline_item)}">${esc(o.medline_item)}</button></td>
      <td>${o.medline_infor_item ? `<button type="button" class="btn btn-link btn-sm p-0" data-open="${esc(o.medline_item)}"
          data-scope="infor" title="All UOMs of this Infor item">${esc(o.medline_infor_item)}</button>` : '<span class="text-muted">—</span>'}</td>
      <td>${esc(o.sub_label)}${entered}</td>
      <td class="text-end">${o.qoe != null ? fmtNumber(o.qoe) : '<span class="text-muted">—</span>'}</td>
      <td class="text-end text-nowrap ${voided ? 'text-decoration-line-through' : ''}">${fmtNumber(o.quantity)}
        <span class="text-muted small">${esc(o.uom)}</span></td>
      <td class="text-nowrap">${vendorId}</td>
      <td>${esc(o.vendor)}</td>
      <td>${esc(o.ordered_by)}${voided ? ' <span class="badge text-bg-secondary">Voided</span>' : ''}</td>
      <td>${o.latest_comment ? esc(o.latest_comment.comment) : ''}</td>
    </tr>`;
  }).join('');
}
