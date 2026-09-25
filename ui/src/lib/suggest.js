/* Home's one sentence, and the one button under it.

   A pure function of what Home has already fetched — no runes, no fetches,
   no DOM — so it can be unit-tested table by table (ui/tests/suggest.test.js)
   and so the sentence is always a function of the numbers on screen.

   suggest({ view, now, today, todayFailed, home, status, name })
     view         'needs' (default) | 'mandates' | 'crawl' | 'pipeline'
     now          Date
     today        /api/panel/today payload, or null while it loads
     todayFailed  true when /api/panel/today did not answer
     home         /api/home payload, or null
     homeFailed   true when /api/home did not answer
     status       app.status (/api/status): running, phase, done, total

   Returns null while the data the chosen view speaks about is still on its
   way (Home keeps the line reserved), else
     { key, text, cta: { label, href, filters?, log?, run? } }
   `key` names the rule that fired (the tests assert on it). The CTA always
   routes somewhere: `filters` are applied to the prospect filters before
   navigating, `log` opens the crawl log, `run` opens the crawl sheet.

   "What needs me", in priority order:
     1 overdue follow-ups          → Open follow-ups
     2 follow-ups due today        → Open follow-ups
     3 a mandate expiring ≤ 14 d   → Open the property (names the street)
     4 a crawl running right now   → Watch the crawl (with progress)
     5 new prospects since yesterday → Open prospects (newest first)
       (new for-sale listings first seen today — the last bucket of
       /api/home's 14-day series — "N new listings since midnight")
     6 nothing                     → "Nothing needs you right now. Next crawl at HH:MM."
   If /api/panel/today failed, rules 1–3 are skipped and, after a running
   crawl, the line says lead management is not answering instead of 5–6. */

export const VIEWS = [
  { value: 'needs', label: 'What needs me' },
  { value: 'mandates', label: 'Mandates expiring' },
  { value: 'crawl', label: "Today's crawl" },
  { value: 'pipeline', label: 'Pipeline' }
];

const DAY = 86400000;
const plural = (n, one, many = one + 's') => `${n} ${n === 1 ? one : many}`;

/** A property's printable street: the address as listed, else the official one, else the title. */
export function streetOf(p) {
  const s = p?.street_address_raw || p?.official_address || p?.title || '';
  return String(s).trim() || 'an untracked property';
}

/** 'YYYY-MM-DD…' → local midnight of that day (a bare date is a LOCAL day). */
function dayOf(v) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(v || ''));
  return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
}

/** Whole days from today to `v` (0 = today, 1 = tomorrow), null if unparseable. */
export function daysUntil(v, now) {
  const d = dayOf(v);
  if (!d) return null;
  const t = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((d - t) / DAY);
}

const whenIn = (n) => (n <= 0 ? 'today' : n === 1 ? 'tomorrow' : `in ${n} days`);

