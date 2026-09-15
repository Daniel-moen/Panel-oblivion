/* "Find me…" state: the brief, the AI's answer and the request in flight.
   Lives outside the page so a hop to the map or a drawer open/close keeps
   the results on screen.

   Both books are searchable, and an answer belongs to the book it was asked
   of: a rental has no score and a sale has no rent, so the two never mix.
   Each book remembers its own last answer under its own storage key. */

import { api } from './api.js';
import { app, toast } from './state.svelte.js';

export const finder = $state({
  brief: '',
  busy: false,
  result: null,     // /api/find payload
  error: null,
  book: 'sale'      // which book the result on screen answers
});

/* The sale key is the original one, so an existing saved answer survives. */
const store = (deal) => (deal === 'rent' ? 'obv2.finder.rent' : 'obv2.finder');

function load(deal) {
  try {
    const raw = localStorage.getItem(store(deal));
    if (!raw) return null;
    const saved = JSON.parse(raw);
    return saved && saved.result ? saved : null;
  } catch {
    return null;   /* absent during prerender, throws in private mode */
  }
}

/* Restore the last answer so a page reload does not cost another model call. */
export function restoreFinder(deal = app.dealType) {
  const saved = load(deal);
  finder.book = deal;
  if (saved) { finder.brief = saved.brief; finder.result = saved.result; }
}

/* Switching books drops the answer on screen — it was about other stock —
   and brings back whatever that book was last asked, if anything. */
export function syncFinderBook(deal = app.dealType) {
  if (finder.book === deal) return;
  finder.result = null;
  finder.error = null;
  finder.brief = '';
  restoreFinder(deal);
}

export async function runFinder(brief = finder.brief) {
  brief = (brief || '').trim();
  if (brief.length < 3 || finder.busy) return;
  const deal = app.dealType;
  finder.brief = brief;
  finder.busy = true;
  finder.error = null;
  try {
    const result = await api.find(brief, app.showSole, deal);
    // The book may have been switched while the model was thinking; that
    // answer is no longer about what is on screen, so it is dropped.
    if (app.dealType !== deal) return;
    finder.result = result;
    finder.book = deal;
    try { localStorage.setItem(store(deal), JSON.stringify({ brief, result })); }
    catch { /* quota / private mode */ }
    if (!result.picks.length) toast('Nothing fits that brief closely — try loosening it');
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
  try { localStorage.removeItem(store(finder.book)); } catch { /* ignore */ }
}

/* Picks joined to the live prospect rows — the AI names listing_keys, the
   cards need the full row (photo, score, drawer). Rentals are keyed the same
   way (they have no group_id, but listing_key is on every row). Picks whose
   row has since dropped off the list (re-crawl, sole toggle, book switch)
   are skipped. */
export function pickedRows() {
  const res = finder.result;
  if (!res) return [];
  const byKey = new Map(app.prospects.map((r) => [r.listing_key, r]));
  return res.picks
    .map((p) => ({ pick: p, r: byKey.get(p.listing_key) }))
    .filter((x) => x.r);
}
