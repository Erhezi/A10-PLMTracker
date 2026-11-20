// Fill/Kill smoke walkthrough: drives headless Edge through Main, the item panel, the forms, the
// Subs page and the Dashboard on dev_server.py's sample data, and fails on any step that doesn't
// show what it should or on any browser error.
//
//   python tools/fillkill_ui/dev_server.py        (in one terminal; a fresh start each run)
//   node tools/fillkill_ui/smoke.mjs              (in another; Node 22+)
//
// Options: --base http://127.0.0.1:5099, --out <folder for failure screenshots>. EDGE=<path to
// msedge.exe or chrome.exe> if the browser isn't in the usual place.

import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { parseArgs } from 'node:util';

const { values: opts } = parseArgs({
  options: { base: { type: 'string', default: 'http://127.0.0.1:5099' }, out: { type: 'string', default: join(tmpdir(), 'fillkill-smoke') } },
});
const BASE = opts.base.replace(/\/$/, '');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const BROWSERS = [process.env.EDGE, 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe'].filter(Boolean);
const browserPath = BROWSERS.find((p) => existsSync(p));
if (!browserPath) { console.log('No Edge found: set EDGE to msedge.exe or chrome.exe'); process.exit(2); }

// --- the browser ---------------------------------------------------------------------------

const profile = mkdtempSync(join(tmpdir(), 'fillkill-smoke-edge-'));
const browser = spawn(browserPath, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
  '--no-first-run', '--no-default-browser-check', '--window-size=1600,1100', 'about:blank'], { stdio: 'ignore' });

let port = null;

// Edge's launcher hands over to other processes, so killing it isn't enough: ask the browser itself
// to close, then remove its profile once it has let go of it.
async function closeBrowser() {
  try {
    const version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
    const socket = new WebSocket(version.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      socket.addEventListener('open', resolve, { once: true });
      socket.addEventListener('error', reject, { once: true });
    });
    socket.send(JSON.stringify({ id: 1, method: 'Browser.close' }));
    await sleep(500);
    socket.close();
  } catch { /* it never started, or is gone already */ }
  if (process.platform === 'win32') spawnSync('taskkill', ['/F', '/T', '/PID', String(browser.pid)], { stdio: 'ignore' });
  else browser.kill();
  for (let i = 0; i < 40 && port; i++) {  // until it stops answering
    try { await fetch(`http://127.0.0.1:${port}/json/version`); await sleep(250); } catch { break; }
  }
  for (let i = 0; i < 40; i++) {
    try { rmSync(profile, { recursive: true, force: true }); return; } catch { await sleep(250); }
  }
  console.log(`(couldn't remove the browser profile ${profile})`);
}

for (let i = 0; i < 100 && !port; i++) {
  try { port = readFileSync(join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0].trim(); } catch { await sleep(100); }
}
let target = null;
for (let i = 0; i < 50 && port && !target; i++) {
  try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === 'page'); } catch { await sleep(200); }
}
if (!target) { console.log('The browser did not start'); await closeBrowser(); process.exit(2); }

const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
let nextId = 1;
const pending = new Map();
const browserErrors = [];
ws.addEventListener('message', (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); return; }
  if (msg.method === 'Runtime.exceptionThrown') {
    browserErrors.push(`exception: ${msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text}`);
  }
  if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
    browserErrors.push(`console.error: ${msg.params.args.map((a) => a.value ?? a.description).join(' ')}`);
  }
  // The browser asks for /favicon.ico on its own; the app has none.
  if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error' && !/\/favicon\.ico$/.test(msg.params.entry.url || '')) {
    browserErrors.push(`${msg.params.entry.text} ${msg.params.entry.url || ''}`.trim());
  }
});
const send = (method, params = {}) => new Promise((resolve) => {
  const id = nextId++;
  pending.set(id, resolve);
  ws.send(JSON.stringify({ id, method, params }));
});

async function evaluate(expression) {
  const res = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (res.result?.exceptionDetails) throw new Error(`${expression}\n  -> ${res.result.exceptionDetails.exception?.description}`);
  return res.result?.result?.value;
}

// Wait until the expression is true; one that throws (the page is still loading) counts as false.
async function waitFor(expression, what, ms = 10000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try { if (await evaluate(expression)) return; } catch { /* not there yet */ }
    await sleep(150);
  }
  throw new Error(`timed out waiting for ${what}`);
}

// A page gets 30 s to load (2026-11-16): the dev server, serving from the OneDrive folder, can take
// a second per file, and Main loads 13 modules.
async function go(path, ready, what) {
  await send('Page.navigate', { url: `${BASE}${path}` });
  await sleep(300);
  await waitFor(ready, what, 30000);
}

const text = (selector) => evaluate(`(document.querySelector(${JSON.stringify(selector)}) || {}).innerText || ''`);
const count = (selector) => evaluate(`document.querySelectorAll(${JSON.stringify(selector)}).length`);
const present = (selector) => waitFor(`document.querySelector(${JSON.stringify(selector)})`, selector);

async function click(selector) {
  await present(selector);
  await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
}

// Double-click the element the expression finds (Main's cells to write in, 2026-10-27).
async function dblclick(expression, what) {
  await waitFor(expression, what);
  await evaluate(`${expression}.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))`);
}

// The first element matching the selector whose text is exactly ``label``.
async function clickText(selector, label) {
  const find = `[...document.querySelectorAll(${JSON.stringify(selector)})].find((el) => el.innerText.trim() === ${JSON.stringify(label)})`;
  await waitFor(find, `${selector} "${label}"`);
  await evaluate(`${find}.click()`);
}

async function setValue(selector, value, eventName = 'change') {
  await present(selector);
  await evaluate(`(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    el.value = ${JSON.stringify(value)};
    el.dispatchEvent(new Event(${JSON.stringify(eventName)}, { bubbles: true }));
  })()`);
}
const panelSays = (words) => waitFor(`document.getElementById('fk-panel-body').innerText.includes(${JSON.stringify(words)})`, `"${words}" in the panel`);
const modalOpen = () => waitFor(`document.getElementById('fk-modal').classList.contains('show')`, 'the form');
const modalClosed = () => waitFor(`!document.getElementById('fk-modal').classList.contains('show')`, 'the form to close');
// The Subs page's drawer for a Medline item (2026-11-20).
const drawerSays = (words) => waitFor(`document.getElementById('fk-item-drawer-body').innerText.includes(${JSON.stringify(words)})`,
  `"${words}" in the drawer`);
async function openDrawer(item) {
  await click(`#fk-subs-rows a[data-item="${item}"]`);
  await waitFor(`document.getElementById('fk-item-drawer').classList.contains('show')
    && document.getElementById('fk-item-drawer-title').innerText === ${JSON.stringify(item)}
    && !document.getElementById('fk-item-drawer-body').innerText.includes('Loading')`, `${item}'s drawer`);
}
async function closeDrawer() {
  await click('#fk-item-drawer .btn-close');
  await waitFor(`!document.querySelector('#fk-item-drawer.show, #fk-item-drawer.hiding, .offcanvas-backdrop')`, 'the drawer to close');
}

function expect(ok, message) {
  if (!ok) throw new Error(message);
}

const daysAgo = (n) => {
  const d = new Date(Date.now() - n * 86400000);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};
const MAIN_READY = `document.querySelector('#fk-main tbody') && !document.querySelector('#fk-main').innerText.includes('Loading')`;
// dev_server.py's sample sites (Medline Sold-To codes): an order is for one (2026-10-27).
const SITE_A = '0000000001';
const SITE_B = '0000000002';
// The text of the last two cells (Total Killed (EA), Total Sub Ordered (EA)) of the item with this Medline item.
const lastCells = (item) => `[...[...document.querySelectorAll('#fk-main tbody.fk-item')].find((b) => b.innerText.includes(${JSON.stringify(item)}))
  .rows[0].cells].slice(-2).map((c) => c.innerText.replace(/\\s+/g, ' ').trim()).join('|')`;
// The main table's line whose Sub Approved by Nursing cell is this Reference SKU.
const lineOf = (sku) => `[...document.querySelectorAll('#fk-main tbody.fk-item > tr')].find((tr) => [...tr.cells]
  .some((c) => c.innerText.trim() === ${JSON.stringify(sku)}))`;

// --- the walkthrough -----------------------------------------------------------------------

