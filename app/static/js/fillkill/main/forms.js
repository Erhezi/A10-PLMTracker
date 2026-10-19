/* Main: the forms in the modal: vendor details (with the contract search and the vendor ID check),
 * record, correct and void an order, correct a sub's vendor part, delete a sub.
 */

import {
  $, alertBox, debounce, esc, fmtNumber, getJSON, needsDetails, postJSON, subText,
} from '../common.js';
import { panelSubs } from './panel.js';
import { afterChange } from './refresh.js';
import { api, orderUrl, state, subUrl } from './state.js';

const modalEl = $('fk-modal');
const modal = window.bootstrap ? window.bootstrap.Modal.getOrCreateInstance(modalEl) : null;
const modalForm = $('fk-modal-form');
let modalSubmit = null;

// Bootstrap ignores show() while the modal fades out and hide() while it fades in, so a quick
// "save, then open the next form" would be lost. Track the fade and wait for it to finish.
let modalPhase = 'hidden';  // hidden | showing | shown | hiding

function whenModal(phase, action) {
  if (modalPhase === phase) action();
  else modalEl.addEventListener(`${phase}.bs.modal`, action, { once: true });
}

function openModal() {
  if (!modal || modalPhase === 'shown' || modalPhase === 'showing') return;
  whenModal('hidden', () => modal.show());
}

function hideModal() {
  if (!modal || modalPhase === 'hidden' || modalPhase === 'hiding') return;
  whenModal('shown', () => modal.hide());
}

// ``onSubmit`` gets the form's values and returns a promise of the message to show.
function showModal(title, fields, submitLabel, onSubmit) {
  modalForm.innerHTML = `
    <div class="modal-header"><h2 class="modal-title h5" id="fk-modal-title">${title}</h2>
      <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>
    <div class="modal-body"><div id="fk-modal-message"></div><div class="row g-2">${fields}</div></div>
    <div class="modal-footer"><button type="button" class="btn btn-sm btn-link" data-bs-dismiss="modal">Cancel</button>
      <button type="submit" class="btn btn-sm btn-primary">${submitLabel}</button></div>`;
  modalSubmit = onSubmit;
  openModal();
}

const field = (name, label, value, attrs, col) => `
  <div class="col-${col || 6}"><label class="form-label small mb-0" for="fk-m-${name}">${label}</label>
    <input class="form-control form-control-sm" id="fk-m-${name}" name="${name}" value="${esc(value == null ? '' : value)}" ${attrs || ''}></div>`;

const plainNumber = (value) => (value != null ? fmtNumber(value).replace(/,/g, '') : '');

function nowLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

// A pick from the panel (any UOM) or from the main table.
function findSub(subId) {
  return panelSubs().concat(...state.rows.map((row) => row.picks)).find((s) => s.sub_id === subId) || null;
}

// --- the contract search ---------------------------------------------------------------------

// Whether the contract line is available for MHS (on a contract of MMAHS organization 105188574).
// A non-MHS line can still be chosen; the badge only says so.
function contractMhsBadge(line) {
  return line.is_mhs === 'Yes'
    ? '<span class="badge text-bg-success ms-auto">MHS</span>'
    : '<span class="badge text-bg-warning ms-auto" title="Not on an MHS contract. You can still choose it.">Non-MHS</span>';
}

const searchContracts = debounce(async (q) => {
  const box = $('fk-contract-results');
  if (!box) return;
  if (q.replace(/\s/g, '').length < 3) { box.innerHTML = ''; return; }
  box.innerHTML = '<span class="text-muted">Searching…</span>';
  try {
    const data = await getJSON(api.contractLines, { q });
    if (!$('fk-contract-q') || $('fk-contract-q').value !== q) return;
    if (!data.lines.length) { box.innerHTML = '<span class="text-muted">No active contract line found; fill in the details below.</span>'; return; }
    state.contractLines = data.lines;
    box.innerHTML = `<div class="list-group">${data.lines.map((line, i) => {
      const facts = [
        line.infor_item ? `Infor item ${esc(line.infor_item)}` : 'No Infor item',
        `${esc(line.uom)}${line.qoe ? ` × ${fmtNumber(line.qoe)}` : ''}`,
        line.contracts > 1 ? `${line.contracts} contracts${line.mhs_contracts && line.mhs_contracts < line.contracts
          ? ` (${line.mhs_contracts} MHS)` : ''}` : '',
      ].filter(Boolean).join(' · ');
      return `
      <button type="button" class="list-group-item list-group-item-action py-1" data-contract="${i}">
        <div class="d-flex gap-2 align-items-baseline">
          <span><span class="fw-semibold">${esc(line.vendor_item)}</span> · ${esc(line.vendor_name)}
            <span class="text-muted">(vendor ${esc(line.vendor_id)})</span></span>
          ${contractMhsBadge(line)}
        </div>
        <div class="text-muted">${facts}</div>
        <div class="text-muted text-truncate">${esc(line.description)}</div>
      </button>`;
    }).join('')}</div>`;
  } catch (error) {
    box.innerHTML = alertBox(error.message);
  }
}, 350);

