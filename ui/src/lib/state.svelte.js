/* Global app state + polling. One status poll drives everything: while a job
   or background task runs, prospects/stats refresh on a slower cadence
   (the /api/prospects payload is heavy — see webapp.py's caching notes), and
   the prospect list itself is only fetched once a page asks for it. */

import { api } from './api.js';

/* Which book the prospect list shows: 'sale' — everything this engine scores
   and sells on — or 'rent'. Read synchronously at module load so the very
   first fetch asks for the right one, and persisted like the crawl selection.
   localStorage is absent during prerender and can throw in private mode. */
let storedDeal = null;
try { storedDeal = localStorage.getItem('obv2.deal'); } catch { /* SSR */ }

export const app = $state({
  dealType: storedDeal === 'rent' ? 'rent' : 'sale',
  config: { suburbs: {}, sources: [] },
  prospects: [],
  stats: null,
  status: {
    running: false, phase: 'idle', log: [], done: 0, total: 0,
    per_source: {}, ai_ok: null, ai_reason: ''
  },
  busy: { resolving: false, locating: [], reevaluating: [] },
  showSole: false,
  loaded: false,          // first prospects fetch has landed
  selectedKey: null,      // drawer
  runOpen: false,         // crawl slide-over
  logOpen: false,         // activity log panel
  toast: null,
  tracked: {}             // group_id -> stage, for badges on prospect cards
});

export const gidOf = (r) =>
  r.group_id != null ? String(r.group_id) : 'solo-' + r.listing_key;

export async function loadTracked() {
  try { app.tracked = await api.trackedIds(); } catch { /* transient */ }
}

export async function trackProspect(r) {
  const gid = gidOf(r);
  try {
    const t = await api.track(gid);
    app.tracked[gid] = t.stage;
    toast('Tracking property — see it in Lead management', 'ok');
    return t;
  } catch (e) {
    toast('Could not track: ' + e.message, 'error');
  }
}

export const selected = () =>
  app.prospects.find((p) => p.listing_key === app.selectedKey) || null;

let toastTimer = null;
export function toast(msg, kind = 'info') {
  app.toast = { msg, kind };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (app.toast = null), 3600);
}

/* ------------------------------------------------------------- loaders --- */
export async function loadProspects() {
  try {
    app.prospects = await api.prospects(app.showSole, app.dealType);
    app.loaded = true;
  } catch (e) {
    if (!app.loaded) toast('Could not load prospects — is the engine running?', 'error');
  }
}

export async function loadStats() {
  try { app.stats = await api.stats(); } catch { /* transient */ }
}

export async function loadConfig() {
  try { app.config = await api.config(); } catch { /* transient */ }
}

export async function setShowSole(v) {
  app.showSole = v;
  await loadProspects();
}

/* Switch books. The two lists share nothing — a rental has no score, no
   property group and no erf — so the open drawer and the current rows are
   dropped rather than left pointing at the other book. */
export async function setDealType(v) {
  const next = v === 'rent' ? 'rent' : 'sale';
  if (next === app.dealType) return;
  app.dealType = next;
  try { localStorage.setItem('obv2.deal', next); } catch { /* private mode */ }
  app.selectedKey = null;
  app.prospects = [];
  app.loaded = false;
  await loadProspects();
}

/* The list is the heaviest thing the app fetches, and most pages (media,
   leads, account) never look at it — so nothing loads it on boot any more.
   A page that shows it asks for it here; a second ask while the first is
   still on the wire rides the same request instead of starting another. */
let prospectsPending = null;
export function ensureProspects() {
  if (app.loaded) return Promise.resolve();
  if (!prospectsPending) {
    prospectsPending = loadProspects().finally(() => (prospectsPending = null));
  }
  return prospectsPending;
}

/* ------------------------------------------------------------- polling --- */
const anyBusy = () =>
  app.busy.resolving || app.busy.locating.length > 0 || app.busy.reevaluating.length > 0;

/* Fast while something is actually happening, so progress feels live; slow
   when idle, where the poll only exists to notice a job started elsewhere. */
const FAST_MS = 2500;
const IDLE_MS = 8000;

let live = false;
let timer = null;
let ticking = false;
let lastHeavy = 0;
let wasActive = false;