/** HH:MM, 24-hour, in the viewer's zone. */
export function hhmm(v) {
  const d = v instanceof Date ? v : new Date(v);
  if (isNaN(d)) return null;
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** Mandates from /api/panel/today that expire within `days`, soonest first. */
export function expiringWithin(today, now, days) {
  return (today?.expiring || [])
    .map((m) => ({ m, n: daysUntil(m.expires_at, now) }))
    .filter((x) => x.n != null && x.n >= 0 && x.n <= days)
    .sort((a, b) => a.n - b.n);
}

/** New for-sale listings first seen today (the last bucket of the 14-day series). */
export function newSinceYesterday(home) {
  const v = home?.series?.new_listings;
  return Array.isArray(v) && v.length ? +v[v.length - 1] || 0 : 0;
}

const propHref = (p) => (p?.group_id != null ? `/leads/properties/${encodeURIComponent(p.group_id)}` : '/leads');

function crawlLine(status) {
  const s = status || {};
  if (s.total) return `A crawl is running — ${s.done ?? 0} of ${plural(s.total, 'page')} done.`;
  return `A crawl is running (${String(s.phase || 'starting').replace(/_/g, ' ')}).`;
}

function nextCrawl(home) {
  const t = home?.crawl?.next_crawl;
  const h = t ? hhmm(t) : null;
  return h ? `Next crawl at ${h}.` : '';
}

const FOLLOWUPS = { label: 'Open follow-ups', href: '/leads' };
const WATCH = { label: 'Watch the crawl', href: '/prospects', log: true };
const NEWEST = { label: 'Open prospects', href: '/prospects', filters: { sort: 'newest' } };
const PIPELINE = { label: 'Open pipeline', href: '/leads/pipeline' };

function needs({ now, today, todayFailed, home, homeFailed, status }) {
  const leadsKnown = !!today && !todayFailed;
  if (!leadsKnown && !todayFailed) return null;          // still loading
  if (leadsKnown) {
    const od = today.overdue?.length || 0;
    if (od) {
      const first = streetOf(today.overdue[0].property);
      return { key: 'overdue', cta: FOLLOWUPS,
               text: `${plural(od, 'follow-up')} overdue — start with ${first}.` };
    }
    const dt = today.due_today?.length || 0;
    if (dt) return { key: 'due', cta: FOLLOWUPS, text: `${plural(dt, 'follow-up')} due today.` };
    const ex = expiringWithin(today, now, 14);
    if (ex.length) {
      const { m, n } = ex[0];
      return { key: 'mandate', cta: { label: 'Open the property', href: propHref(m.property) },
               text: `The mandate on ${streetOf(m.property)} expires ${whenIn(n)}.` };
    }
  }
  if (status?.running) return { key: 'crawl', cta: WATCH, text: crawlLine(status) };
  /* Follow-ups and mandates were never read: "nothing needs you" would be a
     guess, so say what is actually known. */
  if (todayFailed) return { key: 'leads-off', cta: FOLLOWUPS, text: 'Lead management is not answering right now.' };
  if (!home && !homeFailed) return null;                 // new-prospect count not in yet
  const fresh = newSinceYesterday(home);
  if (fresh) return { key: 'new', cta: NEWEST, text: `${plural(fresh, 'new listing')} since midnight.` };
  const next = nextCrawl(home);
  return { key: 'idle', cta: { label: 'Open prospects', href: '/prospects' },
           text: `Nothing needs you right now.${next ? ' ' + next : ''}` };
}

function mandates({ now, today, todayFailed }) {
  if (todayFailed) return { key: 'mandates-off', cta: PIPELINE, text: 'Lead management is not answering right now.' };
  if (!today) return null;
  const soon = expiringWithin(today, now, 14);
  if (soon.length) {
    const { m, n } = soon[0];
    const rest = soon.length - 1;
    return { key: 'mandates-soon', cta: { label: 'Open the property', href: propHref(m.property) },
             text: `The mandate on ${streetOf(m.property)} expires ${whenIn(n)}` +
                   (rest ? `, and ${plural(rest, 'more')} within 14 days.` : '.') };
  }
  const later = expiringWithin(today, now, 366);
  if (later.length) {
    const { m, n } = later[0];
    return { key: 'mandates-later', cta: { label: 'Open the property', href: propHref(m.property) },
             text: `No mandate expires in the next 14 days. Next: ${streetOf(m.property)} in ${n} days.` };
  }
  return { key: 'mandates-none', cta: PIPELINE, text: 'No mandates are about to expire.' };
}

function crawl({ home, homeFailed, status }) {
  if (status?.running) return { key: 'crawl-live', cta: WATCH, text: crawlLine(status) };
  if (!home) return homeFailed ? { key: 'crawl-off', cta: { label: 'Open prospects', href: '/prospects' }, text: 'No crawl is running.' } : null;
  const fresh = newSinceYesterday(home);
  const next = nextCrawl(home);
  if (fresh) return { key: 'crawl-new', cta: NEWEST,
                      text: `Today's crawl found ${plural(fresh, 'new listing')}.${next ? ' ' + next : ''}` };
  if (home.crawl?.last_sweep || home.crawl?.last_full)
    return { key: 'crawl-quiet', cta: { label: 'Open prospects', href: '/prospects' },
             text: `No new listings today.${next ? ' ' + next : ''}` };
  return { key: 'crawl-none', cta: { label: 'Start a crawl', href: '/prospects', run: true },
           text: next ? `No crawl has finished yet. ${next}` : 'No crawl has run yet.' };
}

function pipeline({ today, home, homeFailed }) {
  if (!home) return homeFailed ? { key: 'pipeline-off', cta: PIPELINE, text: 'Your pipeline is one tap away.' } : null;
  const tracked = +home.tracked || 0, active = +home.tracked_active || 0;
  if (!tracked) return { key: 'pipeline-empty', cta: { label: 'Open prospects', href: '/prospects' },
                         text: 'Nothing tracked yet. Start from the hot prospects.' };
  const quiet = today?.stale?.length || 0;
  return { key: 'pipeline', cta: PIPELINE,
           text: `${plural(active, 'lead')} in play of ${tracked} tracked` +
                 (quiet ? `; ${quiet} ${quiet === 1 ? 'has' : 'have'} gone quiet.` : '.') };
}

const BY_VIEW = { needs, mandates, crawl, pipeline };

export function suggest(input) {
  const i = { now: new Date(), today: null, todayFailed: false, home: null, homeFailed: false, status: null, ...input };
  const fn = BY_VIEW[i.view] || needs;
  return fn(i);
}
