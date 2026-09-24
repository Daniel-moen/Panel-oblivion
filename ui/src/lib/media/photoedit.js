/* The photo editor's API client and the few pieces of maths the page needs.

   Everything renders on the server: the recipe (a flat JSON of slider values,
   plus lists of masks, remove patches and heal spots) is saved to
   /api/photo-edit/{id}, and /developed hands back that saved recipe applied
   to a bounded copy of the photo. The page saves on a debounce and then asks
   for the developed JPEG, cache-busted by a hash of what it just saved.

   Virtual copies (Zerko 1.3) are other recipes for the same file: the same
   endpoints with ?copy=<id>. */

import { mfetch, murl, post, del, q, mpath, ensureToken, upload } from '$lib/media.js';

/* ---------------------------------------------------------------- recipe */

/* Recipe() as the backend dumps it (zerko/photo_edit.py). A photo nobody has
   touched comes back as {}; merging over this gives every slider a value. */
export const DEFAULTS = Object.freeze({
  exposure: 0, contrast: 0, highlights: 0, shadows: 0, whites: 0, blacks: 0,
  temp_k: 6500, tint: 0, saturation: 0, vibrance: 0,
  sat_red: 0, sat_orange: 0, sat_yellow: 0, sat_green: 0, sat_aqua: 0, sat_blue: 0, sat_purple: 0, sat_magenta: 0,
  hue_red: 0, hue_orange: 0, hue_yellow: 0, hue_green: 0, hue_aqua: 0, hue_blue: 0, hue_purple: 0, hue_magenta: 0,
  lum_red: 0, lum_orange: 0, lum_yellow: 0, lum_green: 0, lum_aqua: 0, lum_blue: 0, lum_purple: 0, lum_magenta: 0,
  grade_sh_hue: 220, grade_sh_sat: 0, grade_mid_hue: 40, grade_mid_sat: 0, grade_hi_hue: 45, grade_hi_sat: 0, grade_balance: 0,
  pw_lift_hue: 0, pw_lift_sat: 0, pw_lift_y: 0, pw_gamma_hue: 0, pw_gamma_sat: 0, pw_gamma_y: 0,
  pw_gain_hue: 0, pw_gain_sat: 0, pw_gain_y: 0, pw_offset_hue: 0, pw_offset_sat: 0, pw_offset_y: 0,
  wm_index: 0, wm_opacity: 0, wm_scale: 0.22, wm_position: 8, wm_margin: 0.03,
  sharpen: 0, r_gain: 1, g_gain: 1, b_gain: 1, r_lift: 0, g_lift: 0, b_lift: 0,
  defringe: 0, clarity: 0, dehaze: 0,
  curve: [[0, 0], [1, 1]], curve_r: [[0, 0], [1, 1]], curve_g: [[0, 0], [1, 1]], curve_b: [[0, 0], [1, 1]],
  dn_luma: 0, dn_colour: 0, dn_shadows: 0,
  distortion: 0, distortion2: 0, ca_r: 0, ca_b: 0, persp_v: 0, persp_h: 0,
  straighten: 0, geo_scale: 1, rotate: 0, flip_h: false, flip_v: false,
  crop: [0, 0, 1, 1],
  masks: [], slices: [],
  vignette: 0, vig_mid: 0.5, vig_feather: 0.5, vig_round: 0, grain: 0, grain_size: 0.3,
  lens_vig: 0, lens_vig_k: [0, 0, 0, 0, 0],
  spots: [], removes: [], fixes: {},
  gen_ref: '', gen_amount: 1, gen_look: '', gen_geo: ''
});

/* Mask() — one local adjustment (photo_edit.py › Mask). */
export const MASK_DEFAULTS = Object.freeze({
  kind: 'radial', ref: '', cx: 0.5, cy: 0.5, rx: 0.3, ry: 0.3, angle: 0, feather: 0.5, invert: false,
  amount: 1, enabled: true, name: '', part2: null,
  exposure: 0, contrast: 0, highlights: 0, shadows: 0, whites: 0, blacks: 0, saturation: 0,
  temp_shift: 0, tint_shift: 0, clarity: 0,
  range_lo: 0, range_hi: 1, range_soft: 0.1, hue_on: false, hue: 0, hue_width: 30, hue_soft: 25, sat_lo: 0
});

