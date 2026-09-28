/* Team to-do lists — the live half: the "new from others" inbox, the verbs,
   and where a task's property link goes. Pure helpers are in ./tasks.js.

   The inbox (GET /api/team/tasks/inbox) is what somebody else put on MY
   list that I have not looked at yet — team.py keeps `seen_at` per task.
   It drives two things: the badge on the Tasks entry in the dock, and one
   toast per newly assigned task on the next page load ("Daniel gave you a
   task: …"). Opening /tasks on your own list marks it all seen.

   The toast remembers the highest task id it has announced in this browser
   (localStorage), so a reload does not repeat it; the badge is server-backed
   and stays until the list is opened. */
import { api } from './api.js';
import { toast } from './state.svelte.js';
import { propertyHref, toAnnounce, inboxMessage } from './tasks.js';

export const taskInbox = $state({ unseen: 0, tasks: [], loaded: false });

/* Stream B's /property/<listing_key> page, when this build has it: Vite
   resolves the glob at build time, so a missing route costs nothing. */
const PROPERTY_PAGE = Object.keys(import.meta.glob('/src/routes/property/*/+page.svelte')).length > 0;

/** The href for a task's linked property. */
export const propHref = (p) => propertyHref(p, PROPERTY_PAGE);

const TOLD_KEY = 'obv2.tasksToldId';
const told = () => { try { return Number(localStorage.getItem(TOLD_KEY)) || 0; } catch { return 0; } };
const tell = (id) => { try { localStorage.setItem(TOLD_KEY, String(id)); } catch { /* private mode */ } };

/** Refresh the inbox; with `announce`, toast anything not announced yet. */
/* Bumped by markTasksSeen: an inbox answer from a request that started
   before the list was marked seen is stale and must not bring the badge back. */
let seenGen = 0;

export async function refreshInbox({ announce = false } = {}) {
  const gen = seenGen;
  try {
    const got = await api.taskInbox();
    if (gen !== seenGen) return;
    Object.assign(taskInbox, { unseen: got.unseen || 0, tasks: got.tasks || [], loaded: true });
    if (announce) {
      const fresh = toAnnounce(got, told());
      if (fresh.length) {
        toast(inboxMessage(fresh));
        tell(Math.max(...fresh.map((t) => t.id)));
      }
    }
  } catch { /* signed out or an old server: no badge is the right answer */ }
}

/** I have looked at my own list. */
export async function markTasksSeen() {
  const top = taskInbox.tasks.reduce((m, t) => Math.max(m, t.id), 0);
  if (top) tell(Math.max(told(), top));
  seenGen += 1;
  taskInbox.unseen = 0;
  taskInbox.tasks = [];
  try { await api.tasksSeen(); } catch { /* the next refresh puts the badge back */ }
}

/** Poll the inbox: now (announcing), every 60 s while visible, and on return. */
export function startInbox() {
  refreshInbox({ announce: true });
  const t = setInterval(() => { if (!document.hidden) refreshInbox({ announce: true }); }, 60000);
  const onVis = () => { if (!document.hidden) refreshInbox({ announce: true }); };
  document.addEventListener('visibilitychange', onVis);
  return () => { clearInterval(t); document.removeEventListener('visibilitychange', onVis); };
}

/* ——— the verbs, shared by the /tasks page and the Home card ———
   Each call returns the server's row and throws with a readable message;
   callers apply `predicted()` at once and put the old row back on a throw. */
export const VERBS = {
  start: { call: api.startTask, status: 'in_progress' },
  complete: { call: api.completeTask, status: 'done' },
  reopen: { call: api.reopenTask, status: 'open' }
};

/** What the row looks like the moment a verb is pressed. */
export function predicted(t, verb) {
  const status = VERBS[verb].status;
  return { ...t, status, new: false, done_at: status === 'done' ? new Date().toISOString() : null };
}
