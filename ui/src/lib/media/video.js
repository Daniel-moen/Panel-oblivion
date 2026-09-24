/* The video editor and sub-clips — API client and the timeline maths.

   Backend: zerko/video_edit.py (/api/video-projects, /api/video-edit,
   /api/video-render) and zerko/subclips.py (/api/subclips, /api/cuts).
   The layout maths below mirrors video_edit.layout()/trans_after() exactly —
   the preview, the ruler and the render all have to agree on where a clip
   starts, or a transition eats a different amount on screen than in the file.

   Downloads (render, pack, FCPXML, cuts, sub-clip files) are browser-opened
   links that carry ?token= — built with murl after ensureToken(), because
   murl only adds a token once one has been minted. */
import { mfetch, murl, post, put, del, q, ensureToken, upload } from '$lib/media.js';

/* ------------------------------------------------------------------ model */

export const ASPECTS = ['9:16', '4:5', '1:1', '16:9'];
export const ASPECT_WH = { '9:16': [9, 16], '4:5': [4, 5], '1:1': [1, 1], '16:9': [16, 9] };

export const TRANSITIONS = [
  { value: 'cut', label: 'Cut' },
  { value: 'fade', label: 'Cross-fade' },
  { value: 'fadeblack', label: 'Dip to black' },
  { value: 'fadewhite', label: 'Dip to white' },
  { value: 'wipeleft', label: 'Wipe left' },
  { value: 'wiperight', label: 'Wipe right' },
  { value: 'slideleft', label: 'Slide left' },
  { value: 'slideright', label: 'Slide right' },
  { value: 'zoomin', label: 'Zoom in' }
];
const TRANS_SET = new Set(TRANSITIONS.map((t) => t.value));

export const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4];

export const clipLen = (c) => Math.max(0.04, (c.src_out - c.src_in) / Math.max(0.1, c.speed || 1));

export function transAfter(p, i) {
  if (i >= p.clips.length - 1) return 0;
  const c = p.clips[i];
  if (c.trans === 'cut' || !TRANS_SET.has(c.trans)) return 0;
  return Math.max(0, Math.min(c.trans_dur, clipLen(c) / 2, clipLen(p.clips[i + 1]) / 2));
}

/** [{start, len}] per clip and the total — video_edit.layout(). */
export function layout(p) {
  const out = [];
  let t = 0;
  (p?.clips || []).forEach((c, i) => {
    const L = clipLen(c);
    out.push({ start: t, len: L });
    t += L - transAfter(p, i);
  });
  const total = out.length ? out[out.length - 1].start + out[out.length - 1].len : 0;
  return { items: out, total };
}

export const freshId = () =>
  Array.from(crypto.getRandomValues(new Uint8Array(5)), (b) => b.toString(16).padStart(2, '0')).join('');

/** A new timeline clip, shaped like video_edit.Clip. */
export const newClip = (video_id, dur, a = 0, b = null) => ({
  id: freshId(), video_id, src_in: a, src_out: b ?? Math.max(0.1, dur || 5),
  speed: 1, volume: 1, mute: false, fade_in: 0, fade_out: 0,
  trans: 'cut', trans_dur: 0.5,
  frame: { mode: 'fill', x: 0.5, y: 0.5, zoom: 1 },
  grade: null
});

export const FLAT_GRADE = {
  exposure: 0, contrast: 0, highlights: 0, shadows: 0, temp: 0, tint: 0, saturation: 0, lut: '', lut_mix: 1
};

