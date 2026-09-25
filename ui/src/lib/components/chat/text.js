/* Pure helpers for the chat: turning a body into segments the markup renders
   as plain text nodes (never {@html}), and the small date/name formatting the
   thread needs. No Svelte here. */

const URL_RE = /\bhttps?:\/\/[^\s<>"'`]+/gi;
const TRAIL = /[.,;:!?)\]}'"’”]+$/;

/** Split text into [{t:'text'|'link', v, href?}] — links auto-detected. */
function links(text) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(URL_RE)) {
    let url = m[0];
    /* keep a closing paren that belongs to the URL, drop sentence punctuation */
    let tail = '';
    const t = url.match(TRAIL);
    if (t) {
      tail = t[0];
      url = url.slice(0, -tail.length);
      const opens = (url.match(/\(/g) || []).length;
      const closes = (url.match(/\)/g) || []).length;
      if (tail.startsWith(')') && opens > closes) {
        url += ')';
        tail = tail.slice(1);
      }
    }
    if (m.index > last) out.push({ t: 'text', v: text.slice(last, m.index) });
    if (url.length > 8) out.push({ t: 'link', v: url, href: url });
    else out.push({ t: 'text', v: url });
    last = m.index + m[0].length - tail.length;
  }
  if (last < text.length) out.push({ t: 'text', v: text.slice(last) });
  return out;
}

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** Build a matcher for @mentions from the people list — longest name first,
    case-insensitive, ending at a non-word character (the server's rule). */
export function mentionMatcher(people) {
  const names = [];
  for (const p of people || []) {
    if (p.display_name) names.push({ n: p.display_name, p });
    if (p.username) names.push({ n: p.username, p });
  }
  names.push({ n: 'everyone', p: null }, { n: 'here', p: null });
  names.sort((a, b) => b.n.length - a.n.length);
  if (!names.length) return null;
  const re = new RegExp('@(' + names.map((x) => escapeRe(x.n)).join('|') + ')(?![\\p{L}\\p{N}_])', 'giu');
  const lookup = new Map(names.map((x) => [x.n.toLowerCase(), x.p]));
  return { re, lookup };
}

/** Segments for a message body: text, link and mention pieces.
    Only what the server actually recorded is highlighted: an @name that
    resolves to a user in `mentionIds`, or @everyone/@here when the viewer
    is in `mentionIds` and did not write it (a non-admin's @everyone
    mentions nobody, so it stays plain text). */
export function segments(body, matcher, { mentionIds = [], meId = null, mine = false } = {}) {
  const out = [];
  for (const s of links(body || '')) {
    if (s.t !== 'text' || !matcher) { out.push(s); continue; }
    const text = s.v;
    let last = 0;
    matcher.re.lastIndex = 0;
    for (const m of text.matchAll(matcher.re)) {
      const before = m.index > 0 ? text[m.index - 1] : '';
      if (before && /[\p{L}\p{N}_]/u.test(before)) continue;   // an e-mail, not a mention
      const p = matcher.lookup.get(m[1].toLowerCase());
      let hit = false;
      let me = false;
      if (p) {
        hit = mentionIds.includes(p.id);
        me = hit && p.id === meId && !mine;
      } else {
        hit = !mine && meId != null && mentionIds.includes(meId);
        me = hit;
      }
      if (!hit) continue;
      if (m.index > last) out.push({ t: 'text', v: text.slice(last, m.index) });
      out.push({ t: 'mention', v: m[0], me });
      last = m.index + m[0].length;
    }
    if (last < text.length) out.push({ t: 'text', v: text.slice(last) });
  }
  return out;
}

export function initials(name) {
  const parts = (name || '?').trim().split(/\s+/).filter(Boolean).slice(0, 2);
  return parts.map((p) => [...p][0]).join('').toUpperCase() || '?';
}

export function when(at) {
  if (!at) return null;
  /* the server writes UTC without a zone in places; read it as UTC */
  const s = typeof at === 'string' && /^\d{4}-\d\d-\d\d[ T]\d\d:\d\d(:\d\d(\.\d+)?)?$/.test(at)
    ? at.replace(' ', 'T') + 'Z' : at;
  const d = new Date(s);
  return isNaN(d) ? null : d;
}

export function hhmm(at) {
  const d = when(at);
  return d ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : '';
}

export function dayKey(at) {
  const d = when(at);
  return d ? d.toDateString() : '';
}

export function dayLabel(at) {
  const d = when(at);
  if (!d) return '';
  const today = new Date();
  const yest = new Date(today);
  yest.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return 'Today';
  if (d.toDateString() === yest.toDateString()) return 'Yesterday';
  return d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' });
}

/** "2m", "3h", "Tue" — for channel previews. */
export function shortAgo(at) {
  const d = when(at);
  if (!d) return '';
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return 'now';
  if (s < 3600) return Math.floor(s / 60) + 'm';
  if (s < 86400) return Math.floor(s / 3600) + 'h';
  if (s < 6 * 86400) return d.toLocaleDateString([], { weekday: 'short' });
  return d.toLocaleDateString([], { day: 'numeric', month: 'short' });
}

export const isHttp = (u) => {
  try {
    const x = new URL(u);
    return (x.protocol === 'http:' || x.protocol === 'https:') && !!x.hostname;
  } catch {
    return false;
  }
};

export const domainOf = (u) => {
  try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return ''; }
};
