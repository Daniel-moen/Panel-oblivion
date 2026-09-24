/* Client for the media library — the vendored Zerko backend that webapp.py
   mounts at /zerko.

   Two things make this different from api.js. First, every path has to carry
   the mount prefix: the backend returns root-absolute strings of its own
   (`thumbnail_path` comes back as "/thumbnails/ab12.jpg"), and those are
   relative to the mount, not to the site. Second, it wants a bearer token
   where the rest of the dashboard relies on HTTP basic auth — so there is a
   token bootstrap here, minted from the session we already have. Nobody signs
   in twice; /api/media/token turns the basic-auth identity into a JWT. */

export const PREFIX = '/zerko';

/* ------------------------------------------------------------------ token */

let token = null;
let tokenAt = 0;
let inflight = null;
/** The last token-mint failure, so a page can explain itself instead of
    showing an empty library. Plain object, not a rune: this module is a
    `.js` file and stays free of Svelte. media.svelte.js mirrors it into
    reactive state. */
export const bootError = { message: null, status: null };

/* Tokens last 24h server-side; re-mint well inside that so a tab left open
   overnight does not wake up unauthenticated. */
const TOKEN_TTL_MS = 12 * 60 * 60 * 1000;

async function mintToken() {
  const res = await fetch('/api/media/token');
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error((body && body.error) || `HTTP ${res.status}`);
    err.status = res.status;
    err.detail = body;
    throw err;
  }
  token = body.token;
  tokenAt = Date.now();
  return body;
}

/** The bearer token, minted on demand and shared between concurrent callers. */
export async function ensureToken() {
  if (token && Date.now() - tokenAt < TOKEN_TTL_MS) return token;
  if (!inflight) {
    inflight = mintToken()
      .then((b) => { bootError.message = null; bootError.status = null; return b.token; })
      .catch((e) => { bootError.message = e.message; bootError.status = e.status; throw e; })
      .finally(() => { inflight = null; });
  }
  return inflight;
}

/* ------------------------------------------------------------------- urls */

/** A media-backend path turned into one the browser can fetch. */
export const mpath = (p) => PREFIX + (p.startsWith('/') ? p : '/' + p);

/* For <img>, <video> and download links, where no Authorization header can be
   set. Zerko accepts ?token= on exactly the read-only routes that a browser
   opens directly (see current_user_qs upstream); everything that changes
   something goes through mfetch with a real header. */
export function murl(p, params = {}) {
  const u = new URL(mpath(p), window.location.origin);
  for (const [k, v] of Object.entries(params)) if (v != null) u.searchParams.set(k, v);
  if (token) u.searchParams.set('token', token);
  return u.pathname + u.search;
}

/** Poster/thumbnail for a clip; null when it has none yet. */
export const thumbUrl = (v) => (v && v.thumbnail_path ? murl(v.thumbnail_path) : null);

/** The playable stream — the proxy when there is one, else the master. */
export const streamUrl = (v) => murl(`/api/video-proxy/${v.id}`);

/** A browser-viewable copy of a RAW/HEIC still. */
export const photoUrl = (v, w = 1600) => murl(`/api/photo-preview/${v.id}`, { w });

/** Whatever this item is, the thing to put on screen. */
export const posterUrl = (v) =>
  v.media_type === 'photo' ? photoUrl(v, 1200) : thumbUrl(v);

/* ------------------------------------------------------------------ fetch */

async function handle(res) {
  let body = null;
  try { body = await res.json(); } catch { /* streamed or empty */ }
  if (!res.ok) {
    const msg = (body && (body.detail || body.message || body.error)) || `HTTP ${res.status}`;
    const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}

/** Call the media API. Re-mints the token once on a 401 — the usual cause is
    a token that outlived a redeploy, and a silent retry is kinder than
    bouncing someone out of a page mid-scroll. */
export async function mfetch(path, opts = {}, retry = true) {
  const t = await ensureToken();
  const res = await fetch(mpath(path), {
    ...opts,
    headers: {
      ...(opts.body && !(opts.body instanceof FormData)
        ? { 'Content-Type': 'application/json' } : {}),
      ...opts.headers,
      Authorization: 'Bearer ' + t
    }
  });
  if (res.status === 401 && retry) {
    token = null;
    return mfetch(path, opts, false);
  }
  return handle(res);
}

export const q = (params) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {}))
    if (v != null && v !== '' && v !== 'all') u.set(k, v);
  const s = u.toString();
  return s ? '?' + s : '';
};

