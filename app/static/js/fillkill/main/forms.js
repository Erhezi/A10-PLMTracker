/* Main: the forms in the modal: a vendor item (with the contract search, the vendor search by name
 * and the vendor ID check), record, correct and void an order, correct a sub's Reference SKU, delete
 * a sub or a vendor item, put a sub on hold or reject it (2026-10-28), SCM's instruction
 * ("SCM Comments", 2026-10-27; "Will's Comments" until 11-02), and a new sub from Main's Approved by Nursing (2026-10-27). Boxes lose their leading and
 * trailing spaces when left, and a UOM typed another way becomes Infor's (2026-10-20).
 */

import {
  $, NO_VENDOR, STATUS_ORDER, alertBox, config, debounce, esc, fmtDateTime, fmtNumber, formValues, getJSON, inforUom,
  isTheKilledItem, postJSON, trimInput, uomQoe, vendorItemText,
} from '../common.js';
import { panelSubs } from './panel.js';
import { afterChange } from './refresh.js';
import { addVendorItemUrl, api, can, orderUrl, siteName, state, subUrl, vendorItemUrl } from './state.js';

const modalEl = $('fk-modal');
const modal = window.bootstrap ? window.bootstrap.Modal.getOrCreateInstance(modalEl) : null;
const modalForm = $('fk-modal-form');
let modalSubmit = null;
let formItem = null;  // the vendor item form's Medline item: its vendor items can't be the item itself
let orderForm = null;  // the order form's item and vendor item: its check follows the site chosen

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

// ``body`` is the form's HTML; ``onSubmit`` gets the form's values and returns a promise of the
// message to show. ``wide``: the vendor item and order forms get the room they need (2026-10-20).
// ``danger``: a red button, for what can't be undone.
function showModal(title, body, submitLabel, onSubmit, { wide = false, danger = false } = {}) {
  formItem = null;
  orderForm = null;
  modalEl.querySelector('.modal-dialog').classList.toggle('modal-lg', wide);
  modalForm.innerHTML = `
    <div class="modal-header"><h2 class="modal-title h5" id="fk-modal-title">${title}</h2>
      <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>
    <div class="modal-body"><div id="fk-modal-message"></div>${body}</div>
    <div class="modal-footer"><button type="button" class="btn btn-sm btn-link" data-bs-dismiss="modal">Cancel</button>
      <button type="submit" class="btn btn-sm ${danger ? 'btn-danger' : 'btn-primary'}">${submitLabel}</button></div>`;
  modalSubmit = onSubmit;
  openModal();
}

// ``col``: a column width (6), or the column classes ('col-12 col-md-4'). ``note``: a line under the
// box for what the form says about it (#fk-m-<name>-note).
const field = (name, label, value, attrs, col, note) => `
  <div class="${typeof col === 'string' ? col : `col-${col || 6}`}"><label class="form-label small mb-0" for="fk-m-${name}">${label}</label>
    <input class="form-control form-control-sm" id="fk-m-${name}" name="${name}" value="${esc(value == null ? '' : value)}" ${attrs || ''}>${note
    ? `<div class="form-text small mt-0" id="fk-m-${name}-note"></div>` : ''}</div>`;

// A row of fields; or a section of them under a title, so a long form reads in parts.
const fields = (html) => `<div class="row g-2">${html}</div>`;
const section = (title, html, hint) => `
  <section class="fk-form-section">
    <h3 class="fk-form-section-title">${title}${hint ? ` <span class="fw-normal text-muted">${hint}</span>` : ''}</h3>
    <div class="row g-2">${html}</div>
  </section>`;

const plainNumber = (value) => (value != null ? fmtNumber(value).replace(/,/g, '') : '');

function nowLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

// Subs from the panel (any UOM) and the main table's approved ones.
const knownSubs = () => panelSubs().concat(...state.rows.map((row) => row.approved_subs));

// A vendor item and its sub, from the panel or the main table.
function findVendorItem(id) {
  for (const sub of knownSubs()) {
    const item = (sub.vendor_items || []).find((v) => v.vendor_item_id === id);
    if (item) return { sub, item };
  }
  return { sub: null, item: null };
}

// The killed Medline item's UOM with its QOE, as "BX/25" (several: "BX/25, EA/1"): from the panel,
// which has every UOM Medline killed it in, or else the main table's quantities (2026-10-21).
function killedUoms(medline) {
  const inPanel = state.panelData && state.panelData.packagings.find((p) => p.medline_item === medline);
  const row = state.rows.find((r) => r.medline_items.includes(medline));
  const pack = row ? row.packagings.find((p) => p.medline_item === medline) : null;
  const found = inPanel ? inPanel.uom_qoes || [] : (pack ? pack.quantities.map((q) => ({ uom: q.uom, qoe: q.each })) : []);
  return found.map(uomQoe).join(', ');
}

