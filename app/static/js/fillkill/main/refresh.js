/* Main: reloading what a change touches. */

import { loadOrders } from './orders.js';
import { loadPanel, panelIsOpen } from './panel.js';
import { loadMain } from './table.js';

// After a change: the panel (with the message), the table and the orders.
export async function afterChange(message) {
  await Promise.all([loadPanel(message ? { text: message, kind: 'success' } : null), loadMain(), loadOrders()]);
}

// The table's dates or sites changed (the orders section keeps its own dates).
export function reloadAll() {
  loadMain();
  if (panelIsOpen()) loadPanel();
}
