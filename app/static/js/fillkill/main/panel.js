/* Main: the item panel, an offcanvas on the right. Clicked on an Infor item it shows all its UOMs;
 * clicked on a Medline item, only that one. Its tabs are drawn in tabs.js; its forms open in the
 * modal (forms.js).
 */

import {
  $, alertBox, config, debounce, esc, fmtDateTime, fmtNumber, formValues, getJSON, postJSON, trimOnChange,
} from '../common.js';
import {
  addedMessage, openInstructionForm, openOrderEditForm, openOrderForm, openStatusForm, openSubDeleteForm,
  openSubEditForm, openVendorItemDeleteForm, openVendorItemForm, openVoidForm,
} from './forms.js';
import { afterChange } from './refresh.js';
import { api, can, historyUrl, orderUrl, scopeParams, state, subUrl, syncLink } from './state.js';
import { customerFlag, instructionList } from './table.js';
import { renderPanelTab, timeline } from './tabs.js';

export const panelEl = $('fk-panel');
const panel = window.bootstrap ? window.bootstrap.Offcanvas.getOrCreateInstance(panelEl) : null;

export const panelIsOpen = () => Boolean(state.panelItem) && panelEl.classList.contains('show');

// scope 'infor' shows the whole Infor item (all UOMs); otherwise just this Medline item.
export async function openPanel(item, tab, scope) {
  state.panelItem = item;
  state.panelScope = scope === 'infor' ? 'infor' : 'medline';
  if (tab) state.panelTab = tab;
  $('fk-panel-title').textContent = item;
  $('fk-panel-subtitle').textContent = '';
  $('fk-panel-body').innerHTML = '<div class="text-muted small">Loading…</div>';
  if (panel) panel.show();
  await loadPanel();
}

let panelRequest = 0;

export async function loadPanel(message) {
  const item = state.panelItem;
  if (!item) return;
  const ticket = ++panelRequest;
  try {
    const data = await getJSON(api.item, Object.assign({ item }, scopeParams()));
    if (ticket !== panelRequest) return;  // a newer request is on its way
    state.panelData = data;
    renderPanel(message);
  } catch (error) {
    $('fk-panel-body').innerHTML = alertBox(error.message);
  }
}

// What the panel shows. The API always returns the whole Infor item; clicked on a Medline item,
// the panel keeps to that Medline item (one UOM): its subs, kill lines, history and orders.
function panelView() {
  const data = state.panelData;
  const whole = state.panelScope === 'infor';
  const mine = (x) => whole || x.medline_item === state.panelItem;
  const packs = data.packagings.filter(mine);
  const lines = data.lines.filter(mine);
  return {
    whole,
    packs,
    lines,
    orders: data.orders.filter(mine),
    history: data.sub_history.filter(mine),
    many: packs.length > 1,
    reason: whole ? data.latest_reason : lines[0],  // lines are newest first
  };
}

function renderPanel(message) {
  syncLink();
  const data = state.panelData;
  const d = data.details || {};
  const view = panelView();
  $('fk-panel-title').textContent = view.whole && data.infor_item ? `Infor item ${data.infor_item}` : state.panelItem;
  $('fk-panel-subtitle').innerHTML = [
    !view.whole && data.infor_item ? `Infor item ${esc(data.infor_item)}` : '',
    esc((view.whole ? d.description : (view.packs[0] || {}).description) || ''),
    view.reason ? esc(view.reason.comment) : '',
  ].filter(Boolean).join(' · ');

  const subs = view.packs.reduce((n, p) => n + p.subs.length, 0);
  const tabs = [
    ['subs', `Subs <span class="badge text-bg-light">${subs}</span>`],
    ['lines', `Kill lines <span class="badge text-bg-light">${view.lines.length}</span>`],
    ['history', 'Sub History'],
    ['orders', `Orders <span class="badge text-bg-light">${view.orders.length}</span>`],
  ];
  $('fk-panel-body').innerHTML = `
    ${message ? alertBox(message.text, message.kind) : ''}
    ${itemDetails(d)}
    ${instructionBlock(data.instruction)}
    ${packagingList(data, view)}
    <ul class="nav nav-pills nav-fill small mb-3" role="tablist">
      ${tabs.map(([key, label]) => `<li class="nav-item"><button type="button" class="nav-link py-1 ${state.panelTab === key ? 'active' : ''}"
          data-panel-tab="${key}">${label}</button></li>`).join('')}
    </ul>
    <div id="fk-panel-content">${renderPanelTab(state.panelTab, view)}</div>`;
}