// A contract line fills in the vendor details; the sub's vendor part stays nursing's, and a line
// for another vendor item (another packaging, say) is pointed out.
function fillFromContract(line) {
  const part = $('fk-contract-q').dataset.part || '';
  const bare = (value) => String(value || '').toUpperCase().replace(/[\s\-./]/g, '');
  $('fk-contract-note').textContent = part && bare(line.vendor_item) !== bare(part)
    ? `This contract line is for vendor item ${line.vendor_item}; the sub's vendor part is ${part}.` : '';
  $('fk-m-vendor_id').value = line.vendor_id || '';
  vendorNote($('fk-m-vendor_id'), '');
  $('fk-m-vendor').value = line.vendor_name || '';
  $('fk-m-vendor').dataset.autofilled = '1';
  $('fk-m-description').value = line.description || '';
  $('fk-m-uom').value = line.uom || '';
  $('fk-m-qoe').value = plainNumber(line.qoe);
}

// --- the vendor ID check ---------------------------------------------------------------------

// An optional vendor ID box (data-vendor-name names its vendor name box) is checked against
// Infor as it's typed. Infor's name goes into the name box when that is empty or was filled in
// for them (from a contract line or an earlier ID); a name they typed stays.
function vendorInput(target) {
  if (target.dataset.vendorName) lookupVendor(target);
  else if (target.name === 'vendor') delete target.dataset.autofilled;
}

function vendorNote(input, text, problem) {
  const note = $(`${input.id}-note`);
  input.classList.toggle('is-invalid', Boolean(problem));
  if (note) {
    note.textContent = text || '';
    note.classList.toggle('text-danger', Boolean(problem));
  }
}

const lookupVendor = debounce(async (input) => {
  const nameBox = $(input.dataset.vendorName);
  const id = input.value.trim();
  if (!id) { vendorNote(input, ''); return; }
  if (!/^\d+$/.test(id)) { vendorNote(input, "Infor's vendor ID is digits only", true); return; }
  try {
    const data = await getJSON(api.vendor, { id });
    if (input.value.trim() !== id) return;  // typed on meanwhile
    const vendor = data.vendor;
    if (!vendor) { vendorNote(input, "Not in Infor's vendor list", true); return; }
    const status = vendor.vendor_status && vendor.vendor_status !== 'Active' ? ` (${vendor.vendor_status})` : '';
    vendorNote(input, `Infor: ${vendor.vendor_name}${status}`);
    if (nameBox && (!nameBox.value.trim() || nameBox.dataset.autofilled)) {
      nameBox.value = vendor.vendor_name || '';
      nameBox.dataset.autofilled = '1';
    }
  } catch (error) {
    vendorNote(input, error.message, true);
  }
}, 300);

// --- the forms -------------------------------------------------------------------------------

// The contract search, and the vendor details it fills in (the Materials Manager's).
function detailFields(sub) {
  return `
    <div class="col-12"><label class="form-label small mb-0" for="fk-contract-q">Search Infor's active contracts to fill these in</label>
      <input type="search" class="form-control form-control-sm" id="fk-contract-q" autocomplete="off"
             placeholder="Vendor item, manufacturer number, or description words" value="${esc(sub.vendor_part)}"
             data-part="${esc(sub.vendor_part)}">
      <div id="fk-contract-results" class="small mt-1"></div>
      <div id="fk-contract-note" class="small text-warning-emphasis mt-1"></div></div>
    <div class="col-4"><label class="form-label small mb-0" for="fk-m-vendor_id">Vendor ID</label>
      <input class="form-control form-control-sm" id="fk-m-vendor_id" name="vendor_id" value="${esc(sub.vendor_id || '')}"
             maxlength="20" inputmode="numeric" placeholder="Optional" data-vendor-name="fk-m-vendor">
      <div class="form-text small mt-0" id="fk-m-vendor_id-note"></div></div>
    ${field('vendor', 'Vendor *', sub.vendor, 'maxlength="255" required', 8)}
    ${field('description', 'Description', sub.description, 'maxlength="255"', 12)}
    ${field('uom', 'UOM *', sub.uom, 'maxlength="10" required', 4)}
    ${field('qoe', 'QOE', plainNumber(sub.qoe), 'inputmode="decimal"', 4)}`;
}

// Search the contracts for nursing's vendor part as soon as the form opens.
function searchForTheSub(sub) {
  whenModal('shown', () => { if ($('fk-contract-q')) searchContracts(sub.vendor_part); });
}

export function openDetailsForm(sub) {
  if (!sub) return;
  showModal(`Vendor details · ${esc(sub.vendor_part)}`, detailFields(sub), 'Save details',
    (values) => postJSON(subUrl(sub.sub_id, 'details'), values).then(() => 'Vendor details saved.'));
  searchForTheSub(sub);
}

