/* Thin JSON client for the Flask API. Same-origin in production; the Vite
   dev server proxies /api to :5051. */

async function handle(res) {
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON error body */ }
  if (!res.ok) {
    const msg = (body && (body.message || body.error)) || `HTTP ${res.status}`;
    const err = new Error(msg);
    err.code = body && body.error;
    err.status = res.status;
    throw err;
  }
  return body;
}

export const get = (url) => fetch(url).then(handle);
const send = (method) => (url, body) =>
  fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body)
  }).then(handle);
export const patch = send('PATCH');
export const del = send('DELETE');

export const post = (url, body) =>
  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {})
  }).then(handle);

export const api = {
  config: () => get('/api/config'),
  prospects: (sole) => get('/api/prospects' + (sole ? '?sole=1' : '')),
  stats: () => get('/api/stats'),
  status: () => get('/api/status'),
  erfBusy: () => get('/api/erf/busy'),
  mapPoints: (sole) => get('/api/map' + (sole ? '?sole=1' : '')),
  row: (ident) => get('/api/row/' + encodeURIComponent(ident)),
  find: (brief, sole) => post('/api/find', { brief, sole: !!sole }),

  scrape: (payload) => post('/api/scrape', payload),
  stop: () => post('/api/stop'),
  rescore: (useAi) => post('/api/rescore', { use_ai: useAi }),
  erfResolve: (force) => post('/api/erf/resolve', { force }),
  erfLocate: (key) => post('/api/erf/locate', { listing_key: key }),
  erfConfirm: (key, erf) => post('/api/erf/confirm', { listing_key: key, erf }),
  reevaluate: (key) => post('/api/listing/reevaluate', { listing_key: key }),
  deed: (gid) => post('/api/deed/' + encodeURIComponent(gid)),
  owner: (gid) => get('/api/owner/' + encodeURIComponent(gid)),

  /* ---- management panel */
  panelMeta: () => get('/api/panel/meta'),
  panelStats: () => get('/api/panel/stats'),
  tracked: (q = '') => get('/api/tracked' + q),
  trackedIds: () => get('/api/tracked/ids'),
  trackedOne: (gid) => get('/api/tracked/' + encodeURIComponent(gid)),
  track: (gid, extra = {}) => post('/api/tracked', { group_id: String(gid), ...extra }),
  updateTracked: (gid, body) => patch('/api/tracked/' + encodeURIComponent(gid), body),
  untrack: (gid) => del('/api/tracked/' + encodeURIComponent(gid)),
  child: {
    list: (gid, kind) => get(`/api/tracked/${encodeURIComponent(gid)}/${kind}`),
    add: (gid, kind, body) => post(`/api/tracked/${encodeURIComponent(gid)}/${kind}`, body),
    update: (gid, kind, id, body) => patch(`/api/tracked/${encodeURIComponent(gid)}/${kind}/${id}`, body),
    remove: (gid, kind, id) => del(`/api/tracked/${encodeURIComponent(gid)}/${kind}/${id}`)
  },
  tasks: (due = 'open') => get('/api/tasks?due=' + due),
  panelToday: () => get('/api/panel/today'),
  contacts: (q = '') => get('/api/contacts' + (q ? '?q=' + encodeURIComponent(q) : '')),
  contact: (id) => get('/api/contacts/' + id),
  updateContact: (id, body) => patch('/api/contacts/' + id, body),
  snooze: (id, days) => post(`/api/tasks/${id}/snooze`, { days }),
  taskDone: (id, done = true) => post(`/api/tasks/${id}/done`, { done })
};
