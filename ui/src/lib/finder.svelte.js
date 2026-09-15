/* "Find me…" state: the brief, the AI's answer and the request in flight.
   Lives outside the page so a hop to the map or a drawer open/close keeps
   the results on screen. */

import { api } from './api.js';
import { app, toast } from './state.svelte.js';

export const finder = $state({
  brief: '',
  busy: false,
  result: null,     // /api/find payload
  error: null
});

const STORE = 'obv2.finder';

/* Restore the last answer so a page reload does not cost another model call. */
export function restoreFinder() {
  try {
    const raw = localStorage.getItem(STORE);
    if (!raw) return;
    const saved = JSON.parse(raw);
    if (saved && saved.result) { finder.brief = saved.brief; finder.result = saved.result; }
  } catch { /* ignore */ }
}

export async function runFinder(brief = finder.brief) {
  brief = (brief || '').trim();
  if (brief.length < 3 || finder.busy) return;
  finder.brief = brief;
  finder.busy = true;
  finder.error = null;
  try {
    finder.result = await api.find(brief, app.showSole);
    try { localStorage.setItem(STORE, JSON.stringify({ brief, result: finder.result })); }
    catch { /* quota / private mode */ }
    if (!finder.result.picks.length) toast('Nothing fits that brief closely — try loosening it');
  } catch (e) {
    finder.error = e.message || String(e);
    toast('Finder failed: ' + finder.error, 'error');
  } finally {
    finder.busy = false;
  }
}

export function clearFinder() {
  finder.result = null;
  finder.error = null;
  finder.brief = '';
  try { localStorage.removeItem(STORE); } catch { /* ignore */ }
}

/* Picks joined to the live prospect rows — the AI names listing_keys, the
   cards need the full row (photo, score, drawer). Picks whose row has since
   dropped off the list (re-crawl, sole toggle) are skipped. */
export function pickedRows() {
  const res = finder.result;
  if (!res) return [];
  const byKey = new Map(app.prospects.map((r) => [r.listing_key, r]));
  return res.picks
    .map((p) => ({ pick: p, r: byKey.get(p.listing_key) }))
    .filter((x) => x.r);
}
