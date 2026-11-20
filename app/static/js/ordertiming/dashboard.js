/* Order Timing's Dashboard (2026-11-20): the whole picture of Medline's order feed in the days and
 * sites chosen, from /ordertiming/api/dashboard (app/ordertiming/dashboard.py). The headline figures,
 * three charts (lines per day by status; POs by the hour received, by how fast Medline confirmed them;
 * POs by the hour Medline created the order, with an ASN that day or not), the slowest POs to confirm,
 * each site's figures and the rejected lines. Read-only; the days and sites are kept in the URL.
 *
 * An ES module; Chart.js is loaded with `defer` in base.html's head, so it has run before this does.
 * The filters are Main's (common.js), without the search.
 */

import {
  $, alertBox, asOfText, config, esc, filterState, fmtAfter, fmtDate, fmtDateTime, fmtNumber, getJSON, keepInUrl,
  plural, setupFilters, showDays, url,
} from './common.js';

// Colours, checked with the dataviz palette validator (2026-11-20). The statuses keep Main's badge
// hues (Bootstrap's success, primary, warning, danger), stepped to tell apart and read on white;
// stacked from the bottom by how far the line got. The confirm bands are one blue, darker the longer
// Medline took, with not confirmed in the statuses' amber. No ASN is a recessive gray.
const STATUS_ORDER = ['asn', 'confirmed', 'not_confirmed', 'rejected'];
const STATUS_COLOR = { asn: '#198754', confirmed: '#2a78d6', not_confirmed: '#cc9a06', rejected: '#dc3545' };
const BAND_COLOR = {
  within_15: '#86b6ef', within_60: '#3987e5', within_240: '#1c5cab', over_240: '#0d366b', not_confirmed: '#cc9a06',
};
const ASN_SERIES = [['asn', 'ASN sent that day', '#198754'], ['no_asn', 'No ASN in the feed', '#c3c2b7']];
const OTHER = '#6c757d';  // a status the view adds before the app has a colour for it
const INK = { text: '#212529', muted: '#6c757d', grid: '#e9ecef', baseline: '#ced4da', surface: '#ffffff' };

const STATUS_LABEL = Object.fromEntries(config.statuses);
const HOURS = Array.from({ length: 24 }, (_, h) => String(h).padStart(2, '0'));

const state = filterState();
const charts = {};
setupFilters(state, load);

// --- formatting --------------------------------------------------------------------------------

const pct = (n) => (n == null ? '—' : `${n}%`);

function hoursText(h) {
  if (h == null) return '—';
  if (h < 1) return `${Math.round(h * 60)} min`;
  if (h < 48) return `${h.toFixed(1)} h`;
  return `${(h / 24).toFixed(1)} days`;
}

function minutesText(m) {
  if (m == null) return '—';
  if (m < 60) return `${Number.isInteger(m) ? m : m.toFixed(1)} min`;
  return hoursText(m / 60);
}

const weekday = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-US', { weekday: 'short' });
const scope = () => ({ start: state.start, end: state.end, sites: state.sites });
// Main and Short Ships on the same days and sites.
const mainUrl = (extra) => url(config.api.main, { ...scope(), ...extra });
const shortShipsUrl = () => url(config.api.shortships, scope());

// --- the headline --------------------------------------------------------------------------------

function tile(label, value, note, title) {
  return `<div class="col-6 col-md-4 col-xl"><div class="card shadow-sm border-0 h-100 ot-tile"${title ? ` title="${esc(title)}"` : ''}>
    <div class="card-body py-2">
      <div class="small text-muted">${esc(label)}</div>
      <div class="fs-4 fw-semibold">${esc(value)}</div>
      <div class="small text-muted">${note}</div>
    </div></div></div>`;
}

const link = (text, href, title) => `<a href="${esc(href)}"${title ? ` title="${esc(title)}"` : ''}>${esc(text)}</a>`;

function headline(h) {
  const none = !h.pos;
  $('ot-dash-headline').innerHTML = [
    tile('POs', fmtNumber(h.pos), none ? 'None in these days' : esc(`${plural(h.lines, 'line')} · ${plural(h.sites, 'site')}`)),
    tile('Confirmed', pct(h.share_confirmed),
      h.not_confirmed ? link(`${plural(h.not_confirmed, 'PO')} not confirmed yet`, mainUrl({ status: 'not_confirmed' }), 'Open them on Main')
        : (none ? '' : 'Every PO has its 855'),
      "POs with Medline's order confirmation (855) on every line"),
    tile('Median time to confirm', minutesText(h.median_confirm_minutes),
      h.confirmed ? esc(h.slow ? `${plural(h.slow, 'PO')} took over an hour` : 'None took over an hour') : '',
      'From Medline receiving the PO to its 855, over the POs confirmed'),
    tile('ASN the same day', pct(h.share_asn), none ? '' : esc(`${fmtNumber(h.asn)} of ${plural(h.pos, 'PO')}`),
      "POs with a ship notice (ASN, 856) on the day Medline created the order. Medline's report covers each order day only, so an ASN sent the day after isn't counted."),
    tile('Median receipt to ASN', hoursText(h.median_asn_hours), h.asn ? 'POs with an ASN that day' : '',
      'From Medline receiving the PO to its first ASN'),
    tile('Rejected lines', fmtNumber(h.rejected_lines),
      h.rejected_lines ? link(`on ${plural(h.rejected_pos, 'PO')}`, mainUrl({ status: 'rejected' }), 'Open them on Main') : '',
      'Lines Medline flagged as bad lines: they won\'t be filled'),
    tile('Short-shipped lines', fmtNumber(h.short_lines),
      h.short_lines ? `${esc(`${h.share_short}% of lines`)} · ${link('Short Ships', shortShipsUrl(), 'Their items on Short Ships')}` : '',
      'Lines Medline shipped fewer of than ordered'),
  ].join('');
}

