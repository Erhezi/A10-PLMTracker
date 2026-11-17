/* How fresh a feed's data is (app/utility/freshness.py), the note at the top right of Fill/Kill's Main
 * and Order Timing's pages: "Data as of" when Medline made the file we loaded, and "last loaded" when
 * we loaded it (the user, 2026-11-17: what the pages called "Data as of" until then was the load).
 * Grey; the load as a warning badge when it's stale.
 */

const esc = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (ch) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
));
const day = (iso) => String(iso).slice(0, 10);
const time = (iso) => String(iso).slice(11, 16);
const dateTime = (iso) => { const [y, m, d] = day(iso).split('-'); return `${m}/${d}/${y} ${time(iso)}`; };

// ``data``: the server's freshness ({loaded_at, data_as_of, file, stale}). ``feed``: whose data, when
// a page shows more than one: "Fill/Kill data as of ...".
export function freshnessHtml(data, feed) {
  if (!data || !data.loaded_at) return '';
  const asOf = data.data_as_of;
  let asOfText = '';
  let loadedText = `${feed ? `${feed} last loaded` : 'Last loaded'} ${dateTime(data.loaded_at)}`;
  if (asOf) {
    asOfText = `${feed ? `${feed} data` : 'Data'} as of ${dateTime(asOf)}`;
    // After the data's time, the load's time alone when it's the same day.
    loadedText = `last loaded ${day(asOf) === day(data.loaded_at) ? time(data.loaded_at) : dateTime(data.loaded_at)}`;
  }
  const title = data.file
    ? ` title="${esc(`From Medline's file ${data.file} (its time is Central), shown in New York time`)}"` : '';
  if (data.stale) {
    const badge = `<span class="badge text-bg-warning">${esc(loadedText)}: more than 90 minutes ago</span>`;
    // One element, so it stays together in a flex row (Short Ships has a note per feed).
    return asOf ? `<span><span class="text-muted"${title}>${esc(asOfText)} ·</span> ${badge}</span>` : badge;
  }
  return `<span class="text-muted"${title}>${esc(asOf ? `${asOfText} · ${loadedText}` : loadedText)}</span>`;
}

// For a sentence: "as of" the data's time, else "last loaded" ('' without either).
export function freshnessWhen(data) {
  if (!data || !data.loaded_at) return '';
  return data.data_as_of ? `as of ${dateTime(data.data_as_of)}` : `last loaded ${dateTime(data.loaded_at)}`;
}