/* One status read. Callers go through tick(), which keeps these from
   overlapping. */
async function pollOnce() {
  let active = false;
  try {
    app.status = await api.status();
    active = app.status.running;
  } catch { /* server briefly busy mid-crawl; keep last status */ }

  try {
    app.busy = await api.erfBusy();
  } catch { /* ditto */ }
  active = active || anyBusy();

  /* Only refresh the list if something already wanted it: re-downloading
     the whole book behind /media or /leads is exactly the cost we avoid by
     not loading it on boot. Stats are small, so they refresh regardless. */
  const now = Date.now();
  if (active && now - lastHeavy > 5000) {
    lastHeavy = now;
    if (app.loaded) loadProspects();
    loadStats();
  } else if (!active && wasActive) {
    // job just finished — one final refresh so the list settles
    if (app.loaded) loadProspects();
    loadStats();
  }
  wasActive = active;
}

/* A slow status call must not let the next tick (or a visibility catch-up)
   stack a second request pair on top of it. But an ask that arrives mid-read
   — typically an action that just started a job — is not dropped either: the
   read that is on the wire may predate the action, so one more follows it. */
let rerun = false;
async function tick() {
  if (ticking) { rerun = true; return; }
  ticking = true;
  try {
    do { rerun = false; await pollOnce(); } while (rerun);
  } finally {
    ticking = false;
  }
}

/* Self-scheduling like the chat loop (chat.svelte.js): each tick books the
   next one when it lands, at a pace set by what it just saw, and nothing is
   booked while the tab is hidden — a background tab has no one to show a
   progress bar to. */
function loop() {
  timer = null;
  /* A read is already on the wire: have it go once more and let ITS loop
     book the next slot, from fresh status, rather than booking one here
     off the stale status it is about to replace. */
  if (ticking) { rerun = true; return; }
  tick().finally(schedule);
}
function schedule() {
  if (!live || timer || typeof document === 'undefined' || document.hidden) return;
  timer = setTimeout(loop, app.status.running || anyBusy() ? FAST_MS : IDLE_MS);
}
function halt() {
  if (timer) clearTimeout(timer);
  timer = null;
}
/* Poll right now and re-book from what it sees — after an action, so a job
   that just started gets the fast cadence instead of waiting out an idle slot. */
function kick() {
  if (!live) return tick();
  halt();
  loop();
}
function onVisibility() {
  if (document.hidden) halt();
  else {
    halt();       // back in view: catch up now rather than wait out a slot
    loop();
  }
}

export function startPolling() {
  if (live) return;
  live = true;
  loadConfig();
  loadStats();
  loadTracked();
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibility);
  }
  loop();
}

export function stopPolling() {
  live = false;
  halt();
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', onVisibility);
  }
}

/* ------------------------------------------------------------- actions --- */
async function guard(fn, okMsg) {
  try {
    await fn();
    if (okMsg) toast(okMsg);
    kick();
    return true;
  } catch (e) {
    toast(e.message || String(e), 'error');
    return false;
  }
}

export const actions = {
  scrape: (payload) => guard(() => api.scrape(payload), 'Crawl started'),
  stop: () => guard(() => api.stop(), 'Stopping — finishing current requests'),
  rescore: (useAi) => guard(() => api.rescore(useAi), 'Re-scoring existing data'),
  erfResolve: () => guard(() => api.erfResolve(false), 'Resolving erf numbers against the cadastre'),
  erfLocate: (key) => guard(() => api.erfLocate(key), 'AI locate started'),
  reevaluate: (key) => guard(() => api.reevaluate(key), 'Re-evaluating — live refetch, re-score, erf match'),
  erfConfirm: async (key, erf) => {
    const ok = await guard(() => api.erfConfirm(key, erf), 'Erf confirmed');
    if (ok) { loadProspects(); loadStats(); }
    return ok;
  },
  copyRow: async (ident) => {
    try {
      const d = await api.row(ident);
      await navigator.clipboard.writeText(d.row);
      toast('Copied — paste into Excel / Google Sheets');
      return true;
    } catch (e) {
      toast('Copy failed: ' + (e.message || e), 'error');
      return false;
    }
  }
};