function itemDetails(d) {
  const rows = [
    ['Infor item', d.infor_item
      ? [d.infor_item, d.infor_active ? (d.infor_active === 'Yes' ? 'Active' : 'Inactive') : ''].filter(Boolean).join(' · ')
      : 'None: not a Medline vendor item in Infor'],
    ['Long description', d.long_description],
    ['Commodity', [d.commodity_code, d.commodity_description].filter(Boolean).join(' · ')],
    ['Manufacturer', [d.manufacturer, d.mfr_item].filter(Boolean).join(' · ')],
  ].filter(([, value]) => value);
  return `<dl class="row small bg-light border rounded py-2 mx-0 mb-3">${rows.map(([label, value]) => `
    <dt class="col-sm-4 text-muted fw-normal">${esc(label)}</dt><dd class="col-sm-8 mb-1">${esc(value)}</dd>`).join('')}</dl>`;
}

// SCM Comments (2026-10-27): SCM's latest instruction for the item, for everyone. SCM adds
// one here (the user: a button, like the subs' Add sub) or by double-clicking its cell on
// Main; with several, they all open under it.
function instructionBlock(instruction) {
  const latest = instruction && instruction.latest;
  if (!latest && !can.instruct) return '';
  const all = instruction && instruction.count > 1
    ? `<button type="button" class="btn btn-sm btn-link py-0" data-act="instructions">All ${instruction.count}</button>` : '';
  const add = can.instruct
    ? '<button type="button" class="btn btn-sm btn-primary py-0" data-act="instruct"><i class="bi bi-plus-lg"></i> Add comment</button>' : '';
  return `<div class="small border rounded p-2 mb-3">
    <div class="d-flex flex-wrap gap-2 align-items-center mb-1"><span class="fw-semibold me-auto">${esc(config.instructionLabel)}</span>${all}${add}</div>
    ${latest ? `<div class="fk-instruction-text">${esc(latest.instruction)}</div>
      <div class="text-muted">${esc(latest.written_by)}, ${fmtDateTime(latest.written_at)}</div>` : '<div class="text-muted">None yet.</div>'}
    <div class="border-top pt-2 mt-2 d-none" id="fk-panel-instructions"></div>
  </div>`;
}

// The form wants the item's main-table row (each site's kills and orders); an item opened from a
// link may not be on the table for these dates and sites, so then what the panel has.
function instructionRow() {
  const data = state.panelData;
  return state.rows.find((r) => r.medline_items.includes(state.panelItem)) || {
    infor_item: data.infor_item, description: (data.details || {}).description, instruction: data.instruction,
    packagings: [{ medline_item: state.panelItem }], sites: [],
  };
}

// The Medline items (UOMs) shown: those killed in these dates first, then any other Medline has
// killed under the Infor item. Switch between one Medline item and all of them here.
function packagingList(data, view) {
  const total = data.packagings.length;
  let label = view.many ? `${view.packs.length} UOMs (Medline items)` : 'Medline item';
  if (view.whole && total > 1) label += ' · click one to see only it';
  const widen = !view.whole && total > 1
    ? `<button type="button" class="btn btn-link btn-sm p-0 ms-2 align-baseline" data-panel-focus="">Show all ${total} UOMs
        of Infor item ${esc(data.infor_item)}</button>` : '';
  return `<div class="small mb-3"><div class="text-muted mb-1">${label}${widen}</div>
    <ul class="list-unstyled mb-0">${view.packs.map((p) => {
      const notes = [
        esc(p.um),
        p.qoe != null ? `QOE ${fmtNumber(p.qoe)}` : '',
        p.killed_in_range ? '' : 'not killed in these dates',
      ].filter(Boolean).join(' · ');
      const name = view.many
        ? `<button type="button" class="btn btn-link btn-sm p-0 align-baseline" data-panel-focus="${esc(p.medline_item)}">${esc(p.medline_item)}</button>`
        : `<span class="fw-semibold">${esc(p.medline_item)}</span>`;
      return `<li class="mb-1">${name}${customerFlag(p)}
        <span class="text-muted">${notes}</span>
        ${p.description ? `<div class="text-muted text-truncate">${esc(p.description)}</div>` : ''}</li>`;
    }).join('')}</ul></div>`;
}

// Every sub on the Infor item, whichever UOM is shown.
export const panelSubs = () => (state.panelData ? state.panelData.packagings.flatMap((p) => p.subs) : []);

// --- actions ---------------------------------------------------------------------------------

