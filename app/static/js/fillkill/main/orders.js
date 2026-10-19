/* Main: the orders under the table, by their own date, with dates of their own (the table's dates
 * don't change them), so a Materials Manager can look up past orders right here. Default: the
 * last 30 days. Every sub is on the Subs page.
 */

import { $, alertBox, config, esc, fmtDateTime, fmtNumber, getJSON } from '../common.js';
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

  $('fk-orders-rows').addEventListener('click', (event) => {
    const opener = event.target.closest('[data-open]');
    if (opener) openPanel(opener.dataset.open, 'orders');
  });
}

export async function loadOrders() {
  const body = $('fk-orders-rows');
  try {
    const data = await getJSON(api.orders, { start: state.ordersStart, end: state.ordersEnd });
    body.innerHTML = data.orders.length ? data.orders.map((o) => `<tr class="${o.voided_at ? 'text-muted' : ''}">
        <td class="small text-nowrap">${fmtDateTime(o.ordered_dt)}</td>
        <td><button type="button" class="btn btn-link p-0" data-open="${esc(o.medline_item)}">${esc(o.medline_item)}</button></td>
        <td>${esc(o.sub_label)}</td>
        <td class="text-end ${o.voided_at ? 'text-decoration-line-through' : ''}">${fmtNumber(o.quantity)} ${esc(o.uom)}</td>
        <td class="small">${esc(o.vendor)}</td>
        <td class="small">${esc(o.ordered_by)}${o.voided_at ? ' <span class="badge text-bg-secondary">Voided</span>' : ''}</td>
        <td class="small">${o.latest_comment ? esc(o.latest_comment.comment) : ''}</td>
      </tr>`).join('')
      : '<tr><td colspan="7" class="text-muted small">No orders recorded in these dates.</td></tr>';
  } catch (error) {
    body.innerHTML = `<tr><td colspan="7">${alertBox(error.message)}</td></tr>`;
  }
}
