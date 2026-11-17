/* Fill/Kill: what the Main, Subs and Dashboard pages share.
 *
 * The pages' scripts are ES modules (2026-10-19), loaded with <script type="module">: they run once
 * the page is parsed, after base.html has loaded Bootstrap and defined appFetch (which adds the
 * CSRF token). Each page renders its settings as JSON in #fk-config.
 */

export const $ = (id) => document.getElementById(id);

export const config = JSON.parse($('fk-config').textContent);
config.statusLabels = Object.fromEntries(config.statuses || []);

export const esc = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (ch) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
));

export const STATUS_CLASS = {
  approved: 'text-bg-success', hold: 'text-bg-warning', pending_review: 'text-bg-info', rejected: 'text-bg-danger',
};
export const STATUS_ORDER = ['approved', 'hold', 'pending_review', 'rejected'];

export function statusBadge(status, extra) {
  return `<span class="badge ${STATUS_CLASS[status] || 'text-bg-secondary'}${extra ? ' ' + extra : ''}">`
    + `${esc(config.statusLabels[status] || status)}</span>`;
}

export function fmtDate(iso) {
  if (!iso) return '';
  const [y, m, d] = String(iso).slice(0, 10).split('-');
  return `${m}/${d}/${y}`;
}

export function fmtDateTime(iso) {
  if (!iso) return '';
  const text = String(iso);
  return `${fmtDate(text)} ${text.slice(11, 16)}`.trim();
}

// Who, short: the part of the email before the @ (the whole email goes in a title).
export const shortName = (email) => String(email || '').split('@')[0];

export function fmtNumber(value) {
  if (value == null || value === '') return '';
  const n = Number(value);
  return Number.isInteger(n) ? n.toLocaleString() : n.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

// A path with a query; empty values and empty lists are left out.
export function url(path, params) {
  const query = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      if (value.length) query.set(key, value.join(','));
    } else if (value != null && value !== '') {
      query.set(key, value);
    }
  });
  const qs = query.toString();
  return qs ? `${path}?${qs}` : path;
}

export async function getJSON(path, params) {
  const response = await window.appFetch(url(path, params));
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || `The server answered ${response.status}.`);
  return data;
}

// A refused change throws an error carrying the HTTP status (409: someone changed it meanwhile).
export async function postJSON(path, payload) {
  const response = await window.appFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.message || `The server answered ${response.status}.`);
    error.status = response.status;
    throw error;
  }
  return data;
}

// ``fn`` once calls stop for ``ms``; ``.cancel()`` drops a call still waiting.
export function debounce(fn, ms) {
  let timer = null;
  const debounced = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
  debounced.cancel = () => clearTimeout(timer);
  return debounced;
}

export function alertBox(message, kind) {
  return `<div class="alert alert-${kind || 'danger'} py-2 small mb-2" role="alert">${esc(message)}</div>`;
}

// The vendor ID that says Infor has no such vendor (2026-10-19; rules.NO_VENDOR_ID).
export const NO_VENDOR = config.noVendor || { id: '0000000', label: 'Vendor not available in system' };

// A vendor item's or an order's vendor: its name, with Infor's vendor ID.
export function vendorText(v) {
  const id = v.vendor_id === NO_VENDOR.id ? 'not in Infor' : v.vendor_id;
  return `${v.vendor || ''}${id ? ` (${id})` : ''}`;
}

// A UOM with its QOE, as "CA/400" (2026-10-20; "CA × 400" read like a quantity).
export const uomQoe = (v) => `${v.uom || ''}${v.qoe ? `/${fmtNumber(v.qoe)}` : ''}`;

// A vendor item as text: the vendor part, its vendor, and the UOM with its QOE.
export function vendorItemText(v) {
  return `${v.vendor_part} · ${vendorText(v)} · ${uomQoe(v)}`;
}

// A sub needs a vendor item to be ordered (2026-10-20); nursing leaves them to the Materials Manager.
export const needsDetails = (s) => !(s.vendor_items || []).length;

// The add-sub boxes' hints, in the panel and the modal (the user, 2026-11-02).
export const REFERENCE_SKU_HINT = 'The reference manufacturer part or vendor part number, e.g. B-D903245';
export const SUB_NOTE_HINT = 'Optional: additional comments on the product, e.g. supplier, key clinical feature';

// Medline's vendor IDs in Infor (2026-10-20; rules.MEDLINE_VENDOR_IDS). A vendor item from one of
// them whose vendor part is the Medline item itself is the item that was killed, not a sub.
export const MEDLINE_VENDOR_IDS = config.medlineVendorIds || ['1000931', '1017968', '1017969', '1037888'];
export const isTheKilledItem = (medlineItem, part, vendorId) => Boolean(medlineItem && part)
  && MEDLINE_VENDOR_IDS.includes(String(vendorId || '').trim())
  && String(part).trim().toUpperCase() === String(medlineItem).trim().toUpperCase();

// A UOM as Infor has it (2026-10-20): typed another way (CS for CA, VL for VI), Infor's; otherwise
// as typed, upper-cased. The server saves it the same way (rules.infor_uom).
const UOM_ALIASES = config.uomAliases || {};
export function inforUom(uom) {
  const text = String(uom || '').trim().toUpperCase();
  return UOM_ALIASES[text] || text;
}

// A vendor item (or order) without a QOE, in a UOM other than EA (an EA is 1): flagged wherever it
// shows, since how many to order can't be worked out without it (2026-10-21).
export const noQoeBadge = (v) => (v.qoe || inforUom(v.uom) === 'EA' ? ''
  : ' <span class="badge text-bg-warning" title="No QOE: how many eaches it holds is unknown, so the order form can\'t recommend a quantity. Correct it to add the QOE.">no QOE</span>');

// Leading and trailing spaces typed or pasted into a box go as soon as it's left (2026-10-20); the
// server drops them too. Returns whether the box changed.
export function trimInput(el) {
  const boxed = el && (el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && ['text', 'search'].includes(el.type)));
  if (!boxed || el.value === el.value.trim()) return false;
  el.value = el.value.trim();
  return true;
}

export const trimOnChange = (root) => root.addEventListener('change', (event) => trimInput(event.target));

// A form's values, each trimmed.
export const formValues = (form) => Object.fromEntries([...new FormData(form).entries()]
  .map(([key, value]) => [key, typeof value === 'string' ? value.trim() : value]));

// An item's panel on Main, from the Subs page or the Dashboard: ?item=<Medline item>, with
// scope 'infor' for all its UOMs and a tab (subs, lines, history, orders).
export const itemLink = (item, scope, tab) => url(config.mainPage, { item, scope, tab });
