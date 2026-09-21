/* The team chat behind the floating button on every page — the agents
   talking to each other. (Agent Z lives in agent.svelte.js and on /agent;
   the two share nothing but a corner of the screen, and not even that.)

   Module state, like the rest of the app: the thread survives a hop to the
   map and back, and the poll keeps running whether or not the panel is open,
   so the unread count is already right when you look at it.

   Polling, not sockets. Every few seconds the client asks for "everything
   after the last id I hold" — which is also how a phone that has been asleep
   catches up in one request. The loop stops while the tab is hidden: nobody
   needs a background tab hammering Railway all afternoon.

   There are no accounts here (one shared password for the team), so who you
   are is simply the name you typed, kept in this browser. */

import { api } from './api.js';

const NAME_KEY = 'oblivion.chat.name';
const POLL_MS = 4000;
const KEEP = 400;          // messages held in memory; older ones scroll away

/* localStorage throws outright in a locked-down browser, and a chat widget
   is not worth taking the page down for. */
function readName() {
  try {
    return localStorage.getItem(NAME_KEY) || '';
  } catch {
    return '';
  }
}
function writeName(v) {
  try {
    localStorage.setItem(NAME_KEY, v);
  } catch {
    /* the name simply won't survive a reload */
  }
}

export const chat = $state({
  messages: [],     // {id, sender, body, at} — ascending, oldest first
  latestId: 0,      // polling cursor: the newest id we hold
  open: false,      // the panel — fresh each load, like Z's
  unread: 0,        // messages from others while the panel was shut
  me: '',           // display name, from localStorage
  ready: false,     // the first fetch has landed (so "no messages yet" is true)
  sending: false,
  error: ''
});

let timer = null;
let inflight = false;
let live = false;

/* ——— the loop ——— */

function tick() {
  timer = null;
  poll().finally(schedule);
}
function schedule() {
  if (!live || timer || typeof document === 'undefined' || document.hidden) return;
  timer = setTimeout(tick, POLL_MS);
}
function halt() {
  if (timer) clearTimeout(timer);
  timer = null;
}
function onVisibility() {
  if (document.hidden) halt();
  else {
    poll();       // catch up on whatever arrived while we were away
    schedule();
  }
}

export function startChat() {
  if (live) return stopChat;
  live = true;
  chat.me = readName();
  document.addEventListener('visibilitychange', onVisibility);
  poll().finally(schedule);
  return stopChat;
}

export function stopChat() {
  live = false;
  halt();
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', onVisibility);
  }
}

async function poll() {
  if (inflight) return;
  inflight = true;
  try {
    const r = await api.chat(chat.latestId || undefined);
    absorb(r);
    chat.error = '';
  } catch (e) {
    chat.error = e.message || String(e);
  } finally {
    inflight = false;
    chat.ready = true;
  }
}

/* Append what is genuinely new. The cursor only ever advances to a message
   we actually hold — the server caps a catch-up, so trusting `latest` blindly
   would skip the remainder of a very long backlog. */
function absorb(r) {
  const fresh = (r?.messages || []).filter((m) => m && m.id > chat.latestId);
  if (fresh.length) {
    chat.messages = [...chat.messages, ...fresh].slice(-KEEP);
    chat.latestId = fresh[fresh.length - 1].id;
    if (!chat.open) {
      chat.unread += fresh.filter((m) => m.sender !== chat.me).length;
    }
  } else if (!chat.messages.length && typeof r?.latest === 'number') {
    chat.latestId = r.latest;
  }
}

/* ——— talking ——— */

export async function say(text) {
  const body = (text || '').trim();
  if (!body || !chat.me || chat.sending) return false;
  chat.sending = true;
  try {
    const r = await api.say(chat.me, body);
    if (r?.message) absorb({ messages: [r.message] });
    chat.error = '';
    return true;
  } catch (e) {
    chat.error = e.message || String(e);
    return false;
  } finally {
    chat.sending = false;
  }
}

export function setName(name) {
  const n = (name || '').replace(/\s+/g, ' ').trim().slice(0, 40);
  if (!n) return false;
  chat.me = n;
  writeName(n);
  return true;
}

/* ——— the widget ——— */

export function openChat() {
  chat.open = true;
  chat.unread = 0;
  poll();               // don't make them wait out the interval
}
export function closeChat() {
  chat.open = false;
}
export function toggleChat() {
  if (chat.open) closeChat();
  else openChat();
}