// ``done`` is the message to show, or a function of the server's answer that returns it.
async function act(path, payload, done) {
  try {
    const data = await postJSON(path, payload);
    await afterChange(typeof done === 'function' ? done(data) : done);
  } catch (error) {
    // 409: someone changed it meanwhile; the reloaded panel shows the latest next to the message.
    await loadPanel({ text: error.message, kind: error.status === 409 ? 'warning' : 'danger' });
  }
}

async function onClick(event) {
  const tab = event.target.closest('[data-panel-tab]');
  if (tab) {
    state.panelTab = tab.dataset.panelTab;
    renderPanel();
    return;
  }
  // One Medline item, or (empty) the whole Infor item: the data is already here.
  const focus = event.target.closest('[data-panel-focus]');
  if (focus) {
    if (focus.dataset.panelFocus) {
      state.panelItem = focus.dataset.panelFocus;
      state.panelScope = 'medline';
    } else {
      state.panelScope = 'infor';
    }
    renderPanel();
    return;
  }
  const button = event.target.closest('button[data-act]');
  if (!button) return;
  const { act: what } = button.dataset;
  const subId = Number(button.dataset.sub);
  const sub = () => panelSubs().find((s) => s.sub_id === subId);
  const vendorItem = () => (sub() ? sub().vendor_items.find((v) => v.vendor_item_id === Number(button.dataset.vi)) : null);
  if (what === 'instruct') { openInstructionForm(instructionRow()); return; }
  if (what === 'instructions') {
    const target = $('fk-panel-instructions');
    if (!target.classList.contains('d-none')) { target.classList.add('d-none'); return; }
    target.innerHTML = '<span class="text-muted">Loading…</span>';
    target.classList.remove('d-none');
    try {
      target.innerHTML = instructionList((await getJSON(api.instructions, { item: state.panelItem })).instructions);
    } catch (error) {
      target.innerHTML = alertBox(error.message);
    }
    return;
  }
  if (what === 'show-add') { $('fk-add-sub').classList.remove('d-none'); $('fk-add-sku').focus(); return; }
  if (what === 'hide-add') { $('fk-add-sub').classList.add('d-none'); return; }
  if (what === 'order') { openOrderForm(Number(button.dataset.vi)); return; }
  if (what === 'copy-sub') {
    const target = button.dataset.item;
    const pack = state.panelData.packagings.find((p) => p.medline_item === target);
    const o = pack && pack.other_subs.find((x) => x.sub_id === subId);
    if (!o) return;
    // The Reference SKU only: vendor items are for a UOM, the Materials Manager's to add here.
    await act(api.addSub, {
      medline_item: target, reference_sku: o.reference_sku,
      comment: `Added from ${o.medline_item}${o.um ? ` (${o.um})` : ''}, where it is ${config.statusLabels[o.status]}.`,
    }, (data) => `Sub added to ${target}. ${addedMessage(data.sub)}`);
    return;
  }
  if (what === 'edit-sub') { openSubEditForm(sub()); return; }
  if (what === 'add-vi') { openVendorItemForm(sub()); return; }
  if (what === 'edit-vi') { openVendorItemForm(sub(), vendorItem()); return; }
  if (what === 'delete-vi') { openVendorItemDeleteForm(sub(), vendorItem()); return; }
  if (what === 'delete-sub') { openSubDeleteForm(sub()); return; }
  if (what === 'edit-order') { openOrderEditForm(state.panelData.orders.find((o) => o.order_id === Number(button.dataset.order))); return; }
  if (what === 'void-order') { openVoidForm(Number(button.dataset.order)); return; }
  if (what === 'comment-order-open') {
    const form = panelEl.querySelector(`form[data-act="comment-order"][data-order="${button.dataset.order}"]`);
    form.classList.toggle('d-none');
    showOrderMore(form);
    if (!form.classList.contains('d-none')) form.elements.comment.focus();
    return;
  }
  if (what === 'history') {
    const target = $(`fk-history-${button.dataset.entity}-${button.dataset.id}`);
    if (target.innerHTML) { target.innerHTML = ''; showOrderMore(target); return; }
    target.innerHTML = '<span class="text-muted">Loading…</span>';
    showOrderMore(target);
    try {
      const data = await getJSON(historyUrl(button.dataset.entity, button.dataset.id));
      target.innerHTML = timeline(data.history, false);
    } catch (error) {
      target.innerHTML = alertBox(error.message);
    }
  }
}

