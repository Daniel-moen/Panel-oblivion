/* Shoots — the property-shoot business record (Zerko 1.2–1.3).

   A shoot is keyed by the property's address: one house, one shoot, however
   many library folders hang off it. Everything here is a thin client over
   zerko/shoots.py, captions.py, listing_pack.py, rooms.py and delivery.py;
   the docstrings there are the spec. Field names are the backend's exactly. */

import { mfetch, murl, post, put, del, q } from '$lib/media.js';

const patch = (p, body) => mfetch(p, { method: 'PATCH', body: JSON.stringify(body ?? {}) });

/* ---------------------------------------------------------------- who am i */

let meP = null;
/** GET /api/me — role + capabilities. Cached for the tab. */
export function me() {
  if (!meP) meP = mfetch('/api/me').catch((e) => { meP = null; throw e; });
  return meP;
}
export const can = (who, cap) => !!who?.capabilities?.includes(cap);
export const CAP_SHOOTS = 'shoots.manage';
export const CAP_SHARES = 'shares.manage';

/* ------------------------------------------------------------------ status */

export const STATUSES = ['shot', 'editing', 'posted'];
export const STATUS = {
  shot: { label: 'Shot', tone: 'warn' },
  editing: { label: 'Editing', tone: 'mgr' },
  posted: { label: 'Posted', tone: 'ok' }
};

/* --------------------------------------------------------------------- api */

export const shoots = {
  list: (params) => mfetch('/api/shoots' + q({ limit: 1000, ...params })),
  get: (id) => mfetch(`/api/shoots/${id}`),
  /** { address, suburb, agent, shoot_date, shoot_time, note, folders[], lat, lng } */
  create: (body) => post('/api/shoots', body),
  /** any of address, suburb, agent, status, shoot_date, shoot_time, note, lat, lng,
      clear_location, cover_video_id, facts{} */
  update: (id, body) => patch(`/api/shoots/${id}`, body),
  remove: (id) => del(`/api/shoots/${id}`),
  addFolder: (id, path) => post(`/api/shoots/${id}/folders`, { path }),
  removeFolder: (id, path) => del(`/api/shoots/${id}/folders` + q({ path })),
  suggestFolders: () => mfetch('/api/shoots/suggest/folders'),
  forPath: (path) => mfetch('/api/shoots/for-path/' + q({ path })),
  lookupAddress: (id) => post(`/api/shoots/${id}/lookup-address`),

  geocode: (s, near) => mfetch('/api/shoots/geocode/search' +
    q(near ? { q: s, lat: near.lat.toFixed(5), lng: near.lng.toFixed(5) } : { q: s })),
  reverse: (lat, lng) => mfetch('/api/shoots/geocode/reverse' + q({ lat, lng })),

  agents: () => mfetch('/api/shoots/agents'),
  addAgent: (body) => post('/api/shoots/agents', body),

  /* the shoot's media: every file under its folders */
  media: (folderId) => mfetch('/api/videos' + q({ folder_id: folderId, include_subfolders: true, sort_by: 'name', sort_order: 'asc' })),

  /* captions */
  captions: (id) => mfetch(`/api/shoots/${id}/captions`),
  guessClip: (id, videoId) => mfetch(`/api/shoots/${id}/captions/guess` + q({ video_id: videoId })),
  writeCaption: (id, opts) => post(`/api/shoots/${id}/captions`, opts),
  editCaption: (id, cid, text) => patch(`/api/shoots/${id}/captions/${cid}`, { text }),
  copiedCaption: (id, cid) => post(`/api/shoots/${id}/captions/${cid}/copied`),
  deleteCaption: (id, cid) => del(`/api/shoots/${id}/captions/${cid}`),

  /* export by room / listing pack */
  startPack: (id, body) => post(`/api/shoots/${id}/listing-pack`, body),
  packState: (jobId) => mfetch(`/api/listing-pack/${jobId}`),
  packZipUrl: (jobId) => murl(`/api/listing-pack/${jobId}/zip`),

  /* room plan, kept per folder ("folder:<id>") */
  rooms: (key) => mfetch('/api/rooms' + q({ key })),
  saveRooms: (key, rooms, style = 'Bedroom1') => put('/api/rooms', { key, rooms, style }),

  /* delivery portals */
  deliver: (id, body) => post(`/api/shoots/${id}/deliver`, body),
  deliveries: (id) => mfetch(`/api/shoots/${id}/deliveries`)
};

export const CAPTION_PLATFORMS = [
  { value: 'instagram', label: 'Instagram' },
  { value: 'facebook', label: 'Facebook' },
  { value: 'short', label: 'Reels / TikTok' },
  { value: 'listing', label: 'Portal listing' },
  { value: 'whatsapp', label: 'WhatsApp' }
];
export const CAPTION_TONES = ['warm', 'bold', 'luxury', 'simple'];
export const CAPTION_CLIPS = [
  { value: '', label: 'Any' }, { value: 'tour', label: 'Walkthrough' },
  { value: 'drone', label: 'Drone' }, { value: 'photos', label: 'Photos' },
  { value: 'twilight', label: 'Twilight' }, { value: 'teaser', label: 'Teaser' },
  { value: 'details', label: 'Details' }
];
export const KINDS = ['house', 'apartment', 'townhouse', 'plot', 'commercial'];
export const ROOM_PRESETS = ['Exterior', 'Entrance', 'Lounge', 'Dining', 'Kitchen', 'Bedroom', 'Bathroom',
  'Study', 'Patio', 'Garden', 'Pool', 'Garage', 'View', 'Aerial', 'Twilight'];

/* ----------------------------------------------------------------- helpers */

/** The last segment of a folder path, for display. */
export const folderName = (p) => String(p || '').replace(/\\/g, '/').replace(/\/$/, '').split('/').pop() || p;

/** The client-facing link: /media/s/<token> (Zerko's own "/s/…" is the React app's). */
export const deliveryLink = (d) => `${location.origin}/media/s/${d.token}`;

/** Today as YYYY-MM-DD in local time (not UTC — a 1am booking is still today). */
export function isoDay(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** "2026-09-26" → a Date at local midnight. */
export const parseDay = (s) => {
  const [y, m, d] = String(s).slice(0, 10).split('-').map(Number);
  return new Date(y, m - 1, d);
};

export function fmtDay(s, opts = { weekday: 'short', day: 'numeric', month: 'short' }) {
  if (!s) return '';
  try { return parseDay(s).toLocaleDateString('en-ZA', opts); } catch { return s; }
}

export const fmtWhen = (sh) =>
  sh?.shoot_date ? fmtDay(sh.shoot_date) + (sh.shoot_time ? ` · ${sh.shoot_time}` : '') : 'Not booked';

export const fmtRand = (n) => (n == null || n === '' ? '' : 'R ' + Number(n).toLocaleString('en-ZA'));

/** Copy text; falls back to a hidden textarea where the async API is refused. */
export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; }
  catch {
    const ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch { /* give up */ }
    ta.remove();
    return ok;
  }
}

/** Where the work is: the middle of the shoots already on the map. */
export function centreOf(list) {
  const pts = (list || []).filter((s) => s.lat != null && s.lng != null);
  if (!pts.length) return null;
  return {
    lat: pts.reduce((a, s) => a + s.lat, 0) / pts.length,
    lng: pts.reduce((a, s) => a + s.lng, 0) / pts.length
  };
}