// --- the charts -----------------------------------------------------------------------------------

const sum = (values) => values.reduce((a, b) => a + (Number(b) || 0), 0);

// Stacked columns, one dataset per {name, data, color}; the legend gives each series' total. The
// tooltip lists every series at that column (``titles``: its heading; ``footer``: a line under it).
function drawBars(id, labels, series, { titles, footer } = {}) {
  if (!window.Chart) return;
  if (charts[id]) charts[id].destroy();
  const canvas = $(id);
  const box = canvas.parentElement;
  let note = box.querySelector('.fk-chart-note');
  if (!note) {
    note = document.createElement('div');
    note.className = 'fk-chart-note small text-muted position-absolute top-50 start-50 translate-middle';
    note.textContent = 'Nothing in these days.';
    box.appendChild(note);
  }
  const total = sum(series.map((s) => sum(s.data)));
  note.classList.toggle('d-none', total > 0);
  canvas.classList.toggle('invisible', total === 0);
  charts[id] = new window.Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: series.map((s) => ({
        label: `${s.name} · ${fmtNumber(sum(s.data))}`, name: s.name, data: s.data, backgroundColor: s.color,
        // A 2px gap of the card's white between stacked segments; rounded at the top of the stack.
        borderColor: INK.surface, borderWidth: { top: 2, right: 0, bottom: 0, left: 0 }, borderSkipped: 'start',
        borderRadius: 4, maxBarThickness: 24,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          position: 'bottom',
          labels: { color: INK.text, boxWidth: 12, boxHeight: 12, usePointStyle: true, pointStyle: 'rectRounded' },
        },
        tooltip: {
          filter: (item) => item.parsed.y > 0,
          callbacks: {
            title: (items) => (titles ? titles[items[0].dataIndex] : items[0].label),
            label: (item) => ` ${item.dataset.name}: ${fmtNumber(item.parsed.y)}`,
            footer: (items) => (footer && items.length ? footer(items[0].dataIndex) : ''),
          },
        },
      },
      scales: {
        x: { stacked: true, grid: { display: false }, border: { color: INK.baseline },
             ticks: { color: INK.muted, maxRotation: 0, autoSkipPadding: 6 } },
        y: { stacked: true, beginAtZero: true, border: { display: false }, grid: { color: INK.grid },
             ticks: { color: INK.muted, precision: 0 } },
      },
    },
  });
}

// Lines per day in each status, how far the line got from the bottom up.
function drawDays(byDay) {
  const keys = [...STATUS_ORDER.filter((s) => s in byDay.series),
    ...Object.keys(byDay.series).filter((s) => !STATUS_ORDER.includes(s))];
  const series = keys.map((s) => ({ name: STATUS_LABEL[s] || s || 'No status', data: byDay.series[s], color: STATUS_COLOR[s] || OTHER }));
  drawBars('ot-chart-days', byDay.days.map((d) => fmtDate(d).slice(0, 5)), series, {
    titles: byDay.days.map((d) => `${weekday(d)} ${fmtDate(d)}`),
    footer: (i) => `${plural(sum(series.map((s) => s.data[i])), 'line')} · ${fmtNumber(byDay.short[i])} short shipped`,
  });
}

// POs by the hour on Medline's clock; a band with no POs is left out of the legend.
function drawHours(id, keyed, names, colors) {
  const series = names.filter(([key]) => sum(keyed[key] || []) > 0)
    .map(([key, name]) => ({ name, data: keyed[key], color: colors[key] }));
  drawBars(id, HOURS, series, {
    titles: HOURS.map((h) => `${h}:00 to ${h}:59, Medline's clock`),
    footer: (i) => plural(sum(series.map((s) => s.data[i])), 'PO'),
  });
}

// --- the tables ------------------------------------------------------------------------------------