// In the Orders tab's table, an order's line under its row shows while its history or its comment
// box is open (2026-10-20).
function showOrderMore(inside) {
  const more = inside.closest('.fk-order-more');
  if (!more) return;
  const form = more.querySelector('form');
  const open = Boolean(more.querySelector('.fk-history').innerHTML.trim()) || Boolean(form && !form.classList.contains('d-none'));
  more.classList.toggle('d-none', !open);
}

// Approving takes effect at once. Hold and Reject stop the sub being ordered (2026-10-28): a form
// asks why, optionally, and the select shows the status it has until that's saved.
async function onStatusChange(event) {
  const select = event.target.closest('select[data-act="status"]');
  if (!select || !select.value) return;
  const status = select.value;
  if (status === 'hold' || status === 'rejected') {
    select.value = select.dataset.expected === 'pending_review' ? '' : select.dataset.expected;
    openStatusForm(panelSubs().find((s) => s.sub_id === Number(select.dataset.sub)), status);
    return;
  }
  await act(subUrl(select.dataset.sub, 'status'), { status, expected_status: select.dataset.expected },
    `Status set to ${config.statusLabels[status]}.`);
}

async function onSubmit(event) {
  const form = event.target;
  event.preventDefault();
  if (form.id === 'fk-add-form') {
    const payload = formValues(form);
    payload.medline_item = payload.medline_item || state.panelItem;  // the UOM chosen, if several
    await act(api.addSub, payload, (data) => `Sub added. ${addedMessage(data.sub)}`);
    return;
  }
  const comment = form.elements.comment ? form.elements.comment.value.trim() : '';
  if (!comment) return;
  if (form.dataset.act === 'comment-sub') await act(subUrl(form.dataset.sub, 'comments'), { comment }, 'Comment added.');
  if (form.dataset.act === 'comment-order') await act(orderUrl(form.dataset.order, 'comments'), { comment }, 'Comment added.');
}

// --- width -----------------------------------------------------------------------------------

// Drag the panel's left edge (or use the arrow keys on it) to change its width; this browser
// remembers it. Double-click the edge to go back to the default.
const PANEL_WIDTH_KEY = 'fk-panel-width';
const clampWidth = (px) => Math.round(Math.min(Math.max(px, 320), window.innerWidth - 40));

function setPanelWidth(px, save) {
  const width = clampWidth(px);
  panelEl.style.width = `${width}px`;
  if (save) {
    try { localStorage.setItem(PANEL_WIDTH_KEY, String(width)); } catch (error) { /* not remembered */ }
  }
}

function setupResizer() {
  const resizer = $('fk-panel-resize');
  try {
    const saved = Number(localStorage.getItem(PANEL_WIDTH_KEY));
    if (saved) setPanelWidth(saved, false);
  } catch (error) { /* default width */ }

  resizer.addEventListener('pointerdown', (event) => {
    event.preventDefault();
    resizer.setPointerCapture(event.pointerId);
    document.body.classList.add('fk-resizing');
    const move = (e) => setPanelWidth(window.innerWidth - e.clientX, false);
    const done = () => {
      resizer.removeEventListener('pointermove', move);
      resizer.removeEventListener('pointerup', done);
      resizer.removeEventListener('pointercancel', done);
      document.body.classList.remove('fk-resizing');
      setPanelWidth(panelEl.getBoundingClientRect().width, true);
    };
    resizer.addEventListener('pointermove', move);
    resizer.addEventListener('pointerup', done);
    resizer.addEventListener('pointercancel', done);
  });

  resizer.addEventListener('keydown', (event) => {
    const step = { ArrowLeft: 32, ArrowRight: -32 }[event.key];
    if (!step) return;
    event.preventDefault();
    setPanelWidth(panelEl.getBoundingClientRect().width + step, true);
  });

  resizer.addEventListener('dblclick', () => {
    panelEl.style.width = '';
    try { localStorage.removeItem(PANEL_WIDTH_KEY); } catch (error) { /* nothing kept */ }
  });

  window.addEventListener('resize', debounce(() => {
    if (panelEl.style.width) setPanelWidth(parseFloat(panelEl.style.width), false);
  }, 150));
}

export function setupPanel() {
  setupResizer();
  panelEl.addEventListener('click', onClick);
  trimOnChange(panelEl);  // the add-sub and comment boxes (2026-10-20)
  panelEl.addEventListener('change', onStatusChange);
  panelEl.addEventListener('submit', onSubmit);
  panelEl.addEventListener('hidden.bs.offcanvas', () => {
    state.panelItem = null;
    state.panelData = null;
    syncLink();
  });
}