const clone = (x) => JSON.parse(JSON.stringify(x));

/** A full recipe from whatever the server sent (possibly {}). */
export const fullRecipe = (r) => ({ ...clone(DEFAULTS), ...clone(r || {}) });

/** Only the keys the backend's Recipe model knows — /auto and presets can
    carry extras, and a stray key is harmless but noisy. */
export function cleanRecipe(r) {
  const out = {};
  for (const k of Object.keys(DEFAULTS)) out[k] = r[k] === undefined ? clone(DEFAULTS[k]) : r[k];
  return out;
}

/** Fields that belong to one photo and never travel with a look. */
export const OWN_FIELDS = ['spots', 'removes', 'gen_ref', 'gen_amount', 'gen_look', 'gen_geo', 'fixes', 'lens_vig_k'];

/** Lay a look (preset, snapshot from elsewhere) over this photo's recipe:
    painted things stay this photo's own. */
export function applyLook(current, look) {
  const next = { ...fullRecipe(look) };
  for (const k of OWN_FIELDS) next[k] = clone(current[k] ?? DEFAULTS[k]);
  const ownBrushes = (current.masks || []).filter((m) => m.kind === 'brush');
  const portable = (look.masks || []).filter((m) => m.kind !== 'brush');
  next.masks = [...portable, ...ownBrushes];
  return next;
}

/** A short stable hash — the cache-buster on /developed. */
export function hash(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0).toString(36);
}

export const isDefault = (r, k) => JSON.stringify(r[k]) === JSON.stringify(DEFAULTS[k]);

/** Groups for "copy settings to other photos" (/api/photo-presets/sync keys). */
export const SYNC_GROUPS = [
  { id: 'light', label: 'Light', keys: ['exposure', 'contrast', 'highlights', 'shadows', 'whites', 'blacks', 'curve', 'curve_r', 'curve_g', 'curve_b'] },
  { id: 'wb', label: 'White balance', keys: ['temp_k', 'tint'] },
  { id: 'colour', label: 'Colour', keys: ['saturation', 'vibrance',
      ...['red', 'orange', 'yellow', 'green', 'aqua', 'blue', 'purple', 'magenta'].flatMap((b) => [`sat_${b}`, `hue_${b}`, `lum_${b}`]),
      'grade_sh_hue', 'grade_sh_sat', 'grade_mid_hue', 'grade_mid_sat', 'grade_hi_hue', 'grade_hi_sat', 'grade_balance',
      'r_gain', 'g_gain', 'b_gain', 'r_lift', 'g_lift', 'b_lift', 'slices'] },
  { id: 'detail', label: 'Detail', keys: ['sharpen', 'clarity', 'dehaze', 'defringe', 'dn_luma', 'dn_colour', 'dn_shadows'] },
  { id: 'lens', label: 'Lens', keys: ['distortion', 'distortion2', 'ca_r', 'ca_b', 'lens_vig'] },
  { id: 'geometry', label: 'Straighten & crop', keys: ['persp_v', 'persp_h', 'straighten', 'geo_scale', 'rotate', 'flip_h', 'flip_v', 'crop'] },
  { id: 'effects', label: 'Vignette & grain', keys: ['vignette', 'vig_mid', 'vig_feather', 'vig_round', 'grain', 'grain_size'] },
  { id: 'masks', label: 'Mask shapes', keys: ['masks'] },
  { id: 'wm', label: 'Watermark', keys: ['wm_index', 'wm_opacity', 'wm_scale', 'wm_position', 'wm_margin'] }
];

/* ----------------------------------------------------------- geometry maths */

const CA_UNIT = 0.003;
export { CA_UNIT };

/** Where a point of the displayed (developed) frame comes from in the source
    photo, both in 0..1. A port of source_uv() in photo_edit.py: the Remove
    tool, AI click-select and the 100% loupe all work in SOURCE space, while
    you point at the developed frame. `aspect` is the source's w / h. */