// What a form is about, at its top: the sub (its Reference SKU) for the killed Medline item, with
// that item's UOM/QOE, and, when there is one, the vendor item.
function summary(sub, item, more) {
  const uoms = killedUoms(sub.medline_item);
  return `
    <div class="fk-form-summary small">
      <div><span class="text-muted">Reference SKU</span> <span class="fw-semibold">${esc(sub.reference_sku)}</span>
        <span class="text-muted">for ${esc(sub.medline_item)}${uoms ? ` (${esc(uoms)})` : ''}${sub.source === 'medline_pbo'
          ? ' · Medline PBO' : ''}</span></div>
      ${item ? `<div><span class="text-muted">Vendor item</span> <span class="fw-semibold">${esc(vendorItemText(item))}</span>${item.description
        ? ` <span class="text-muted">· ${esc(item.description)}</span>` : ''}</div>` : ''}${more || ''}
    </div>`;
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
    if (!data.lines.length) { box.innerHTML = '<span class="text-muted">No active contract line found; fill in the vendor item below.</span>'; return; }
    state.contractLines = data.lines;
    // A short scrolling list (about 3-4 lines show); more words narrow it down.
    const count = data.more
      ? `The first ${data.lines.length} lines: add a word to narrow them down, e.g. a description word.`
      : `${data.lines.length} line${data.lines.length === 1 ? '' : 's'}`;
    box.innerHTML = `<div class="text-muted mb-1">${count}</div>
      <div class="list-group fk-pick-list fk-contract-list">${data.lines.map((line, i) => {
      const facts = [
        line.infor_item ? `Infor item ${esc(line.infor_item)}` : 'No Infor item',
        esc(uomQoe(line)),
        line.contracts > 1 ? `${line.contracts} contracts${line.mhs_contracts && line.mhs_contracts < line.contracts
          ? ` (${line.mhs_contracts} MHS)` : ''}` : '',
      ].filter(Boolean).join(' · ');
      // The Medline item itself, from Medline: listed, but it can't be chosen (2026-10-20).
      const itself = isTheKilledItem(formItem, line.vendor_item, line.vendor_id);
      return `
      <button type="button" class="list-group-item list-group-item-action py-1" ${itself ? 'disabled' : `data-contract="${i}"`}>
        <div class="d-flex gap-2 align-items-baseline">
          <span><span class="fw-semibold">${esc(line.vendor_item)}</span> · ${esc(line.vendor_name)}
            <span class="text-muted">(vendor ${esc(line.vendor_id)})</span></span>
          ${itself ? '<span class="badge text-bg-danger ms-auto">The killed item itself</span>' : contractMhsBadge(line)}
        </div>
        ${itself ? `<div class="text-danger">${esc(formItem)} itself, the Medline item that was killed: not a sub.</div>` : ''}
        <div class="text-muted">${facts}</div>
        <div class="text-muted text-truncate">${esc(line.description)}</div>
      </button>`;
    }).join('')}</div>`;
  } catch (error) {
    box.innerHTML = alertBox(error.message);
  }
}, 350);

// A contract line fills in the vendor item: its vendor part, vendor, vendor ID, UOM and the rest.
// The sub's Reference SKU stays as entered (2026-10-20).
function fillFromContract(line) {
  $('fk-m-vendor_part').value = line.vendor_item || '';
  $('fk-m-manufacturer_part').value = line.manufacturer_number || '';
  $('fk-m-infor_item').value = line.infor_item || '';
  $('fk-m-vendor_id').value = line.vendor_id || '';
  vendorNote($('fk-m-vendor_id'), '');
  $('fk-m-vendor').value = line.vendor_name || '';
  $('fk-m-vendor').dataset.autofilled = '1';
  stopVendorSearch();
  vendorNameNote();
  $('fk-m-description').value = line.description || '';
  $('fk-m-uom').value = line.uom || '';
  uomChanged($('fk-m-uom'));
  $('fk-m-qoe').value = plainNumber(line.qoe);
  killedItemCheck();
}

// --- what's typed: the UOM, and the Medline item itself ---------------------------------------

// A UOM typed another way becomes Infor's as soon as the box is left (CS is CA, VL is VI), with a
// note saying so; one Infor doesn't list another way stays as typed (2026-10-20).
function uomChanged(input) {
  const typed = input.value.trim().toUpperCase();
  input.value = inforUom(typed);
  const note = $(`${input.id}-note`);
  if (note) note.textContent = typed && input.value !== typed ? `${typed} is ${input.value} in Infor` : '';
}

// The Medline item itself from Medline isn't a sub (2026-10-20): said under the vendor part once
// the vendor ID is one of Medline's. The server refuses it too.
function killedItemCheck() {
  const part = $('fk-m-vendor_part');
  const idBox = $('fk-m-vendor_id');
  const note = $('fk-m-vendor_part-note');
  if (!part || !idBox || !note) return;
  const itself = isTheKilledItem(formItem, part.value, idBox.value);
  part.classList.toggle('is-invalid', itself);
  note.classList.toggle('text-danger', itself);
  note.textContent = itself
    ? `${formItem} itself, from Medline: the Medline item that was killed can't be ordered as its sub.` : '';
}

// --- the vendor: by name, and its ID ---------------------------------------------------------

// The vendor ID is needed (2026-10-19): Infor's, or 0000000 when Infor has no such vendor. Typing
// the vendor's name lists Infor's vendors it matches (their names, legal names and search names);
// choosing one fills in its ID and Infor's name. The ID leads (2026-10-21): whenever it changes,
// Infor's name for it goes into the name box, whatever was there, and a name box left after a
// search nobody chose from goes back to the ID's vendor. The server saves Infor's name for the ID
// too. With 0000000 the name is theirs to type.
function vendorInput(target) {
  if (target.name === 'vendor_part' || target.name === 'vendor_id') killedItemCheck();
  if (target.dataset.vendorName) {
    lookupVendor(target);
    vendorNameNote();
  } else if (target.name === 'vendor') {
    delete target.dataset.autofilled;
    // With 0000000 Infor has no such vendor: the name is theirs to type, nothing to look up.
    if (noInforId()) vendorNameNote();
    else searchVendors(target.value.trim());
  }
}

