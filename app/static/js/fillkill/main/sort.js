/* Main: sorting the table by a header (the user, 2026-11-16). Each Infor item moves as one, its UOMs
 * and approved subs with it. The first click sorts text A to Z and numbers and dates largest or newest
 * first; the second, the other way; the third goes back to the table's own order (Infor item,
 * Medline item, description). Blanks stay last either way, and ties keep the table's own order.
 * The page link keeps the sort (?sort=&dir=).
 */

import { $, esc } from '../common.js';
import { state } from './state.js';
import { renderRows } from './table.js';

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });
const sum = (values) => values.reduce((total, n) => total + (Number(n) || 0), 0);
const quantities = (row) => row.packagings.flatMap((p) => p.quantities);

// Ordered, killed and filled: in eaches when every UOM has a QOE, so a case outweighs an each;
// otherwise the quantities as they are.
const total = (key) => (row) => (row.quantities_each ? row.quantities_each[key] : sum(quantities(row).map((q) => q[key])));

// Each sortable column (its header's data-sort): 'text', or 'number' (dates too), and the Infor
// item's value; null or '' is blank. A list sorts by its first value, then the next.
const SORTS = {
  infor_item: ['text', (row) => row.infor_item],
  medline_item: ['text', (row) => row.medline_items[0]],
  description: ['text', (row) => row.description],
  // The largest QOE among its UOMs.
  qoe: ['number', (row) => {
    const each = quantities(row).map((q) => q.each).filter((n) => n != null);
    return each.length ? Math.max(...each) : null;
  }],
  ordered: ['number', total('ordered')],
  killed: ['number', total('killed')],
  filled: ['number', total('filled')],
  lines: ['number', (row) => row.lines],
  // Medline's reason type, then its date (Est Avail Date).
  reason: ['text', (row) => (row.latest_reason && row.latest_reason.reason
    ? [row.latest_reason.reason, String(row.latest_reason.reason_date || '')] : null)],
  // How many subs, then how many approved.
  subs: ['number', (row) => [sum(Object.values(row.subs_status || {})), (row.subs_status || {}).approved || 0]],
  approved: ['number', (row) => row.approved_subs.length],
  // The latest SCM comment's date.
  instruction: ['number', (row) => (row.instruction ? row.instruction.latest.written_at : null)],
  // How many vendor items: the approved subs' and those without a sub.
  vendor_items: ['number', (row) => sum(row.approved_subs.map((s) => (s.vendor_items || []).length))
    + sum(row.packagings.map((p) => p.vendor_items.length))],
  // The latest order's date (row.orders is newest first).
  ordering: ['number', (row) => (row.orders.length ? row.orders[0].ordered_dt : null)],
  killed_each: ['number', (row) => row.killed_each],
  sub_ordered_each: ['number', (row) => row.sub_ordered_each],
};

const blank = (value) => value == null || value === '' || (Array.isArray(value) && blank(value[0]));

function compare(a, b) {
  if (Array.isArray(a)) {
    for (let i = 0; i < a.length; i += 1) {
      const found = compare(a[i], b[i]);
      if (found) return found;
    }
    return 0;
  }
  return typeof a === 'number' && typeof b === 'number' ? a - b : collator.compare(String(a), String(b));
}

// The rows in the chosen order: a new list, or the same one with no sort.
export function sortRows(rows) {
  const sort = state.sort && SORTS[state.sort.key];
  if (!sort) return rows;
  const sign = state.sort.dir === 'asc' ? 1 : -1;
  const keyed = rows.map((row) => ({ row, value: sort[1](row) }));
  keyed.sort((a, b) => {
    const [blankA, blankB] = [blank(a.value), blank(b.value)];
    if (blankA || blankB) return blankA - blankB;
    return sign * compare(a.value, b.value);
  });
  return keyed.map((k) => k.row);
}

function showSort() {
  $('fk-main').tHead.querySelectorAll('th[data-sort]').forEach((th) => {
    const dir = state.sort && state.sort.key === th.dataset.sort ? state.sort.dir : null;
    if (dir) th.setAttribute('aria-sort', dir === 'asc' ? 'ascending' : 'descending');
    else th.removeAttribute('aria-sort');
    th.querySelector('.fk-sort-icon').className = `bi fk-sort-icon ${{ asc: 'bi-arrow-up', desc: 'bi-arrow-down' }[dir]
      || 'bi-arrow-down-up'}`;
  });
}

export function setupSort() {
  if (state.sort && !SORTS[state.sort.key]) state.sort = null;  // a link from another version
  const head = $('fk-main').tHead;
  // The arrow stays with the label's last word, never on a line of its own.
  head.querySelectorAll('th[data-sort] .fk-sort').forEach((button) => {
    const words = button.textContent.trim().split(/\s+/);
    const last = words.pop();
    button.innerHTML = `${words.length ? `${esc(words.join(' '))} ` : ''}<span class="text-nowrap">${esc(last)}`
      + '<i class="bi fk-sort-icon" aria-hidden="true"></i></span>';
  });
  head.addEventListener('click', (event) => {
    const button = event.target.closest('.fk-sort');
    if (!button) return;
    const key = button.closest('th').dataset.sort;
    const first = SORTS[key][0] === 'text' ? 'asc' : 'desc';
    if (!state.sort || state.sort.key !== key) state.sort = { key, dir: first };
    else if (state.sort.dir === first) state.sort = { key, dir: first === 'asc' ? 'desc' : 'asc' };
    else state.sort = null;
    showSort();
    renderRows();
  });
  showSort();
}
