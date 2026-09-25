/* The team chat behind the header's chat button on every page — channels,
   attachments, @mentions. (Agent Z lives in agent.svelte.js and on /agent;
   the two share nothing.) docs/CHAT.md is the contract with the server and
   with the Playwright harness.

   Module state, like the rest of the app: the channels and the threads you
   have opened survive a hop to the map and back, and the poll keeps running
   whether or not the sheet is open, so the unread count is already right
   when you look at it.

   Polling, not sockets. ONE self-scheduling timer asks /api/chat/sync for
   "every change after rev N" — 4 s while the sheet is open and the tab is
   visible, 30 s while it is shut, nothing while the tab is hidden (one
   catch-up when it comes back). Requests never overlap. A change is applied
   by message id — insert or replace — because an edit or a delete arrives as
   the same id with a higher rev.

   Sends are optimistic: a pending bubble carrying a client_id sits at the
   foot of the thread until the server's row replaces it. A failed send stays
   on screen with Retry (same client_id, so a retry of a send that actually
   landed comes back as the original row, not a duplicate) and Discard. A
   message is never dropped silently. */

import { api } from './api.js';
import { app } from './state.svelte.js';

const OPEN_MS = 4000;
const SHUT_MS = 30000;
const MAX_BACKOFF_MS = 60000;
const KEEP = 600;          // messages held per channel; older ones page back in
const PAGE = 50;
const MAX_ATTACH = 6;

export const chat = $state({
  open: false,             // the sheet
  view: 'channel',         // 'channel' | 'mentions'
  active: null,            // the open channel's id
  channels: [],            // /api/chat/channels rows, patched by sync
  byChannel: {},           // id -> {messages, pending, hasMore, loaded, loading, loadingOlder}
  unread: 0,               // total unread across channels (the strip's badge reads this)
  mentions: 0,             // unread mentions — the header badge goes accent for these
  cursor: null,            // sync rev
  me: null,                // {id, username, display_name, is_admin}
  people: [],              // /api/chat/people
  drafts: {},              // id -> {text, attachments, mentions:[{id, name}]}
  mentionList: [],         // the Mentions view
  mentionsLoading: false,
  divider: null,           // {channel, after}: the "New" line, fixed when a channel is opened
  jumpTo: null,            // a message id to bring into view when its channel opens
  atBottom: true,          // the open thread is scrolled to its foot (so it is being read)
  overlay: '',             // a picker/menu inside the sheet that Escape should close first
  ready: false,            // the first /channels has landed
  error: '',               // something a person did went wrong (shown until dismissed)
  syncError: ''            // the poll keeps failing (set after 2 failures in a row)
});

/* One channel's thread. A class, so `messages` can be $state.raw: rows are
   plain objects replaced whole (by id) on every change, never proxied —
   a few hundred messages per channel stay cheap. */
class Bucket {
  messages = $state.raw([]);
  pending = $state([]);
  hasMore = $state(false);
  loaded = $state(false);
  loading = $state(false);
  loadingOlder = $state(false);
  error = $state('');
}

/* What the server has confirmed as read, per channel id. The display's
   last_read_id may run ahead of it; a read POST goes out whenever the
   newest row on screen is past this. */
const acked = new Map();
const ackOf = (id) => acked.get(id) || 0;
function ack(id, v) {
  if (typeof v === 'number' && v > ackOf(id)) acked.set(id, v);
}

/* ——— helpers ——— */

const key = (id) => String(id);
export const channelById = (id) => chat.channels.find((c) => c.id === id) || null;

export function bucket(id) {
  const k = key(id);
  if (!chat.byChannel[k]) chat.byChannel[k] = new Bucket();
  return chat.byChannel[k];
}

export function draft(id) {
  const k = key(id);
  if (!chat.drafts[k]) chat.drafts[k] = { text: '', attachments: [], mentions: [] };
  return chat.drafts[k];
}