const SEARCH_HINT = "Type the name to find Infor's vendor ID";
const noInforId = () => Boolean($('fk-m-vendor_id')) && $('fk-m-vendor_id').value.trim() === NO_VENDOR.id;

// With 0000000, ask for the vendor's name until it's typed in.
function vendorNameNote() {
  const nameBox = $('fk-m-vendor');
  const note = $('fk-m-vendor-note');
  if (!nameBox || !note) return;
  const typeIt = noInforId() && !nameBox.value.trim();
  note.textContent = typeIt ? "Not in Infor: type the vendor's name." : '';
  note.classList.toggle('text-warning-emphasis', typeIt);
  nameBox.placeholder = noInforId() ? "The vendor's name, as you know it" : SEARCH_HINT;
}

let vendorSearch = 0;  // the latest search; choosing a vendor (or 0000000) outdates any on its way

const searchVendors = debounce(async (q) => {
  const box = $('fk-vendor-results');
  if (!box) return;
  const mine = ++vendorSearch;
  if (q.replace(/[\s*]/g, '').length < 2) { box.innerHTML = ''; return; }
  try {
    const data = await getJSON(api.vendors, { q });
    if (mine !== vendorSearch || !$('fk-m-vendor') || $('fk-m-vendor').value.trim() !== q) return;  // outdated
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
    if (mine === vendorSearch) box.innerHTML = alertBox(error.message);
  }
}, 300);

// The vendor is chosen: no list comes back from a search still waiting or on its way.
function stopVendorSearch() {
  searchVendors.cancel();
  vendorSearch += 1;
  const box = $('fk-vendor-results');
  if (box) box.innerHTML = '';
}

function pickVendor(vendor) {
  const idBox = $('fk-m-vendor_id');
  idBox.value = vendor.vendor_id;
  vendorNote(idBox, `Infor: ${vendor.vendor_name}${vendor.vendor_status && vendor.vendor_status !== 'Active' ? ` (${vendor.vendor_status})` : ''}`);
  $('fk-m-vendor').value = vendor.vendor_name || '';
  $('fk-m-vendor').dataset.autofilled = '1';
  stopVendorSearch();
  vendorNameNote();
  killedItemCheck();
}

// Infor has no such vendor: said on purpose, with 0000000. The vendor's name, typed or Infor's,
// is cleared, for them to type the one they know (2026-10-20).
function noInforVendor() {
  const idBox = $('fk-m-vendor_id');
  const nameBox = $('fk-m-vendor');
  idBox.value = NO_VENDOR.id;
  vendorNote(idBox, NO_VENDOR.label);
  stopVendorSearch();
  nameBox.value = '';
  delete nameBox.dataset.autofilled;
  vendorNameNote();
  killedItemCheck();
  nameBox.focus();
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
  // No vendor for the ID (none yet, not one Infor knows, or 0000000): a name Infor filled in for an
  // earlier ID goes with it; one they typed stays.
  const dropInforName = () => {
    if (nameBox && nameBox.dataset.autofilled) { nameBox.value = ''; delete nameBox.dataset.autofilled; }
    vendorNameNote();
  };
  if (!id) { vendorNote(input, ''); dropInforName(); return; }
  if (!/^\d+$/.test(id)) { vendorNote(input, "Infor's vendor ID is digits only", true); dropInforName(); return; }
  if (id === NO_VENDOR.id) {
    vendorNote(input, NO_VENDOR.label);
    stopVendorSearch();
    dropInforName();
    return;
  }
  try {
    const data = await getJSON(api.vendor, { id });
    if (input.value.trim() !== id) return;  // typed on meanwhile
    const vendor = data.vendor;
    if (!vendor) { vendorNote(input, "Not in Infor's vendor list", true); dropInforName(); return; }
    const status = vendor.vendor_status && vendor.vendor_status !== 'Active' ? ` (${vendor.vendor_status})` : '';
    vendorNote(input, `Infor: ${vendor.vendor_name}${status}`);
    if (nameBox) {
      nameBox.value = vendor.vendor_name || '';
      nameBox.dataset.autofilled = '1';
      vendorNameNote();
    }
  } catch (error) {
    vendorNote(input, error.message, true);
  }
}, 300);

// The name box left with something typed: unless it's 0000000's name to type, it goes back to Infor's
// name for the vendor ID (choosing from the list changes the ID, and the name with it).
function vendorNameLeft() {
  const idBox = $('fk-m-vendor_id');
  const id = idBox ? idBox.value.trim() : '';
  if (/^\d+$/.test(id) && id !== NO_VENDOR.id) lookupVendor(idBox);
}

// --- the forms -------------------------------------------------------------------------------