// A row each, as tall as the chart beside it: Medline's order number and when it created the order
// (seconds before its 855, on O2) on hover.
function slowest(rows) {
  $('ot-dash-slowest').innerHTML = rows.length ? rows.map((o) => `<tr>
      <td><a class="fw-semibold" href="${esc(mainUrl({ q: o.po || o.order_no }))}"
        title="Medline order ${esc(o.order_no)}. Open this PO on Main">${esc(o.po || o.order_no)}</a></td>
      <td class="small">${esc(o.site_name || o.site)}</td>
      <td class="text-nowrap">${esc(fmtDateTime(o.received_at))}</td>
      <td class="text-nowrap" title="Medline created its order ${esc(fmtDateTime(o.created_at))}">${esc(fmtAfter(o.confirmed_at, o.received_at))}</td>
      <td class="text-end text-nowrap fw-semibold">${esc(minutesText(o.minutes))}</td>
      <td class="text-end">${fmtNumber(o.lines)}</td>
    </tr>`).join('') : '<tr><td colspan="6" class="small text-muted">No confirmed POs in these days.</td></tr>';
}

function siteCells(s) {
  const under = (text) => (text ? `<div class="small text-muted">${esc(text)}</div>` : '');
  return `<td class="text-end">${fmtNumber(s.pos)}</td>
    <td class="text-end">${fmtNumber(s.lines)}</td>
    <td class="text-end">${pct(s.share_confirmed)}${under(s.not_confirmed ? `${fmtNumber(s.not_confirmed)} not yet` : '')}</td>
    <td class="text-end">${esc(minutesText(s.median_confirm_minutes))}</td>
    <td class="text-end">${fmtNumber(s.slow)}</td>
    <td class="text-end">${pct(s.share_asn)}${under(plural(s.asn, 'PO'))}</td>
    <td class="text-end">${esc(hoursText(s.median_asn_hours))}</td>
    <td class="text-end">${fmtNumber(s.rejected_lines)}</td>
    <td class="text-end">${fmtNumber(s.short_lines)}${under(s.share_short == null ? '' : `${s.share_short}%`)}</td>`;
}

function sites(rows, total) {
  $('ot-dash-sites').innerHTML = rows.length ? rows.map((s) => `<tr>
      <th scope="row" class="fw-normal"><span title="Sold-To ${esc(s.site)}">${esc(s.site_name)}</span></th>${siteCells(s)}
    </tr>`).join('') : '<tr><td colspan="10" class="small text-muted">No POs in these days.</td></tr>';
  $('ot-dash-sites-total').innerHTML = rows.length > 1
    ? `<tr class="fw-semibold"><th scope="row">All sites</th>${siteCells(total)}</tr>` : '';
}

function rejected(rows) {
  const seeAll = $('ot-dash-rejected-link');
  seeAll.href = mainUrl({ status: 'rejected' });
  seeAll.hidden = !rows.length;
  $('ot-dash-rejected').innerHTML = rows.length ? rows.map((r) => `<tr>
      <td><span class="badge text-bg-danger">${esc(r.rej_code || 'No code')}</span></td>
      <td><div class="fw-semibold">${esc(r.medline_item || '—')}</div><div class="small text-muted">${esc(r.item_on_po || '')}</div></td>
      <td class="small">${esc(r.description || '')}</td>
      <td class="text-end">${fmtNumber(r.lines)}</td>
      <td class="text-end">${fmtNumber(r.pos)}</td>
    </tr>`).join('') : '<tr><td colspan="5" class="small text-muted">Medline rejected no lines in these days.</td></tr>';
}

// --- loading -----------------------------------------------------------------------------------------

function render(data) {
  $('ot-dash-error').innerHTML = '';
  showDays(state, data.scope);  // as the server held them to the days Order Timing reaches
  keepInUrl(scope());
  const { start, end } = data.scope;
  $('ot-dash-range').textContent = start === end ? fmtDate(start) : `${fmtDate(start)} to ${fmtDate(end)}`;
  asOfText(data.data);
  headline(data.headline);
  drawDays(data.by_day);
  drawHours('ot-chart-received', data.by_hour_received.series, config.confirm_bands, BAND_COLOR);
  drawHours('ot-chart-created', data.by_hour_created.series, ASN_SERIES.map(([key, name]) => [key, name]),
    Object.fromEntries(ASN_SERIES.map(([key, , color]) => [key, color])));
  slowest(data.slowest);
  sites(data.sites, data.headline);
  rejected(data.rejected);
}

let ticket = 0;

// While it loads, what's shown stays, dimmed (no flash of empty charts).
async function load() {
  const mine = ++ticket;
  keepInUrl(scope());
  $('ot-dash-body').classList.add('ot-dash-loading');
  try {
    const data = await getJSON(config.api.dashboard, scope());
    if (mine === ticket) render(data);
  } catch (error) {
    if (mine === ticket) $('ot-dash-error').innerHTML = alertBox(error.message);
  } finally {
    if (mine === ticket) $('ot-dash-body').classList.remove('ot-dash-loading');
  }
}

asOfText(config.data);
if (config.problem) {
  $('ot-problem').innerHTML = alertBox(config.problem, 'warning');
  $('ot-dash-body').hidden = true;
} else {
  load();
}
