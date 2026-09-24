/* Shared state for the Media section.

   Module-level runes, the same shape leads.svelte.js uses: the library list,
   the folder tree and the job poll are expensive enough that every page
   should read one copy rather than fetch its own. Leaving Browse for Search
   and coming back keeps the grid.

   The job poll is the one piece of machinery here. Zerko publishes progress
   over Server-Sent Events, but media.py blocks that route on purpose — an SSE
   stream pins a gunicorn worker thread for as long as the tab is open, and
   there are only eight. Polling on a timer that backs off to nothing when
   there is no work costs a request every few seconds while something is
   running and none at all when nothing is. */

import { media, bootError } from './media.js';

export const mstate = $state({
  /* backend reachability */
  ready: false,
  status: null,              // /api/media/status payload
  error: null,

  /* library */
  clips: [],
  loading: false,
  loaded: false,
  folders: [],
  tags: [],
  stats: null,

  /* what the grid is showing */
  filters: { search: '', folder_id: null, media_type: 'all', rating: null,
             tags: '', sort_by: 'date', sort_order: 'desc' },
  view: 'grid',              // grid | list
  selection: new Set(),

  /* the open clip (lightbox / drawer) */
  openId: null,
  openClip: null,

  /* who is looking: GET /api/me — role + capabilities */
  me: null,

  /* library extras (Zerko 1.2–1.4) */
  labelFilter: null,         // client-side: /api/videos has no label param
  clipboard: [],             // ids copied for paste-into-folder

  /* background work */
  jobs: { running: [], recent: [] },
  rescan: null,
  proxies: null,
  busy: false
});

/* --------------------------------------------------------------- toasts */

export const mtoast = $state({ items: [] });
let toastSeq = 0;

export function say(msg, kind = 'ok', ms = 3200) {
  const id = ++toastSeq;
  mtoast.items = [...mtoast.items, { id, msg, kind }];
  setTimeout(() => { mtoast.items = mtoast.items.filter((t) => t.id !== id); }, ms);
  return id;
}

const fail = (e) => say(e?.message || 'Something went wrong', 'error');

/* ------------------------------------------------------------ bootstrap */

let booting = null;

/** Work out whether there is a media backend at all, and whether it has a
    footage drive. Every Media page awaits this before it renders anything,
    so "no media root on this deployment" is a designed state rather than an
    empty grid. */
export function boot() {
  if (booting) return booting;
  booting = media.status()
    .then(async (s) => {
      mstate.status = s;
      if (!s.backend) {
        mstate.error = s.backend_error
          ? 'The media backend is not installed in this deployment.'
          : 'The media backend is unavailable.';
        return s;
      }
      // Mint the token now so <img>/<video> URLs built during the first
      // render already carry one.
      await media.stats().then((st) => { mstate.stats = st; }).catch(() => {});
      loadMe();                 // capabilities; pages hide what the role lacks
      mstate.ready = true;
      mstate.error = bootError.message || null;
      return s;
    })
    .catch((e) => { mstate.error = e.message; return null; });
  return booting;
}

/* -------------------------------------------------------------- library */

export async function loadClips(extra = {}) {
  mstate.loading = true;
  try {
    const params = { ...mstate.filters, ...extra };
    mstate.clips = (await media.videos(params)) || [];
    mstate.loaded = true;
  } catch (e) { fail(e); mstate.clips = []; }
  finally { mstate.loading = false; }
}

export async function loadFolders() {
  try { mstate.folders = (await media.folderTree()) || []; } catch { /* sidebar just stays flat */ }
}

export async function loadTags() {
  try { mstate.tags = (await media.tags()) || []; } catch { /* filters degrade */ }
}

export async function openClip(id) {
  mstate.openId = id;
  mstate.openClip = null;
  try { mstate.openClip = await media.video(id); }
  catch (e) { fail(e); mstate.openId = null; }
}

export const closeClip = () => { mstate.openId = null; mstate.openClip = null; };

/** Step to the next/previous clip in the current grid without closing. */
export function stepClip(delta) {
  const list = mstate.clips;
  if (!list.length || mstate.openId == null) return;
  const i = list.findIndex((c) => c.id === mstate.openId);
  if (i < 0) return;
  openClip(list[(i + delta + list.length) % list.length].id);
}

/* ------------------------------------------------------------ selection */

export function toggleSelect(id) {
  const next = new Set(mstate.selection);
  next.has(id) ? next.delete(id) : next.add(id);
  mstate.selection = next;          // reassign: Set mutation is not tracked
}
export const clearSelect = () => { mstate.selection = new Set(); };
export const selectAll = () => { mstate.selection = new Set(mstate.clips.map((c) => c.id)); };

/* ----------------------------------------------------------------- jobs */