export function sourceUV(u, v, r, aspect) {
  const [cx, cy, cw, ch] = [...(r.crop || []), 0, 0, 1, 1].slice(0, 4);
  let x = (cx + u * cw - 0.5) * aspect;
  let y = cy + v * ch - 0.5;
  if (r.flip_h) x = -x;
  if (r.flip_v) y = -y;
  if (r.rotate) {
    const t = (r.rotate * Math.PI) / 180, c = Math.cos(t), s = Math.sin(t);
    [x, y] = [x * c - y * s, x * s + y * c];
  }
  const sc = Math.max(1e-6, r.geo_scale || 1);
  x /= sc; y /= sc;
  if (r.straighten) {
    const t = (r.straighten * Math.PI) / 180, c = Math.cos(t), s = Math.sin(t);
    [x, y] = [x * c - y * s, x * s + y * c];
  }
  if (r.persp_v || r.persp_h) {
    let d = 1 + (r.persp_v || 0) * y + (r.persp_h || 0) * x;
    if (Math.abs(d) < 1e-3) d = Math.sign(d || 1) * 1e-3;
    x /= d; y /= d;
  }
  if (r.distortion || r.distortion2) {
    const r2 = x * x + y * y;
    const f = 1 + (r.distortion || 0) * r2 + (r.distortion2 || 0) * r2 * r2;
    x *= f; y *= f;
  }
  return [x / aspect + 0.5, y + 0.5];
}

/** How many source widths one displayed width spans (for brush radii). */
export const displayToSourceScale = (r) => ((r.crop?.[2] ?? 1) / Math.max(1e-6, r.geo_scale || 1));

/* -------------------------------------------------------------------- urls */

/** The saved edit, developed on the server. `v` only busts the cache. */
export const developedUrl = (id, { w = 1600, copy = null, v = null } = {}) =>
  murl(`/api/photo-edit/${id}/developed`, { w, copy: copy || null, v });

/** The photo as shot (no develop, no geometry). */
export const baseUrl = (id, w = 1600) => murl(`/api/photo-edit/${id}/base`, { w });

/** A 100% crop of the original around (x, y), 0..1 of the source. */
export const tileUrl = (id, { x, y, zoom, w = 600 }) =>
  murl(`/api/photo-edit/${id}/tile`, { x: x.toFixed(4), y: y.toFixed(4), zoom: zoom.toFixed(3), w });

/** A stored brush mask (greyscale PNG) by its ref "<video>/<name>". */
export const maskUrl = (ref) => {
  const [vid, name] = String(ref).split('/');
  return murl(`/api/photo-edit/${vid}/masks/${name}`);
};

/* --------------------------------------------------------------------- api */

const cq = (copy) => (copy ? q({ copy }) : '');