const steps = [
  ['Main opens on today', async () => {
    await go('/dev-login?as=all', `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length`, 'the main table');
    // The search first, as Order Timing's; the dates on Today, its quick button pressed (2026-11-19).
    expect(await evaluate(`!!(document.getElementById('fk-search').compareDocumentPosition(document.getElementById('fk-start'))
      & Node.DOCUMENT_POSITION_FOLLOWING)`), 'the search is not before the dates');
    expect(await evaluate(`document.querySelector('#fk-quick-dates [aria-pressed="true"]')?.innerText`) === 'Today',
      'the dates are not on today');
    expect(!(await evaluate('location.search')).includes('start='), 'the link has the default dates');
    expect(await evaluate(`document.querySelector('#fk-orders-quick [aria-pressed="true"]')?.innerText`) === 'Today',
      'the orders are not on today');
    expect(await count('#fk-main tbody.fk-item') === 2, `${await count('#fk-main tbody.fk-item')} items today, not 2`);
    // When Medline made the file (8:04 Central is 9:04 here), then when it was loaded (2026-11-17).
    expect(/^Data as of \d\d\/\d\d\/\d{4} 09:04 · last loaded 09:30/.test(await text('#fk-data-as-of')),
      `the data as of: ${await text('#fk-data-as-of')}`);
    // At most 450px tall, scrolling inside, its header staying on top; the orders too (2026-10-20).
    for (const table of ['#fk-main', '#fk-orders']) {
      const cap = await evaluate(`getComputedStyle(document.querySelector('${table}').parentElement).maxHeight`);
      expect(cap === '450px', `${table} is capped at ${cap}, not 450px`);
    }
    expect(await evaluate(`getComputedStyle(document.querySelector('#fk-main thead th')).position`) === 'sticky', 'the header does not stay on top');
    expect(await text('#fk-orders-title') === 'Sub Orders Recorded', `the orders are titled ${await text('#fk-orders-title')}`);
  }],
  ['A range of dates, kept in the page link', async () => {
    // The last 7 days (the sample's three days of lines), then a range typed in.
    await click('#fk-quick-dates [data-days="7"]');
    await waitFor(`document.querySelectorAll('#fk-main tbody.fk-item').length === 3`, '3 items in the last 7 days');
    expect(await evaluate(`document.querySelector('#fk-quick-dates [aria-pressed="true"]')?.innerText`) === 'Last 7 days',
      'Last 7 days is not pressed');
    expect(await evaluate(`document.getElementById('fk-start').value`) === daysAgo(6), 'the last 7 days start elsewhere');
    await setValue('#fk-start', daysAgo(2));
    await waitFor(`location.search.includes('start=${daysAgo(2)}')`, 'the dates in the link');
    expect(await evaluate(`!document.querySelector('#fk-quick-dates [aria-pressed="true"]')`), 'a quick date still pressed');
    expect(await count('#fk-main tbody.fk-item') === 3, '3 items over three days');
    expect(await count('#fk-main .fk-flag') >= 1, "no flag on the Medline item whose customer item isn't the Infor item");
  }],
  ['Search', async () => {
    await setValue('#fk-search', 'nitrile', 'input');
    await waitFor(`document.querySelectorAll('#fk-main tbody.fk-item').length === 1`, 'one glove item');
    await setValue('#fk-search', '', 'input');
    await waitFor(`document.querySelectorAll('#fk-main tbody.fk-item').length === 3`, 'all 3 items again');
  }],
  ['Sorting by a header, kept in the page link', async () => {
    // Each item's Infor item, in the table's order (2026-11-16).
    const order = () => evaluate(`[...document.querySelectorAll('#fk-main tbody.fk-item')]
      .map((b) => b.rows[0].cells[0].innerText.split('\\n')[0].trim()).join('|')`);
    const header = (key) => `#fk-main th[data-sort="${key}"] .fk-sort`;
    const sortedBy = (key, dir) => waitFor(dir ? `document.querySelector('#fk-main th[data-sort="${key}"]').getAttribute('aria-sort') === '${dir}'`
      : `!document.querySelector('#fk-main th[aria-sort]')`, `${key} ${dir || 'unsorted'}`);
    const own = '100339|999999|Not in Infor';
    expect(await order() === own, `the table's own order: ${await order()}`);
    // A number, largest first (2,300 EA, 8 EA, 6 EA), then smallest first, then the table's own order.
    await click(header('killed_each'));
    await sortedBy('killed_each', 'descending');
    expect(await order() === '999999|100339|Not in Infor', `Total Killed (EA), largest first: ${await order()}`);
    expect((await evaluate('location.search')).includes('sort=killed_each&dir=desc'), 'the link lacks the sort');
    await click(header('killed_each'));
    await sortedBy('killed_each', 'ascending');
    expect(await order() === 'Not in Infor|100339|999999', `Total Killed (EA), smallest first: ${await order()}`);
    await click(header('killed_each'));
    await sortedBy('killed_each', null);
    expect(await order() === own && !(await evaluate('location.search')).includes('sort='), `not back to the table's own order: ${await order()}`);
    // Text, A to Z first; a blank stays last either way.
    await click(header('infor_item'));
    await click(header('infor_item'));
    await sortedBy('infor_item', 'descending');
    expect(await order() === '999999|100339|Not in Infor', `Infor Item, Z to A, the blank last: ${await order()}`);
    await click(header('infor_item'));
    // Medline's reason type, Z to A (Disco`d, Backorder, Allocated Item), from the page link.
    await click(header('reason'));
    await click(header('reason'));
    await sortedBy('reason', 'descending');
    await go(`/fillkill/${await evaluate('location.search')}`, `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length === 3`,
      'the table from the page link');
    await sortedBy('reason', 'descending');
    expect(await order() === 'Not in Infor|100339|999999', `Latest Reason, Z to A, from the link: ${await order()}`);
    await click(header('reason'));
    await sortedBy('reason', null);
  }],
  ['The panel: a whole Infor item, then one UOM', async () => {
    await clickText('#fk-main button[data-scope="infor"]', '999999');
    await waitFor(`document.getElementById('fk-panel-title').innerText === 'Infor item 999999'`, 'the Infor item in the panel');
    await panelSays('2 UOMs');
    expect((await evaluate('location.search')).includes('scope=infor'), 'the link lacks the panel');
    await click('[data-panel-tab="lines"]');
    // Both at one site, folded like any other (2026-11-20, the user): a click shows its two lines.
    await waitFor(`document.querySelectorAll('#fk-panel-content tr.fk-site-row').length === 1
      && document.querySelectorAll('#fk-panel-content tr.fk-kill-line').length === 2`, 'one site, its two kill lines');
    expect(await evaluate(`document.querySelector('#fk-panel-content tr.fk-site-row').getAttribute('aria-expanded')`) === 'false',
      'a single site open before a click');
    await click('#fk-panel-content tr.fk-site-row');
    // Each line's ship-to by its code (Ship-To Name 2 without "- UBOAT"), and Medline's reason type (2026-11-16),
    // its comment right after it on the same line (2026-11-20, the user).
    await panelSays('PWLREO3 · OR');
    await panelSays('Allocated Item Allocation limit has been reached');
    expect(await evaluate(`[...document.querySelectorAll('#fk-panel-content tr.fk-kill-line')]
      .every((tr) => !tr.cells[tr.cells.length - 1].querySelector('div'))`), "a kill line's comment under its reason, not after it");
    expect(!(await evaluate(`document.getElementById('fk-panel-body').innerText.includes('UBOAT')`)), 'UBOAT in the kill lines');
    await click('[data-panel-focus="MDS2585HC"]');
    await waitFor(`document.querySelectorAll('#fk-panel-content tr.fk-kill-line').length === 1`, "one UOM's kill line");
    await click('[data-panel-tab="history"]');
    await panelSays('Nothing yet.');
  }],
  ['Total Killed: its sites, and its kill lines by site', async () => {
    // The cup, killed at both sample sites in these dates: "2 sites", each site's on hover (2026-11-19).
    const cell = `document.querySelector('#fk-main td[data-kill-lines="DYND70294BH"]')`;
    expect((await evaluate(`${cell}.innerText.replace(/\\s+/g, ' ').trim()`)) === '8 EA 2 sites',
      `the cup's Total Killed: ${await evaluate(`${cell}.innerText`)}`);
    const each = await evaluate(`${cell}.querySelector('[title]').title`);
    expect(each === 'SAMPLE SITE A: 5 EA\nSAMPLE SITE B: 3 EA', `the sites on hover: ${each}`);
    // One site: no tag.
    expect(!(await evaluate(`document.querySelector('#fk-main td[data-kill-lines="MDS2585H"]').innerText`)).includes('sites'),
      'a sites tag with one site');
    // Double-click: the cup's kill lines in its panel.
    await dblclick(cell, "the cup's Total Killed");
    await waitFor(`document.getElementById('fk-panel-title').innerText === 'DYND70294BH'
      && document.querySelector('[data-panel-tab="lines"].active')`, "the cup's kill lines in the panel");
    // By site, as Order Timing's orders (2026-11-20): a row per site and one for all, most lines first,
    // then by name; each site's lines hidden until it's clicked.
    const bySite = () => evaluate(`[...document.querySelectorAll('#fk-panel-content tr.fk-site-row, #fk-panel-content .fk-site-total tr')]
      .map((tr) => [...tr.cells].slice(1).map((c) => c.innerText.replace(/\\s+/g, ' ').trim()).join(';')).join('|')`);
    const shown = () => evaluate(`[...document.querySelectorAll('#fk-panel-content tr.fk-kill-line')].filter((tr) => tr.offsetParent).length`);
    await waitFor(`document.querySelectorAll('#fk-panel-content tr.fk-site-row').length === 2`, 'its two sites');
    await panelSays('2 kill lines at 2 sites');
    expect(await bySite() === 'SAMPLE SITE A;5 EA;1;1|SAMPLE SITE B;3 EA;1;1|All sites;8 EA;2;2', `the cup by site: ${await bySite()}`);
    const where = await evaluate(`document.querySelector('#fk-panel-content tr.fk-site-row td:last-child [title]').title`);
    expect(where === 'PWLREICU · INTENS CARE UNIT: 1 line', `site A's locations on hover: ${where}`);
    expect(await shown() === 0, `kill lines showing before a site is clicked: ${await shown()}`);
    // A click on site A shows its line, with its ship-to; Enter on site B, B's.
    const siteRow = (name) => `#fk-panel-content tr.fk-site-row[data-site="${name}"]`;
    await click(siteRow('SAMPLE SITE A'));
    await waitFor(`document.querySelector('${siteRow('SAMPLE SITE A')}').getAttribute('aria-expanded') === 'true'`, 'site A open');
    expect(await shown() === 1, `site A's kill lines: ${await shown()}`);
    await panelSays('PWLREICU · INTENS CARE UNIT');
    await evaluate(`document.querySelector('${siteRow('SAMPLE SITE B')}').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))`);
    expect(await shown() === 2, `sites A and B's kill lines: ${await shown()}`);
    expect(await text('[data-lines-all]') === 'Hide all lines', `with every site open: ${await text('[data-lines-all]')}`);
    await click('[data-lines-all]');
    expect(await shown() === 0 && (await text('[data-lines-all]')) === 'Show all lines', 'Hide all lines left some showing');
    await click('[data-lines-all]');
    expect(await shown() === 2, `Show all lines: ${await shown()}`);
    // The sites open stay open on another tab and back.
    await click(siteRow('SAMPLE SITE B'));
    await click('[data-panel-tab="subs"]');
    await click('[data-panel-tab="lines"]');
    await waitFor(`document.querySelector('${siteRow('SAMPLE SITE A')}')?.getAttribute('aria-expanded') === 'true'
      && document.querySelector('${siteRow('SAMPLE SITE B')}').getAttribute('aria-expanded') === 'false'`, 'site A still open, B closed');
    // The All UOMs line: the whole Infor item's; its one site folded, its UOMs in eaches too (3 BX of 100, 2 CS of 1,000).
    await dblclick(`document.querySelector('#fk-main tr.fk-total td[data-kill-lines][data-scope="infor"]')`, 'the gloves\' All UOMs line');
    await waitFor(`document.getElementById('fk-panel-title').innerText === 'Infor item 999999'`, 'the whole Infor item');
    await waitFor(`document.querySelectorAll('#fk-panel-content tr.fk-site-row').length === 1`, 'its one site');
    expect(await bySite() === 'SAMPLE SITE A;3 BX 2 CS 2,300 EA;2;2', `the gloves by site: ${await bySite()}`);
    expect(await shown() === 0 && !(await count('[data-lines-all]')), 'one site: its lines showing, or a Show all lines');
    // Total Killed (EA), the next to last cell: the whole Infor item's too, its sites closed again.
    await dblclick(`[...[...document.querySelectorAll('#fk-main tbody.fk-item')].find((b) => b.innerText.includes('DYND70294BH'))
      .rows[0].cells].at(-2)`, "the cup's Total Killed (EA)");
    await waitFor(`document.getElementById('fk-panel-title').innerText === 'Infor item 100339'`, "the cup's Infor item");
    await waitFor(`document.querySelectorAll('#fk-panel-content tr.fk-site-row').length === 2`, "the cup's Infor item's sites");
    expect(await bySite() === 'SAMPLE SITE A;5 EA;1;1|SAMPLE SITE B;3 EA;1;1|All sites;8 EA;2;2', `the cup's Infor item by site: ${await bySite()}`);
    expect(await shown() === 0, `another item's sites open: ${await shown()}`);
    // A click on a Medline item, an Infor item or Subs Status opens the panel on its Subs tab,
    // whichever tab was open (2026-11-19).
    const onSubs = (title) => waitFor(`document.getElementById('fk-panel-title').innerText === '${title}'
      && document.querySelector('[data-panel-tab="subs"].active')`, `${title} on its Subs tab`);
    await click('#fk-main button[data-open="DYND70294BH"]:not([data-scope])');
    await onSubs('DYND70294BH');
    await click('[data-panel-tab="lines"]');
    await clickText('#fk-main button[data-scope="infor"]', '999999');
    await onSubs('Infor item 999999');
    await click('[data-panel-tab="orders"]');
    await click('#fk-main td[data-open="SAMPLE0001"]');
    await onSubs('SAMPLE0001');
    // Nothing outlines a cell to double-click any more (2026-11-19, the user).
    expect(!(await evaluate(`[...document.styleSheets].flatMap((s) => { try { return [...s.cssRules]; } catch { return []; } })
      .some((r) => /data-(dblclick|kill-lines)\\]:hover/.test(r.selectorText || ''))`)), 'a hover outline on the cells to double-click');
  }],
  ['Nursing adds a Reference SKU: approved, so it can be ordered', async () => {
    await click('#fk-main button[data-open="DYND70294BH"]:not([data-scope])');
    await waitFor(`document.getElementById('fk-panel-title').innerText === 'DYND70294BH'`, 'DYND70294BH in the panel');
    await click('[data-panel-tab="subs"]');
    await click('[data-act="show-add"]');
    await setValue('#fk-add-sku', '88885');
    await setValue('#fk-add-comment', 'From the supplier by phone');
    await evaluate(`document.getElementById('fk-add-form').requestSubmit()`);
    await panelSays('Approved: it can be ordered.');
    expect((await text('#fk-panel-content')).includes('Vendor item needed'), 'no "Vendor item needed"');
    // Approved by Nursing shows the Reference SKU, with a pencil until there's something to order (2026-10-20).
    await waitFor(`[...document.querySelectorAll('#fk-main tbody.fk-item')].some((b) => b.innerText.includes('88885')
      && b.querySelector('[data-add-vi] .bi-pencil-square'))`, 'the approved sub, with its pencil, in the table');
    // Its comments beside it (2026-10-21): the icon counts them and opens them; a click elsewhere closes them.
    const chat = `[...document.querySelectorAll('#fk-main [data-comments]')].find((b) => b.closest('td').innerText.includes('88885'))`;
    await waitFor(`${chat} && ${chat}.innerText.trim() === '1'`, 'the comments icon, counting 1');
    // The latest reads under the sub, with who and when (2026-10-27, for the nursing manager).
    const said = await evaluate(`${chat}.closest('td').querySelector('.fk-sub-comment').innerText.replace(/\\s+/g, ' ').trim()`);
    expect(said.startsWith('From the supplier by phone all ·'), `the comment under the sub: ${said}`);
    await evaluate(`${chat}.click()`);
    await waitFor(`(document.querySelector('.fk-comments-popover') || {}).innerText?.includes('From the supplier by phone')`,
      'the comment in its popover');
    await sleep(1000);  // it stays open until closed (a Bootstrap popover can hide itself when its content changes)
    expect(await count('.fk-comments-popover') === 1, 'the comments closed on their own');
    await evaluate('document.body.click()');
    await waitFor(`!document.querySelector('.fk-comments-popover')`, 'the comments to close');
  }],
  ['The Materials Manager adds a vendor item from a contract line', async () => {
    await click('#fk-panel-content [data-act="add-vi"]');
    await modalOpen();
    await waitFor(`document.querySelectorAll('[data-contract]').length === 2`, 'two contract lines');
    const results = await text('#fk-contract-results');
    expect(results.includes('2 contracts (1 MHS)') && results.includes('Non-MHS'), 'the contracts and MHS badges are not shown');
    // The killed item's UOM/QOE beside it (2026-10-21), here from the panel.
    expect((await text('.fk-form-summary')).includes('Reference SKU 88885 for DYND70294BH (EA/1)'),
      `the summary: ${await text('.fk-form-summary')}`);
    // The killed cup itself, from Medline: listed but can't be chosen, and flagged when typed (2026-10-20).
    await setValue('#fk-contract-q', 'DYND70294BH', 'input');
    await waitFor(`document.getElementById('fk-contract-results').innerText.includes('The killed item itself')`, 'the killed item marked');
    expect(await count('[data-contract]') === 0, 'the killed item itself can be chosen');
    await setValue('#fk-m-vendor_part', 'dynd70294bh', 'input');
    await setValue('#fk-m-vendor_id', '1000931', 'input');
    expect((await text('#fk-m-vendor_part-note')).includes('DYND70294BH itself'), 'no note under the vendor part');
    await setValue('#fk-contract-q', '88885', 'input');
    await waitFor(`document.querySelectorAll('[data-contract]').length === 2`, 'the two contract lines again');
    await click('[data-contract="0"]');
    expect((await text('#fk-m-vendor_part-note')) === '', 'the note under the vendor part stayed');
    expect(await evaluate(`document.getElementById('fk-m-vendor').value`) === 'CARDINAL HEALTH', 'the vendor not filled in');
    expect(await evaluate(`document.getElementById('fk-m-vendor_id').value`) === '1000001', 'the vendor ID not filled in');
    await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
    await modalClosed();
    await panelSays('Vendor item added.');
    // Main: the sub keeps its Reference SKU, without the pencil; the vendor item is a tile beside it.
    await waitFor(`document.querySelector('#fk-main [data-order-vi]')`, 'a vendor item tile in the table');
    const tile = await text('#fk-main [data-order-vi]');
    expect(tile.includes('88885') && tile.includes('BX') && tile.includes('1000001 · CARDINAL HEALTH'), `the tile: ${tile}`);
    expect(await count('#fk-main [data-add-vi] .bi-pencil-square') === 0, 'the pencil stayed');
  }],
  ['The contract search: a short scrolling list, narrowed by more words', async () => {
    await click('#fk-panel-content [data-act="add-vi"]');
    await modalOpen();
    await setValue('#fk-contract-q', 'chloraprep', 'input');
    await waitFor(`document.querySelectorAll('[data-contract]').length === 6`, 'six ChloraPrep lines');
    const list = await evaluate(`(() => { const l = document.querySelector('.fk-contract-list');
      return { shown: l.clientHeight, all: l.scrollHeight, rem: parseFloat(getComputedStyle(document.documentElement).fontSize) }; })()`);
    expect(list.all > list.shown && list.shown <= 15 * list.rem + 1, `the list doesn't scroll within 15rem (${JSON.stringify(list)})`);
    await setValue('#fk-contract-q', '930103 chloraprep bx', 'input');
    await waitFor(`document.querySelectorAll('[data-contract]').length === 1`, 'one line for "930103 chloraprep bx"');
    expect((await text('#fk-contract-results')).includes('B-D930103CSZ'), 'not B-D930103CSZ');
    await click('#fk-modal-form [data-bs-dismiss="modal"].btn-link');
    await modalClosed();
  }],
  ['Recording an order from a vendor item tile, for a site', async () => {
    await click('#fk-main [data-order-vi]');
    await modalOpen();
    expect((await text('.fk-form-summary')).includes('88885 · CARDINAL HEALTH (1000001) · BX/100'), 'the vendor item is not shown');
    const check = async () => (await text('.fk-order-check')).replace(/\s+/g, ' ');
    // Every site shown: the Materials Manager chooses the order's site first (2026-10-27).
    expect(await evaluate(`document.getElementById('fk-m-site').value`) === '', 'a site was chosen for them');
    expect((await check()).includes('Choose the site this order is for'), `the check before a site: ${await check()}`);
    // Killed by the each at site A (5 of the 8 EA), ordered by the box of 100: what was killed there
    // and a recommendation, in red, and no quantity (2026-10-20).
    await setValue('#fk-m-site', SITE_A);
    const said = await check();
    expect(said.includes('Killed at SAMPLE SITE A in these dates: 5 EA (DYND70294BH: 5 EA (EA/1))') && said.includes('still needed: 5 EA')
      && said.includes('Recommended order: 1 BX') && said.includes('= 0.05 BX, rounded up') && said.includes('Quantity is left blank'),
    `the check: ${said}`);
    expect(await evaluate(`getComputedStyle(document.querySelector('.fk-order-check')).backgroundColor`) === 'rgb(248, 215, 218)',
      'the check is not on red');
    const quantity = '#fk-modal-form [name="quantity"]';
    expect(await evaluate(`document.querySelector('${quantity}').value`) === '', 'the quantity is filled in');
    expect(await evaluate(`document.querySelector('${quantity}').placeholder`) === 'Recommended: 1', 'no recommendation in the box');
    await setValue(quantity, '1');
    await setValue('#fk-m-po_number', ' 3000564756 ');
    await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
    await modalClosed();
    await panelSays('Order recorded for SAMPLE SITE A.');
    await waitFor(`document.querySelector('#fk-main').innerText.includes('Ordered')`, 'Ordered in the table');
    // Killed and ordered for the item, in eaches (2026-10-21): 8 EA killed at two sites, 1 BX of 100
    // ordered for site A; site B has ordered nothing for its 3 EA (2026-10-27).
    await waitFor(`${lastCells('DYND70294BH')} === '8 EA 2 sites|100 EA SAMPLE SITE B: 3 EA short'`, 'the eaches columns', 5000)
      .catch(async () => { throw new Error(`the eaches columns: ${await evaluate(lastCells('DYND70294BH'))}`); });
    await waitFor(`document.getElementById('fk-orders-rows').innerText.includes('DYND70294BH')`, 'the order under the table');
    // Its row (2026-10-20): site and PO (2026-10-27), Infor item, vendor part, QOE, ordered with a grey
    // UOM, vendor ID, vendor name.
    const cells = await evaluate(`[...document.querySelector('#fk-orders-rows tr').cells].map((c) => c.innerText.replace(/\\s+/g, ' ').trim())`);
    expect(JSON.stringify(cells.slice(1, 10)) === JSON.stringify(['SAMPLE SITE A', 'DYND70294BH', '100339', '88885', '100', '1 BX',
      '3000564756', '1000001', 'CARDINAL HEALTH']), `the order's row: ${JSON.stringify(cells)}`);
    expect(await evaluate(`getComputedStyle(document.querySelector('#fk-orders-rows tr').cells[6].querySelector('.text-muted')).color`)
      !== await evaluate(`getComputedStyle(document.querySelector('#fk-orders-rows tr').cells[6]).color`), 'the UOM is not grey');
    // The search box: by any of its numbers, dashes optional; the PO number too.
    await setValue('#fk-orders-q', 'nothing-like-it', 'input');
    await waitFor(`document.getElementById('fk-orders-rows').innerText.includes('No order in these dates matches.')`, 'no match');
    await setValue('#fk-orders-q', '100339 888-85', 'input');
    await waitFor(`document.getElementById('fk-orders-rows').innerText.includes('DYND70294BH')`, 'the order found by Infor item and part');
    await setValue('#fk-orders-q', '3000564756', 'input');
    await waitFor(`document.getElementById('fk-orders-rows').innerText.includes('DYND70294BH')`, 'the order found by its PO');
    await setValue('#fk-orders-q', '', 'input');
  }],
  ["The panel's orders: a table, a row's history under it", async () => {
    await click('[data-panel-tab="orders"]');
    const rows = '#fk-panel-content table.fk-orders-tab tbody tr:not(.fk-order-more)';
    await waitFor(`document.querySelectorAll('${rows}').length === 1`, 'one order row');
    const cells = await evaluate(`[...document.querySelector('${rows}').cells].map((c) => c.innerText.replace(/\\s+/g, ' ').trim())`);
    expect(cells[1] === 'SAMPLE SITE A PO 3000564756' && cells[2] === '88885 for 88885' && cells[3] === '1 BX/100'
      && cells[4] === 'CARDINAL HEALTH 1000001', `the order's row: ${JSON.stringify(cells)}`);
    const more = `document.querySelector('#fk-panel-content .fk-order-more')`;
    expect(await evaluate(`${more}.classList.contains('d-none')`), 'the line under the row shows before it is asked for');
    await click('#fk-panel-content [data-act="history"][data-entity="order"]');
    await waitFor(`!${more}.classList.contains('d-none') && ${more}.innerText.includes('Recorded the order')`, 'the history under the row');
    await click('#fk-panel-content [data-act="history"][data-entity="order"]');
    await waitFor(`${more}.classList.contains('d-none')`, 'the history to close');
    await click('[data-panel-tab="subs"]');
  }],
  ['Putting a sub on hold, with a reason: it leaves Sub Approved by Nursing', async () => {
    // Nursing doesn't want it ordered any more (2026-10-28): Hold asks why, optionally, and the
    // select keeps the status it has until that's saved.
    await setValue('#fk-panel-content select[data-act="status"]', 'hold');
    await modalOpen();
    await waitFor(`document.activeElement.id === 'fk-m-comment'`, 'the cursor in the reason');
    expect(await evaluate(`document.querySelector('#fk-panel-content select[data-act="status"]').value`) === 'approved',
      'the select says Hold before it is saved');
    await setValue('#fk-m-comment', 'Recalled by the maker');
    await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
    await modalClosed();
    await panelSays('Status set to Hold.');
    await panelSays('Hold: Recalled by the maker');  // its comment, on its card
    await waitFor(`![...document.querySelectorAll('#fk-main tbody.fk-item')].find((b) => b.innerText.includes('DYND70294BH')).innerText.includes('88885')`, '88885 to leave Sub Approved by Nursing and its tiles');
    expect(await evaluate(`[...document.querySelectorAll('#fk-main tbody.fk-item')].find((b) => b.innerText.includes('DYND70294BH')).innerText.includes('Ordered')`), 'its order left Main with it');
    await click('[data-panel-tab="history"]');
    await panelSays('88885');
    await panelSays('Added the vendor item');
  }],
  ["The recommendation is what's still needed: killed less what's already ordered", async () => {
    // Infor item 999999: MDS2585HC killed 2 CS (Infor's CA, of 1000) and MDS2585H 3 BX of 100, 2,300 EA.
    // Owens' 88885-CS is a CS of 1000 too, saved as CA (2026-10-21).
    await click('#fk-main button[data-open="MDS2585HC"]:not([data-scope])');
    await waitFor(`document.getElementById('fk-panel-title').innerText === 'MDS2585HC'`, 'MDS2585HC in the panel');
    await click('[data-panel-tab="subs"]');
    await click('[data-act="show-add"]');
    await setValue('#fk-add-sku', '  88885-CS  ');
    expect(await evaluate(`document.getElementById('fk-add-sku').value`) === '88885-CS', 'the spaces stayed');
    await evaluate(`document.getElementById('fk-add-form').requestSubmit()`);
    await panelSays('Approved: it can be ordered.');
    await click('#fk-panel-content [data-act="add-vi"]');
    await modalOpen();
    const line = `[...document.querySelectorAll('[data-contract]')].find((b) => b.querySelector('.fw-semibold').innerText === '88885-CS')`;
    await waitFor(line, '88885-CS among the contract lines');
    await evaluate(`${line}.click()`);
    expect(await evaluate(`document.getElementById('fk-m-uom').value`) === 'CA', 'the UOM is not Infor\'s CA');
    expect((await text('#fk-m-uom-note')) === 'CS is CA in Infor', 'no note that CS is CA');
    await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
    await modalClosed();
    await panelSays('Vendor item added.');
    const quantity = '#fk-modal-form [name="quantity"]';
    const check = async () => (await text('.fk-order-check')).replace(/\s+/g, ' ');
    // 2,300 EA still needed at site A, where both were killed, is 2.3 CA: 3 recommended, left blank
    // (not a whole number).
    await click('#fk-panel-content [data-act="order"]');
    await modalOpen();
    await setValue('#fk-m-site', SITE_A);
    let said = await check();
    expect(said.includes('still needed: 2,300 EA') && said.includes('Recommended order: 3 CA') && said.includes("2.3 CA isn't a whole number"),
      `the check: ${said}`);
    expect(await evaluate(`document.querySelector('${quantity}').value`) === '', 'the quantity is filled in');
    // Ordered short: 1 CA of 1000.
    await setValue(quantity, '1');
    await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
    await modalClosed();
    await panelSays('Order recorded for SAMPLE SITE A.');
    await waitFor(`${lastCells('MDS2585HC')} === '2,300 EA|1,000 EA 1,300 EA short'`, 'the shortfall', 5000).catch(async () => {
      throw new Error(`the eaches columns: ${await evaluate(lastCells('MDS2585HC'))}`);
    });
    // The next order takes off what's been ordered: 1,300 EA still needed, 2 CA.
    await click('#fk-panel-content [data-act="order"]');
    await modalOpen();
    await setValue('#fk-m-site', SITE_A);
    said = await check();
    expect(said.includes('Sub ordered for SAMPLE SITE A in these dates: 1,000 EA') && said.includes('still needed: 1,300 EA')
      && said.includes('Recommended order: 2 CA'), `the check: ${said}`);
    // Site B killed none of it: nothing to recommend there.
    await setValue('#fk-m-site', SITE_B);
    said = await check();
    expect(said.includes('SAMPLE SITE B had no kills of this item') && await evaluate(`document.querySelector('${quantity}').placeholder`) === '',
      `the check for site B: ${said}`);
    await sleep(500);  // Bootstrap ignores a close while the form is still fading in
    await click('#fk-modal-form [data-bs-dismiss="modal"].btn-link');
    await modalClosed();
  }],
  ['Filled in when it matches what was killed; a vendor item without a QOE is flagged', async () => {
    // SAMPLE0001 was killed 6 EA at site B (not in Infor, so no QOE: an EA is 1). Main filtered to
    // site B, as a site's Materials Manager would: the order form starts on it, and the orders under
    // the table are site B's (2026-10-27).
    const quantity = '#fk-modal-form [name="quantity"]';
    await click('#fk-site-1');
    await waitFor(`document.getElementById('fk-sites-button').innerText.trim() === 'SAMPLE SITE B'
      && document.querySelectorAll('#fk-main tbody.fk-item').length === 2`, "site B's two items");
    await waitFor(`!document.getElementById('fk-orders-rows').innerText.includes('DYND70294BH')`, "site A's order gone from the orders");
    await click('#fk-main button[data-open="SAMPLE0001"]:not([data-scope])');
    await waitFor(`document.getElementById('fk-panel-title').innerText === 'SAMPLE0001'`, 'SAMPLE0001 in the panel');
    await click('[data-panel-tab="subs"]');
    await click('[data-act="show-add"]');
    await setValue('#fk-add-sku', 'S1');
    await evaluate(`document.getElementById('fk-add-form').requestSubmit()`);
    await panelSays('Approved: it can be ordered.');
    for (const [part, uom] of [['S1-EA', 'EA'], ['S1-BX', 'BX']]) {
      await click('#fk-panel-content [data-act="add-vi"]');
      await modalOpen();
      await setValue('#fk-m-vendor_part', part, 'input');
      await click('[data-no-vendor]');
      await setValue('#fk-m-vendor', 'Local Supply Co', 'input');
      await setValue('#fk-m-uom', uom);
      await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
      await modalClosed();
      await panelSays('Vendor item added.');
    }
    const orderFor = (part) => `[...document.querySelectorAll('#fk-panel-content .fk-vendor-items li')]
      .find((li) => li.innerText.includes(${JSON.stringify(part)})).querySelector('[data-act="order"]')`;
    // The EA vendor item is what was killed: 6 EA filled in; with 4 ordered, 2 more.
    for (const [expected, ordered] of [['6', '4'], ['2', null]]) {
      await waitFor(orderFor('S1-EA'), 'Record order for S1-EA');
      await evaluate(`${orderFor('S1-EA')}.click()`);
      await modalOpen();
      expect(await evaluate(`document.getElementById('fk-m-site').value`) === SITE_B, 'the form is not on the site shown');
      expect(await evaluate(`document.querySelector('${quantity}').value`) === expected, `the quantity is not ${expected}`);
      expect((await text('.fk-order-check')).includes('Quantity filled in'), 'no "Quantity filled in"');
      if (ordered) {
        await setValue(quantity, ordered);
        await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
        await modalClosed();
        await waitFor(`${lastCells('SAMPLE0001')} === '6 EA|4 EA 2 EA short'`, 'the order in the table');
        await waitFor(`document.getElementById('fk-orders-rows').innerText.includes('SAMPLE0001')`, "the order in site B's orders");
      } else {
        await sleep(500);
        await click('#fk-modal-form [data-bs-dismiss="modal"].btn-link');
        await modalClosed();
      }
    }
    // A BX without a QOE: flagged on its tile, and the form says why there's no quantity to recommend.
    await waitFor(`[...document.querySelectorAll('#fk-main [data-order-vi]')].some((b) => b.innerText.includes('S1-BX')
      && b.innerText.includes('no QOE'))`, 'the "no QOE" badge on the tile');
    await evaluate(`${orderFor('S1-BX')}.click()`);
    await modalOpen();
    const said = (await text('.fk-order-check')).replace(/\s+/g, ' ');
    expect(said.includes('No QOE: This vendor item has no QOE') && said.includes('No recommended quantity'), `the check: ${said}`);
    expect(await evaluate(`document.querySelector('${quantity}').value + '|' + document.querySelector('${quantity}').placeholder`) === '|',
      'a quantity or a recommendation without a QOE');
    await sleep(500);
    await click('#fk-modal-form [data-bs-dismiss="modal"].btn-link');
    await modalClosed();
    await click('#fk-site-1');  // every site again
    await waitFor(`document.querySelectorAll('#fk-main tbody.fk-item').length === 3`, 'all 3 items again');
  }],
  ['The Subs page', async () => {
    await go('/fillkill/subs', `document.querySelectorAll('#fk-subs-rows tr').length && !document.getElementById('fk-subs-rows').innerText.includes('Loading')`, 'the subs');
    expect((await text('#fk-subs-rows')).includes('88885 BX/100 · CARDINAL HEALTH (1000001)'), 'the sub and its vendor item are not listed');
    const cap = await evaluate(`getComputedStyle(document.getElementById('fk-subs-rows').closest('.fk-scroll')).maxHeight`);
    expect(cap === '600px', `the subs table is capped at ${cap}, not 600px`);
    // 2026-11-19 (the user): Reference SKU says it's the sub item's; Weeks on Fill/Kill (26 weeks, or 10,
    // or 30 days), a stick for each, after Latest Comment; Orders last, its header saying what it shows.
    const heads = () => evaluate(`[...document.querySelectorAll('.fk-table thead th')].map((th) => th.innerText.replace(/\\s+/g, ' ').trim())`);
    const head = await heads();
    expect(head[1] === 'Reference SKU Sub Item SKU', `the Reference SKU header: ${head[1]}`);
    expect(head[6] === 'Latest Comment'
      && head[7] === 'Weeks on Fill/Kill # in last 26 weeks · last seen A stick a week (Mon–Sun), this week at right',
      `the headers after Latest Comment: ${head[6]} | ${head[7]}`);
    expect(head.at(-1) === 'Orders # of orders · last ordered', `the last header: ${head.at(-1)}`);
    // The cups, killed today and yesterday: this calendar week's stick lit (2026-11-20, Monday to Sunday),
    // and last week's too on a Monday, when yesterday was last week's Sunday; an order recorded on its sub.
    const cups = `[...document.querySelectorAll('#fk-subs-rows tr')].find((tr) => tr.innerText.includes('88885 BX/100'))`;
    const strip = () => evaluate(`[...${cups}.querySelectorAll('.fk-stick')].map((s) => s.classList.contains('fk-stick-on') ? 1 : 0).join('')`);
    const onFillKill = () => evaluate(`${cups}.cells[7].innerText.replace(/\\s+/g, ' ').trim()`);
    const today = `${daysAgo(0).slice(5, 7)}/${daysAgo(0).slice(8)}/${daysAgo(0).slice(0, 4)}`;
    const monday = new Date(`${daysAgo(0)}T00:00:00Z`).getUTCDay() === 1;
    const weeks = (n) => (monday ? `${'0'.repeat(n - 2)}11` : `${'0'.repeat(n - 1)}1`);
    expect(await strip() === weeks(26), `the cups' 26 weeks: ${await strip()}`);
    expect(await onFillKill() === `${monday ? 2 : 1} · ${today}`, `the cups' weeks on Fill/Kill: ${await onFillKill()}`);
    const thisWeek = await evaluate(`[...${cups}.querySelectorAll('.fk-stick')].at(-1).title`);
    expect(thisWeek.endsWith('(this week, so far): on Fill/Kill') || (thisWeek.includes(`–${today}`) && new Date().getDay() === 0),
      `this week's stick: ${thisWeek}`);
    const stick = await evaluate(`(() => { const r = ${cups}.querySelector('.fk-stick').getBoundingClientRect(); return [r.width, r.height]; })()`);
    expect(stick[1] >= 10 && stick[0] >= 3, `the sticks are ${stick[0]}x${stick[1]}px`);
    const ordered = await evaluate(`${cups}.cells[${cups}.cells.length - 1].innerText.trim()`);
    expect(/^\d+ · \d\d\/\d\d\/\d{4}$/.test(ordered), `the cups' orders: ${ordered}`);
    // 30 days: Days on Fill/Kill, a stick a day; the export follows.
    await setValue('#fk-subs-period', '30d');
    await waitFor(`document.getElementById('fk-subs-export').href.includes('fillkill_period=30d')
      && ${cups}.querySelectorAll('.fk-stick').length === 30`, 'the days and the export to follow the period');
    expect((await heads())[7].startsWith('Days on Fill/Kill # in last 30 days · last seen A stick a day'), `the header: ${(await heads())[7]}`);
    expect(await strip() === `${'0'.repeat(28)}11` && await onFillKill() === `2 · ${today}`, `the cups' 30 days: ${await strip()}, ${await onFillKill()}`);
    // 10 weeks: wider sticks, about as wide in all.
    await setValue('#fk-subs-period', '10w');
    await waitFor(`${cups}.querySelectorAll('.fk-stick').length === 10`, 'a stick a week for 10 weeks');
    const wide = await evaluate(`${cups}.querySelector('.fk-sticks').getBoundingClientRect().width`);
    expect(wide > 100 && wide < 130 && (await strip()) === weeks(10), `10 weeks: ${await strip()}, ${wide}px wide`);
    // No sub (2026-11-19): MDS2585H, killed today with no sub, has a row of its own, after the subs.
    const rows = () => evaluate(`[...document.querySelectorAll('#fk-subs-rows tr')].map((tr) => [tr.cells[0].innerText.split('\\n')[0].trim(),
      tr.cells[3].innerText.trim()].join(' | '))`);
    expect((await rows()).at(-1) === 'MDS2585H | No sub', `the last row: ${(await rows()).at(-1)}`);
    expect((await text('#fk-subs-count')).includes('1 item with no sub'), `the count: ${await text('#fk-subs-count')}`);
    // A Medline item opens its drawer here, not Main (2026-11-20, the user): the item, then every live sub on it.
    await openDrawer('DYND70294BH');
    expect(await evaluate('location.pathname') === '/fillkill/subs', `the click left the page: ${await evaluate('location.pathname')}`);
    expect((await text('#fk-item-drawer-subtitle')) === 'Infor item 100339 · CUP,DENTURE,8OZ', `the drawer's subtitle: ${await text('#fk-item-drawer-subtitle')}`);
    await drawerSays('CUP DENTURE 8 OZ');  // Infor's long description
    await drawerSays('Total 1 sub');
    const cupSub = await text('#fk-item-drawer-body .fk-drawer-sub');
    expect(cupSub.includes('88885') && cupSub.includes('Hold') && cupSub.includes('88885 BX/100 · CARDINAL HEALTH (1000001)')
      && /\d+ orders? · last ordered \d\d\/\d\d\/\d{4}/.test(cupSub), `the cups' sub in the drawer: ${cupSub}`);
    expect((await evaluate(`document.querySelector('#fk-item-drawer-body a[href*="item="]').href`)).includes('item=DYND70294BH'),
      'no Open on Main for the cups');
    await closeDrawer();
    await openDrawer('MDS2585H');
    await drawerSays('No subs yet');
    expect((await text('#fk-item-drawer-subtitle')) === 'Infor item 999999 · GLOVE,EXAM,NITRILE,M', `the gloves' subtitle: ${await text('#fk-item-drawer-subtitle')}`);
    await closeDrawer();
    await setValue('#fk-subs-status', 'no_sub');
    await waitFor(`document.querySelectorAll('#fk-subs-rows tr').length === 1
      && document.getElementById('fk-subs-rows').innerText.includes('No sub')`, 'only the item with no sub');
    await setValue('#fk-subs-status', '');
    await waitFor(`document.querySelectorAll('#fk-subs-rows tr').length > 1`, 'every status again');
    // Sorting (2026-11-19): Status A to Z puts No sub last, Z to A first, a third click undoes it; Medline Item A to Z.
    const sortBy = async (key) => { await click(`th[data-sort="${key}"] .fk-sort`); await sleep(100); };
    await sortBy('status');
    const byStatus = await rows();
    expect(byStatus.at(-1).endsWith('No sub') && byStatus[0].endsWith('Approved')
      && await evaluate(`document.querySelector('th[data-sort="status"]').getAttribute('aria-sort')`) === 'ascending', `by status: ${byStatus}`);
    await sortBy('status');
    expect((await rows())[0].endsWith('No sub'), `by status, Z to A: ${await rows()}`);
    await sortBy('status');
    expect(await evaluate(`document.querySelector('th[data-sort="status"]').hasAttribute('aria-sort')`) === false, 'still sorted after a third click');
    await sortBy('medline_item');
    const items = (await rows()).map((r) => r.split(' | ')[0]);
    expect(JSON.stringify(items) === JSON.stringify([...items].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))),
      `by Medline item: ${items}`);
    await sortBy('medline_item');
    await sortBy('medline_item');
    await setValue('#fk-subs-q', '88885', 'input');
    await waitFor(`document.getElementById('fk-subs-export').href.includes('q=88885')`, 'the export link to follow the search');
  }],
  ['The Dashboard', async () => {
    await go('/fillkill/dashboard', `document.querySelectorAll('#fk-dash-flow .card').length === 3`, 'the flow cards');
    expect(await count('#fk-dash-headline .card') === 6, 'not 6 headline cards');
    expect((await text('#fk-dash-flow')).includes('Kill to order'), 'no "Kill to order"');
    // 2026-10-21: no subs-per-week or rejected sections, no Ordering in the top items; a Today button.
    expect(await count('#fk-chart-new-subs, #fk-dash-rejected') === 0, 'the sections taken off are there');
    expect(!(await text('#fk-dash-top')).includes('No order') && await evaluate(
      `[...document.querySelector('#fk-dash-top').closest('table').tHead.rows[0].cells].length`) === 5, 'the top items have an Ordering column');
    // 2026-11-20: the quick button the dates are is pressed, the default's (the last 30 days) on opening.
    const pressed = `[...document.querySelectorAll('#fk-dash-quick [aria-pressed="true"]')].map((b) => b.innerText).join('|')`;
    expect(await evaluate(pressed) === 'Last 30 days', 'Last 30 days not the one button pressed on opening');
    await click('#fk-dash-quick [data-days="today"]');
    const [y, m, d] = daysAgo(0).split('-');
    await waitFor(`document.getElementById('fk-dash-range').innerText === '${m}/${d}/${y} to ${m}/${d}/${y}'`, 'the range on today');
    await waitFor(`document.querySelectorAll('#fk-dash-top tr').length === 2`, "today's two items");
    expect(await evaluate(pressed) === 'Today', 'Today not the one button pressed');
  }],
  ['Order Timing, a module of its own: a Viewer finds orders in Medline\'s feed, and opens its Dashboard', async () => {
    // 2026-10-30: any Fill/Kill role views it. 2026-11-16: Main finds our orders in Medline's feed.
    const current = (label) => evaluate(`[...document.querySelectorAll('a[aria-current="page"]')].map((a) => a.innerText.trim()).join('|') === ${JSON.stringify(label)}`);
    const orderRows = `document.querySelectorAll('#ot-rows .ot-order-row').length`;
    // The quick range pressed (2026-11-20): its button's days, or '' for none.
    const pressed = () => evaluate(`[...document.querySelectorAll('[data-days][aria-pressed="true"]')].map((b) => b.dataset.days).join('|')`);
    await go('/dev-login?as=viewer&next=/fillkill/', MAIN_READY, 'Main');
    await click('.module-nav a[href$="/ordertiming/"]');
    await waitFor(`${orderRows} === 5`, "Order Timing's today (2026-11-17): five orders");
    expect(await current('Order Timing|Main'), 'Order Timing and its Main are not the current module and page');
    expect((await text('#ot-count')) === '5 orders', `the count: ${await text('#ot-count')}`);
    expect(await evaluate(`document.getElementById('ot-start').value === document.getElementById('ot-end').value`),
      'Main does not open on one day');
    expect(await pressed() === '1', `Main's quick range pressed: '${await pressed()}'`);
    expect(/^Data as of \d\d\/\d\d\/\d{4} 09:02 · last loaded 09:30/.test(await text('#ot-as-of')),
      `the data as of: ${await text('#ot-as-of')}`);
    // Closed until clicked; a click shows its lines.
    expect(await evaluate(`document.querySelector('#ot-rows .ot-lines-row').hidden`), 'the lines show before a click');
    await click('#ot-rows .ot-order-row');
    await waitFor(`!document.querySelector('#ot-rows .ot-lines-row').hidden`, "the first order's lines");
    // A PO: its order alone, its lines open, confirmed.
    await setValue('#ot-q', '3000600001', 'input');
    await waitFor(`${orderRows} === 1`, 'PO 3000600001 alone');
    expect((await evaluate('location.search')).includes('q=3000600001'), 'the search is not in the link');
    const order = (await text('#ot-rows')).replace(/\s+/g, ' ');
    expect(order.includes('Confirmed') && order.includes('1 rejected') && order.includes('INVALID PART'),
      `PO 3000600001: ${order}`);
    // Its PO type and total lines on the PO's row; each line's type, and the bad line with its reject code.
    expect((await text('#ot-rows .ot-order-row .ot-po-type')).trim() === 'EDI', `the PO type: ${await text('#ot-rows .ot-po-type')}`);
    expect((await text('#ot-rows .ot-order-row .ot-total')).trim() === '3', `the total lines: ${await text('#ot-rows .ot-total')}`);
    expect(await evaluate(`[...document.querySelectorAll('#ot-rows .ot-line-type')].every((td) => td.innerText.trim() === 'STD')`),
      'a line without its line type');
    expect(await evaluate(`[...document.querySelectorAll('#ot-rows .ot-lines tbody tr')].map((tr) => tr.querySelector('.ot-bad-line').innerText.trim() + tr.querySelector('.ot-rej-code').innerText.trim()).join('|') === '|YESE1|'`),
      'the bad line and its reject code');
    expect(await evaluate(`[...document.querySelectorAll('#ot-rows .ot-lines tbody tr')].map((tr) => tr.querySelector('.ot-manufacturer').innerText.trim() + ' ' + tr.querySelector('.ot-mfr-item').innerText.trim()).join('|') === 'MEDLINE D70294|ACME XYZ-1|MEDLINE MDS2585H'`),
      "each line's manufacturer and part number");
    expect(!order.includes('Delivery'), 'SAP deliveries are still shown');
    expect(await count('#ot-rows tr.ot-match, #ot-rows tr.ot-other') === 0, 'a PO found whole has lines highlighted');
    // Several POs pasted.
    await setValue('#ot-q', '3000600002, 3000600003', 'input');
    await waitFor(`${orderRows} === 2`, 'the two POs pasted');
    expect((await text('#ot-rows')).includes('Not confirmed'), 'PO 3000600002 is not shown as not confirmed');
    // A PO Medline hasn't reported: said so, with a way to look further back.
    await setValue('#ot-q', '3000699999', 'input');
    await waitFor(`document.querySelector('#ot-rows [data-search-window]')`, 'the not-found message');
    expect((await text('#ot-rows')).includes("Medline hasn't reported receiving it"), 'the not-found message');
    expect(await evaluate(`(document.getElementById('ot-pager').offsetParent === null)`), 'the pager shows for one page');
    // 2026-11-17: the Rejected tab, every order with a rejected line, the line found standing out.
    await setValue('#ot-q', '', 'input');
    await click('#ot-tabs [data-status="rejected"]');
    await waitFor(`${orderRows} === 1 && document.querySelectorAll('#ot-rows tr.ot-match').length === 1`, 'the rejected line found');
    expect(await count('#ot-rows tr.ot-other') === 2, 'the order\'s other lines are not shown as not found');
    expect((await text('#ot-rows .ot-total')).replace(/\s+/g, ' ').trim() === '3 1 found', `the total and found: ${await text('#ot-rows .ot-total')}`);
    expect((await evaluate('location.search')).includes('status=rejected'), 'the tab is not in the link');
    // A tab doesn't open its orders (the user, 2026-11-17): a click does. Its lines come first.
    expect(await evaluate(`document.querySelector('#ot-rows .ot-lines-row').hidden`), "the tab opened its order's lines");
    expect(await evaluate(`document.querySelector('#ot-rows .ot-lines tbody tr').classList.contains('ot-match')
      && document.querySelector('#ot-rows .ot-lines tbody tr').innerText.includes('INVALID PART')`), 'the rejected line is not first');
    // Each tab counts the last 7 days' orders, whichever tab is chosen; an order counts under each
    // status its lines are in.
    const tabs = `[...document.querySelectorAll('#ot-tabs [data-status]')].map((b) => b.dataset.status + '=' + (b.querySelector('.ot-tab-count') || {}).innerText + (b.classList.contains('active') ? '*' : '')).join('|')`;
    await waitFor(`${tabs} === '=5|rejected=1*|asn=1|confirmed=4|not_confirmed=1|short=2'`, 'the tabs, in their order, and their counts');
    // Short shipped (2026-11-17): not a status, a tally of its own; its tab, the orders with a short line.
    await click('#ot-tabs [data-status="short"]');
    await waitFor(`${orderRows} === 2`, 'the two orders with a short-shipped line today');
    const tallies = `[...document.querySelectorAll('#ot-rows .ot-short-tally')].map((td) => td.innerText.trim()).join('|')`;
    expect(await evaluate(`${tallies} === '1|2'`), `the short-shipped tallies: ${await evaluate(tallies)}`);
    expect(await count('#ot-rows .ot-line-short .ot-short-note') === 3, `the lines short: ${await count('#ot-rows .ot-line-short .ot-short-note')}`);
    expect(!(await text('#ot-rows')).includes('short shipped'), 'short shipped is still a status chip');
    // The last 30 days: 29 orders, 20 a page, the pager above the table; no "All".
    expect(await count('[data-days="all"]') === 0, 'an "All" days button');
    await click('#ot-tabs [data-status=""]');
    await click('[data-days="30"]');
    await waitFor(`${orderRows} === 20 && !(document.getElementById('ot-pager').offsetParent === null)`, 'the first page of 20');
    expect((await text('#ot-count')) === '29 orders', `the count: ${await text('#ot-count')}`);
    expect(await pressed() === '30', `the quick range pressed: '${await pressed()}'`);
    expect((await text('#ot-range')) === 'Orders 1–20 of 29', `the range: ${await text('#ot-range')}`);
    await click('#ot-pages [data-page="2"]');
    await waitFor(`${orderRows} === 9 && document.querySelector('#ot-pages .active').innerText.trim() === '2'`, 'page 2: nine orders');
    expect((await evaluate('location.search')).includes('page=2'), 'the page is not in the link');
    expect((await text('#ot-range')) === 'Orders 21–29 of 29', `page 2's range: ${await text('#ot-range')}`);
    // A filter changed: back to page 1. A PO forty days old is past what Main reaches.
    await setValue('#ot-q', '3000600027', 'input');
    await waitFor(`document.getElementById('ot-rows').innerText.includes('Order Timing looks back to')`,
      'PO 3000600027 not found, and how far back said');
    expect(await evaluate(`(document.getElementById('ot-pager').offsetParent === null)`), 'the pager shows with nothing found');
    expect(!(await evaluate('location.search')).includes('page='), 'a search kept page 2');
    await setValue('#ot-q', '', 'input');
    await waitFor(`${orderRows} === 20`, 'the last 30 days again');
    // Short Ships (2026-11-17): an item a row, the most killed in Fill/Kill in 30 days first.
    const itemRows = `document.querySelectorAll('#ot-rows .ot-order-row').length`;
    const cells = (selector) => `[...document.querySelectorAll('#ot-rows .ot-order-row')].map((tr) => tr.querySelector('${selector}').innerText.trim().replace(/\\s+/g, ' ')).join('|')`;
    const kills = `${cells('.ot-kills-today')} + '/' + ${cells('.ot-kills-7')} + '/' + ${cells('.ot-kills-30')}`;
    await click('.page-nav a[href$="/ordertiming/shortships"]');
    // It opens on today (2026-11-18): orders 31 and 33's short lines, one an item.
    await waitFor(`${itemRows} === 3`, "Short Ships' three items today");
    expect(await current('Order Timing|Short Ships'), 'Order Timing and its Short Ships are not the current module and page');
    expect(await evaluate(`document.getElementById('ot-start').value === document.getElementById('ot-end').value`),
      'Short Ships did not open on one day');
    expect(await pressed() === '1', `Short Ships' quick range pressed: '${await pressed()}'`);
    expect((await text('#ot-count')) === '3 items', `the count: ${await text('#ot-count')}`);
    expect(await evaluate(`${cells('.ot-item')} === 'DYND70294BH|MDS2585H|B-D930103CS'`), `the items: ${await evaluate(cells('.ot-item'))}`);
    // Each count with what its lines killed and how many ship-to locations (2026-11-20), the numbers
    // only, "lines · qty UOM · locations", the locations listed on hover.
    const cupToday = '1 · 5 EA · 1', glovesKills = '1 · 3 BX · 1', cupWeek = '2 · 8 EA · 2';
    expect(await evaluate(`${kills} === '${cupToday}|${glovesKills}|0/${cupWeek}|${glovesKills}|0/${cupWeek}|${glovesKills}|0'`),
      `the kill counts: ${await evaluate(kills)}`);
    const where = `document.querySelector('#ot-rows .ot-kills-7 .ot-kill-where').title`;
    expect(await evaluate(`${where} === '2 ship-to locations\\nPMOSK6\\nPWLREICU'`), `the cup's locations on hover: ${await evaluate(where)}`);
    expect(await evaluate(`getComputedStyle(document.querySelector('#ot-rows .ot-kills-7')).textAlign === 'center'`),
      'the kill counts are not centred');
    expect(await evaluate(`${cells('.ot-short-lines')} === '1 1 PO|1 1 PO|1 1 PO'`), `today's short lines: ${await evaluate(cells('.ot-short-lines'))}`);
    // Qty short, Qty ordered and the QOE, the quantities in eaches below by it (B-D930103CS has none).
    const qtys = `${cells('.ot-qty-short')} + ' / ' + ${cells('.ot-qty-ordered')} + ' / ' + ${cells('.ot-qoe')}`;
    expect(await evaluate(`${qtys} === '5 CS 60 EA|3 BX 300 EA|2 CA / 5 CS 60 EA|4 BX 400 EA|2 CA / 12|100|—'`),
      `the quantities and QOEs: ${await evaluate(qtys)}`);
    await click('[data-days="7"]');
    await waitFor(`${cells('.ot-short-lines')} === '3 3 POs|1 1 PO|1 1 PO'`, 'the short lines of the last 7 days');
    expect(await pressed() === '7', `the quick range pressed: '${await pressed()}'`);
    expect(await evaluate(`${cells('.ot-qty-short')}.startsWith('9 CS 108 EA|')`), `the cup's 7 days short: ${await evaluate(cells('.ot-qty-short'))}`);
    expect(/Fill\/Kill data as of \d\d\/\d\d\/\d{4} 09:04 · last loaded 09:30/.test(await text('#ot-as-of')),
      `the data as of: ${await text('#ot-as-of')}`);
    // An item's short lines: the PO, when created, its total lines, line type, and Fill/Kill's reason.
    expect(await evaluate(`document.querySelector('#ot-rows .ot-lines-row').hidden`), 'the lines show before a click');
    await click('#ot-rows .ot-order-row');
    await waitFor(`!document.querySelector('#ot-rows .ot-lines-row').hidden`, "the first item's lines");
    const shortLines = `[...document.querySelector('#ot-rows .ot-lines-row').querySelectorAll('.ot-lines tbody tr')]`;
    // Its columns, in the user's order (2026-11-18): the PO, its line and line type, then PO created.
    const lineHead = `[...document.querySelector('#ot-rows .ot-lines-row').querySelectorAll('.ot-lines thead th')].slice(0, 6).map((th) => th.innerText.trim().split('\\n')[0]).join('|')`;
    expect(await evaluate(`${lineHead} === 'PO|PO line #|Line type|PO created|Total lines|Site'`), `the lines' columns: ${await evaluate(lineHead)}`);
    const lineText = `${shortLines}.map((tr) => ['.ot-line-po', '.ot-po-lines', '.ot-line-type', '.ot-reason'].map((s) => tr.querySelector(s).innerText.trim().split('\\n')[0]).join(' ')).join('|')`;
    expect(await evaluate(`${lineText} === '3000600031 2 FILL-KILL Backorder|3000600004 2 STD Not in Fill/Kill yet|3000600032 1 FILL-KILL Backorder'`),
      `the lines: ${await evaluate(lineText)}`);
    expect(await evaluate(`${shortLines}.every((tr) => tr.querySelector('.ot-po-created').innerText.trim().length > 0)`), 'a line without its PO created');
    // A header sorts, kept in the link; the sites narrow the lines and the kills.
    await click('#ot-head [data-sort-key="medline_item"]');
    await waitFor(`${cells('.ot-item')} === 'B-D930103CS|DYND70294BH|MDS2585H'`, 'sorted by item');
    expect((await evaluate('location.search')).includes('sort=medline_item'), 'the sort is not in the link');
    await clickText('#ot-sites label', 'SAMPLE SITE B');
    await waitFor(`${cells('.ot-item')} === 'DYND70294BH'`, "site B's one item");
    const atB = '1 · 3 EA · 1';
    expect(await evaluate(`${kills} === '0/${atB}/${atB}'`), `site B's kill counts: ${await evaluate(kills)}`);
    // The item on Fill/Kill's Main, its panel open.
    await click('#ot-rows .ot-order-row a[href*="/fillkill/"]');
    await waitFor(`document.getElementById('fk-panel-title') && document.getElementById('fk-panel-title').innerText.trim() === 'DYND70294BH'`,
      "the item's panel on Fill/Kill's Main");
    expect((await evaluate('location.search')).includes('item=DYND70294BH'), 'the item is not in the link');
    await go('/ordertiming/', `document.querySelectorAll('#ot-rows .ot-order-row').length`, "Order Timing's Main");
    await click('.page-nav a[href$="/ordertiming/dashboard"]');
    // 2026-11-20: the Dashboard, on the last 7 days (eight sample orders, one not confirmed, one rejected
    // line): its headline, three charts, the two sites with their total, and the rejected line.
    const tiles = `document.querySelectorAll('#ot-dash-headline .card')`;
    await waitFor(`${tiles}.length === 7 && !document.getElementById('ot-dash-body').classList.contains('ot-dash-loading')`,
      "Order Timing's Dashboard");
    expect(await current('Order Timing|Dashboard'), 'Order Timing and its Dashboard are not the current module and page');
    expect(await pressed() === '7', `the Dashboard's quick range pressed: '${await pressed()}'`);
    const tile = (n) => evaluate(`${tiles}[${n}].innerText.replace(/\\s+/g, ' ').trim()`);
    expect((await tile(0)).startsWith('POs 8 '), `the POs tile: ${await tile(0)}`);
    expect((await tile(1)).includes('1 PO not confirmed yet'), `the Confirmed tile: ${await tile(1)}`);
    expect(await evaluate('Object.keys(Chart.instances).length') === 3, 'not three charts');
    expect(await count('#ot-dash-sites tr') === 2 && await count('#ot-dash-sites-total tr') === 1, 'not two sites and their total');
    expect((await text('#ot-dash-rejected')).includes('INVALID PART'), `the rejected lines: ${await text('#ot-dash-rejected')}`);
    // Today: five orders; the days are in the link.
    await click('[data-days="1"]');
    await waitFor(`${tiles}[0].innerText.replace(/\\s+/g, ' ').startsWith('POs 5 ')`, "today's five orders");
    expect((await evaluate('location.search')).includes(`start=${daysAgo(0)}`), 'the days are not in the link');
    expect(await pressed() === '1', `the quick range pressed: '${await pressed()}'`);
    // Days of one's own: no quick range pressed.
    await setValue('#ot-start', daysAgo(2), 'change');
    await waitFor(`location.search.includes('start=${daysAgo(2)}')`, 'the days typed in');
    expect(await pressed() === '', `a quick range pressed for days typed in: '${await pressed()}'`);
  }],
  ['No sub approved: SCM adds a vendor item for the item itself, and a Materials Manager orders it', async () => {
    // 2026-11-02, the user: SCM may direct the sites to order the same item from another vendor, with
    // no sub nursing approved. MDS2585H has no sub yet.
    await go('/dev-login?as=scm', `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length`, 'the main table');
    const add = `document.querySelector('#fk-main [data-add-item-vi="MDS2585H"]')`;
    await waitFor(add, "MDS2585H's + Vendor item, with no sub approved");
    await evaluate(`${add}.click()`);
    await modalOpen();
    const about = (await text('.fk-form-summary')).replace(/\s+/g, ' ');
    expect(about.includes('No sub, as SCM directs, for MDS2585H (BX/100)'), `the summary: ${about}`);
    // Its contract search starts from the Infor item, to find the same item from another vendor.
    expect(await evaluate(`document.getElementById('fk-contract-q').value`) === '999999', "the search doesn't start from the Infor item");
    await setValue('#fk-m-vendor_part', 'OM-2585', 'input');
    await setValue('#fk-m-vendor_id', '1000002', 'input');
    await waitFor(`document.getElementById('fk-m-vendor').value === 'OWENS & MINOR'`, "Owens & Minor's name");
    await setValue('#fk-m-uom', 'BX');
    await setValue('#fk-m-qoe', '100');
    await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
    await modalClosed();
    const glove = `[...document.querySelectorAll('#fk-main tbody.fk-item')].find((b) => b.innerText.includes('MDS2585H'))`;
    await waitFor(`${glove}.querySelector('div.fk-vi-tile')?.innerText.includes('OM-2585')`, 'the tile, on the line without a sub');
    // A Materials Manager records an order from it, as from a sub's.
    await go('/dev-login?as=mm', `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length`, 'the main table');
    await waitFor(`${glove}.querySelector('[data-order-vi]')`, 'the tile to order from');
    await evaluate(`${glove}.querySelector('[data-order-vi]').click()`);
    await modalOpen();
    expect((await text('.fk-form-summary')).includes('No sub, as SCM directs'), `the order form's summary: ${await text('.fk-form-summary')}`);
    await setValue('#fk-m-site', SITE_A);
    await setValue('#fk-m-quantity', '1');
    await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
    await modalClosed();
    await waitFor(`${glove}.querySelector('.badge.text-bg-success')?.innerText === 'Ordered'`, 'MDS2585H ordered');
    // The panel lists it apart from the subs; its order says it had no sub.
    await click('#fk-main button[data-open="MDS2585H"]:not([data-scope])');
    await click('[data-panel-tab="subs"]');
    await panelSays('Vendor items without a sub');
    expect(await count('#fk-panel-content [data-act="order"]') === 1, 'no Record order on it in the panel');
    await click('[data-panel-tab="orders"]');
    await panelSays('no sub, as SCM directs');
  }],
  ['A nurse: no vendor items, and their Reference SKU is approved on Main', async () => {
    await go('/dev-login?as=nurse', `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length`, 'the main table');
    await click('#fk-main button[data-open="MDS2585H"]:not([data-scope])');
    await waitFor(`document.querySelector('[data-act="show-add"]')`, 'Add sub');
    await click('[data-act="show-add"]');
    await setValue('#fk-add-sku', 'GLV-2');
    await evaluate(`document.getElementById('fk-add-form').requestSubmit()`);
    await panelSays('Approved: it can be ordered.');
    expect(await count('#fk-panel-content [data-act="add-vi"]') === 0, 'a nurse can add vendor items');
    expect(await count('#fk-panel-content [data-act="order"]') === 0, 'a nurse sees "Record order"');
    // Their sub is in the table without the pencil: adding its vendor items is the Materials
    // Manager's, and a pencil they can't use looked broken (2026-10-21).
    await waitFor(`[...document.querySelectorAll('#fk-main tbody.fk-item')].some((b) => b.innerText.includes('GLV-2'))`, 'the approved sub');
    expect(await count('#fk-main .bi-pencil-square, #fk-main [data-add-vi], #fk-main [data-add-item-vi]') === 0,
      'a nurse sees the pencil or can open the vendor item form');
    // A second sub from Main, without the panel (2026-10-27): a double-click on the Medline item's
    // Sub Approved by Nursing cell opens the form.
    await go('/dev-login?as=nurse', `${MAIN_READY} && ${lineOf('GLV-2')}`, 'the main table');
    await dblclick(`${lineOf('GLV-2')}.querySelector('td[data-add-sub="MDS2585H"]')`, "GLV-2's cell");
    await modalOpen();
    const about = (await text('.fk-form-summary')).replace(/\s+/g, ' ');
    expect(about.includes('MDS2585H (BX/100)') && about.includes('1 approved Sub Approved by Nursing GLV-2'), `the add-sub form's summary: ${about}`);
    // The boxes' hints (the user, 2026-11-02).
    expect((await evaluate(`document.getElementById('fk-m-reference_sku').placeholder`)).startsWith('The reference manufacturer part or vendor part number'),
      "the Reference SKU's hint");
    expect((await evaluate(`document.getElementById('fk-m-comment').placeholder`)).startsWith('Optional: additional comments on the product'),
      "the note's hint");
    await waitFor(`document.activeElement.id === 'fk-m-reference_sku'`, 'the cursor in the Reference SKU');
    await setValue('#fk-m-reference_sku', 'GLV-3');
    await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
    await modalClosed();
    await waitFor(`[...document.querySelectorAll('#fk-main tbody.fk-item')].some((b) => b.innerText.includes('GLV-2')
      && b.innerText.replace(/\\s+/g, ' ').includes('Approved 2'))`, 'two approved subs on MDS2585H');
    // A second approved sub on the same UOM gets a line of its own in the table (2026-10-21), and
    // nothing to choose between them: both can be ordered (2026-10-28).
    await waitFor(`${lineOf('GLV-3')} && !${lineOf('GLV-3')}.innerText.includes('GLV-2')`, 'GLV-3 on a line of its own');
  }],
  ['A Materials Manager finds the vendor ID by name, or uses 0000000', async () => {
    await go('/dev-login?as=mm', `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length`, 'the main table');
    // Two approved subs on MDS2585H: each one's "+ Vendor item for" is on its own line, beside it (2026-10-21).
    for (const [mine, other] of [['GLV-2', 'GLV-3'], ['GLV-3', 'GLV-2']]) {
      const text = await evaluate(`${lineOf(mine)}.innerText`);
      expect(text.includes(`Vendor item for ${mine}`) && !text.includes(other), `${mine}'s line: ${text}`);
    }
    // From the sub's pencil on Main.
    const pencil = `[...document.querySelectorAll('#fk-main tbody.fk-item')].find((b) => b.innerText.includes('GLV-2')).querySelector('[data-add-vi]')`;
    await waitFor(pencil, "GLV-2's pencil");
    await evaluate(`${pencil}.click()`);
    await modalOpen();
    expect((await text('.fk-form-summary')).includes('GLV-2 for MDS2585H (BX/100)'),
      `the form is not for GLV-2 on MDS2585H's BX/100 (from the table): ${await text('.fk-form-summary')}`);
    // Without a vendor ID nothing is saved.
    await setValue('#fk-m-vendor_part', 'GLV-2-EA', 'input');
    await setValue('#fk-m-vendor', 'Local Supply Co', 'input');
    await setValue('#fk-m-uom', 'EA', 'input');
    // A box left loses its spaces, and a UOM typed another way becomes Infor's (2026-10-20).
    await setValue('#fk-m-vendor_part', '  GLV-2-EA ');
    expect(await evaluate(`document.getElementById('fk-m-vendor_part').value`) === 'GLV-2-EA', 'the spaces stayed');
    await setValue('#fk-m-uom', ' vl ');
    expect(await evaluate(`document.getElementById('fk-m-uom').value`) === 'VI', 'VL is not VI');
    expect((await text('#fk-m-uom-note')) === 'VL is VI in Infor', 'no note that VL is VI');
    await setValue('#fk-m-uom', 'ea');
    expect(await evaluate(`document.getElementById('fk-m-uom').value`) === 'EA' && (await text('#fk-m-uom-note')) === '', 'EA is not EA');
    await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
    await waitFor(`(document.getElementById('fk-modal-message') || {}).innerText?.includes('Vendor ID (or 0000000')`, 'the vendor ID required');
    // The name finds Infor's vendors: the list scrolls, and choosing one fills in its ID.
    await setValue('#fk-m-vendor', 'cardinal', 'input');
    await waitFor(`document.querySelectorAll('[data-vendor-pick]').length === 5`, "five Cardinal vendors");
    expect(await evaluate(`(() => { const l = document.querySelector('.fk-vendor-list'); return l.scrollHeight > l.clientHeight; })()`),
      "the vendor list doesn't scroll");
    await evaluate(`[...document.querySelectorAll('[data-vendor-pick]')].find((b) => b.innerText.trim().startsWith('1000557')).click()`);
    expect(await evaluate(`document.getElementById('fk-m-vendor_id').value`) === '1000557', 'the vendor ID not filled in');
    expect(await evaluate(`document.getElementById('fk-m-vendor').value`) === 'CARDINAL HEALTH MEDICAL PRODUCTS', "Infor's name not filled in");
    // The ID leads (2026-10-21): another ID brings its own name, a name left without choosing from
    // the list goes back to the ID's vendor, and with no ID, Infor's name goes.
    const name = `document.getElementById('fk-m-vendor').value`;
    await setValue('#fk-m-vendor_id', '1000002', 'input');
    await waitFor(`${name} === 'OWENS & MINOR'`, 'the name of vendor 1000002');
    await setValue('#fk-m-vendor', 'cardin', 'input');
    await setValue('#fk-m-vendor', 'cardin', 'change');
    await waitFor(`${name} === 'OWENS & MINOR'`, "the name back to the ID's vendor");
    await setValue('#fk-m-vendor_id', '', 'input');
    await waitFor(`${name} === ''`, 'the name gone with the ID');
    // Infor doesn't have the vendor: 0000000, on purpose. Infor's name goes; theirs is asked for.
    await click('[data-no-vendor]');
    expect(await evaluate(`document.getElementById('fk-m-vendor_id').value`) === '0000000', 'not 0000000');
    expect((await text('#fk-m-vendor_id-note')) === 'Vendor not available in system', 'no "Vendor not available in system"');
    expect(await evaluate(`document.getElementById('fk-m-vendor').value`) === '', "Infor's name still there");
    expect(await evaluate(`document.activeElement.id`) === 'fk-m-vendor', 'the name box is not where the cursor is');
    expect((await text('#fk-m-vendor-note')).includes("type the vendor's name"), 'no ask for the name');
    // Typed in, it isn't looked up in Infor; the ask goes.
    await setValue('#fk-m-vendor', 'Local Supply Co', 'input');
    await sleep(600);
    expect(await count('[data-vendor-pick]') === 0 && (await text('#fk-vendor-results')) === '', 'the name was searched in Infor');
    expect((await text('#fk-m-vendor-note')) === '', 'the ask for the name stayed');
    await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
    await modalClosed();
    await waitFor(`[...document.querySelectorAll('#fk-main [data-order-vi]')].some((b) => b.innerText.includes('Not in Infor · Local Supply Co'))`,
      'the vendor item tile, not in Infor');
  }, { refusals: [/\/vendor-items$/] }],  // the save without a vendor ID
  ["A Reference SKU stays as entered; each way to order it is a vendor item of its own", async () => {
    // Nursing approves 930103, BD's part; Medline sells it as B-D930103CSZ (a box of 40) and
    // B-D930103CS (a case of 400): one sub, two vendor items (2026-10-20).
    await go('/dev-login?as=nurse', `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length`, 'the main table');
    await click('#fk-main button[data-open="DYND70294BH"]:not([data-scope])');
    await click('[data-act="show-add"]');
    await setValue('#fk-add-sku', '930103');
    await evaluate(`document.getElementById('fk-add-form').requestSubmit()`);
    await panelSays('Sub added');
    await go('/dev-login?as=mm', `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length`, 'the main table');
    await click('#fk-main button[data-open="DYND70294BH"]:not([data-scope])');
    const card = `[...document.querySelectorAll('#fk-panel-content .card')].find((c) => c.querySelector('.fw-semibold').innerText === '930103')`;
    for (const part of ['B-D930103CSZ', 'B-D930103CS']) {
      await waitFor(card, 'the 930103 sub');
      await evaluate(`${card}.querySelector('[data-act="add-vi"]').click()`);
      await modalOpen();
      const line = `[...document.querySelectorAll('[data-contract]')].find((b) => b.querySelector('.fw-semibold').innerText === ${JSON.stringify(part)})`;
      await waitFor(line, `${part} among the contract lines for 930103`);
      await evaluate(`${line}.click()`);
      expect(await evaluate(`document.getElementById('fk-m-vendor_part').value`) === part, `${part} not filled in`);
      await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
      await modalClosed();
      await panelSays('Vendor item added.');
      // The form closes before the panel reloads, and the first add's message is still up: wait
      // for this vendor item itself.
      await waitFor(`(${card}?.querySelector('.fk-vendor-items')?.innerText || '').includes(${JSON.stringify(part + ' ')})`,
        `${part} among the 930103 vendor items`);
    }
    const items = await evaluate(`${card}.querySelector('.fk-vendor-items').innerText`);
    expect(items.includes('B-D930103CSZ') && items.includes('BX/40') && items.includes('B-D930103CS ') && items.includes('CA/400'),
      `the vendor items: ${items}`);
    // The status stays the Sub Approver's, and there's no picking (2026-10-28).
    expect(await evaluate(`${card}.querySelector('select[data-act="status"]') === null`), 'a Materials Manager can set the status');
    expect(await count('#fk-panel-content [data-act="pick"], #fk-panel-content [data-act="unpick"]') === 0, 'a pick button');
    // Main: the approved sub is 930103, with a tile for each.
    await waitFor(`[...document.querySelectorAll('#fk-main tbody.fk-item')].some((b) => b.innerText.includes('930103')
      && b.querySelectorAll('[data-order-vi]').length === 2)`, 'two tiles for 930103');
  }],
  ["SCM writes SCM Comments; the sites read them on Main", async () => {
    // 2026-10-27: SCM guides the sites' Materials Managers and doesn't
    // order: no tiles to click, but the item's comment to write.
    await go('/dev-login?as=scm', `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length`, 'the main table');
    expect(await count('#fk-main button[data-order-vi]') === 0 && await count('#fk-main div.fk-vi-tile') >= 1,
      'SCM can click a tile to record an order');
    // Between the approved subs and their vendor items (the user, 2026-10-27).
    const heads = await evaluate(`[...document.querySelectorAll('#fk-main thead th')].map((th) => th.innerText.trim())`);
    const at = heads.indexOf("SCM Comments");
    expect(at > 0 && heads[at - 1] === 'Sub Approved by Nursing' && heads[at + 1] === 'Vendor Item Detail', `the columns: ${heads.join(', ')}`);
    // A double-click on its cell opens the form.
    await dblclick(`document.querySelector('#fk-main td[data-instruct="DYND70294BH"]')`, "the item's cell");
    await modalOpen();
    expect((await text('label[for="fk-m-instruction"]')).startsWith('Comment from SCM'), "the box isn't labelled Comment from SCM");
    expect((await evaluate(`document.getElementById('fk-m-instruction').placeholder`)).startsWith('Comments from SCM (Will), e.g. autosub in place'),
      "the comment's hint");
    const summary = (await text('.fk-form-summary')).replace(/\s+/g, ' ');
    expect(summary.includes('Infor item 100339') && summary.includes('SAMPLE SITE A: killed 5 EA, sub ordered 100 EA'),
      `the comment form's summary: ${summary}`);
    await waitFor(`document.activeElement.id === 'fk-m-instruction'`, 'the cursor in the comment');
    await setValue('#fk-m-instruction', 'Site A: covered.\nSite B: 1 BX of 88885 today.');
    await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
    await modalClosed();
    const cell = `document.querySelector('#fk-main [data-instructions="DYND70294BH"]')?.closest('td')`;
    await waitFor(`${cell} && ${cell}.querySelector('.fk-instruction-text').innerText.includes('Site B: 1 BX of 88885 today.')`,
      'the comment on Main');
    expect((await evaluate(`${cell}.innerText`)).includes('scm ·'), 'no who and when under it');
    // Or from the item's panel: Add comment (the user: a button, like Add sub).
    await click('#fk-main button[data-open="DYND70294BH"]:not([data-scope])');
    await panelSays('Site B: 1 BX of 88885 today.');
    await click('#fk-panel-body [data-act="instruct"]');
    await modalOpen();
    await setValue('#fk-m-instruction', 'All sites: order 930103 as usual.');
    await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
    await modalClosed();
    await panelSays('Comment saved for Infor item 100339.');
    await click('#fk-panel-body [data-act="instructions"]');
    await waitFor(`document.getElementById('fk-panel-instructions').innerText.includes('Site B: 1 BX of 88885 today.')`, 'both comments in the panel');
    await waitFor(`${cell}.innerText.includes('All sites: order 930103 as usual.')`, 'the latest on Main');
    // A Materials Manager reads them, all of them in the popover, and can't write one.
    await go('/dev-login?as=mm', `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length`, 'the main table');
    await waitFor(cell, 'the comment');
    expect(await count('#fk-main td[data-instruct]') === 0, 'a Materials Manager can write comments');
    await click('#fk-main [data-instructions="DYND70294BH"]');
    await waitFor(`(document.querySelector('.fk-comments-popover') || {}).innerText?.includes('Site B: 1 BX')`, 'the comments popover');
    expect((await text('.fk-comments-popover')).includes("SCM Comments"), "the popover isn't titled SCM Comments");
    await evaluate('document.body.click()');
    await waitFor(`!document.querySelector('.fk-comments-popover')`, 'the popover to close');
    await click('#fk-main button[data-open="DYND70294BH"]:not([data-scope])');
    await panelSays('All sites: order 930103 as usual.');
    expect(await count('#fk-panel-body [data-act="instruct"]') === 0, 'a Materials Manager has Add comment');
  }],
  ['A viewer: nothing to change', async () => {
    await go('/dev-login?as=viewer', `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length`, 'the main table');
    await click('#fk-main button[data-open="MDS2585H"]:not([data-scope])');
    await panelSays('GLV-2');
    expect(await count('#fk-panel-body [data-act="show-add"], #fk-panel-body select[data-act="status"], #fk-panel-body [data-act="add-vi"]') === 0,
      'a viewer can change subs');
    expect(await count('#fk-main [data-order-vi], #fk-main [data-add-vi], #fk-main [data-add-item-vi]') === 0,
      'a viewer can record orders or add vendor items');
    expect(await count('#fk-main td[data-dblclick]') === 0, 'a viewer has cells to double-click');
    expect(await count('#fk-main .bi-pencil-square') === 0, 'a viewer sees the pencil of a sub without vendor items (GLV-3)');
    expect(await count('#fk-main div.fk-vi-tile') >= 3, 'a viewer sees no vendor item tiles');
    expect(await count('#fk-reset') === 0, 'a viewer has Reset data');
  }],
  ['The Subs page: an item with more than one sub has them together, and all of them in its drawer', async () => {
    // Still the viewer. DYND70294BH has 88885 (on hold) and 930103; MDS2585H, GLV-2 and GLV-3 (2026-11-20, the user).
    await go('/fillkill/subs', `document.querySelectorAll('#fk-subs-rows a[data-item]').length
      && !document.getElementById('fk-subs-rows').innerText.includes('Loading')`, 'the subs');
    // An item's rows: its cell on the first ("Total 2 subs" under it), their Reference SKUs, and the rows
    // after the first blank where the item's own cells are (the item, its weeks on Fill/Kill).
    const groupOf = (item) => evaluate(`(() => {
      const first = document.querySelector('#fk-subs-rows a[data-item="${item}"]').closest('tr');
      const rows = [first];
      while (rows.at(-1).classList.contains('fk-group-continues')) rows.push(rows.at(-1).nextElementSibling);
      return [first.cells[0].innerText.replace(/\\s+/g, ' ').trim(), rows.map((tr) => tr.cells[1].innerText.trim()).sort().join(','),
        rows.slice(1).every((tr) => !tr.cells[0].innerText.trim() && !tr.cells[7].innerText.trim())].join(' | ');
    })()`);
    expect(await groupOf('MDS2585H') === 'MDS2585H 999999 Total 2 subs | GLV-2,GLV-3 | true', `the gloves' subs: ${await groupOf('MDS2585H')}`);
    expect(await groupOf('DYND70294BH') === 'DYND70294BH 100339 Total 2 subs | 88885,930103 | true', `the cups' subs: ${await groupOf('DYND70294BH')}`);
    expect(await count('#fk-subs-rows a[data-item="MDS2585H"]') === 1, 'the gloves on more than one row of their own');
    // A filter keeping one of them still says how many the item has.
    await setValue('#fk-subs-status', 'hold');
    await waitFor(`document.querySelectorAll('#fk-subs-rows tr').length === 1`, 'the sub on hold');
    expect(await groupOf('DYND70294BH') === 'DYND70294BH 100339 Total 2 subs · 1 shown | 88885 | true', `on hold: ${await groupOf('DYND70294BH')}`);
    await setValue('#fk-subs-status', '');
    await waitFor(`document.querySelectorAll('#fk-subs-rows a[data-item="MDS2585H"]').length === 1`, 'every status again');
    // Sorted by Status, each row is on its own, with its item and the total; a third click groups them again.
    const sortBy = async (key) => { await click(`th[data-sort="${key}"] .fk-sort`); await sleep(100); };
    await sortBy('status');
    expect(await evaluate(`[...document.querySelectorAll('#fk-subs-rows a[data-item="MDS2585H"]')]
      .map((a) => a.closest('td').innerText.includes('Total 2 subs')).join()`) === 'true,true', 'the gloves by status, each on its own row');
    await sortBy('status');
    await sortBy('status');
    expect(await count('#fk-subs-rows a[data-item="MDS2585H"]') === 1, 'the gloves not together again');
    // The drawer: every sub, approved first, and how many of each.
    await openDrawer('DYND70294BH');
    await drawerSays('Total 2 subs · 1 Approved · 1 Hold');
    const skus = () => evaluate(`[...document.querySelectorAll('#fk-item-drawer-body .fk-drawer-sub .fs-6')].map((e) => e.innerText).join(',')`);
    expect(await skus() === '930103,88885', `the cups' subs in the drawer: ${await skus()}`);
    await drawerSays('B-D930103CSZ');  // 930103's vendor items
    await closeDrawer();
    await openDrawer('MDS2585H');
    await drawerSays('Total 2 subs');
    expect(await skus() === 'GLV-2,GLV-3', `the gloves' subs in the drawer: ${await skus()}`);
    await closeDrawer();
  }],
  // Last: it empties what the steps before added (2026-11-02, the development server only).
  ['An admin resets the data: every sub, vendor item, order and comment goes', async () => {
    await go('/dev-login?as=all', `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length`, 'the main table');
    expect(await count('#fk-main .fk-vi-tile') >= 1, 'no subs to reset');
    await click('#fk-reset');
    await modalOpen();
    expect((await text('#fk-modal-form')).includes('sqlite (in memory)'), "the form doesn't name the database");
    await setValue('#fk-m-confirm', 'reset');
    await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
    await waitFor(`(document.getElementById('fk-modal-message') || {}).innerText?.includes('Type RESET to confirm.')`, 'the refusal');
    await setValue('#fk-m-confirm', 'RESET');
    await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
    await modalClosed();
    await waitFor(`document.getElementById('fk-reset-note').innerText.startsWith('Reset: ')`, 'what was deleted');
    await waitFor(`document.querySelectorAll('#fk-main tbody.fk-item').length && !document.querySelector('#fk-main .fk-vi-tile')`,
      'no subs left on Main');
  }, { refusals: [/\/api\/reset$/] }],  // "reset" isn't RESET
];

