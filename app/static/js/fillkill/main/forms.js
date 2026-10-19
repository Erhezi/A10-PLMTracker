/* Main: the forms in the modal: vendor details (with the contract search, the vendor search by
 * name and the vendor ID check), record, correct and void an order, correct a sub's vendor part,
 * delete a sub.
 */

import {
  $, NO_VENDOR, alertBox, debounce, esc, fmtNumber, getJSON, needsDetails, postJSON, subText,
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
    // A short scrolling list (about 3-4 lines show); more words narrow it down.
    const count = data.more
      ? `The first ${data.lines.length} lines: add a word to narrow them down, e.g. a description word.`
      : `${data.lines.length} line${data.lines.length === 1 ? '' : 's'}`;
    box.innerHTML = `<div class="text-muted mb-1">${count}</div>
      <div class="list-group fk-pick-list fk-contract-list">${data.lines.map((line, i) => {
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

// A contract line fills in the vendor details, the vendor part ordered among them: what nursing
// entered may be the manufacturer's part or another vendor's (2026-10-19). What they entered stays
// with the sub, and a change of part is pointed out.
function fillFromContract(line) {
  const entered = $('fk-contract-q').dataset.part || '';
  const bare = (value) => String(value || '').toUpperCase().replace(/[\s\-./]/g, '');
  $('fk-contract-note').textContent = entered && bare(line.vendor_item) !== bare(entered)
    ? `The vendor part becomes ${line.vendor_item}, this contract line's; ${entered}, as entered, stays with the sub.` : '';
  $('fk-m-vendor_part').value = line.vendor_item || '';
  $('fk-m-manufacturer_part').value = line.manufacturer_number || '';
  $('fk-m-infor_item').value = line.infor_item || '';
  $('fk-m-vendor_id').value = line.vendor_id || '';
  vendorNote($('fk-m-vendor_id'), '');
  $('fk-m-vendor').value = line.vendor_name || '';
  $('fk-m-vendor').dataset.autofilled = '1';
  $('fk-vendor-results').innerHTML = '';
  $('fk-m-description').value = line.description || '';
  $('fk-m-uom').value = line.uom || '';
  $('fk-m-qoe').value = plainNumber(line.qoe);
}

// --- the vendor: by name, and its ID ---------------------------------------------------------

// The vendor ID is needed (2026-10-19): Infor's, or 000000 when Infor has no such vendor. Typing
// the vendor's name lists Infor's vendors it matches (their names, legal names and search names);
// choosing one fills in its ID and Infor's name. A typed ID is checked against Infor, and Infor's
// name goes into the name box when that is empty or was filled in for them (from a contract line,
// the list or an earlier ID); a name they typed stays.
function vendorInput(target) {
  if (target.dataset.vendorName) {
    lookupVendor(target);
  } else if (target.name === 'vendor') {
    delete target.dataset.autofilled;
    searchVendors(target.value.trim());
  }
}

const searchVendors = debounce(async (q) => {
  const box = $('fk-vendor-results');
  if (!box) return;
  if (q.replace(/[\s*]/g, '').length < 2) { box.innerHTML = ''; return; }
  try {
    const data = await getJSON(api.vendors, { q });
    if (!$('fk-m-vendor') || $('fk-m-vendor').value.trim() !== q) return;  // typed on meanwhile
    state.vendorResults = data.vendors;
    const none = `<div class="text-muted">No Infor vendor has "${esc(q)}" in its name. Try part of it,
      or use ${esc(NO_VENDOR.id)} if Infor doesn't have the vendor.</div>`;
    box.innerHTML = data.vendors.length ? `
      <div class="text-muted mb-1">Infor's vendors${data.more ? ` (the first ${data.vendors.length}: type more of the name)` : ''}:</div>
      <div class="list-group fk-pick-list fk-vendor-list">${data.vendors.map((v, i) => {
        // Infor's other names for it, when they differ: what may have matched.
        const others = [...new Set([v.legal_name, v.search_name])].filter((name) => name && name !== v.vendor_name);
        return `
        <button type="button" class="list-group-item list-group-item-action py-1" data-vendor-pick="${i}">
          <div class="text-truncate"><span class="fw-semibold">${esc(v.vendor_id)}</span> · ${esc(v.vendor_name)}
            ${v.vendor_status && v.vendor_status !== 'Active' ? `<span class="badge text-bg-secondary ms-1">${esc(v.vendor_status)}</span>` : ''}</div>
          ${others.length ? `<div class="text-muted text-truncate" title="${esc(others.join('\n'))}">${esc(others.join(' · '))}</div>` : ''}
        </button>`;
      }).join('')}</div>` : none;
  } catch (error) {
    box.innerHTML = alertBox(error.message);
  }
}, 300);