export const post = (p, body) => mfetch(p, { method: 'POST', body: JSON.stringify(body ?? {}) });
export const put = (p, body) => mfetch(p, { method: 'PUT', body: JSON.stringify(body ?? {}) });
export const del = (p) => mfetch(p, { method: 'DELETE' });

/* ------------------------------------------------------------------- api */

export const media = {
  /* ---- is any of this even available */
  status: () => fetch('/api/media/status').then(handle),

  /* ---- library */
  stats: () => mfetch('/api/stats'),
  serverStats: () => mfetch('/api/server-stats'),
  storage: () => mfetch('/api/storage/breakdown'),
  videos: (params) => mfetch('/api/videos' + q(params)),
  video: (id) => mfetch(`/api/videos/${id}`),
  folders: () => mfetch('/api/folders'),
  folderTree: () => mfetch('/api/folders/tree'),
  createFolder: (name, parent_id) => post('/api/folders', { name, parent_id }),
  renameFolder: (id, name) => put(`/api/folders/${id}`, { name }),

  /* ---- one clip */
  rename: (id, name) => post(`/api/videos/${id}/rename`, { name }),
  rate: (id, rating) => post(`/api/videos/${id}/rating`, { rating }),
  setStatus: (id, status) => post(`/api/videos/${id}/status`, { status }),
  setTags: (id, tag_ids) => post(`/api/videos/${id}/tags`, { tag_ids }),
  untag: (id, tagId) => del(`/api/videos/${id}/tags/${tagId}`),
  move: (id, folder_id) => post(`/api/videos/${id}/folder`, { folder_id }),
  /* delete_file=true is the real trash move; without it upstream only drops
     the catalogue row and the next rescan brings the file back. */
  remove: (id, permanent = false) => del(`/api/videos/${id}?delete_file=true${permanent ? '&permanent=true' : ''}`),
  bulk: (body) => post('/api/videos/bulk', body),
  notes: (id) => mfetch(`/api/videos/${id}/notes`),
  addNote: (id, content) => post(`/api/videos/${id}/notes`, { content }),
  delNote: (nid) => del(`/api/notes/${nid}`),
  suggestTags: (id) => mfetch(`/api/videos/${id}/suggest-tags`),

  /* ---- search */
  transcriptSearch: (s) => mfetch('/api/videos/transcript-search' + q({ q: s })),

  /* ---- tags */
  tags: () => mfetch('/api/tags'),
  tagTree: () => mfetch('/api/tags/tree'),
  tagOverview: () => mfetch('/api/tags/overview'),
  createTag: (name, parent_id) => post('/api/tags', { name, parent_id }),
  deleteTag: (id) => del(`/api/tags/${id}`),
  autoTag: (include_transcripts = true) => post('/api/tags/auto-generate', { include_transcripts }),

  /* ---- duplicates */
  duplicates: () => mfetch('/api/duplicates'),
  duplicateScan: () => post('/api/duplicates/scan'),
  duplicatePreview: (body) => post('/api/duplicates/preview', body),
  duplicateResolve: (body) => post('/api/duplicates/resolve', body),

  /* ---- jobs */
  jobs: () => mfetch('/api/videos/jobs/status'),
  clearJobs: () => post('/api/videos/jobs/clear'),
  rescan: () => post('/api/rescan'),
  rescanStatus: () => mfetch('/api/rescan/status'),
  proxyStatus: () => mfetch('/api/proxies/status'),
  generateProxies: () => post('/api/proxies/generate-missing'),
  cancelProxies: () => post('/api/proxies/cancel'),
  repairThumbs: () => post('/api/thumbnails/repair'),
  transcribe: (id) => post(`/api/videos/${id}/transcribe`),

  /* ---- shares */
  shares: () => mfetch('/api/shares'),
  createShare: (body) => post('/api/shares', body),
  revokeShare: (id) => del(`/api/shares/${id}`),
  shareSelects: (id) => mfetch(`/api/shares/${id}/selects`),
  /* The owner-side exports are downloads, so they go through murl. */
  fcpxmlUrl: (id) => murl(`/api/shares/${id}/export.fcpxml`),
  csvUrl: (id) => murl(`/api/shares/${id}/export.csv`),

  /* ---- who am I: role + capability list, for hiding what the role can't do */
  me: () => mfetch('/api/me'),

  /* ---- colour labels (Lightroom-style). There is no single-clip route:
     the bulk action is the one writer, so one clip is a bulk of one.
     label null clears it. */
  label: (video_ids, label) => post('/api/videos/bulk', { action: 'label', video_ids, label }),

  /* ---- trash. DELETE without delete_file removes the catalogue row only
     (the next rescan brings it back); delete_file=true is the reversible
     move into _Trash that the Trash view lists. */
  trashOne: (id) => del(`/api/videos/${id}?delete_file=true`),
  trashMany: (video_ids) => post('/api/videos/bulk', { action: 'delete', video_ids }),
  trash: () => mfetch('/api/trash'),
  restore: (id) => post(`/api/videos/${id}/restore`),
  restoreAll: () => post('/api/trash/restore-all'),
  emptyTrash: () => post('/api/trash/empty'),
  trashSettings: (auto_days) => post('/api/trash/settings', { auto_days }),

  /* ---- virtual copies of a photo (photo_edit.py) */
  copies: (id) => mfetch(`/api/photo-edit/${id}/copies`),
  newCopy: (id, name, recipe) => post(`/api/photo-edit/${id}/copies`, { name, recipe }),
  renameCopy: (id, copyId, name) =>
    mfetch(`/api/photo-edit/${id}/copies/${copyId}`, { method: 'PATCH', body: JSON.stringify({ name }) }),
  delCopy: (id, copyId) => del(`/api/photo-edit/${id}/copies/${copyId}`),

  /* ---- the bell */
  activity: () => mfetch('/api/activity'),
  activitySeen: () => post('/api/activity/seen'),

  /* ---- projects: a folder per shoot with numbered stage folders */
  projects: () => mfetch('/api/projects'),
  createProject: (body) => post('/api/projects', body),
  bringIn: (id, video_ids, stage = 'originals', move_files = true) =>
    post(`/api/projects/${id}/bring-in`, { video_ids, stage, move_files }),
  forgetProject: (id) => del(`/api/projects/${id}`),

  /* ---- copy/paste and zip download */
  copyTo: (video_ids, folder_id) => post('/api/videos/copy', { video_ids, folder_id }),
  zipUrl: (ids) => murl('/api/download-zip', { ids: ids.join(',') }),
  fileUrl: (id) => murl(`/api/video-file/${id}`),

  /* ---- the general file store */
  files: {
    list: (path = '') => mfetch('/api/files/list' + q({ path })),
    tree: (path = '') => mfetch('/api/files/tree' + q({ path })),
    search: (s, path = '') => mfetch('/api/files/search' + q({ q: s, path })),
    recent: () => mfetch('/api/files/recent'),
    starred: () => mfetch('/api/files/starred'),
    usage: () => mfetch('/api/files/usage'),
    mkdir: (dir, name) => post('/api/files/mkdir', { dir, name }),
    rename: (path, name) => post('/api/files/rename', { path, name }),
    move: (paths, dest, mode = 'move') => post('/api/files/move', { paths, dest, mode }),
    remove: (paths) => post('/api/files/delete', { paths }),
    star: (path, starred) => post('/api/files/star', { path, starred }),
    trash: () => mfetch('/api/files/trash'),
    restore: (ids) => post('/api/files/trash/restore', { ids }),
    emptyTrash: () => post('/api/files/trash/empty'),
    shares: () => mfetch('/api/files/shares'),
    share: (path, expires_days) => post('/api/files/shares', { path, expires_days }),
    revoke: (id) => del(`/api/files/shares/${id}`),
    downloadUrl: (path) => murl('/api/files/download', { path }),
    zipUrl: (paths) => {
      const u = new URLSearchParams();
      for (const p of paths) u.append('path', p);
      if (token) u.set('token', token);
      return mpath('/api/files/zip') + '?' + u.toString();
    },
    thumbUrl: (path, w = 360) => murl('/api/files/thumb', { path, w })
  }
};

