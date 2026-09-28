/* Team to-do lists — the pure half (no runes, no fetch), so node --test can
   exercise it: ui/tests/tasks.test.js.

   A task is team.py's public row: {id, user_id, created_by, title, notes,
   status ('open' | 'in_progress' | 'done'), due_date ('YYYY-MM-DD' | null),
   priority (1 high · 2 normal · 3 low), done_at, seen_at, property
   ({group_id, label, suburb, listing_key} | null), overdue, assigned, new,
   created_by_name, user_name}.

   Dates: due dates are calendar days, compared as strings in the VIEWER's
   local day; done_at is a UTC instant, bucketed by the viewer's local week
   (Monday first, as in South Africa). */

const pad = (n) => String(n).padStart(2, '0');

/** 'YYYY-MM-DD' for the local calendar day of `d`. */
export function localDay(d = new Date()) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** 'YYYY-MM-DD' for `day` + n days. */
export function addDays(day, n) {
  const [y, m, dd] = day.split('-').map(Number);
  return localDay(new Date(y, m - 1, dd + n));
}

/** Local midnight on the Monday of the week containing `now`. */
export function weekStart(now = new Date()) {
  const back = (now.getDay() + 6) % 7;            // Mon 0 … Sun 6
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() - back);
}

/** A server timestamp ('2026-09-28T10:00:00Z' or 'YYYY-MM-DD HH:MM:SS', UTC) → Date. */
export function parseTs(ts) {
  if (!ts) return null;
  const s = String(ts);
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s.replace(' ', 'T') + 'Z');
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Where a live task stands against its due date, from the viewer's today. */
export function dueState(t, today = localDay()) {
  if (!t || t.status === 'done' || !t.due_date) return null;
  if (t.due_date < today) return 'overdue';
  if (t.due_date === today) return 'today';
  if (t.due_date === addDays(today, 1)) return 'tomorrow';
  return 'later';
}

const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** '3 Oct' / 'Fri 3 Oct' for a 'YYYY-MM-DD'. */
export function dayLabel(day, withDow = true) {
  const [y, m, d] = day.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  return (withDow ? DOW[dt.getDay()] + ' ' : '') + `${d} ${MON[m - 1]}`;
}

/** The words for a due date: 'Overdue · 2 days', 'Due today', 'Due Fri 3 Oct'. */
export function dueLabel(t, today = localDay()) {
  const st = dueState(t, today);
  if (!st) return '';
  if (st === 'today') return 'Due today';
  if (st === 'tomorrow') return 'Due tomorrow';
  if (st === 'overdue') {
    const [y, m, d] = t.due_date.split('-').map(Number);
    const [ty, tm, td] = today.split('-').map(Number);
    const days = Math.round((new Date(ty, tm - 1, td) - new Date(y, m - 1, d)) / 86400000);
    return days === 1 ? 'Overdue · since yesterday' : `Overdue · ${days} days`;
  }
  const within = t.due_date <= addDays(today, 6);
  return 'Due ' + dayLabel(t.due_date, within);
}

/** Done tasks split into this week (since Monday) and earlier, newest first. */
export function splitDone(tasks, now = new Date()) {
  const start = weekStart(now).getTime();
  const done = (tasks || []).filter((t) => t.status === 'done')
    .map((t) => ({ t, at: parseTs(t.done_at)?.getTime() ?? 0 }))
    .sort((a, b) => b.at - a.at);
  return {
    thisWeek: done.filter((x) => x.at >= start).map((x) => x.t),
    earlier: done.filter((x) => x.at < start).map((x) => x.t)
  };
}

/** Live tasks in working order: in progress, then overdue, due today, the
    rest by due date (undated last), then priority, then oldest first. */
export function liveOrder(tasks, today = localDay()) {
  const rank = (t) => {
    if (t.status === 'in_progress') return 0;
    const s = dueState(t, today);
    return s === 'overdue' ? 1 : s === 'today' ? 2 : 3;
  };
  return (tasks || []).filter((t) => t.status !== 'done').slice().sort((a, b) =>
    rank(a) - rank(b) ||
    (a.due_date || '9999').localeCompare(b.due_date || '9999') ||
    (a.priority || 2) - (b.priority || 2) ||
    String(a.created_at || '').localeCompare(String(b.created_at || '')) ||
    a.id - b.id);
}

/** Home's card: what needs doing now — overdue, due today, in progress, and
    anything new from somebody else. */
export function focusTasks(tasks, today = localDay()) {
  return liveOrder(tasks, today).filter((t) => {
    const s = dueState(t, today);
    return t.status === 'in_progress' || s === 'overdue' || s === 'today' || t.new;
  });
}

/** A person's column on the Team board. */
export function boardColumns(tasks, now = new Date()) {
  const today = localDay(now);
  const live = liveOrder(tasks, today);
  return {
    in_progress: live.filter((t) => t.status === 'in_progress'),
    open: live.filter((t) => t.status === 'open'),
    doneWeek: splitDone(tasks, now).thisWeek
  };
}

/** "from Daniel" on a task somebody else put on the list; "from you" when
    the viewer wrote it for someone else. Empty for your own. */
export function fromLine(t, viewerId) {
  if (!t || !t.created_by || t.created_by === t.user_id) return '';
  if (viewerId != null && t.created_by === viewerId) return 'from you';
  return t.created_by_name ? `from ${t.created_by_name}` : '';
}

/** The linked property's page: Stream B's /property/<listing_key> when the
    app has it and the row carries a key, else the lead's page. */
export function propertyHref(p, hasPropertyPage = false) {
  if (!p || !p.group_id) return null;
  if (hasPropertyPage && p.listing_key) return '/property/' + encodeURIComponent(p.listing_key);
  return '/leads/properties/' + encodeURIComponent(p.group_id);
}

/** Inbox items not yet announced by a toast (ids above the last one told). */
export function toAnnounce(inbox, lastId = 0) {
  return (inbox?.tasks || []).filter((t) => t.id > (Number(lastId) || 0));
}

/** The toast for newly assigned tasks: one → its title; several → who from. */
export function inboxMessage(items) {
  if (!items?.length) return '';
  if (items.length === 1) {
    const t = items[0];
    return `${t.created_by_name || 'Someone'} gave you a task: ${t.title}`;
  }
  const who = [...new Set(items.map((t) => t.created_by_name).filter(Boolean))];
  const names = who.length <= 2 ? who.join(' and ') : `${who.slice(0, -1).join(', ')} and ${who.at(-1)}`;
  return `${items.length} new tasks${names ? ' from ' + names : ''}`;
}

/** When a task was finished, in the viewer's clock: '14:05', 'Yesterday',
    'Mon', '12 Sep'. */
export function doneLabel(doneAt, now = new Date()) {
  const d = parseTs(doneAt);
  if (!d) return '';
  const day = localDay(d), today = localDay(now);
  if (day === today) return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (day === addDays(today, -1)) return 'Yesterday';
  if (day > addDays(today, -7)) return DOW[d.getDay()];
  return dayLabel(day, false);
}