function pickVendor(vendor) {
  const idBox = $('fk-m-vendor_id');
  idBox.value = vendor.vendor_id;
  vendorNote(idBox, `Infor: ${vendor.vendor_name}${vendor.vendor_status && vendor.vendor_status !== 'Active' ? ` (${vendor.vendor_status})` : ''}`);
  $('fk-m-vendor').value = vendor.vendor_name || '';
  $('fk-m-vendor').dataset.autofilled = '1';
  $('fk-vendor-results').innerHTML = '';
}

// Infor has no such vendor: said on purpose, with 000000; the name they typed stays.
function noInforVendor() {
  const idBox = $('fk-m-vendor_id');
  idBox.value = NO_VENDOR.id;
  vendorNote(idBox, NO_VENDOR.label);
  $('fk-vendor-results').innerHTML = '';
  $('fk-m-vendor').focus();
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
  if (id === NO_VENDOR.id) { vendorNote(input, NO_VENDOR.label); return; }
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

// The contract search, and the vendor details it fills in (the Materials Manager's): the vendor part
// ordered, the manufacturer's part and Infor's item number among them (2026-10-19).
function detailFields(sub) {
  const entered = sub.entered_part || sub.vendor_part;
  return `
    <div class="col-12"><label class="form-label small mb-0" for="fk-contract-q">Search Infor's active contracts to fill these in</label>
      <input type="search" class="form-control form-control-sm" id="fk-contract-q" autocomplete="off"
             placeholder="Vendor item, manufacturer number, Infor item, or words, e.g. 930103 chloraprep"
             value="${esc(sub.vendor_part)}" data-part="${esc(entered)}">
      <div id="fk-contract-results" class="small mt-1"></div>
      <div id="fk-contract-note" class="small text-warning-emphasis mt-1"></div></div>
    ${field('vendor_part', 'Vendor part *', sub.vendor_part, 'maxlength="100" required', 5)}
    ${field('manufacturer_part', 'Manufacturer part', sub.manufacturer_part, 'maxlength="100"', 4)}
    ${field('infor_item', 'Infor item', sub.infor_item, 'maxlength="50"', 3)}
    <div class="col-12 small text-muted mt-0">Entered as <span class="fw-semibold">${esc(entered)}</span>${sub.source === 'medline_pbo'
      ? ' (Medline PBO)' : ''}: the vendor part is the one ordered, which may differ.</div>
    <div class="col-7"><label class="form-label small mb-0" for="fk-m-vendor">Vendor *</label>
      <input class="form-control form-control-sm" id="fk-m-vendor" name="vendor" value="${esc(sub.vendor || '')}"
             maxlength="255" required autocomplete="off" placeholder="Type the name to find Infor's vendor ID"></div>
    <div class="col-5"><label class="form-label small mb-0" for="fk-m-vendor_id">Vendor ID *</label>
      <input class="form-control form-control-sm" id="fk-m-vendor_id" name="vendor_id" value="${esc(sub.vendor_id || '')}"
             maxlength="20" inputmode="numeric" required placeholder="Infor's" data-vendor-name="fk-m-vendor">
      <div class="form-text small mt-0" id="fk-m-vendor_id-note">${sub.vendor_id === NO_VENDOR.id ? esc(NO_VENDOR.label) : ''}</div>
      <button type="button" class="btn btn-link btn-sm p-0 text-nowrap" data-no-vendor
              title="${esc(NO_VENDOR.label)}">Not in Infor? Use ${esc(NO_VENDOR.id)}</button></div>
    <div class="col-12"><div id="fk-vendor-results" class="small"></div></div>
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
    const vendor = event.target.closest('[data-vendor-pick]');
    if (vendor) pickVendor(state.vendorResults[Number(vendor.dataset.vendorPick)]);
    if (event.target.closest('[data-no-vendor]')) noInforVendor();
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