// The vendor: its name (typing it searches Infor's vendors) and its vendor ID, with 0000000 when
// Infor has no such vendor. In a vendor item and an order's correction.
function vendorFields(v) {
  return `
    <div class="col-12 col-md-8"><label class="form-label small mb-0" for="fk-m-vendor">Vendor *</label>
      <input class="form-control form-control-sm" id="fk-m-vendor" name="vendor" value="${esc(v.vendor || '')}"
             maxlength="255" required autocomplete="off" placeholder="${esc(SEARCH_HINT)}"${v.vendor_id && v.vendor_id !== NO_VENDOR.id
             ? ' data-autofilled="1"' : ''}>
      <div class="form-text small mt-0" id="fk-m-vendor-note"></div></div>
    <div class="col-12 col-md-4"><label class="form-label small mb-0" for="fk-m-vendor_id">Vendor ID *</label>
      <input class="form-control form-control-sm" id="fk-m-vendor_id" name="vendor_id" value="${esc(v.vendor_id || '')}"
             maxlength="20" inputmode="numeric" required placeholder="Infor's" data-vendor-name="fk-m-vendor">
      <div class="form-text small mt-0" id="fk-m-vendor_id-note">${v.vendor_id === NO_VENDOR.id ? esc(NO_VENDOR.label) : ''}</div>
      <button type="button" class="btn btn-link btn-sm p-0 text-nowrap" data-no-vendor
              title="${esc(NO_VENDOR.label)}">Not in Infor? Use ${esc(NO_VENDOR.id)}</button></div>
    <div class="col-12"><div id="fk-vendor-results" class="small"></div></div>`;
}

// The contract search and the vendor item it fills in, each a section (the Materials Manager's or a
// Sub Finder's): a vendor's part in a UOM, with its manufacturer part and Infor item (2026-10-20).
function vendorItemSections(sub, item) {
  const v = item || {};
  return section("Find it on Infor's contracts", `
    <div class="col-12">
      <input type="search" class="form-control form-control-sm" id="fk-contract-q" autocomplete="off"
             aria-label="Search Infor's active contracts"
             placeholder="Vendor item, manufacturer number, Infor item, or words, e.g. 930103 chloraprep bx"
             value="${esc(item ? item.vendor_part : sub.reference_sku)}">
      <div id="fk-contract-results" class="small mt-1"></div></div>`,
  'optional: choosing a line fills in the vendor item below')
  + section('Vendor item', `
    ${field('vendor_part', 'Vendor part *', v.vendor_part, 'maxlength="100" required', 'col-12 col-md-4', true)}
    ${field('manufacturer_part', 'Manufacturer part', v.manufacturer_part, 'maxlength="100"', 'col-6 col-md-4')}
    ${field('infor_item', 'Infor item', v.infor_item, 'maxlength="50"', 'col-6 col-md-4')}
    ${vendorFields(v)}
    ${field('description', 'Description', v.description, 'maxlength="255"', 'col-12 col-md-6')}
    ${field('uom', 'UOM *', v.uom, 'maxlength="10" required', 'col-6 col-md-3', true)}
    ${field('qoe', 'QOE', plainNumber(v.qoe), 'inputmode="decimal"', 'col-6 col-md-3')}`,
  'one per vendor ID, vendor part and UOM');
}

// Search the contracts for what's in the search box as soon as the form opens: the Reference SKU
// (or the vendor part being corrected), unless they've started typing already.
function searchForIt() {
  whenModal('shown', () => { if ($('fk-contract-q')) searchContracts($('fk-contract-q').value); });
}

// A vendor item: added to a sub, or corrected (2026-10-20). The sub's Reference SKU stays as entered.
export function openVendorItemForm(sub, item) {
  if (!sub) return;
  const note = item ? '' : `<div class="text-muted">A way to order it: each vendor ID, vendor part and UOM is a vendor item
    of its own.</div>`;
  showModal(item ? `Correct a vendor item · ${esc(item.vendor_part)}` : `Add a vendor item · ${esc(sub.reference_sku)}`,
    summary(sub, item, note) + vendorItemSections(sub, item), item ? 'Save correction' : 'Add vendor item',
    (values) => (item
      ? postJSON(vendorItemUrl(item.vendor_item_id, 'edit'), values).then(() => 'Vendor item corrected.')
      : postJSON(addVendorItemUrl(sub.sub_id), values).then(() => 'Vendor item added.')),
    { wide: true });
  formItem = sub.medline_item;
  killedItemCheck();
  searchForIt();
}

// --- what's still needed, against the vendor item ordered --------------------------------------

// Eaches per unit: the QOE given, or 1 for an EA without one.
const eachesPer = (uom, qoe) => (qoe != null && qoe !== '' ? Number(qoe) : (inforUom(uom) === 'EA' ? 1 : null));
const sameNumber = (a, b) => a != null && b != null && Math.abs(a - b) < 1e-9;
const isWhole = (n) => Math.abs(n - Math.round(n)) < 1e-9;

const CHECK_STYLES = {
  danger: 'bg-danger-subtle text-danger-emphasis border-danger-subtle',
  warning: 'bg-warning-subtle text-warning-emphasis border-warning-subtle',
  plain: 'bg-body-tertiary',
};
const checkBox = (style, lines) => `<div class="${CHECK_STYLES[style]} border rounded-2 px-3 py-2 mb-3 small fk-order-check"
    ${style === 'plain' ? '' : 'role="alert"'}>${lines.filter(Boolean).map((line) => `<div>${line}</div>`).join('')}</div>`;

