/* Unit tests for Home's one sentence ($lib/suggest.js).

   Run:  cd ui && npm test        (node --test tests/, no dependencies)

   suggest() is pure, so every case builds its inputs by hand: a fixed local
   `now`, a /api/panel/today payload (`today`), a /api/home payload (`home`)
   and an /api/status payload (`status`). Dates are built with local Date
   methods, so the expectations hold in any TZ. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { suggest } from '../src/lib/suggest.js';

const NOW = new Date(2026, 8, 25, 9, 30);                // 25 Sep 2026 09:30 local

/** 'YYYY-MM-DD' for NOW + n local days. */
function dayPlus(n) {
  const d = new Date(NOW.getFullYear(), NOW.getMonth(), NOW.getDate() + n);
  const p = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
const hhmmOf = (d) => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;

const prop = (street, gid) => ({ street_address_raw: street, group_id: gid });
const NEXT = new Date(Date.UTC(2026, 8, 25, 23, 0));      // an ISO instant; shown in local time
const NEXT_HHMM = hhmmOf(NEXT);

const emptyToday = () => ({ overdue: [], due_today: [], expiring: [], stale: [] });
const quietHome = (fresh = 0) => ({
  tracked: 0, tracked_active: 0,
  series: { new_listings: [...Array(13).fill(3), fresh] },
  crawl: { running: false, next_crawl: NEXT.toISOString(), last_sweep: '2026-09-24T23:00:00Z' }
});

/** Everything at once: each rule of the 'needs' view has something to say. */
function everything() {
  return {
    view: 'needs', now: NOW,
    today: {
      overdue: [{ property: prop('12 Victoria Rd', 7) }, { property: prop('3 Other St', 8) }],
      due_today: [{ property: prop('5 Due Ave', 9) }],
      expiring: [{ expires_at: dayPlus(5), property: prop('44 Beach Rd', 42) }],
      stale: []
    },
    home: quietHome(4),
    status: { running: true, phase: 'fetching_pages', done: 3, total: 10 }
  };
}
/* Strip the top rule, one at a time, in priority order. */
const STRIP = [
  (i) => { i.today.overdue = []; },
  (i) => { i.today.due_today = []; },
  (i) => { i.today.expiring = []; },
  (i) => { i.status = { running: false }; },
  (i) => { i.home = quietHome(0); }
];
const ORDER = ['overdue', 'due', 'mandate', 'crawl', 'new', 'idle'];

// ——— the priority order of the default view ———

const CASES = [
  {
    name: 'overdue follow-ups',
    input: { today: { ...emptyToday(), overdue: [{ property: prop('12 Victoria Rd', 7) }, { property: prop('3 X St', 8) }] }, home: quietHome() },
    key: 'overdue', text: /^2 follow-ups overdue — start with 12 Victoria Rd\.$/, href: '/leads'
  },
  {
    name: 'one overdue is singular',
    input: { today: { ...emptyToday(), overdue: [{ property: prop('12 Victoria Rd', 7) }] }, home: quietHome() },
    key: 'overdue', text: /^1 follow-up overdue/, href: '/leads'
  },
  {
    name: 'due today',
    input: { today: { ...emptyToday(), due_today: [{}, {}, {}] }, home: quietHome() },
    key: 'due', text: /^3 follow-ups due today\.$/, href: '/leads'
  },
  {
    name: 'mandate expiring in 5 days names the street',
    input: { today: { ...emptyToday(), expiring: [{ expires_at: dayPlus(5), property: prop('44 Beach Rd', 42) }] }, home: quietHome() },
    key: 'mandate', text: /^The mandate on 44 Beach Rd expires in 5 days\.$/, href: '/leads/properties/42'
  },
  {
    name: 'mandate expiring exactly 14 days out still fires',
    input: { today: { ...emptyToday(), expiring: [{ expires_at: dayPlus(14), property: prop('1 Edge Rd', 3) }] }, home: quietHome() },
    key: 'mandate', text: /1 Edge Rd expires in 14 days/, href: '/leads/properties/3'
  },
  {
    name: 'mandate expiring tomorrow',
    input: { today: { ...emptyToday(), expiring: [{ expires_at: dayPlus(1), property: prop('9 Soon St', 5) }] }, home: quietHome() },
    key: 'mandate', text: /9 Soon St expires tomorrow\./, href: '/leads/properties/5'
  },
  {
    name: 'the soonest of several mandates is named',
    input: { today: { ...emptyToday(), expiring: [
      { expires_at: dayPlus(10), property: prop('10 Later Rd', 10) },
      { expires_at: dayPlus(2), property: prop('2 Sooner Rd', 2) }] }, home: quietHome() },
    key: 'mandate', text: /2 Sooner Rd expires in 2 days/, href: '/leads/properties/2'
  },
  {
    name: 'a mandate 20 days out does NOT fire',
    input: { today: { ...emptyToday(), expiring: [{ expires_at: dayPlus(20), property: prop('20 Far Rd', 20) }] }, home: quietHome() },
    key: 'idle', href: '/prospects'
  },
  {
    name: 'an already expired mandate does not fire',
    input: { today: { ...emptyToday(), expiring: [{ expires_at: dayPlus(-2), property: prop('Old Rd', 1) }] }, home: quietHome() },
    key: 'idle'
  },
  {
    name: 'crawl running shows progress',
    input: { today: emptyToday(), home: quietHome(), status: { running: true, phase: 'fetching_pages', done: 3, total: 10 } },
    key: 'crawl', text: /^A crawl is running — 3 of 10 pages done\.$/, href: '/prospects', log: true
  },
  {
    name: 'crawl running needs no /api/home',
    input: { today: emptyToday(), home: null, status: { running: true, phase: 'scoring', done: 1, total: 1 } },
    key: 'crawl', text: /1 of 1 page done/
  },
  {
    name: 'new prospects since yesterday',
    input: { today: emptyToday(), home: quietHome(4) },
    key: 'new', text: /^4 new listings since midnight\.$/, href: '/prospects', sort: 'newest'
  },
  {
    name: 'idle names the next crawl in local HH:MM',
    input: { today: emptyToday(), home: quietHome(0) },
    key: 'idle', text: new RegExp(`^Nothing needs you right now\\. Next crawl at ${NEXT_HHMM}\\.$`), href: '/prospects'
  },
  {
    name: 'idle without a scheduled crawl says just the first sentence',
    input: { today: emptyToday(), home: { ...quietHome(0), crawl: { running: false, next_crawl: null } } },
    key: 'idle', text: /^Nothing needs you right now\.$/
  }
];

for (const c of CASES) {
  test(`needs: ${c.name}`, () => {
    const r = suggest({ view: 'needs', now: NOW, status: { running: false }, ...c.input });
    assert.ok(r, 'returns a suggestion');
    assert.equal(r.key, c.key);
    if (c.text) assert.match(r.text, c.text);
    assert.ok(r.cta && r.cta.label && r.cta.label.trim(), 'CTA has a label');
    if (c.href) assert.equal(r.cta.href, c.href);
    if (c.log) assert.equal(r.cta.log, true);
    if (c.sort) assert.equal(r.cta.filters?.sort, c.sort);
  });
}

test('needs is the default view', () => {
  const i = everything();
  delete i.view;
  assert.equal(suggest(i).key, 'overdue');
  assert.equal(suggest({ ...everything(), view: 'nonsense' }).key, 'overdue');
});

test('each higher rule beats every lower one', () => {
  const i = everything();
  for (let k = 0; k < ORDER.length; k++) {
    assert.equal(suggest(i)?.key, ORDER[k], `with the top ${k} rule(s) removed`);
    if (STRIP[k]) STRIP[k](i);
  }
});

test('the idle line at the end of the strip-down names the next crawl', () => {
  const i = everything();
  STRIP.forEach((s) => s(i));
  assert.equal(suggest(i).text, `Nothing needs you right now. Next crawl at ${NEXT_HHMM}.`);
});

// ——— loading states ———

test('loading: nothing fetched yet → null', () => {
  assert.equal(suggest({ view: 'needs', now: NOW }), null);
});

test('loading: today in, home still on its way → null (unless a higher rule fires)', () => {
  assert.equal(suggest({ view: 'needs', now: NOW, today: emptyToday(), home: null }), null);
  assert.equal(suggest({ view: 'needs', now: NOW, today: { ...emptyToday(), due_today: [{}] }, home: null }).key, 'due');
});

test('loading: home in, today still on its way → null', () => {
  assert.equal(suggest({ view: 'needs', now: NOW, today: null, home: quietHome(4) }), null);
});

test('loading: each other view returns null before its data', () => {
  for (const view of ['mandates', 'crawl', 'pipeline'])
    assert.equal(suggest({ view, now: NOW }), null, view);
});

// ——— todayFailed ———

test('todayFailed skips rules 1–3 and falls through to the crawl', () => {
  const i = { ...everything(), todayFailed: true };
  assert.equal(suggest(i).key, 'crawl');
});

test('todayFailed with no crawl says so, never "nothing needs you"', () => {
  const i = { ...everything(), todayFailed: true, status: { running: false } };
  const r = suggest(i);
  assert.equal(r.key, 'leads-off');
  assert.equal(r.text, 'Lead management is not answering right now.');
  assert.equal(r.cta.href, '/leads');
  assert.equal(suggest({ view: 'needs', now: NOW, todayFailed: true, homeFailed: true }).key, 'leads-off');
});

// ——— the other views ———

test("view 'mandates': soonest within 14 days, with the count of the rest", () => {
  const r = suggest({ view: 'mandates', now: NOW, today: { ...emptyToday(), expiring: [
    { expires_at: dayPlus(3), property: prop('3 A Rd', 3) },
    { expires_at: dayPlus(9), property: prop('9 B Rd', 9) },
    { expires_at: dayPlus(30), property: prop('30 C Rd', 30) }] } });
  assert.equal(r.key, 'mandates-soon');
  assert.equal(r.text, 'The mandate on 3 A Rd expires in 3 days, and 1 more within 14 days.');
  assert.equal(r.cta.href, '/leads/properties/3');
});

test("view 'mandates': nothing within 14 days names the next one", () => {
  const r = suggest({ view: 'mandates', now: NOW, today: { ...emptyToday(), expiring: [
    { expires_at: dayPlus(20), property: prop('20 Far Rd', 20) }] } });
  assert.equal(r.key, 'mandates-later');
  assert.match(r.text, /Next: 20 Far Rd in 20 days\./);
});

test("view 'crawl': a running crawl, else today's new listings", () => {
  const live = suggest({ view: 'crawl', now: NOW, home: quietHome(2), status: { running: true, phase: 'scoring', done: 5, total: 8 } });
  assert.equal(live.key, 'crawl-live');
  assert.match(live.text, /5 of 8 pages done/);
  assert.equal(live.cta.log, true);
  const done = suggest({ view: 'crawl', now: NOW, home: quietHome(2), status: { running: false } });
  assert.equal(done.key, 'crawl-new');
  assert.equal(done.text, `Today's crawl found 2 new listings. Next crawl at ${NEXT_HHMM}.`);
  assert.equal(done.cta.filters?.sort, 'newest');
});

test("view 'pipeline': leads in play of tracked, and the quiet ones", () => {
  const r = suggest({ view: 'pipeline', now: NOW, today: { ...emptyToday(), stale: [{}, {}] },
                      home: { ...quietHome(), tracked: 12, tracked_active: 5 } });
  assert.equal(r.key, 'pipeline');
  assert.equal(r.text, '5 leads in play of 12 tracked; 2 have gone quiet.');
  assert.equal(r.cta.href, '/leads/pipeline');
  const empty = suggest({ view: 'pipeline', now: NOW, home: quietHome() });
  assert.equal(empty.key, 'pipeline-empty');
});

// ——— CTA hrefs ———

test('CTA hrefs', () => {
  const base = { view: 'needs', now: NOW, status: { running: false } };
  const fu = suggest({ ...base, today: { ...emptyToday(), overdue: [{ property: prop('X', 1) }] }, home: quietHome() });
  assert.deepEqual([fu.cta.href, fu.cta.label], ['/leads', 'Open follow-ups']);
  const m = suggest({ ...base, today: { ...emptyToday(), expiring: [{ expires_at: dayPlus(2), property: prop('Y', 'g 7') }] }, home: quietHome() });
  assert.equal(m.cta.href, '/leads/properties/g%207');
  const nogid = suggest({ ...base, today: { ...emptyToday(), expiring: [{ expires_at: dayPlus(2), property: { street_address_raw: 'Z' } }] }, home: quietHome() });
  assert.equal(nogid.cta.href, '/leads');
  const c = suggest({ ...base, today: emptyToday(), home: quietHome(), status: { running: true } });
  assert.equal(c.cta.href, '/prospects');
  assert.equal(c.cta.log, true);
  const n = suggest({ ...base, today: emptyToday(), home: quietHome(3) });
  assert.equal(n.cta.href, '/prospects');
  assert.deepEqual(n.cta.filters, { sort: 'newest' });
});
