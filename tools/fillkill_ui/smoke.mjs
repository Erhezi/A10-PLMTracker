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

async function go(path, ready, what) {
  await send('Page.navigate', { url: `${BASE}${path}` });
  await sleep(300);
  await waitFor(ready, what);
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
// The main table's line whose Nursing's Pick cell is this Reference SKU.
const lineOf = (sku) => `[...document.querySelectorAll('#fk-main tbody.fk-item > tr')].find((tr) => [...tr.cells]
  .some((c) => c.innerText.trim() === ${JSON.stringify(sku)}))`;

// --- the walkthrough -----------------------------------------------------------------------

const steps = [
  ['Main opens on today', async () => {
    await go('/dev-login?as=all', `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length`, 'the main table');
    expect(await text('#fk-date-mode') === 'Select a range', 'the dates are not on today');
    expect(await count('#fk-main tbody.fk-item') === 2, `${await count('#fk-main tbody.fk-item')} items today, not 2`);
    expect((await text('#fk-data-as-of')).includes('Data as of') || (await text('#fk-data-as-of')).includes('Latest line update'), 'no data date');
    // At most 450px tall, scrolling inside, its header staying on top; the orders too (2026-10-20).
    for (const table of ['#fk-main', '#fk-orders']) {
      const cap = await evaluate(`getComputedStyle(document.querySelector('${table}').parentElement).maxHeight`);
      expect(cap === '450px', `${table} is capped at ${cap}, not 450px`);
    }
    expect(await evaluate(`getComputedStyle(document.querySelector('#fk-main thead th')).position`) === 'sticky', 'the header does not stay on top');
  }],
  ['A range of dates, kept in the page link', async () => {
    await click('#fk-date-mode');
    await setValue('#fk-start', daysAgo(2));
    await waitFor(`document.querySelectorAll('#fk-main tbody.fk-item').length === 3`, '3 items over three days');
    expect((await evaluate('location.search')).includes(`start=${daysAgo(2)}`), 'the link lacks the dates');
    expect(await count('#fk-main .fk-flag') >= 1, "no flag on the Medline item whose customer item isn't the Infor item");
  }],
  ['Search', async () => {
    await setValue('#fk-search', 'nitrile', 'input');
    await waitFor(`document.querySelectorAll('#fk-main tbody.fk-item').length === 1`, 'one glove item');
    await setValue('#fk-search', '', 'input');
    await waitFor(`document.querySelectorAll('#fk-main tbody.fk-item').length === 3`, 'all 3 items again');
  }],
  ['The panel: a whole Infor item, then one UOM', async () => {
    await clickText('#fk-main button[data-scope="infor"]', '999999');
    await waitFor(`document.getElementById('fk-panel-title').innerText === 'Infor item 999999'`, 'the Infor item in the panel');
    await panelSays('2 UOMs');
    expect((await evaluate('location.search')).includes('scope=infor'), 'the link lacks the panel');
    await click('[data-panel-tab="lines"]');
    await waitFor(`document.querySelectorAll('#fk-panel-content tbody tr').length === 2`, 'two kill lines');
    await click('[data-panel-focus="MDS2585HC"]');
    await waitFor(`document.querySelectorAll('#fk-panel-content tbody tr').length === 1`, "one UOM's kill line");
    await click('[data-panel-tab="picks"]');
    await panelSays('Nothing yet.');
  }],
  ['Nursing adds a Reference SKU: approved, and picked as the only one', async () => {
    await click('#fk-main button[data-open="DYND70294BH"]:not([data-scope])');
    await waitFor(`document.getElementById('fk-panel-title').innerText === 'DYND70294BH'`, 'DYND70294BH in the panel');
    await click('[data-panel-tab="subs"]');
    await click('[data-act="show-add"]');
    await setValue('#fk-add-sku', '88885');
    await setValue('#fk-add-comment', 'From the supplier by phone');
    await evaluate(`document.getElementById('fk-add-form').requestSubmit()`);
    await panelSays('Approved and picked');
    expect((await text('#fk-panel-content')).includes('Vendor item needed'), 'no "Vendor item needed"');
    // Nursing's Pick is the Reference SKU, with a pencil until there's something to order (2026-10-20).
    await waitFor(`[...document.querySelectorAll('#fk-main tbody.fk-item')].some((b) => b.innerText.includes('88885')
      && b.querySelector('[data-add-vi] .bi-pencil-square'))`, 'the pick, with its pencil, in the table');
    // Its comments beside it (2026-10-21): the icon counts them and opens them; a click elsewhere closes them.
    const chat = `[...document.querySelectorAll('#fk-main [data-comments]')].find((b) => b.closest('td').innerText.includes('88885'))`;
    await waitFor(`${chat} && ${chat}.innerText.trim() === '1'`, 'the comments icon, counting 1');
    // The latest reads under the pick, with who and when (2026-10-27, for the nursing manager).
    const said = await evaluate(`${chat}.closest('td').querySelector('.fk-pick-comment').innerText.replace(/\\s+/g, ' ').trim()`);
    expect(said.startsWith('From the supplier by phone all ·'), `the comment under the pick: ${said}`);
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
    // Main: the pick keeps its Reference SKU, without the pencil; the vendor item is a tile beside it.
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
  ['Putting the pick on hold', async () => {
    await setValue('#fk-panel-content select[data-act="status"]', 'hold');
    await panelSays('Status set to');
    await click('[data-panel-tab="picks"]');
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
    await panelSays('Approved and picked');
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
    await panelSays('Approved and picked');
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
    await click('[data-days="today"]');
    const [y, m, d] = daysAgo(0).split('-');
    await waitFor(`document.getElementById('fk-dash-range').innerText === '${m}/${d}/${y} to ${m}/${d}/${y}'`, 'the range on today');
    await waitFor(`document.querySelectorAll('#fk-dash-top tr').length === 2`, "today's two items");
  }],
  ['A nurse: no vendor items, and their Reference SKU is the pick', async () => {
    await go('/dev-login?as=nurse', `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length`, 'the main table');
    await click('#fk-main button[data-open="MDS2585H"]:not([data-scope])');
    await waitFor(`document.querySelector('[data-act="show-add"]')`, 'Add sub');
    await click('[data-act="show-add"]');
    await setValue('#fk-add-sku', 'GLV-2');
    await evaluate(`document.getElementById('fk-add-form').requestSubmit()`);
    await panelSays('Approved and picked');
    expect(await count('#fk-panel-content [data-act="add-vi"]') === 0, 'a nurse can add vendor items');
    expect(await count('#fk-panel-content [data-act="order"]') === 0, 'a nurse sees "Record order"');
    // Their pick is in the table without the pencil: adding its vendor items is the Materials
    // Manager's, and a pencil they can't use looked broken (2026-10-21).
    await waitFor(`[...document.querySelectorAll('#fk-main tbody.fk-item')].some((b) => b.innerText.includes('GLV-2'))`, 'the pick');
    expect(await count('#fk-main .bi-pencil-square, #fk-main [data-add-vi]') === 0, 'a nurse sees the pencil or can open the vendor item form');
    // A second sub from Main, without the panel (2026-10-27): a double-click on the Medline item's
    // Nursing's Pick cell opens the form.
    await go('/dev-login?as=nurse', `${MAIN_READY} && ${lineOf('GLV-2')}`, 'the main table');
    await dblclick(`${lineOf('GLV-2')}.querySelector('td[data-add-sub="MDS2585H"]')`, "GLV-2's cell");
    await modalOpen();
    const about = (await text('.fk-form-summary')).replace(/\s+/g, ' ');
    expect(about.includes('MDS2585H (BX/100)') && about.includes('1 approved · picked GLV-2'), `the add-sub form's summary: ${about}`);
    await waitFor(`document.activeElement.id === 'fk-m-reference_sku'`, 'the cursor in the Reference SKU');
    await setValue('#fk-m-reference_sku', 'GLV-3');
    await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
    await modalClosed();
    await waitFor(`[...document.querySelectorAll('#fk-main tbody.fk-item')].some((b) => b.innerText.includes('GLV-2')
      && b.innerText.replace(/\\s+/g, ' ').includes('Approved 2'))`, 'two approved subs on MDS2585H');
    // A second pick on the same UOM gets a line of its own in the table (2026-10-21).
    await click('#fk-main button[data-open="MDS2585H"]:not([data-scope])');
    const glv3 = `[...document.querySelectorAll('#fk-panel-content .card')].find((c) => c.querySelector('.fw-semibold').innerText === 'GLV-3')`;
    await waitFor(`${glv3} && ${glv3}.querySelector('[data-act="pick"]')`, 'Pick on GLV-3');
    await evaluate(`${glv3}.querySelector('[data-act="pick"]').click()`);
    await panelSays('Picked.');
    await waitFor(`${lineOf('GLV-3')} && !${lineOf('GLV-3')}.innerText.includes('GLV-2')`, 'GLV-3 on a line of its own');
  }],
  ['A Materials Manager finds the vendor ID by name, or uses 0000000', async () => {
    await go('/dev-login?as=mm', `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length`, 'the main table');
    // Two picks on MDS2585H: each pick's "+ Vendor item for" is on its own line, beside it (2026-10-21).
    for (const [mine, other] of [['GLV-2', 'GLV-3'], ['GLV-3', 'GLV-2']]) {
      const text = await evaluate(`${lineOf(mine)}.innerText`);
      expect(text.includes(`Vendor item for ${mine}`) && !text.includes(other), `${mine}'s line: ${text}`);
    }
    // From the pick's pencil on Main.
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
    }
    const items = await evaluate(`${card}.querySelector('.fk-vendor-items').innerText`);
    expect(items.includes('B-D930103CSZ') && items.includes('BX/40') && items.includes('B-D930103CS ') && items.includes('CA/400'),
      `the vendor items: ${items}`);
    // A Materials Manager picks and unpicks too (2026-10-21); the status stays the Sub Approver's.
    expect(await evaluate(`${card}.querySelector('select[data-act="status"]') === null`), 'a Materials Manager can set the status');
    await evaluate(`${card}.querySelector('[data-act="unpick"]').click()`);
    await panelSays('Unpicked.');
    await waitFor(`${card} && ${card}.querySelector('[data-act="pick"]')`, 'Pick on the 930103 sub');
    await evaluate(`${card}.querySelector('[data-act="pick"]').click()`);
    await panelSays('Picked.');
    // Main: the pick is 930103, with a tile for each.
    await waitFor(`[...document.querySelectorAll('#fk-main tbody.fk-item')].some((b) => b.innerText.includes('930103')
      && b.querySelectorAll('[data-order-vi]').length === 2)`, 'two tiles for 930103');
  }],
  ["The MM Lead writes Will's Comments; the sites read them on Main", async () => {
    // 2026-10-27: the Materials Management lead guides the sites' Materials Managers and doesn't
    // order: no tiles to click, but the item's comment to write.
    await go('/dev-login?as=lead', `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length`, 'the main table');
    expect(await count('#fk-main button[data-order-vi]') === 0 && await count('#fk-main div.fk-vi-tile') >= 1,
      'an MM Lead can click a tile to record an order');
    // Between the pick and its vendor items (the user, 2026-10-27).
    const heads = await evaluate(`[...document.querySelectorAll('#fk-main thead th')].map((th) => th.innerText.trim())`);
    const at = heads.indexOf("Will's Comments");
    expect(at > 0 && heads[at - 1] === "Nursing's Pick" && heads[at + 1] === 'Vendor Item Detail', `the columns: ${heads.join(', ')}`);
    // A double-click on its cell opens the form.
    await dblclick(`document.querySelector('#fk-main td[data-instruct="DYND70294BH"]')`, "the item's cell");
    await modalOpen();
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
    expect((await evaluate(`${cell}.innerText`)).includes('lead ·'), 'no who and when under it');
    // Or from the item's panel: Add comment (the user: a button, like Add sub).
    await click('#fk-main button[data-open="DYND70294BH"]:not([data-scope])');
    await panelSays('Site B: 1 BX of 88885 today.');
    await click('#fk-panel-body [data-act="instruct"]');
    await modalOpen();
    await setValue('#fk-m-instruction', 'All sites: order the pick as usual.');
    await evaluate(`document.getElementById('fk-modal-form').requestSubmit()`);
    await modalClosed();
    await panelSays('Comment saved for Infor item 100339.');
    await click('#fk-panel-body [data-act="instructions"]');
    await waitFor(`document.getElementById('fk-panel-instructions').innerText.includes('Site B: 1 BX of 88885 today.')`, 'both comments in the panel');
    await waitFor(`${cell}.innerText.includes('All sites: order the pick as usual.')`, 'the latest on Main');
    // A Materials Manager reads them, all of them in the popover, and can't write one.
    await go('/dev-login?as=mm', `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length`, 'the main table');
    await waitFor(cell, 'the comment');
    expect(await count('#fk-main td[data-instruct]') === 0, 'a Materials Manager can write comments');
    await click('#fk-main [data-instructions="DYND70294BH"]');
    await waitFor(`(document.querySelector('.fk-comments-popover') || {}).innerText?.includes('Site B: 1 BX')`, 'the comments popover');
    expect((await text('.fk-comments-popover')).includes("Will's Comments"), "the popover isn't titled Will's Comments");
    await evaluate('document.body.click()');
    await waitFor(`!document.querySelector('.fk-comments-popover')`, 'the popover to close');
    await click('#fk-main button[data-open="DYND70294BH"]:not([data-scope])');
    await panelSays('All sites: order the pick as usual.');
    expect(await count('#fk-panel-body [data-act="instruct"]') === 0, 'a Materials Manager has Add comment');
  }],
  ['A viewer: nothing to change', async () => {
    await go('/dev-login?as=viewer', `${MAIN_READY} && document.querySelectorAll('#fk-main tbody.fk-item').length`, 'the main table');
    await click('#fk-main button[data-open="MDS2585H"]:not([data-scope])');
    await panelSays('GLV-2');
    expect(await count('#fk-panel-body [data-act="show-add"], #fk-panel-body select[data-act="status"], #fk-panel-body [data-act="add-vi"]') === 0,
      'a viewer can change subs');
    expect(await count('#fk-main [data-order-vi], #fk-main [data-add-vi]') === 0, 'a viewer can record orders or add vendor items');
    expect(await count('#fk-main td[data-dblclick]') === 0, 'a viewer has cells to double-click');
    expect(await count('#fk-main .bi-pencil-square') === 0, 'a viewer sees the pencil of a pick without vendor items (GLV-3)');
    expect(await count('#fk-main div.fk-vi-tile') >= 3, 'a viewer sees no vendor item tiles');
  }],
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