// The order form's check (2026-10-21; first version 10-20; per site from 2026-10-27, since each
// site orders for itself). What's still needed at the order's site is the Infor item's eaches killed
// there in these dates less its sub orders for that site, and the recommended order is that over the
// vendor item's QOE, rounded up to whole units. The quantity is filled in only when the vendor item
// has the UOM and QOE this Medline item was killed in there and the need comes out whole; otherwise
// it's left for the Materials Manager. A QOE missing anywhere (the vendor item, a UOM killed, an
// order already placed) is said in red: there's then no number. No site chosen yet: it says to
// choose one.
function orderCheck(medline, row, item, site) {
  const none = { quantity: '', recommended: null, html: '' };
  if (!row) return none;
  if (!site) {
    return { ...none, html: checkBox('plain', ["Choose the site this order is for: what's still needed there is worked out once you do."]) };
  }
  const here = (row.sites || []).find((s) => s.site === site);
  const kills = here ? here.kills.filter((k) => k.killed > 0)
    .map((k) => ({ ...k, medline: k.medline_item, per: eachesPer(k.uom, k.each) })) : [];
  const at = esc(siteName(site));
  if (!kills.length) {
    return { ...none, html: checkBox('warning', [`${at} had no kills of this item in these Fill/Kill dates${state.sites.length
      ? ' (with the sites shown)' : ''}: nothing to recommend. Enter a quantity only to order anyway.`]) };
  }
  const uom = esc(item.uom);
  const perUnit = eachesPer(item.uom, item.qoe);
  const asKilled = (q) => `${esc(q.medline)}: ${fmtNumber(q.killed)} ${esc(q.uom)}${q.per != null ? ` (${esc(q.uom)}/${fmtNumber(q.per)})` : ''}`;
  const eaches = (n) => (n != null ? `${fmtNumber(n)} EA` : 'can\'t be counted');
  const known = here.killed_each != null && here.sub_ordered_each != null;
  const need = known ? here.killed_each - here.sub_ordered_each : null;
  const facts = [
    `<span class="fw-semibold">Killed at ${at} in these dates: ${eaches(here.killed_each)}</span>${row.packagings.length > 1
      ? ` for Infor item ${esc(row.infor_item)}` : ''} (${kills.map(asKilled).join('; ')})`,
    `Sub ordered for ${at} in these dates: ${eaches(here.sub_ordered_each)}${known
      ? ` · <span class="fw-semibold">still needed: ${fmtNumber(Math.max(need, 0))} EA</span>` : ''}`,
  ];

  const problems = [];
  const noQoe = [...new Set(kills.filter((q) => q.per == null).map((q) => `${q.medline}'s ${q.uom}`))];
  if (noQoe.length) problems.push(`Infor has no QOE for ${esc(noQoe.join(', '))}, so the kills can't be counted in eaches.`);
  if (here.sub_ordered_each == null) {
    problems.push(`An order already placed for ${at} in these dates has no QOE, so what's been ordered can't be counted in eaches. Correct that order to add it.`);
  }
  if (perUnit == null) {
    problems.push(`This vendor item has no QOE, so how many ${uom} cover what's needed can't be worked out. Correct the vendor item to add its QOE, or work the quantity out yourself.`);
  }
  if (problems.length) {
    return { ...none, html: checkBox('danger', [...facts,
      ...problems.map((p) => `<span class="fw-semibold"><i class="bi bi-exclamation-triangle-fill"></i> No QOE:</span> ${p}`),
      `No recommended quantity: enter how many ${uom} to order.`]) };
  }
  if (need <= 1e-9) {
    return { ...none, html: checkBox('warning', [...facts,
      `The sub orders for ${at} in these dates already cover what was killed there: nothing more is needed. Enter a quantity only to order more.`]) };
  }

  const units = need / perUnit;
  const whole = Math.max(1, Math.ceil(units - 1e-9));
  const exact = isWhole(units);
  const advice = `<span class="fw-semibold">Recommended order: ${fmtNumber(whole)} ${uom}</span> (${fmtNumber(need)} EA ÷ ${fmtNumber(perUnit)}
    EA per ${uom} = ${fmtNumber(units)} ${uom}${exact ? '' : ', rounded up'})`;
  const mine = kills.filter((q) => q.medline === medline);
  const same = mine.length === 1 && inforUom(mine[0].uom) === inforUom(item.uom) && sameNumber(mine[0].per, perUnit);
  if (same && exact) {
    return { quantity: whole, recommended: whole, html: checkBox('plain', [...facts, advice,
      `Quantity filled in: the vendor item comes as ${esc(uomQoe(item))}, as ${esc(medline)} was killed.`]) };
  }
  let why;
  if (!mine.length) why = `${esc(medline)} wasn't killed at ${at} in these dates (what's needed is the Infor item's)`;
  else if (mine.length > 1) why = `${esc(medline)} was killed at ${at} in ${mine.length} UOMs`;
  else if (!same) why = `the vendor item comes as ${esc(uomQoe(item))}, and ${esc(medline)} was killed as ${esc(mine[0].uom)}${mine[0].per != null ? `/${fmtNumber(mine[0].per)}` : ''}`;
  else why = `${fmtNumber(units)} ${uom} isn't a whole number`;
  return { quantity: '', recommended: whole, html: checkBox('danger', [...facts, advice,
    `Quantity is left blank: ${why}. Enter how many ${uom} to order.`]) };
}

