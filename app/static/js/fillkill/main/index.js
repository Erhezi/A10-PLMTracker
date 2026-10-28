/* Fill/Kill Management: the Main page (plan v2 §5.2).
 *
 * Reads the JSON API, draws the main table, the item panel and the orders below, and sends actions
 * through appFetch (CSRF token included). Controls a user's roles don't allow aren't drawn; the
 * server checks every action anyway.
 *
 *   state.js     what's shown, and the page link that keeps it
 *   controls.js  dates, sites, search, Needs chips
 *   table.js     the main table
 *   panel.js     the item panel; tabs.js draws its tabs
 *   forms.js     the forms in the modal, the contract search, the vendor ID check
 *   orders.js    the orders under the table
 *   refresh.js   reloading after a change
 *
 * The modules import each other's functions (the panel opens forms, a form reloads the panel), so
 * some imports go both ways. That is fine as long as no module calls another's function while it
 * loads: each sets itself up in its setup function, called here.
 */

import { setupDates, setupNeeds, setupSearch, setupSites } from './controls.js';
import { setupForms } from './forms.js';
import { loadOrders, setupOrders } from './orders.js';
import { openPanel, setupPanel } from './panel.js';
import { linked } from './state.js';
import { loadMain, setupTable } from './table.js';

setupDates();
setupSites();
setupSearch();
setupNeeds();
setupTable();
setupPanel();
setupForms();
setupOrders();
loadMain();
loadOrders();

// A link can open an item's panel: ?item=<Medline item>, with &scope=infor for all its UOMs and
// &tab=subs|lines|history|orders (the Subs page and the Dashboard link to it).
if (linked.get('item')) openPanel(linked.get('item'), linked.get('tab'), linked.get('scope'));