let jobTimer = null;
let jobWatchers = 0;

async function pollJobs() {
  try {
    const [jobs, rescan, proxies] = await Promise.all([
      media.jobs().catch(() => null),
      media.rescanStatus().catch(() => null),
      media.proxyStatus().catch(() => null)
    ]);
    if (jobs) mstate.jobs = jobs;
    mstate.rescan = rescan;
    mstate.proxies = proxies;
  } catch { /* a missed poll is not worth a toast */ }

  // Fast while something is happening, slow when idle, so an open tab is
  // nearly free.
  const active = (mstate.jobs?.running?.length || 0) > 0
    || mstate.rescan?.running || (mstate.proxies?.pending || 0) > 0;
  clearTimeout(jobTimer);
  if (jobWatchers > 0) jobTimer = setTimeout(pollJobs, active ? 2000 : 15000);
}

/** Call from onMount; returns the teardown. */
export function watchJobs() {
  jobWatchers += 1;
  if (jobWatchers === 1) pollJobs();
  return () => {
    jobWatchers -= 1;
    if (jobWatchers <= 0) { clearTimeout(jobTimer); jobTimer = null; }
  };
}

/* -------------------------------------------------------------- actions */

export async function runRescan() {
  mstate.busy = true;
  try { await media.rescan(); say('Indexing the library…'); pollJobs(); }
  catch (e) { fail(e); } finally { mstate.busy = false; }
}

export async function runProxies() {
  try { await media.generateProxies(); say('Queued the missing proxies'); pollJobs(); }
  catch (e) { fail(e); }
}

export async function runAutoTag() {
  try { await media.autoTag(); say('Tagging pass started'); pollJobs(); }
  catch (e) { fail(e); }
}

export async function rate(clip, rating) {
  const before = clip.rating;
  clip.rating = rating;                       // optimistic: a star must feel instant
  try { await media.rate(clip.id, rating); }
  catch (e) { clip.rating = before; fail(e); }
}


/* ----------------------------------------------------- who may do what */

/* The capability names from zerko/permissions.py. Hiding a control is a
   courtesy — the backend middleware is the guard. */
export const CAP = {
  DOWNLOAD: 'media.download', UPLOAD: 'media.upload', ORGANISE: 'media.organise',
  ANNOTATE: 'media.annotate', TRASH: 'media.trash', HARD_DELETE: 'media.harddelete',
  TRANSCRIBE: 'jobs.transcribe', PROXY: 'jobs.proxy', SHARES: 'shares.manage', ADMIN: 'admin'
};

let meLoading = null;
export function loadMe() {
  if (mstate.me) return Promise.resolve(mstate.me);
  if (!meLoading) {
    meLoading = media.me()
      .then((m) => { mstate.me = m; return m; })
      .catch(() => null)
      .finally(() => { meLoading = null; });
  }
  return meLoading;
}

/** True when the signed-in role holds this capability. False until /api/me
    has answered, so nothing destructive flashes up and then vanishes. */
export const can = (cap) => !!mstate.me?.capabilities?.includes(cap);

/* ------------------------------------------------------- colour labels */

export const LABELS = [
  { value: 'red', label: 'Red', color: '#f26d64' },
  { value: 'yellow', label: 'Yellow', color: '#f0b429' },
  { value: 'green', label: 'Green', color: '#3ecf8e' },
  { value: 'blue', label: 'Blue', color: '#5aa9f5' },
  { value: 'purple', label: 'Purple', color: '#a78bfa' }
];
export const labelColor = (v) => LABELS.find((l) => l.value === v)?.color || null;

/** Set (or clear, with null) the colour label on these clips. Optimistic on
    the grid and the open clip; rolled back if the server says no. */
export async function setLabel(ids, label) {
  const want = new Set(ids);
  const before = new Map();
  for (const c of mstate.clips) if (want.has(c.id)) { before.set(c.id, c.label); c.label = label; }
  const open = mstate.openClip && want.has(mstate.openClip.id) ? mstate.openClip : null;
  const openBefore = open?.label;
  if (open) open.label = label;
  try {
    await media.label(ids, label);
    return true;
  } catch (e) {
    for (const c of mstate.clips) if (before.has(c.id)) c.label = before.get(c.id);
    if (open) open.label = openBefore;
    fail(e);
    return false;
  }
}

/** Drop clips from the grid (after they went to the trash or moved away). */
export function dropClips(ids) {
  const gone = new Set(ids);
  mstate.clips = mstate.clips.filter((c) => !gone.has(c.id));
  if (mstate.selection.size) mstate.selection = new Set([...mstate.selection].filter((i) => !gone.has(i)));
  if (mstate.openId != null && gone.has(mstate.openId)) closeClip();
}