// The site an order is for (2026-10-27): the Materials Manager's to choose. ``required``: a new order,
// or one that has a site; one from before sites can stay without.
function siteSelect(selected, { required = true, col = 'col-12 col-md-5' } = {}) {
  return `<div class="${col}"><label class="form-label small mb-0" for="fk-m-site">Site${required ? ' *' : ''}</label>
    <select class="form-select form-select-sm" id="fk-m-site" name="site"${required ? ' required' : ''}>
      <option value=""${selected ? '' : ' selected'}>${required ? 'Choose the site…' : 'Site not recorded'}</option>
      ${(config.sites || []).map((s) => `<option value="${esc(s.code)}"${s.code === selected ? ' selected' : ''}>${esc(s.name || s.code)}</option>`).join('')}
    </select></div>`;
}

const poField = (value, col) => field('po_number', 'PO number', value, `maxlength="20" inputmode="numeric" autocomplete="off"
  placeholder="Optional: Infor's PO, e.g. 3000564756" title="Infor's PO number, digits only. Optional: it links the order back to the killed items later."`, col);

// Recording an order for a vendor item of an approved sub: it's placed with the vendor item's vendor part,
// vendor, vendor ID, UOM and QOE (2026-10-20), for the site the Materials Manager chooses, with
// Infor's PO number if they have it (2026-10-27). The site starts on the one the filter shows, when
// it shows just one (a Materials Manager looking at their own site); otherwise they choose it.
export function openOrderForm(vendorItemId) {
  const { sub, item } = findVendorItem(vendorItemId);
  if (!item) return;
  const medline = sub.medline_item;
  const row = state.rows.find((r) => r.medline_items.includes(medline));
  const site = state.sites.length === 1 ? state.sites[0] : '';
  const check = orderCheck(medline, row, item, site);
  const hint = check.recommended != null ? `placeholder="Recommended: ${check.recommended}"` : '';
  showModal(`Record an order · ${esc(medline)}`, `${summary(sub, item)}<div id="fk-order-check">${check.html}</div>` + section('Order', `
    ${siteSelect(site)}
    ${field('quantity', `Quantity (${esc(item.uom)}) *`, check.quantity, `type="number" min="1" step="1" required ${hint}`, 'col-6 col-md-3')}
    ${poField('', 'col-6 col-md-4')}
    ${field('ordered_dt', 'Ordered', nowLocal(), 'type="datetime-local"', 'col-6 col-md-4')}
    ${field('comment', 'Comment', '', 'maxlength="400"', 'col-12 col-md-8')}`),
  'Record order', (values) => postJSON(api.recordOrder, Object.assign(values, { vendor_item_id: vendorItemId, expected_status: 'approved' }))
    .then(() => `Order recorded for ${siteName(values.site)}.`), { wide: true });
  orderForm = { medline, row, item, filled: check.quantity };
}

// Another site chosen: its check, and its recommendation. A quantity the form filled in follows it;
// one they typed stays.
function orderSiteChanged(select) {
  if (!orderForm || !$('fk-order-check')) return;
  const check = orderCheck(orderForm.medline, orderForm.row, orderForm.item, select.value);
  $('fk-order-check').innerHTML = check.html;
  const quantity = $('fk-m-quantity');
  quantity.placeholder = check.recommended != null ? `Recommended: ${check.recommended}` : '';
  if (quantity.value === String(orderForm.filled)) quantity.value = check.quantity;
  orderForm.filled = check.quantity;
}

// An order keeps what it was placed with (vendor part, vendor, vendor ID, UOM, QOE): corrected here,
// with its site and PO number (2026-10-27). One from before sites can be given one.
export function openOrderEditForm(order) {
  if (!order) return;
  showModal(`Correct an order · ${esc(order.vendor_part)}`, fields(`
    ${siteSelect(order.site, { required: Boolean(order.site), col: 'col-12 col-md-6' })}
    ${poField(order.po_number, 'col-12 col-md-6')}
    ${field('quantity', 'Quantity', order.quantity, 'type="number" min="1" step="1"', 'col-4')}
    ${field('uom', 'UOM', order.uom, 'maxlength="10"', 'col-4')}
    ${field('qoe', 'QOE', plainNumber(order.qoe), 'inputmode="decimal"', 'col-4')}
    ${field('vendor_part', 'Vendor part', order.vendor_part, 'maxlength="100"', 'col-12')}
    ${vendorFields(order)}
    ${field('ordered_dt', 'Ordered', String(order.ordered_dt || '').slice(0, 16), 'type="datetime-local"', 'col-12 col-md-6')}`),
  'Save correction', (values) => postJSON(orderUrl(order.order_id, 'edit'), values).then(() => 'Order corrected.'), { wide: true });
}

// Hold or Reject (2026-10-28): the sub can't be ordered then, and leaves Approved by Nursing on Main.
// Nursing may say why: the reason is kept as the sub's comment, after its new status.
export function openStatusForm(sub, status) {
  if (!sub) return;
  const label = config.statusLabels[status];
  const verb = status === 'hold' ? 'Put on Hold' : 'Reject';
  showModal(`${verb} · ${esc(sub.reference_sku)}`, fields(`
    <div class="col-12 small text-muted">${esc(sub.reference_sku)} on ${esc(sub.medline_item)}. ${status === 'hold'
      ? "On hold, it can't be ordered and leaves Approved by Nursing on Main, until you approve it again."
      : "Rejected, it can't be ordered and leaves Approved by Nursing on Main."} Its orders so far stay.</div>
    ${field('comment', 'Reason', '', `maxlength="${config.reasonMax}" placeholder="Optional: why, for the Materials Managers"`, 12)}`),
  verb, (values) => postJSON(subUrl(sub.sub_id, 'status'), { status, comment: values.comment, expected_status: sub.status })
    .then(() => `Status set to ${label}.`));
  whenModal('shown', () => { const box = $('fk-m-comment'); if (box) box.focus(); });
}

