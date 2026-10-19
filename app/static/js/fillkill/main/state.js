/* Main: what's shown, and the page link that keeps it. */

import { $, config } from '../common.js';

export const can = config.can || {};
export const api = config.api;

export const state = {
  start: (config.default && config.default.start) || '',
  end: (config.default && config.default.end) || '',
  sites: [],
  needs: 'all',
  search: '',
  ordersStart: '',  // the orders section's own dates
  ordersEnd: '',
  dateMode: 'range',  // 'today' or 'range'
  rows: [],
  counts: {},
  panelItem: null,
  panelTab: 'subs',
  panelScope: 'medline',  // 'infor': the whole Infor item; 'medline': only panelItem (one UOM)
  panelData: null,
  contractLines: [],  // the contract search's latest results
  vendorResults: [],  // the vendor search's latest results
};

// The page link keeps what's shown, so it can be shared or bookmarked (2026-10-19): ?dates=today
// or ?start=&end=, ?sites=a,b, ?q= (the search), ?needs=, and the open panel's ?item=&scope=&tab=.
export const linked = new URLSearchParams(window.location.search);
if (linked.get('dates') === 'today' && config.today) {
  state.start = config.today;
  state.end = config.today;
} else if (linked.get('start') && linked.get('end')) {
  state.start = linked.get('start');
  state.end = linked.get('end');
}
state.sites = (linked.get('sites') || '').split(',').filter(Boolean);
state.search = (linked.get('q') || '').trim().toLowerCase();
if (linked.get('needs') && (config.needs || []).some(([key]) => key === linked.get('needs'))) state.needs = linked.get('needs');

// Keep the page link in step with what's shown (no new history entry each time).
export function syncLink() {
  const params = new URLSearchParams();
  if (state.dateMode === 'today') params.set('dates', 'today');
  else if (state.start && state.end) { params.set('start', state.start); params.set('end', state.end); }
  if (state.sites.length) params.set('sites', state.sites.join(','));
  const search = $('fk-search').value.trim();
  if (search) params.set('q', search);
  if (state.needs !== 'all') params.set('needs', state.needs);
  if (state.panelItem) {
    params.set('item', state.panelItem);
    if (state.panelScope === 'infor') params.set('scope', 'infor');
    if (state.panelTab && state.panelTab !== 'subs') params.set('tab', state.panelTab);
  }
  const query = params.toString();
  window.history.replaceState(null, '', query ? `${window.location.pathname}?${query}` : window.location.pathname);
}

export function scopeParams() {
  return { start: state.start, end: state.end, sites: state.sites };
}

export const subUrl = (subId, action) => api.subAction.replace('/0/', `/${subId}/`).replace('ACTION', action);
export const orderUrl = (orderId, action) => api.orderAction.replace('/0/', `/${orderId}/`).replace('ACTION', action);
export const historyUrl = (entity, id) => api.history.replace('ENTITY', entity).replace(/\/0$/, `/${id}`);
