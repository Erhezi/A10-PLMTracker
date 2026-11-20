/* Main: what's shown, and the page link that keeps it. */

import { $, config } from '../common.js';

export const can = config.can || {};
export const api = config.api;

// Medline's Sold-To codes and their names: an order is for a site (2026-10-27).
const SITE_NAMES = Object.fromEntries((config.sites || []).map((site) => [site.code, site.name || site.code]));
export const siteName = (code) => (code ? SITE_NAMES[code] || code : 'Site not recorded');

export const state = {
  start: (config.default && config.default.start) || '',
  end: (config.default && config.default.end) || '',
  sites: [],
  needs: 'all',
  search: '',
  ordersStart: '',  // the orders section's own dates
  ordersEnd: '',
  orders: [],  // the orders in those dates, before the search box narrows them
  rows: [],
  sort: null,  // the main table's sort, by a header (2026-11-16): { key, dir: 'asc'|'desc' }; null, the server's order
  counts: {},
  panelItem: null,
  panelTab: 'subs',
  panelScope: 'medline',  // 'infor': the whole Infor item; 'medline': only panelItem (one UOM)
  linesOpen: new Set(),  // the panel's kill lines: the sites whose lines show (2026-11-20), until another item opens
  panelData: null,
  contractLines: [],  // the contract search's latest results
  vendorResults: [],  // the vendor search's latest results
};

// The page link keeps what's shown, so it can be shared or bookmarked (2026-10-19): ?start=&end=
// (left out on today, the default, so a bookmark opens on today; an old ?dates=today link opens
// there too), ?sites=a,b, ?q= (the search), ?needs=, the table's ?sort=&dir= (2026-11-16), and the
// open panel's ?item=&scope=&tab=. table.js checks the sort's key.
export const linked = new URLSearchParams(window.location.search);
if (linked.get('start') && linked.get('end')) {
  state.start = linked.get('start');
  state.end = linked.get('end');
}
state.sites = (linked.get('sites') || '').split(',').filter(Boolean);
state.search = (linked.get('q') || '').trim().toLowerCase();
if (linked.get('needs') && (config.needs || []).some(([key]) => key === linked.get('needs'))) state.needs = linked.get('needs');
if (linked.get('sort')) state.sort = { key: linked.get('sort'), dir: linked.get('dir') === 'asc' ? 'asc' : 'desc' };

// Keep the page link in step with what's shown (no new history entry each time).
export function syncLink() {
  const params = new URLSearchParams();
  const opening = config.default || {};
  if (state.start && state.end && !(state.start === opening.start && state.end === opening.end)) {
    params.set('start', state.start);
    params.set('end', state.end);
  }
  if (state.sites.length) params.set('sites', state.sites.join(','));
  const search = $('fk-search').value.trim();
  if (search) params.set('q', search);
  if (state.needs !== 'all') params.set('needs', state.needs);
  if (state.sort) { params.set('sort', state.sort.key); params.set('dir', state.sort.dir); }
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
export const addVendorItemUrl = (subId) => api.addVendorItem.replace('/0/', `/${subId}/`);
export const vendorItemUrl = (id, action) => api.vendorItemAction.replace('/0/', `/${id}/`).replace('ACTION', action);
export const orderUrl = (orderId, action) => api.orderAction.replace('/0/', `/${orderId}/`).replace('ACTION', action);
export const historyUrl = (entity, id) => api.history.replace('ENTITY', entity).replace(/\/0$/, `/${id}`);