function uuid() {
  try {
    if (crypto?.randomUUID) return crypto.randomUUID();
  } catch { /* insecure context */ }
  const b = new Uint8Array(16);
  try { crypto.getRandomValues(b); } catch { for (let i = 0; i < 16; i++) b[i] = Math.random() * 256; }
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

function recount() {
  let n = 0;
  for (const c of chat.channels) n += c.unread || 0;
  chat.unread = n;
}

/* Is this channel being read right now — open, in front, scrolled to the
   foot, tab visible? Then nothing arriving in it is "unread". */
function reading(id) {
  return chat.open && chat.view === 'channel' && chat.active === id && chat.atBottom
    && !app.selectedKey && !app.runOpen
    && typeof document !== 'undefined' && !document.hidden;
}

/* ——— the loop ——— */

let timer = null;
let inflight = false;
let again = false;          // a kick landed while a sync was in flight
let live = false;
let stamp = null;
let stopTitle = null;
let failures = 0;           // consecutive sync failures, for the backoff

/* The sheet is actually on screen (not stepped aside for the drawer or the
   crawl panel) — only then is the fast cadence worth it. */
const sheetVisible = () => chat.open && !app.selectedKey && !app.runOpen;

function schedule(ms) {
  if (timer) clearTimeout(timer);
  timer = null;
  if (!live || typeof document === 'undefined' || document.hidden) return;
  let wait = ms ?? (sheetVisible() ? OPEN_MS : SHUT_MS);
  if (ms == null && failures) wait = Math.max(wait, Math.min(MAX_BACKOFF_MS, OPEN_MS * 2 ** (failures - 1)));
  timer = setTimeout(tick, wait);
}

async function tick() {
  if (timer) clearTimeout(timer);
  timer = null;
  if (inflight) { again = true; return; }
  inflight = true;
  let more = false;
  try {
    more = await sync();
    failures = 0;
    chat.syncError = '';
  } catch (e) {
    failures += 1;
    if (failures >= 2) chat.syncError = e?.message || String(e);
  } finally {
    inflight = false;
  }
  const soon = !failures && (again || more);
  again = false;
  schedule(soon ? 50 : undefined);
}

/** Run a sync now (or right after the one in flight), then carry on. */
function kick() { tick(); }

/** The sheet came back on screen (the drawer or crawl panel closed): pick
    the fast cadence up again straight away. */
export function resumeChat() {
  if (live && sheetVisible()) kick();
}

function onVisibility() {
  if (document.hidden) schedule();   // clears the timer; nothing is scheduled while hidden
  else kick();                       // catch up on whatever arrived while we were away
}

async function sync() {
  if (!chat.ready || chat.cursor == null) {
    await loadChannels();
    return false;
  }
  const r = await api.chatSync(chat.cursor);
  const msgs = r?.messages || [];
  let unknown = false;
  const mentionsBefore = chat.mentions;
  for (const m of msgs) if (!absorb(m)) unknown = true;
  /* the server caps a catch-up: when there is more, advance only to what we
     actually hold, never past it */
  if (r?.more && msgs.length) chat.cursor = msgs[msgs.length - 1].rev;
  else if (typeof r?.cursor === 'number') chat.cursor = r.cursor;
  applyCounts(r);
  const s = r?.channels_stamp ?? null;
  if (stamp == null && s != null) stamp = s;          // seed: nothing to catch up on
  const moved = s != null && s !== stamp;
  /* per-channel mention counts only come from /channels: refetch when the
     total moves */
  const mentionsMoved = typeof r?.mentions === 'number' && r.mentions !== mentionsBefore;
  if (unknown || moved || mentionsMoved) {
    await loadChannels();
    if (s != null) stamp = s;                         // only once the refetch landed
  }
  return !!r?.more;
}

function applyCounts(r) {
  if (r?.unread && typeof r.unread === 'object') {
    for (const c of chat.channels) {
      const n = r.unread[c.id] ?? r.unread[key(c.id)] ?? 0;
      c.unread = reading(c.id) ? 0 : n;
      if (!c.unread) c.mentions = 0;   // a mention is an unread message
    }
    recount();
  }
  if (typeof r?.mentions === 'number') chat.mentions = r.mentions;
  if (chat.active != null && reading(chat.active)) markRead();
}

export async function loadChannels() {
  const r = await api.chatChannels();
  const old = new Map(chat.channels.map((c) => [c.id, c]));
  chat.channels = (r?.channels || []).map((c) => {
    ack(c.id, c.last_read_id);
    const was = old.get(c.id);
    /* the server has not heard our read yet — don't flash a badge back up */
    if (reading(c.id)) return { ...c, unread: 0, mentions: 0 };
    if (was && was.last_read_id > (c.last_read_id || 0)) return { ...c, last_read_id: was.last_read_id };
    return c;
  });
  if (r?.me) chat.me = r.me;
  if (chat.cursor == null && typeof r?.cursor === 'number') chat.cursor = r.cursor;
  recount();
  chat.mentions = chat.channels.reduce((n, c) => n + (c.mentions || 0), 0);
  if (!chat.ready) {
    chat.ready = true;
    if (chat.cursor == null) {
      const s = await api.chatSync();
      chat.cursor = s?.cursor ?? 0;
      stamp = s?.channels_stamp ?? stamp;
      applyCounts(s);
    }
  }
  if (chat.active != null && !channelById(chat.active)) chat.active = null;
  ensureActive();
  return r;
}

/* ——— applying one message (from sync, a send, an edit) ——— */

function preview(m) {
  if (m.deleted) return 'Message deleted';
  if (m.body) return m.body.replace(/\s+/g, ' ').slice(0, 120);
  const a = m.attachments?.[0];
  if (!a) return '';
  return a.type === 'property' ? '🏠 ' + (a.label || 'Property')
    : a.type === 'media' ? '🖼 ' + (a.name || 'Media')
    : '🔗 ' + (a.title || a.domain || a.url || 'Link');
}

/** Returns false when the message is for a channel we do not know. */
function absorb(m) {
  if (!m || m.id == null) return true;
  const ch = channelById(m.channel_id);
  const b = chat.byChannel[key(m.channel_id)];
  /* a pending bubble goes only once its row is really in the thread —
     otherwise a sent message would vanish */
  if (b && put(b, m)) dropPending(b, m);
  if (!ch) return false;
  if (!ch.last || m.id >= ch.last.id) {
    ch.last = { id: m.id, sender: m.sender, preview: preview(m), at: m.created_at };
  }
  return true;
}

function dropPending(b, m) {
  if (!m.mine || !m.client_id) return;
  const i = b.pending.findIndex((p) => p.client_id === m.client_id);
  if (i >= 0) b.pending.splice(i, 1);
}

function replaceAt(list, i, v) {
  const out = list.slice();
  out[i] = v;
  return out;
}

/** Insert or replace one row (messages is raw: always a new array).
    Returns true when the row is in the thread afterwards. */
function put(b, m) {
  const list = b.messages;
  const i = list.findIndex((x) => x.id === m.id);
  if (i >= 0) {
    if ((m.rev ?? 0) >= (list[i].rev ?? 0)) b.messages = replaceAt(list, i, m);
    return true;
  }
  /* only extend a thread we hold the tail of; older history pages in */
  if (!b.loaded && !b.loading) return false;
  if (!list.length || m.id > list[list.length - 1].id) b.messages = [...list, m];
  else {
    const at = list.findIndex((x) => x.id > m.id);
    if (at === 0 && b.hasMore) return false;   // older than the page we hold: it will page in
    b.messages = at < 0 ? [...list, m] : [...list.slice(0, at), m, ...list.slice(at)];
  }
  return true;
}

/** Channels not on screen keep only their newest KEEP rows. */
function trimOthers() {
  for (const [k, b] of Object.entries(chat.byChannel)) {
    if (k === key(chat.active) && chat.open) continue;
    if (b.messages.length > KEEP) {
      b.messages = b.messages.slice(-KEEP);
      b.hasMore = true;
    }
  }
}

/* ——— opening channels and paging ——— */

/** With the sheet open on the channel view and nothing chosen yet, land on
    the first channel with something unread, else #general. */
function ensureActive() {
  if (!chat.open || chat.view !== 'channel' || chat.active != null || !chat.channels.length) return;
  const first = chat.channels.find((c) => c.unread) || chat.channels.find((c) => c.kind === 'general') || chat.channels[0];
  openChannel(first.id);
}

export async function openChannel(id) {
  if (id == null) return;
  const ch = channelById(id);
  chat.view = 'channel';
  chat.overlay = '';
  const switched = chat.active !== id;
  chat.active = id;
  if (switched) trimOthers();
  chat.atBottom = true;
  chat.divider = ch && ch.unread ? { channel: id, after: ch.last_read_id || 0 } : null;
  draft(id);
  const b = bucket(id);
  if (b.loaded || b.loading) {
    if (reading(id)) markRead();
    return;
  }
  await loadTail(id);
}

/** (Re)load a channel's tail, merged with whatever sync already dropped in. */
export async function loadTail(id) {
  const ch = channelById(id);
  const b = bucket(id);
  if (b.loading) return;
  b.loading = true;
  b.error = '';
  try {
    const limit = Math.min(200, Math.max(PAGE, (ch?.unread || 0) + 10));
    const r = await api.chatMessages(id, { limit });
    const got = r?.messages || [];
    /* merge: sync may already have dropped fresher rows in while we waited */
    const byId = new Map(got.map((m) => [m.id, m]));
    for (const m of b.messages) {
      const had = byId.get(m.id);
      if (!had || (m.rev ?? 0) > (had.rev ?? 0)) byId.set(m.id, m);
    }
    b.messages = [...byId.values()].sort((a, z) => a.id - z.id);
    b.hasMore = !!r?.has_more;
    b.loaded = true;
    for (const m of got) dropPending(b, m);
  } catch (e) {
    b.error = e?.message || String(e);
  } finally {
    b.loading = false;
  }
  if (reading(id)) markRead();
}

export async function loadOlder(id) {
  const b = bucket(id);
  if (!b.loaded || !b.hasMore || b.loadingOlder || !b.messages.length) return 0;
  b.loadingOlder = true;
  b.error = '';
  try {
    const r = await api.chatMessages(id, { before: b.messages[0].id, limit: PAGE });
    const got = (r?.messages || []).filter((m) => !b.messages.some((x) => x.id === m.id));
    b.messages = [...got, ...b.messages];
    b.hasMore = !!r?.has_more;
    return got.length;
  } catch (e) {
    b.error = e?.message || String(e);
    return 0;
  } finally {
    b.loadingOlder = false;
  }
}

/* ——— reading ——— */

let readTimer = null;
let readBusy = false;
let readDirty = false;

/** Debounced: tell the server the open channel is read to its newest row. */
export function markRead() {
  if (readTimer) clearTimeout(readTimer);
  readTimer = setTimeout(flushRead, 500);
}

async function flushRead() {
  readTimer = null;
  const id = chat.active;
  if (id == null || !reading(id)) return;
  if (readBusy) { readDirty = true; return; }
  const ch = channelById(id);
  const b = chat.byChannel[key(id)];
  if (!ch || !b?.messages.length) return;
  const last = b.messages[b.messages.length - 1].id;
  /* the server's word, not the display's: your own post never counts as a
     read there, so a colleague's line just before it would stay unread */
  if (last <= ackOf(id) && !ch.unread) return;
  ch.unread = 0;
  ch.mentions = 0;
  recount();
  readBusy = true;
  try {
    const r = await api.chatRead(id, last);
    const got = r?.last_read_id ?? last;
    ack(id, got);
    ch.last_read_id = Math.max(ch.last_read_id || 0, got);
    if (typeof r?.unread === 'number') ch.unread = reading(id) ? 0 : r.unread;
    if (typeof r?.mentions === 'number') chat.mentions = r.mentions;
    recount();
  } catch { /* the next sync puts the count right */ }
  finally {
    readBusy = false;
    if (readDirty) {
      readDirty = false;
      flushRead();
    }
  }
}

/* ——— sending ——— */

const MENTION_OK = /^[\p{L}\p{N}](?:[\p{L}\p{N} .'’-]*[\p{L}\p{N}])?$/u;

/** How to write a person into the composer so the server's @-parser finds
    them: "@Display Name" when the name is plain words, else "@username". */
export function mentionText(p) {
  const dn = (p?.display_name || '').trim();
  return dn && MENTION_OK.test(dn) ? dn : p.username;
}

function payload(a) {
  if (a.type === 'property') return { type: 'property', gid: String(a.gid) };
  if (a.type === 'media') return { type: 'media', id: a.id };
  return { type: 'link', url: a.url, ...(a.title ? { title: a.title } : {}) };
}

/** Did the text keep this @mention? The picker records ids; the text decides. */
function stillMentioned(text, name) {
  const t = text.toLowerCase();
  const n = '@' + name.toLowerCase();
  let at = t.indexOf(n);
  while (at >= 0) {
    const next = t[at + n.length];
    if (next == null || !/[\p{L}\p{N}_]/u.test(next)) return true;
    at = t.indexOf(n, at + 1);
  }
  return false;
}

export function send(id) {
  const d = draft(id);
  const body = (d.text || '').trim();
  if (!body && !d.attachments.length) return false;
  if (body.length > 2000) {
    chat.error = `That message is ${body.length} characters — the limit is 2000.`;
    return false;
  }
  const entry = {
    client_id: uuid(),
    channel_id: id,
    body,
    attachments: d.attachments.map((a) => ({ ...a })),
    mentions: [...new Set(d.mentions.filter((m) => stillMentioned(body, m.name)).map((m) => m.id))],
    created_at: new Date().toISOString(),
    status: 'sending',
    error: ''
  };
  bucket(id).pending.push(entry);
  d.text = '';
  d.attachments = [];
  d.mentions = [];
  chat.error = '';
  deliver(id, entry.client_id);
  return true;
}

function pendingOf(id, cid) {
  return chat.byChannel[key(id)]?.pending.find((p) => p.client_id === cid) || null;
}

async function deliver(id, cid) {
  const p = pendingOf(id, cid);
  if (!p) return;
  p.status = 'sending';
  p.error = '';
  try {
    const r = await api.chatPost(id, {
      body: p.body,
      attachments: p.attachments.map(payload),
      mentions: p.mentions,
      client_id: p.client_id
    });
    const m = r?.message || r;
    const row = m?.id != null ? { ...m, mine: true, client_id: m.client_id ?? cid } : null;
    if (row) absorb(row);
    const b = chat.byChannel[key(id)];
    if (b && pendingOf(id, cid)) {
      /* the thread was not loaded (or the row was not placed): fetch its
         tail, which carries this row and retires the bubble */
      if (row && !b.loaded) await loadTail(id);
      const i = b.pending.findIndex((x) => x.client_id === cid);
      if (i >= 0 && b.messages.some((x) => x.client_id === cid || x.id === row?.id)) b.pending.splice(i, 1);
      else if (i >= 0 && row) {
        b.pending[i].status = 'failed';
        b.pending[i].error = 'Sent, but could not be shown — reopen the channel';
      }
    }
    if (reading(id)) markRead();
  } catch (e) {
    const q = pendingOf(id, cid);
    if (q) {
      q.status = 'failed';
      q.error = e?.message || 'Not sent';
    }
  }
}

export function retry(id, cid) {
  deliver(id, cid);
}

export function discard(id, cid) {
  const b = chat.byChannel[key(id)];
  const i = b ? b.pending.findIndex((x) => x.client_id === cid) : -1;
  if (i >= 0) b.pending.splice(i, 1);
}

export function addAttachment(id, a) {
  const d = draft(id);
  if (d.attachments.length >= MAX_ATTACH) {
    chat.error = `Up to ${MAX_ATTACH} attachments per message.`;
    return false;
  }
  const same = (x) => x.type === a.type && (
    a.type === 'property' ? String(x.gid) === String(a.gid)
      : a.type === 'media' ? x.id === a.id : x.url === a.url);
  if (d.attachments.some(same)) return true;
  d.attachments.push(a);
  return true;
}

export function removeAttachment(id, i) {
  draft(id).attachments.splice(i, 1);
}

/* ——— edit / delete ——— */

export async function editMessage(mid, body) {
  const r = await api.chatEdit(mid, body);
  const m = r?.message || r;
  if (m?.id != null) absorb(m);
  return m;
}

export async function deleteMessage(mid) {
  const r = await api.chatDelete(mid);
  const m = r?.message || r;
  if (m?.id != null) absorb(m);
  else {
    for (const b of Object.values(chat.byChannel)) {
      const i = b.messages.findIndex((y) => y.id === mid);
      if (i >= 0) b.messages = replaceAt(b.messages, i, { ...b.messages[i], deleted: true, body: '', attachments: [] });
    }
  }
}

/* ——— channels ——— */

export async function createTopic(name) {
  const r = await api.chatCreateChannel({ name });
  const ch = r?.channel || r;
  await loadChannels();
  if (ch?.id != null) openChannel(ch.id);
  return ch;
}

/** "Discuss" on a property: find or make its channel, open the sheet on it,
    and put the property in that channel's draft. The prospect drawer is
    closed on the way — the chat steps aside while it is up. */
export async function openChannelForProperty(gid, info = {}) {
  if (gid == null || gid === '') return null;
  app.selectedKey = null;
  chat.open = true;
  chat.view = 'channel';
  try {
    const r = await api.chatCreateChannel({ property_gid: String(gid) });
    const ch = r?.channel || r;
    if (!ch || ch.id == null) throw new Error('No channel came back');
    if (!channelById(ch.id) || !ch.property) await loadChannels();
    const known = channelById(ch.id);
    if (known?.property && !ch.property) ch.property = known.property;
    addAttachment(ch.id, {
      type: 'property', gid: String(gid),
      /* the server's snapshot first, so the chip reads exactly like the
         channel row and the card that will be posted */
      label: ch.property?.label || info.label || ch.name || 'Property',
      suburb: ch.property?.suburb ?? info.suburb ?? null,
      price_zar: ch.property?.price_zar ?? info.price_zar ?? null,
      tier: ch.property?.tier ?? info.tier ?? null,
      photo_url: ch.property?.photo_url ?? info.photo_url ?? null
    });
    await openChannel(ch.id);
    kick();
    return ch;
  } catch (e) {
    chat.error = e?.message || String(e);
    return null;
  }
}

/* ——— mentions and people ——— */

export async function loadMentions() {
  chat.mentionsLoading = true;
  try {
    const r = await api.chatMentions(50);
    chat.mentionList = r?.mentions || r?.messages || [];
  } catch (e) {
    chat.error = e?.message || String(e);
  } finally {
    chat.mentionsLoading = false;
  }
}

export function showMentions() {
  chat.view = 'mentions';
  chat.overlay = '';
  loadMentions();
}

let peopleAt = 0;
export async function loadPeople(force = false) {
  if (!force && Date.now() - peopleAt < 60000 && chat.people.length) return;
  peopleAt = Date.now();
  try {
    const r = await api.chatPeople();
    const next = r?.people || [];
    if (JSON.stringify(next) !== JSON.stringify(chat.people)) chat.people = next;
  } catch { peopleAt = 0; }
}

/* ——— the tab title: "(2) Oblivion" while mentions wait ——— */

const PREFIX = /^\(\d+\+?\) /;

function applyTitle() {
  if (typeof document === 'undefined') return;
  const base = document.title.replace(PREFIX, '');
  const want = chat.mentions > 0 ? `(${chat.mentions > 99 ? '99+' : chat.mentions}) ${base}` : base;
  if (document.title !== want) document.title = want;
}

function watchTitle() {
  const stopFx = $effect.root(() => {
    $effect(() => {
      chat.mentions;
      applyTitle();
    });
  });
  /* SvelteKit rewrites <title> on navigation; put the prefix back on. */
  let mo = null;
  try {
    mo = new MutationObserver(() => applyTitle());
    mo.observe(document.head, { subtree: true, childList: true, characterData: true });
  } catch { /* no observer: the prefix returns on the next count change */ }
  return () => {
    stopFx();
    mo?.disconnect();
    if (typeof document !== 'undefined') document.title = document.title.replace(PREFIX, '');
  };
}

/* ——— lifecycle ——— */

export function startChat() {
  if (live) return stopChat;
  live = true;
  document.addEventListener('visibilitychange', onVisibility);
  stopTitle = watchTitle();
  kick();
  return stopChat;
}

export function stopChat() {
  live = false;
  if (timer) clearTimeout(timer);
  timer = null;
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', onVisibility);
  }
  stopTitle?.();
  stopTitle = null;
}

/* ——— the sheet ——— */

export function openChat() {
  chat.open = true;
  loadPeople();
  if (chat.view === 'channel' && chat.active == null) ensureActive();
  else if (chat.active != null && chat.view === 'channel') openChannel(chat.active);
  kick();                 // don't make them wait out the interval
}
export function closeChat() {
  chat.open = false;
  chat.overlay = '';
  chat.divider = null;
  trimOthers();
  schedule();             // back to the slow cadence
}
export function toggleChat() {
  if (chat.open) closeChat();
  else openChat();
}

/* The header chat button's badge (strip + Home): unread mentions win and
   show in the accent colour; otherwise the plain unread count. */
export function chatBadge() {
  const kind = chat.mentions > 0 ? 'mention' : 'plain';
  const n = kind === 'mention' ? chat.mentions : chat.unread;
  const label = chat.open ? 'Close team chat'
    : chat.mentions ? `Open team chat, ${chat.mentions} mention${chat.mentions === 1 ? '' : 's'}`
    : chat.unread ? `Open team chat, ${chat.unread} unread` : 'Open team chat';
  return { kind, n, txt: n > 9 ? '9+' : String(n), label, show: n > 0 && !chat.open };
}