/* ------------------------------------------------------------- uploading */

/* XHR rather than fetch: upload progress events are the whole point, and the
   drop zone shows a ring per file. Returns a handle with .promise and
   .abort() so a page can cancel a queue. */
export function upload(path, fields, file, onProgress) {
  const xhr = new XMLHttpRequest();
  const promise = ensureToken().then((t) => new Promise((resolve, reject) => {
    const form = new FormData();
    for (const [k, v] of Object.entries(fields || {})) if (v != null) form.append(k, v);
    form.append('file', file, file.name);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total, e.loaded, e.total);
    };
    xhr.onload = () => {
      let body = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* not json */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else {
        const err = new Error((body && (body.detail || body.error)) || `HTTP ${xhr.status}`);
        err.status = xhr.status;
        reject(err);
      }
    };
    xhr.onerror = () => reject(new Error('The upload did not reach the server.'));
    xhr.onabort = () => reject(Object.assign(new Error('Upload cancelled'), { aborted: true }));
    xhr.open('POST', mpath(path));
    xhr.setRequestHeader('Authorization', 'Bearer ' + t);
    xhr.send(form);
  }));
  return { promise, abort: () => xhr.abort() };
}

/** Upload into the media library — a plain multipart POST (/api/upload). */
export const uploadMedia = (file, folderId, onProgress) =>
  upload('/api/upload', { folder_id: folderId }, file, onProgress);

