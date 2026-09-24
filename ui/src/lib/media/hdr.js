/* HDR & Looks — the API client for /media/hdr.

   Three backends, all under the /zerko mount:
     /api/hdr        bracket finding, the merge engine (HDR fusion, flambient,
                     panorama), a small live preview, RAW decoder state
     /api/ai/image   the studio's Looks (name + instruction + example photos)
                     and whether an image model is configured at all
     /api/ai/photo   painting a Look onto a photo (a job), the painted
                     results kept per photo, room types (Claude)

   Two installers upstream exposes (/api/hdr/raw-support/install and
   /api/ai/image/install) are blocked by the host on purpose; nothing here
   calls them. */

import { mfetch, murl, mpath, post, put, del, ensureToken, upload } from '$lib/media.js';

/* ------------------------------------------------------------------ who */

let meP = null;
/** /api/me — role + capabilities. Cached for the page's life. */
export function me() {
  if (!meP) meP = mfetch('/api/me').catch((e) => { meP = null; throw e; });
  return meP;
}
export const can = (who, cap) => !!who?.capabilities?.includes(cap);

/* ------------------------------------------------------------------ hdr */

/** The defaults of HdrLook (zerko/hdr.py) — the HDR panel's sliders. */
export const HDR_LOOK = Object.freeze({
  method: 'natural', deghost: true, windows: 0.4, exposure: 0, shadows: 0.15,
  contrast: 0.1, saturation: 0.05, detail: 0.2, warmth: 0, noise: 0.4
});

/** The defaults of MergeBody, minus groups/look/flash. */
export const MERGE_DEFAULTS = Object.freeze({
  mode: 'hdr', ambient_mix: 0.45, align: true, max_dim: 6000, fmt: 'jpg',
  quality: 92, subfolder: 'HDR', add_to_library: true, polish: true,
  allow_preview_raw: false, bits16: false
});

export const hdr = {
  /** {groups:[{key, items:[{id, filename, thumbnail_path, taken_at, bias, flash}]}], ungrouped, message} */
  scan: (body) => post('/api/hdr/scan', body),
  /** {job_id, total} */
  merge: (body) => post('/api/hdr/merge', body),
  /** {id, running, done, total, current, results:[{path, filename, frames, id}], errors:[], cancelled} */
  job: (id) => mfetch(`/api/hdr/jobs/${id}`),
  cancel: (id) => post(`/api/hdr/jobs/${id}/cancel`),
  /** {installed, name, offline_wheel?} */
  rawSupport: () => mfetch('/api/hdr/raw-support'),

  /** The set fused with these settings, small — an object URL for an <img>
      (the caller revokes it). POST returning a JPEG, so plain fetch. */
  async preview(ids, look, align = true, size = 1000) {
    const t = await ensureToken();
    const res = await fetch(mpath('/api/hdr/preview'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + t },
      body: JSON.stringify({ ids, look, align, size })
    });
    if (!res.ok) {
      const b = await res.json().catch(() => null);
      throw new Error((b && b.detail) || `HTTP ${res.status}`);
    }
    return URL.createObjectURL(await res.blob());
  }
};

/* ---------------------------------------------------------------- looks */

export const looks = {
  /** {on, backend, name} */
  status: () => mfetch('/api/ai/image/status'),
  /** {looks:[{id, name, prompt, examples:[name], tailor, seed, real}]} */
  list: () => mfetch('/api/ai/image/looks'),
  create: (body) => post('/api/ai/image/looks', body),
  update: (id, body) => put(`/api/ai/image/looks/${id}`, body),
  remove: (id) => del(`/api/ai/image/looks/${id}`),
  order: (ids) => put('/api/ai/image/looks-order', { ids }),
  /** Two examples at most: the newest replaces the oldest. Resolves to the look. */
  addExample: (id, file, onProgress) => upload(`/api/ai/image/looks/${id}/examples`, {}, file, onProgress),
  removeExample: (id, name) => del(`/api/ai/image/looks/${id}/examples/${name}`),
  exampleUrl: (id, name) => murl(`/api/ai/image/looks/${id}/examples/${name}`)
};

/* ------------------------------------------------------------ ai photo */

export const ROOM_TYPES = ['Exterior', 'Aerial', 'Entrance', 'Lounge', 'Dining', 'Kitchen', 'Scullery',
  'Bedroom', 'Bathroom', 'Study', 'Family room', 'Patio', 'Garden', 'Pool', 'Garage', 'Laundry', 'View', 'Detail'];
/** Room types where a dusk shot is the classic hero image. */
export const TWILIGHT_ROOMS = new Set(['Exterior', 'Aerial', 'Patio', 'Garden', 'Pool', 'View', 'Entrance']);

export const aiPhoto = {
  /** Paint a look (or words) onto photos: returns the job {id, state, done, failed, items:[], error}. */
  gen: (body) => post('/api/ai/photo/gen', body),
  job: (id) => mfetch(`/api/ai/photo/jobs/${id}`),
  /** {items:[{video_id, ref, look, look_id, prompt, made, scene, outside}]} newest first */
  gens: (vid) => mfetch(`/api/ai/photo/${vid}/gens`),
  /** Keep a result as one of the look's examples. */
  keepAsExample: (ref, look_id) => post('/api/ai/photo/gen-example', { ref, look_id }),
  /** Claude names the room each photo shows. merge:false = report only. */
  rooms: (video_ids) => post('/api/ai/photo/rooms/sort', { key: 'hdr-looks', video_ids, merge: false })
};

/** The two pictures of a painted result: the edit it came from and the look. */
export function genPics(ref) {
  const [vid, name] = String(ref).split('/');
  return {
    before: murl(`/api/photo-edit/${vid}/masks/${name}d`),
    after: murl(`/api/photo-edit/${vid}/masks/${name}g`)
  };
}

/** Put a painted result onto the photo's saved edit as its look layer. */
export async function applyGen(vid, item, amount = 1) {
  const cur = await mfetch(`/api/photo-edit/${vid}`);
  const recipe = {
    ...(cur?.recipe || {}),
    gen_ref: item.ref,
    gen_amount: amount,
    gen_look: String(item.look || '').slice(0, 80),
    gen_geo: item.geo || ''
  };
  return post(`/api/photo-edit/${vid}`, recipe);
}

/** Take the look layer off the photo's saved edit. */
export async function clearGen(vid) {
  const cur = await mfetch(`/api/photo-edit/${vid}`);
  return post(`/api/photo-edit/${vid}`, { ...(cur?.recipe || {}), gen_ref: '', gen_amount: 1, gen_look: '', gen_geo: '' });
}

/** Current look layer on the photo's saved edit ('' when none). */
export const savedGenRef = (vid) =>
  mfetch(`/api/photo-edit/${vid}`).then((r) => r?.recipe?.gen_ref || '').catch(() => '');

/* ---------------------------------------------------------------- misc */

/** Poll fn every ms until done(result) — returns stop(). */
export function poll(fn, done, onTick, onError, ms = 1500) {
  let stopped = false;
  let timer = null;
  const tick = async () => {
    if (stopped) return;
    try {
      const r = await fn();
      if (stopped) return;
      onTick?.(r);
      if (done(r)) return;
    } catch (e) {
      if (stopped) return;
      onError?.(e);
      return;
    }
    timer = setTimeout(tick, ms);
  };
  tick();
  return () => { stopped = true; clearTimeout(timer); };
}