// Recording an order: the Materials Manager fills in (or checks) the sub's vendor details, which
// are saved on the sub, and the order takes them; then the quantity.
export function openOrderForm(subId, item) {
  const sub = findSub(subId);
  if (!sub) return;
  const medline = sub.medline_item || item;
  const row = state.rows.find((r) => r.medline_items.includes(medline));
  const pack = row ? row.packagings.find((p) => p.medline_item === medline) : null;
  const killed = pack && pack.quantities.length === 1 ? pack.quantities[0].killed : '';
  // Materials Managers may order for the whole Infor item: its UOMs added up in eaches.
  const combined = row && row.packagings.length > 1 && row.quantities_each
    ? `<div class="col-12 small text-muted">All ${row.packagings.length} UOMs of Infor item ${esc(row.infor_item)} killed
        ${fmtNumber(row.quantities_each.killed)} EA in these dates${sub.qoe ? ` (${fmtNumber(row.quantities_each.killed / sub.qoe)} ×
        ${esc(sub.uom || 'unit')} of ${fmtNumber(sub.qoe)})` : ''}.</div>` : '';
  showModal(`Record an order · ${esc(medline)}`, `
    <div class="col-12 small text-muted">Pick: <span class="fw-semibold">${esc(subText(sub))}</span>
      ${killed ? ` · ${esc(medline)} killed in these dates: ${fmtNumber(killed)} ${esc(pack.quantities[0].uom)}` : ''}</div>${combined}
    ${detailFields(sub)}
    <div class="col-12"><hr class="my-1"></div>
    ${field('quantity', 'Quantity *', killed, 'type="number" min="1" step="1" required', 4)}
    ${field('ordered_dt', 'Ordered', nowLocal(), 'type="datetime-local"', 8)}
    ${field('comment', 'Comment', '', 'maxlength="400"', 12)}`,
  'Record order', (values) => postJSON(api.recordOrder, Object.assign(values, { sub_id: subId, expected_status: 'approved' }))
    .then(() => 'Order recorded.'));
  if (needsDetails(sub)) searchForTheSub(sub);
}

export function openOrderEditForm(order) {
  if (!order) return;
  showModal(`Correct an order · ${esc(order.sub_label)}`, `
    ${field('quantity', 'Quantity', order.quantity, 'type="number" min="1" step="1"', 4)}
    ${field('uom', 'UOM', order.uom, 'maxlength="10"', 4)}
    ${field('qoe', 'QOE', plainNumber(order.qoe), 'inputmode="decimal"', 4)}
    ${field('vendor', 'Vendor', order.vendor, 'maxlength="255"', 6)}
    ${field('ordered_dt', 'Ordered', String(order.ordered_dt || '').slice(0, 16), 'type="datetime-local"', 6)}`,
  'Save correction', (values) => postJSON(orderUrl(order.order_id, 'edit'), values).then(() => 'Order corrected.'));
}

// Deleting a sub needs a reason; the sub's row and history stay.
export function openSubDeleteForm(sub) {
  if (!sub) return;
  showModal(`Delete a sub · ${esc(sub.vendor_part)}`, `
    <div class="col-12 small text-muted">${esc(subText(sub))} on ${esc(sub.medline_item)}. It leaves the item and the
      library; who deleted it, when and why stay in its history.</div>
    ${field('reason', 'Why? *', '', 'maxlength="400" required', 12)}`,
  'Delete sub', (values) => postJSON(subUrl(sub.sub_id, 'delete'), { reason: values.reason, expected_status: sub.status })
    .then(() => 'Sub deleted.'));
}

export function openVoidForm(orderId) {
  showModal('Void an order', field('reason', 'Why? *', '', 'maxlength="400" required', 12),
    'Void order', (values) => postJSON(orderUrl(orderId, 'void'), values).then(() => 'Order voided.'));
}

// Nursing corrects the vendor part (until the sub has an order); the details are the Materials
// Manager's ("Vendor details").
export function openSubEditForm(sub) {
  if (!sub) return;
  showModal(`Correct the vendor part · ${esc(sub.vendor_part)}`,
    field('vendor_part', 'Vendor part *', sub.vendor_part, 'maxlength="100" required', 8),
    'Save', (values) => postJSON(subUrl(sub.sub_id, 'edit'), { vendor_part: values.vendor_part }).then(() => 'Vendor part corrected.'));
}

export function setupForms() {
  modalEl.addEventListener('show.bs.modal', () => { modalPhase = 'showing'; });
  modalEl.addEventListener('shown.bs.modal', () => { modalPhase = 'shown'; });
  modalEl.addEventListener('hide.bs.modal', () => { modalPhase = 'hiding'; });
  modalEl.addEventListener('hidden.bs.modal', () => { modalPhase = 'hidden'; });

  modalForm.addEventListener('input', (event) => {
    if (event.target.id === 'fk-contract-q') searchContracts(event.target.value);
    vendorInput(event.target);
  });

  modalForm.addEventListener('click', (event) => {
    const contract = event.target.closest('[data-contract]');
    if (contract) fillFromContract(state.contractLines[Number(contract.dataset.contract)]);
  });

  modalForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!modalSubmit) return;
    const values = Object.fromEntries(new FormData(modalForm).entries());
    try {
      const message = await modalSubmit(values);
      hideModal();
      await afterChange(message);
    } catch (error) {
      $('fk-modal-message').innerHTML = alertBox(error.message, error.status === 409 ? 'warning' : 'danger');
    }
  });
}
