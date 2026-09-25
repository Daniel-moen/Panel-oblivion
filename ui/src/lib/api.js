/* Thin JSON client for the Flask API. Same-origin in production; the Vite
   dev server proxies /api to :5051. */

/* Set once we have started leaving for /login, so a page full of pollers all
   401-ing at the same moment navigates once instead of fighting each other. */
let leaving = false;

async function handle(res) {
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON error body */ }
  if (!res.ok) {
    /* The session expired or was revoked while the app was open: every poller
       would otherwise just toast forever. Send the browser to sign in, once,
       and come back to where it was. */
    if (res.status === 401 && body?.error === 'auth_required'
        && typeof location !== 'undefined' && !leaving
        && !location.pathname.startsWith('/login')) {
      leaving = true;
      location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
    }
    /* The server is the only thing that decides what you may do, so a 403
       reaches the UI as a normal outcome, not a crash. Say which privilege
       is missing in words a person can repeat to whoever hands them out. */
    const NEED = {
      crawl: 'run crawls', leads: 'change leads', media: 'use the media library',
      admin: 'manage people'
    };
    const msg = (body?.error === 'forbidden' && body?.need)
      ? `Your account cannot ${NEED[body.need] || body.need}. Ask the owner.`
      : (body && (body.message || body.error)) || `HTTP ${res.status}`;
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
  /* type 'rent' asks for the to-rent book; anything else is the for-sale
     one, which is what every caller got before rentals existed. */
  prospects: (sole, type) => {
    const p = new URLSearchParams();
    if (sole) p.set('sole', '1');
    if (type === 'rent') p.set('type', 'rent');
    const q = p.toString();
    return get('/api/prospects' + (q ? '?' + q : ''));
  },
  /* The list above is slim — the drawer-only detail (reasoning, listings,
     erf candidates, coordinates …) is left off every row to keep it small.
     This fetches the full row for one prospect, from the same book the list
     came from, so the drawer can fill itself in. */
  prospect: (key, sole, type) => {
    const p = new URLSearchParams();
    if (sole) p.set('sole', '1');
    if (type === 'rent') p.set('type', 'rent');
    const q = p.toString();
    return get('/api/prospect/' + encodeURIComponent(key) + (q ? '?' + q : ''));
  },
  stats: () => get('/api/stats'),
  status: () => get('/api/status'),
  erfBusy: () => get('/api/erf/busy'),
  mapPoints: (sole) => get('/api/map' + (sole ? '?sole=1' : '')),
  row: (ident) => get('/api/row/' + encodeURIComponent(ident)),
  /* type 'rent' briefs the finder against the to-rent book; anything
     else is the for-sale one. */
  find: (brief, sole, type) =>
    post('/api/find', { brief, sole: !!sole, type: type === 'rent' ? 'rent' : 'sale' }),
  /* Agent Z: the whole thread every turn — the server holds no state. No
     type is sent: Z reads the conversation and picks the book itself. */
  agent: (messages, sole) => post('/api/agent', { messages, sole: !!sole }),

  /* Team chat — the agents talking to each other, nothing to do with Z.
     `after` is the id of the newest message the client already holds; left
     off, the server hands back the tail of the book. */
  chat: (after) => get('/api/chat' + (after ? '?after=' + after : '')),
  say: (sender, body) => post('/api/chat', { sender, body }),

  scrape: (payload) => post('/api/scrape', payload),
  stop: () => post('/api/stop'),
  rescore: (useAi) => post('/api/rescore', { use_ai: useAi }),
  erfResolve: (force) => post('/api/erf/resolve', { force }),
  erfLocate: (key) => post('/api/erf/locate', { listing_key: key }),
  erfConfirm: (key, erf) => post('/api/erf/confirm', { listing_key: key, erf }),
  reevaluate: (key) => post('/api/listing/reevaluate', { listing_key: key }),
  deed: (gid) => post('/api/deed/' + encodeURIComponent(gid)),

  /* Call brief. The GET is deterministic and cached server-side; briefAi
     spends a model call, so it is only ever fired by a button. */
  brief: (gid) => get('/api/brief/' + encodeURIComponent(gid)),
  briefAi: (gid) => post('/api/brief/' + encodeURIComponent(gid) + '/ai'),
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
  taskDone: (id, done = true) => post(`/api/tasks/${id}/done`, { done }),

  /* ---- sign-in (auth.py)
     Same-origin fetch, so the session cookie rides along on its own; nothing
     here ever sends the password. The two register calls are the halves of
     one WebAuthn ceremony — options, then the browser, then verify. */
  me: () => get('/api/me'),
  /* Your own display name. Role and privileges are an admin's to set — even
     on your own row — so this takes one field and one field only. */
  updateMe: (body) => patch('/api/me', body),
  passkeys: () => get('/api/passkeys'),
  passkeyRegisterOptions: () => post('/api/passkeys/register/options'),
  passkeyRegisterVerify: (token, name, credential) =>
    post('/api/passkeys/register/verify', { token, name, credential }),
  passkeyDelete: (id) => del('/api/passkeys/' + id),
  sessionRevoke: (id) => post('/api/sessions/' + encodeURIComponent(id) + '/revoke'),
  logout: () => post('/logout'),

  /* ---- people and invites (auth.py, all behind the `admin` privilege)
     There is no create-a-user call and there never will be: an account comes
     into existence only when someone opens an invite and registers a passkey,
     so the admin surface is invites in and people out. `createInvite` is the
     one response that ever carries a raw token — show it once, then it is
     gone for good. */
  users: () => get('/api/users'),
  updateUser: (id, body) => patch('/api/users/' + id, body),
  deleteUser: (id) => del('/api/users/' + id),
  reinvite: (id, days) => post(`/api/users/${id}/reinvite`, { days }),
  invites: () => get('/api/invites'),
  createInvite: (body) => post('/api/invites', body),
  revokeInvite: (id) => del('/api/invites/' + id),

  /* ---- team: per-person tasks and presence (team.py). `user` is only
     honoured for admins — a member asking for somebody else's list gets a
     403 from the server, so the UI never draws the switcher for them. */
  myTasks: (user) => get('/api/team/tasks' + (user ? '?user=' + user : '')),
  taskBoard: () => get('/api/team/tasks/board'),
  createTask: (body) => post('/api/team/tasks', body),
  updateTask: (id, body) => patch('/api/team/tasks/' + id, body),
  startTask: (id) => post(`/api/team/tasks/${id}/start`),
  completeTask: (id) => post(`/api/team/tasks/${id}/complete`),
  reopenTask: (id) => post(`/api/team/tasks/${id}/reopen`),
  deleteTask: (id) => del('/api/team/tasks/' + id),
  propertySearch: (q) => get('/api/team/properties?q=' + encodeURIComponent(q)),
  presence: (pagePath) => post('/api/presence', { page: pagePath }),
  online: () => get('/api/online'),
  revokeAnySession: (sid) => post(`/api/team/sessions/${encodeURIComponent(sid)}/revoke`)
};