export const pe = {
  me: () => mfetch('/api/me'),
  video: (id) => mfetch(`/api/videos/${id}`),
  photos: (params = {}) => mfetch('/api/videos' + q({ media_type: 'photo', sort_by: 'date', sort_order: 'desc', ...params })),

  /* recipe */
  get: (id, copy) => mfetch(`/api/photo-edit/${id}${cq(copy)}`),
  save: (id, recipe, copy) => post(`/api/photo-edit/${id}${cq(copy)}`, recipe),
  clear: (id) => del(`/api/photo-edit/${id}`),
  auto: (id) => mfetch(`/api/photo-edit/${id}/auto`),
  size: (id) => mfetch(`/api/photo-edit/${id}/size`),

  /* geometry */
  upright: (id, mode, r) => mfetch(`/api/photo-edit/${id}/upright` + q({
    mode, distortion: r.distortion || 0, distortion2: r.distortion2 || 0, rotate: r.rotate || 0 })),
  lens: (id) => mfetch(`/api/photo-edit/${id}/lens`),

  /* virtual copies */
  copies: (id) => mfetch(`/api/photo-edit/${id}/copies`),
  newCopy: (id, name, recipe) => post(`/api/photo-edit/${id}/copies`, { name, recipe }),
  renameCopy: (id, cid, name) => mfetch(`/api/photo-edit/${id}/copies/${cid}`, { method: 'PATCH', body: JSON.stringify({ name }) }),
  deleteCopy: (id, cid) => del(`/api/photo-edit/${id}/copies/${cid}`),

  /* picks, stars */
  pick: (id, pick) => post(`/api/photo-edit/${id}/pick`, { pick }),
  stars: (id, rating) => post(`/api/photo-edit/${id}/stars`, { rating }),
  edited: (ids) => post('/api/photo-presets/edited', { video_ids: ids }),

  /* snapshots (of the original's edit) */
  snapshots: (id) => mfetch(`/api/photo-edit/${id}/snapshots`),
  addSnapshot: (id, name, recipe) => post(`/api/photo-edit/${id}/snapshots`, { name, recipe }),
  deleteSnapshot: (id, index) => del(`/api/photo-edit/${id}/snapshots/${index}`),

  /* presets */
  presets: () => mfetch('/api/photo-presets'),
  savePreset: (name, recipe) => post('/api/photo-presets', { name, recipe }),
  deletePreset: (pid) => del(`/api/photo-presets/${pid}`),
  presetFor: (pid, id) => mfetch(`/api/photo-presets/${pid}/for/${id}`),
  applyTo: (ids, recipe) => post('/api/photo-presets/apply', { video_ids: ids, recipe }),
  syncTo: (ids, recipe, keys) => post('/api/photo-presets/sync', { video_ids: ids, recipe, keys }),

  /* remove tool (LaMa via onnxruntime, OpenCV quick fill until it is here) */
  removeStatus: () => mfetch('/api/photo-edit/remove/status'),
  removePrepare: () => post('/api/photo-edit/remove/prepare'),
  remove: (id, points, r, removes) => post(`/api/photo-edit/${id}/remove`, { points, r, removes }),

  /* window pull */
  windows: (id, w, h) => post(`/api/photo-edit/${id}/windows`, { w, h }),
  windowPull: (id, mask_ref, from_id, removes) => post(`/api/photo-edit/${id}/window-pull`, { mask_ref, from_id, removes }),

  /* AI selections (Segment Anything via onnxruntime; a 202 while it downloads) */
  aiStatus: () => mfetch('/api/photo-edit/ai/status'),
  select: (id, body) => selectRaw(id, body),

  /* export */
  export: (id, body) => post(`/api/photo-edit/${id}/export`, body),
  batch: (body) => post('/api/photo-edit-batch', body),
  batchStatus: (job) => mfetch(`/api/photo-edit-batch/${job}`),
  batchCancel: (job) => post(`/api/photo-edit-batch/${job}/cancel`),

  /* watermarks */
  watermarks: () => mfetch('/api/photo-edit/watermarks'),
  uploadWatermark: (file) => upload('/api/photo-edit/watermarks', {}, file),
  deleteWatermark: (name) => del(`/api/photo-edit/watermarks/${encodeURIComponent(name)}`)
};

/* /select answers 202 {downloading, done, total} the first time: mfetch
   would hand that back as a plain body, which is fine — but make it explicit
   so the caller can tell "here is your mask" from "ask again". */
async function selectRaw(id, body) {
  const r = await post(`/api/photo-edit/${id}/select`, body);
  return r && r.downloading ? { pending: true, ...r } : r;
}

/** The watermark PNG as an object URL: its route wants a header, not ?token=. */
export async function watermarkBlobUrl(name) {
  const t = await ensureToken();
  const res = await fetch(mpath(`/api/photo-edit/watermarks/${encodeURIComponent(name)}/raw`),
    { headers: { Authorization: 'Bearer ' + t } });
  if (!res.ok) return null;
  return URL.createObjectURL(await res.blob());
}

/* -------------------------------------------------------------- formatting */

export const fmtSigned = (v, d = 2) => (v > 0 ? '+' : '') + Number(v).toFixed(d);
export const pct = (done, total) => (total ? Math.round((100 * done) / total) : 0);
export const fmtMB = (b) => (b / 1048576).toFixed(0) + ' MB';
