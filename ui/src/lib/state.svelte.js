/* Global app state + polling. One status poll drives everything: while a job
   or background task runs, prospects/stats refresh on a slower cadence
   (the /api/prospects payload is heavy — see webapp.py's caching notes). */

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

/* ------------------------------------------------------------- polling --- */
const anyBusy = () =>
  app.busy.resolving || app.busy.locating.length > 0 || app.busy.reevaluating.length > 0;

let timer = null;
let lastHeavy = 0;
let wasActive = false;

async function tick() {
  let active = false;
  try {
    app.status = await api.status();
    active = app.status.running;
  } catch { /* server briefly busy mid-crawl; keep last status */ }

  try {
    app.busy = await api.erfBusy();
  } catch { /* ditto */ }
  active = active || anyBusy();

  const now = Date.now();
  if (active && now - lastHeavy > 5000) {
    lastHeavy = now;
    loadProspects();
    loadStats();
  } else if (!active && wasActive) {
    // job just finished — one final refresh so the list settles
    loadProspects();
    loadStats();
  }
  wasActive = active;
}

export function startPolling() {
  if (timer) return;
  loadConfig();
  loadProspects();
  loadStats();
  loadTracked();
  tick();
  timer = setInterval(tick, 2500);
}

export function stopPolling() {
  clearInterval(timer);
  timer = null;
}

/* ------------------------------------------------------------- actions --- */
async function guard(fn, okMsg) {
  try {
    await fn();
    if (okMsg) toast(okMsg);
    tick();
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
