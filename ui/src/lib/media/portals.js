/* Portals (Zerko 1.2 shares) and the "who am I" call the Media pages gate on.

   A portal is one of three kinds: `send` (the client looks, picks, comments,
   downloads), `receive` (the client uploads into an inbox folder of its own),
   or `both`. Links made before kinds existed come back with a kind inferred
   by the backend, so nothing here has to guess.

   The link a client opens is /media/s/<token>, rendered by share_page.py —
   Zerko's own "/s/<token>" is the upstream React route, not ours. */

import { mfetch, mpath, murl, post, del, q, ensureToken, upload } from '$lib/media.js';

/* ------------------------------------------------------------------ me */

let meP = null;
/** { username, role, role_label, capabilities[] } — cached for the page's
    life; roles follow the dashboard's People page and change rarely. */
export function me(fresh = false) {
  if (!meP || fresh) meP = mfetch('/api/me').catch((e) => { meP = null; throw e; });
  return meP;
}
export const can = (who, cap) => !!who?.capabilities?.includes(cap);

export const CAPS = {
  SHARES: 'shares.manage',
  SHOOTS: 'shoots.manage',
  ORGANISE: 'media.organise',
  HARD_DELETE: 'media.harddelete',
  PROXY: 'jobs.proxy',
  ADMIN: 'admin'
};

/* ------------------------------------------------------------- portals */

export const portalLink = (token) => `${location.origin}/media/s/${token}`;

export const portals = {
  list: () => mfetch('/api/shares'),
  create: (body) => post('/api/shares', body),
  /** A send portal that belongs to a shoot (its folder, its address). */
  deliver: (shootId, body) => post(`/api/shoots/${shootId}/deliver`, body),
  edit: (id, body) => mfetch(`/api/shares/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  revoke: (id) => del(`/api/shares/${id}`),
  selects: (id) => mfetch(`/api/shares/${id}/selects`),
  activity: (id) => mfetch(`/api/shares/${id}/activity`),
  intake: (id) => mfetch(`/api/shares/${id}/intake`),
  fileIntake: (id, body) => post(`/api/shares/${id}/intake/file`, body),
  fcpxmlUrl: (id) => murl(`/api/shares/${id}/export.fcpxml`),
  csvUrl: (id) => murl(`/api/shares/${id}/export.csv`),

  /* Proofing pins live on the public route; staff read them with
     ?preview=<own token>, which gets past a client password and counts
     nothing as a view. */
  async pins(token) {
    const t = await ensureToken();
    const res = await fetch(mpath(`/api/public/share/${encodeURIComponent(token)}/pins`) + q({ preview: t }));
    if (!res.ok) throw new Error(`Could not load pins (HTTP ${res.status})`);
    return res.json();
  },
  /** The client's view of a portal (file list etc.), as staff: counts nothing. */
  async preview(token) {
    const t = await ensureToken();
    const res = await fetch(mpath(`/api/public/share/${encodeURIComponent(token)}`) + q({ preview: t }));
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },
  resolvePin: (pinId, resolved) =>
    mfetch(`/api/proofing/pins/${pinId}`, { method: 'PATCH', body: JSON.stringify({ resolved }) }),

  watermarks: () => mfetch('/api/photo-edit/watermarks'),
  /** Add a logo (PNG, for the transparency). Returns { name, index, count }. */
  addWatermark: (file) => upload('/api/photo-edit/watermarks', {}, file).promise,
  shoots: () => mfetch('/api/shoots')
};

/* Plain English for the kinds, used by the form and the cards. */
export const KINDS = [
  { value: 'send', label: 'Send', icon: 'send',
    hint: 'The client watches, picks favourites, leaves notes and downloads.' },
  { value: 'receive', label: 'Receive', icon: 'inbox',
    hint: 'The client uploads files into an inbox of their own. They see nothing of the library.' },
  { value: 'both', label: 'Both', icon: 'layers',
    hint: 'The client sees what you sent and can send files back.' }
];
export const kindOf = (s) => s?.kind || (s?.allow_upload ? 'both' : 'send');

/** Zerko stamps naive UTC ("2026-09-24T20:00:11"); read it as UTC and show
    it in the viewer's own time. */
export function when(iso) {
  if (!iso) return '';
  const d = new Date(/Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z');
  if (isNaN(d)) return String(iso).slice(0, 16).replace('T', ' ');
  return d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}
export const day = (iso) => (iso ? String(iso).slice(0, 10) : '');
