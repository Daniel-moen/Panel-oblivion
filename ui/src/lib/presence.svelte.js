/* Presence — the heartbeat out, and the roster in.

   OUT: `beat(path)` posts one lightweight heartbeat carrying the page the
   tab is on. The root layout calls it on every route change; `startHeartbeat`
   repeats it on the server's interval while the tab is VISIBLE (a hidden tab
   goes quiet, which is exactly how the server learns you walked away) and
   once more the moment the tab comes back.

   IN: `roster` is /api/online, polled every 30 s by whoever is showing it —
   the home strip, the /online page — through a ref-counted subscription so
   two views on screen at once still cost one request. The two directions are
   independent: a page that shows nobody still beats.

   Both sides are courtesies: the server decides who is online from what it
   was sent, and a member is handed a roster with no sessions in it. */

import { api } from './api.js';

export const roster = $state({
  loaded: false,
  now: null,
  me: null,
  is_admin: false,
  online: 0,
  users: [],
  thresholds: { online: 120, away: 600, heartbeat: 45 },
  error: null
});

let interval = 45;         // seconds; the server tells us its own on each beat
let lastPath = '/';
let beatTimer = null;
let beating = false;

export async function beat(path) {
  if (typeof document === 'undefined') return;
  if (path) lastPath = path;
  if (beating) return;
  beating = true;
  try {
    const r = await api.presence(lastPath);
    if (r && r.interval) interval = r.interval;
  } catch {
    /* signed out (api.js handles the 401), or the engine is down: the next
       beat will say so again; nothing to tell the person here */
  } finally {
    beating = false;
  }
}

function schedule() {
  clearTimeout(beatTimer);
  beatTimer = setTimeout(() => {
    if (document.visibilityState === 'visible') beat();
    schedule();
  }, interval * 1000);
}

/** Start the periodic heartbeat. Returns a stop function for the layout. */
export function startHeartbeat() {
  if (typeof document === 'undefined') return () => {};
  const onVis = () => {
    if (document.visibilityState === 'visible') { beat(); schedule(); }
  };
  document.addEventListener('visibilitychange', onVis);
  schedule();
  return () => {
    document.removeEventListener('visibilitychange', onVis);
    clearTimeout(beatTimer);
    beatTimer = null;
  };
}

/* ---- the roster --- */
let subscribers = 0;
let rosterTimer = null;
let loading = false;

export async function loadRoster() {
  if (loading) return;
  loading = true;
  try {
    const got = await api.online();
    Object.assign(roster, got, { loaded: true, error: null });
  } catch (e) {
    roster.error = e.message || String(e);
  } finally {
    loading = false;
  }
}

/** Subscribe to the live roster; call the returned function to let go. */
export function watchRoster(every = 30) {
  subscribers += 1;
  if (subscribers === 1) {
    loadRoster();
    rosterTimer = setInterval(() => {
      if (typeof document === 'undefined' || document.visibilityState === 'visible') loadRoster();
    }, every * 1000);
  } else {
    loadRoster();
  }
  return () => {
    subscribers = Math.max(0, subscribers - 1);
    if (subscribers === 0) { clearInterval(rosterTimer); rosterTimer = null; }
  };
}

/* ---- words --- */

/** '3 h ago', 'just now', '2 d ago' — from seconds. */
export function agoShort(seconds) {
  if (seconds == null) return 'never';
  const s = Math.max(0, Math.round(seconds));
  if (s < 45) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 36) return `${h} h ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d} d ago`;
  return `${Math.round(d / 30)} mo ago`;
}

export const STATUS_LABEL = { online: 'Online', away: 'Away', offline: 'Offline' };