// Deleting a sub needs a reason; the sub's row and history stay.
export function openSubDeleteForm(sub) {
  if (!sub) return;
  showModal(`Delete a sub · ${esc(sub.reference_sku)}`, fields(`
    <div class="col-12 small text-muted">${esc(sub.reference_sku)} on ${esc(sub.medline_item)}. It leaves the item and the
      library, with its vendor items; who deleted it, when and why stay in its history.</div>
    ${field('reason', 'Why? *', '', 'maxlength="400" required', 12)}`),
  'Delete sub', (values) => postJSON(subUrl(sub.sub_id, 'delete'), { reason: values.reason, expected_status: sub.status })
    .then(() => 'Sub deleted.'));
}

// Deleting a vendor item needs a reason too; refused while it has orders that aren't voided.
export function openVendorItemDeleteForm(sub, item) {
  if (!item) return;
  showModal(`Delete a vendor item · ${esc(item.vendor_part)}`, fields(`
    <div class="col-12 small text-muted">${esc(vendorItemText(item))}, for ${esc(sub.reference_sku)}. It can't be ordered
      any more; its orders, and who deleted it, when and why, stay.</div>
    ${field('reason', 'Why? *', '', 'maxlength="400" required', 12)}`),
  'Delete vendor item', (values) => postJSON(vendorItemUrl(item.vendor_item_id, 'delete'), { reason: values.reason })
    .then(() => 'Vendor item deleted.'));
}

export function openVoidForm(orderId) {
  showModal('Void an order', fields(field('reason', 'Why? *', '', 'maxlength="400" required', 12)),
    'Void order', (values) => postJSON(orderUrl(orderId, 'void'), values).then(() => 'Order voided.'));
}

// Nursing corrects the Reference SKU (until the sub has an order); its vendor items are the
// Materials Manager's.
export function openSubEditForm(sub) {
  if (!sub) return;
  showModal(`Correct the Reference SKU · ${esc(sub.reference_sku)}`,
    fields(field('reference_sku', 'Reference SKU *', sub.reference_sku, 'maxlength="100" required', 8)),
    'Save', (values) => postJSON(subUrl(sub.sub_id, 'edit'), { reference_sku: values.reference_sku })
      .then(() => 'Reference SKU corrected.'));
}

// SCM's instruction to the sites' Materials Managers (2026-10-27; "SCM Comments" on the
// page), for the Infor item, the main table's row: opened by double-clicking its cell, or from the
// item panel. It becomes the latest; the earlier ones stay. What each site killed and has ordered in
// these dates is above it, to write it from (the panel's item may not be on the table: no sites then).
export function openInstructionForm(row) {
  if (!row) return;
  const item = row.packagings[0].medline_item;
  const what = row.infor_item ? `Infor item ${row.infor_item}` : item;
  const eaches = (n) => (n != null ? `${fmtNumber(n)} EA` : "can't be counted");
  const sites = (row.sites || []).filter((s) => s.site);
  const latest = row.instruction && row.instruction.latest;
  const summaryLines = [
    `<div><span class="fw-semibold">${esc(what)}</span> <span class="text-muted">${esc(row.description || '')}</span></div>`,
    sites.length ? `<div><span class="text-muted">In these Fill/Kill dates</span> ${sites.map((s) => `${esc(siteName(s.site))}:
      killed ${eaches(s.killed_each)}, sub ordered ${eaches(s.sub_ordered_each)}`).join(' · ')}</div>` : '',
    latest ? `<div><span class="text-muted">Latest</span> <span class="fk-instruction-text">${esc(latest.instruction)}</span>
      <span class="text-muted">· ${esc(latest.written_by)}, ${fmtDateTime(latest.written_at)}</span></div>` : '',
  ];
  showModal(`${esc(config.instructionLabel)} · ${esc(what)}`, `<div class="fk-form-summary small">${summaryLines.join('')}</div>${fields(`
    <div class="col-12"><label class="form-label small mb-0" for="fk-m-instruction">Comment from SCM *</label>
      <textarea class="form-control form-control-sm" id="fk-m-instruction" name="instruction" rows="5" required
                maxlength="${config.instructionMax || 1000}"
                placeholder="How the sites should order it, e.g. White Plains and Wakefield: 2 CA of B-D930103CS each. Einstein: use stock until Friday."></textarea>
      <div class="form-text small">It shows on Main as the latest, for everyone; the earlier ones are kept. Nobody is emailed:
        the sites read it on Main.</div></div>`)}`,
  'Save comment',
  (values) => postJSON(api.instructions, { medline_item: item, instruction: values.instruction })
    .then(() => `Comment saved for ${what}.`), { wide: true });
  whenModal('shown', () => { const box = $('fk-m-instruction'); if (box) box.focus(); });
}

// What happened to a new sub: approved on entry, so it can be ordered, or waiting for review.
export function addedMessage(added) {
  return added.status === 'approved' ? 'Approved: it can be ordered.' : 'It is pending review.';
}