/** Upload into the general file store.

    The file store has no single-shot endpoint: it takes an init/chunk/complete
    handshake so a dropped connection resumes from the byte the server actually
    has rather than starting a 4 GB file again. The upload id is derived
    server-side from who/where/what/how-big, so picking the same file after a
    closed tab finds the half that already arrived.

    Progress is reported per chunk (8 MB by default), so a small document
    jumps straight to 100% — which is honest: it arrived in one piece. */
export function uploadFile(file, dir, onProgress) {
  let cancelled = false;

  const promise = (async () => {
    const t = await ensureToken();
    const init = await mfetch('/api/files/upload/init', {
      method: 'POST',
      body: JSON.stringify({
        dir,
        name: file.name,
        size: file.size,
        mtime: file.lastModified || null,
        relative_path: file.webkitRelativePath || null,
        conflict: 'rename'
      })
    });

    const chunkSize = init.chunk_size || 8 * 1024 * 1024;
    let offset = init.offset || 0;
    if (offset) onProgress?.(offset / file.size, offset, file.size);

    while (offset < file.size) {
      if (cancelled) throw Object.assign(new Error('Upload cancelled'), { aborted: true });
      const end = Math.min(file.size, offset + chunkSize);
      const res = await fetch(mpath(`/api/files/upload/${init.upload_id}?offset=${offset}`), {
        method: 'PUT',
        headers: { Authorization: 'Bearer ' + t },
        body: file.slice(offset, end)
      });
      if (res.status === 409) {
        // The server is at a different byte than we thought; follow it.
        const b = await res.json().catch(() => ({}));
        if (typeof b.expected !== 'number') throw new Error('Upload fell out of step.');
        offset = b.expected;
        continue;
      }
      if (!res.ok) {
        const b = await res.json().catch(() => null);
        throw new Error((b && (b.detail || b.error)) || `HTTP ${res.status}`);
      }
      const b = await res.json();
      offset = b.offset;
      onProgress?.(offset / file.size, offset, file.size);
    }

    return mfetch(`/api/files/upload/${init.upload_id}/complete`, { method: 'POST' });
  })();

  return { promise, abort: () => { cancelled = true; } };
}

/* ------------------------------------------------------------- formatting */

export function fmtDuration(s) {
  if (s == null) return '';
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  const p = (n) => String(n).padStart(2, '0');
  return h ? `${h}:${p(m)}:${p(x)}` : `${m}:${p(x)}`;
}

export function fmtBytes(n) {
  if (!n) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  const v = n / 1024 ** i;
  return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${u[i]}`;
}

/** "4 hours of footage" reads better than a duration on the dashboard. */
export function fmtHours(seconds) {
  if (!seconds) return '0';
  const h = seconds / 3600;
  return h >= 10 ? Math.round(h).toString() : h.toFixed(1).replace(/\.0$/, '');
}