/** "1:02.40" — a timecode with hundredths, for in/out points. */
export function tc(sec) {
  sec = Math.max(0, Number(sec) || 0);
  const m = Math.floor(sec / 60);
  const s = sec - m * 60;
  const h = Math.floor(m / 60);
  const ss = s.toFixed(2).padStart(5, '0');
  return h ? `${h}:${String(m % 60).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

/* -------------------------------------------------------------------- api */

const patch = (p, body) => mfetch(p, { method: 'PATCH', body: JSON.stringify(body ?? {}) });

export const vapi = {
  me: () => mfetch('/api/me'),

  /* projects */
  projects: () => mfetch('/api/video-projects'),
  project: (id) => mfetch(`/api/video-projects/${id}`),
  create: (body) => post('/api/video-projects', body),
  save: (id, body) => put(`/api/video-projects/${id}`, body),
  remove: (id) => del(`/api/video-projects/${id}`),
  duplicate: (id) => post(`/api/video-projects/${id}/duplicate`),

  /* what the timeline draws */
  probe: (vid) => mfetch(`/api/video-edit/probe/${vid}`),
  frameUrl: (vid, t = 0, w = 160) => murl(`/api/video-edit/frame/${vid}`, { t: (Math.round(t * 10) / 10).toFixed(1), w }),
  luts: () => mfetch('/api/video-edit/luts'),
  uploadLut: (file, onProgress) => upload('/api/video-edit/luts', {}, file, onProgress),

  /* outputs */
  render: (id, body) => post(`/api/video-projects/${id}/render`, body),
  pack: (id, proxies = false) => post(`/api/video-projects/${id}/pack`, { proxies }),
  job: (job) => mfetch(`/api/video-render/${job}`),
  cancel: (job) => post(`/api/video-render/${job}/cancel`),
  jobFileUrl: async (job) => { await ensureToken(); return murl(`/api/video-render/${job}/file`); },
  fcpxmlUrl: async (id) => { await ensureToken(); return murl(`/api/video-projects/${id}/fcpxml`); },

  /* library pick list */
  videos: (params) => mfetch('/api/videos' + q(params)),
  video: (id) => mfetch(`/api/videos/${id}`),

  /* sub-clips */
  subclips: (video_id) => mfetch('/api/subclips' + q({ video_id })),
  addSub: (body) => post('/api/subclips', body),
  editSub: (id, body) => patch(`/api/subclips/${id}`, body),
  delSub: (id) => del(`/api/subclips/${id}`),
  exportSub: (id, mode = 'fast') => post(`/api/subclips/${id}/export`, { mode }),
  subFileUrl: async (id) => { await ensureToken(); return murl(`/api/subclips/${id}/file`); },

  /* cuts handed over as a download */
  cuts: (body) => post('/api/cuts/download', body),
  cutsStatus: (job) => mfetch(`/api/cuts/download/${job}`),
  cutsFileUrl: async (job) => { await ensureToken(); return murl(`/api/cuts/download/${job}/file`); }
};

/* --------------------------------------------------------------- helpers */

/** Start a browser download of a same-origin URL without leaving the page. */
export function download(url, name = '') {
  const a = document.createElement('a');
  a.href = url;
  if (name) a.download = name;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/** Poll `fetcher` until `done(result)`; returns a stop function. Backs off
    gently so a long render costs a request every couple of seconds. */
export function poll(fetcher, onUpdate, done, { every = 1200, max = 4000 } = {}) {
  let stopped = false;
  let timer = null;
  let wait = every;
  const tick = async () => {
    if (stopped) return;
    try {
      const r = await fetcher();
      if (stopped) return;
      onUpdate(r, null);
      if (done(r)) return;
    } catch (e) {
      if (stopped) return;
      onUpdate(null, e);
      return;
    }
    wait = Math.min(max, wait * 1.15);
    timer = setTimeout(tick, wait);
  };
  tick();
  return () => { stopped = true; clearTimeout(timer); };
}

/** The user's Zerko capabilities, as a Set. If /api/me can't be read the
    controls stay visible and the backend's own permission check (403 with a
    sentence) has the last word — better than a page of hidden buttons. */
export async function loadCaps() {
  try {
    const me = await vapi.me();
    return new Set(me?.capabilities || []);
  } catch {
    return new Set(['media.read', 'media.download', 'media.upload', 'media.annotate']);
  }
}