// A new sub for a Medline item, from a double-click on its Approved by Nursing cell (2026-10-27): the
// panel's Add sub, in the modal. Its subs so far, and the approved ones, are above it.
export function openAddSubForm(medline) {
  const row = state.rows.find((r) => r.medline_items.includes(medline));
  const pack = row ? row.packagings.find((p) => p.medline_item === medline) : null;
  if (!pack) return;
  const uoms = killedUoms(medline);
  const counts = STATUS_ORDER.filter((s) => pack.subs_status[s]).map((s) => `${pack.subs_status[s]} ${config.statusLabels[s].toLowerCase()}`);
  const what = can.review
    ? "It's approved as soon as it's added, so it can be ordered: the Materials Manager adds its vendor items."
    : "It waits for a Sub Approver's review.";
  showModal(`Add a sub · ${esc(medline)}`, `
    <div class="fk-form-summary small">
      <div><span class="fw-semibold">${esc(medline)}</span>${uoms ? ` <span class="text-muted">(${esc(uoms)})</span>` : ''}
        <span class="text-muted">${esc(row.infor_item ? `Infor item ${row.infor_item} · ` : '')}${esc(pack.description || row.description || '')}</span></div>
      <div><span class="text-muted">Subs on file</span> ${counts.length ? esc(counts.join(' · ')) : 'none'}</div>${pack.approved_subs.length
        ? `<div><span class="text-muted">Approved by Nursing</span> ${esc(pack.approved_subs.map((s) => s.reference_sku).join(', '))}</div>` : ''}
    </div>${fields(`
    ${field('reference_sku', 'Reference SKU *', '', `maxlength="100" required autocomplete="off"
      placeholder="The part you approved, e.g. the manufacturer's"`, 12)}
    ${field('comment', 'Note', '', 'maxlength="400" placeholder="Optional: what you know about it, e.g. from the supplier"', 12)}
    <div class="col-12 small text-muted">${what}</div>`)}`,
  'Add sub', (values) => postJSON(api.addSub, { medline_item: medline, reference_sku: values.reference_sku, comment: values.comment })
    .then((data) => `Sub added to ${medline}. ${addedMessage(data.sub)}`));
  whenModal('shown', () => { const input = $('fk-m-reference_sku'); if (input) input.focus(); });
}

// The development server's Reset data, for admins (2026-11-02; config.reset only there): empties the
// workflow, as db/fillkill/90_reset_workflow.sql does. The server wants RESET typed.
const RESET_TABLES = [['Sub', 'subs'], ['SubVendorItem', 'vendor items'], ['SubOrder', 'orders'],
  ['History', 'history rows'], ['ItemInstruction', 'SCM comments']];

export function openResetForm() {
  const reset = config.reset;
  if (!reset) return;
  showModal('Reset the Fill/Kill data', fields(`
    <div class="col-12 small">Deletes every sub, vendor item, order, history row and SCM comment in
      <strong>${esc(reset.database)}</strong>, as <code>db/fillkill/90_reset_workflow.sql</code> does. It can't be undone.
      Medline's kill lines stay, and Medline's backorder substitutes come back the next time Main loads.</div>
    ${reset.live ? `<div class="col-12">${alertBox("This is O2, the live app's database: the live app's Fill/Kill data goes too.", 'warning')}</div>` : ''}
    ${field('confirm', 'Type RESET to confirm *', '', 'required autocomplete="off"', 12)}`),
  'Reset data', async (values) => {
    const data = await postJSON(reset.url, { confirm: values.confirm });
    const message = `Reset: ${RESET_TABLES.map(([table, label]) => `${fmtNumber(data.deleted[table] || 0)} ${label}`).join(', ')} deleted.`;
    $('fk-reset-note').textContent = message;  // the panel, where messages go, is usually closed
    return message;
  }, { danger: true });
}

export function setupForms() {
  const resetButton = $('fk-reset');
  if (resetButton) resetButton.addEventListener('click', openResetForm);
  modalEl.addEventListener('show.bs.modal', () => { modalPhase = 'showing'; });
  modalEl.addEventListener('shown.bs.modal', () => { modalPhase = 'shown'; });
  modalEl.addEventListener('hide.bs.modal', () => { modalPhase = 'hiding'; });
  modalEl.addEventListener('hidden.bs.modal', () => { modalPhase = 'hidden'; });

  modalForm.addEventListener('input', (event) => {
    if (event.target.id === 'fk-contract-q') searchContracts(event.target.value);
    vendorInput(event.target);
  });

  // A box left: its leading and trailing spaces go, and a UOM becomes Infor's (2026-10-20).
  modalForm.addEventListener('change', (event) => {
    if (trimInput(event.target) && (event.target.name === 'vendor_part' || event.target.name === 'vendor_id')) killedItemCheck();
    if (event.target.name === 'uom') uomChanged(event.target);
    if (event.target.name === 'site') orderSiteChanged(event.target);
    if (event.target.name === 'vendor') vendorNameLeft();
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
    const values = formValues(modalForm);
    try {
      const message = await modalSubmit(values);
      hideModal();
      await afterChange(message);
    } catch (error) {
      $('fk-modal-message').innerHTML = alertBox(error.message, error.status === 409 ? 'warning' : 'danger');
    }
  });
}