await send('Runtime.enable');
await send('Page.enable');
await send('Log.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1100, deviceScaleFactor: 1, mobile: false });

let failed = 0;
try {
  for (const [name, run, { refusals = [] } = {}] of steps) {
    const before = browserErrors.length;
    try {
      await run();
      // A step may make the server refuse something on purpose: the browser logs that as an error.
      const refused = (error) => /status of 4\d\d/.test(error) && refusals.some((path) => path.test(error.split(' ').pop()));
      const errors = browserErrors.slice(before).filter((error) => !refused(error));
      if (errors.length) throw new Error(`browser errors:\n    ${errors.join('\n    ')}`);
      console.log(`ok    ${name}`);
    } catch (error) {
      failed += 1;
      console.log(`FAIL  ${name}\n      ${error.message}`);
      mkdirSync(opts.out, { recursive: true });
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      const file = join(opts.out, `${name.replace(/[^\w]+/g, '-').toLowerCase()}.png`);
      writeFileSync(file, Buffer.from(shot.result.data, 'base64'));
      console.log(`      screenshot: ${file}`);
      if (failed >= 3) { console.log('Stopping after 3 failures.'); break; }
    }
  }
} finally {
  ws.close();
  await closeBrowser();
}
console.log(failed ? `${failed} step(s) failed` : `All ${steps.length} steps passed`);
process.exit(failed ? 1 : 0);
