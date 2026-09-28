/* Prospect-list filters, the server query behind them, and saved views.

   The /prospects page no longer downloads the whole book and filters it
   here: it sends the filters to GET /api/prospects/query and gets one page
   of rows, the total and facet counts back (prospect_query.py documents
   every parameter). The parameter names ARE the filter keys below, so one
   query string serves the API, the page URL (bookmark / share a view), the
   CSV export and saved views alike.

   Filter state lives outside the page so the choices survive a hop to the
   map and back. Multi-value filters (tier, suburb, …) are comma-joined
   strings: '' is "any", 'hot' is one, 'hot,warm' is either. */

import { app, onListRefresh } from './state.svelte.js';
import { get, post, del } from './api.js';

/* key -> '' (unset). Order is the order chips are listed in. */
const BLANK = {
  q: '', tier: '', mandate: '', suburb: '', region: '', source: '', agency: '',
  ptype: '', price_min: '', price_max: '', beds_min: '', beds_max: '', baths_min: '',
  floor_min: '', floor_max: '', erf_min: '', erf_max: '', ppm2_min: '', ppm2_max: '',
  gv_min: '', gv_max: '', score_min: '', cut: '', reduced: '', dom_min: '', dom_max: '',
  relisted: '', off_min: '', under_offer: '', agencies_min: '', portals_min: '',
  expiry: '', dev: '', photo: '', erf: '', life: '', lead: '', furnished: '', available: ''
};
export const FILTER_KEYS = Object.keys(BLANK);

export const filters = $state({ ...BLANK, sort: 'score', view: 'cards' });

export function clearFilters() {
  Object.assign(filters, BLANK);
}

export const activeKeys = () => FILTER_KEYS.filter((k) => filters[k] !== '' && filters[k] != null);
export const isFiltering = () => activeKeys().length > 0;

/* ---------------------------------------------------- multi-value helpers */
export const listOf = (k) => (filters[k] ? String(filters[k]).split(',').filter(Boolean) : []);
export const has = (k, v) => listOf(k).includes(v);
export function toggle(k, v) {
  const cur = listOf(k);
  filters[k] = (cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v]).join(',');
}

/* The price box counts in millions for a sale and in thousands per month
   for a rental; the parameter is always whole rand. */
export const priceScale = () => (app.dealType === 'rent' ? 1e3 : 1e6);
export const priceShown = (k) => {
  const v = parseFloat(filters[k]);
  return Number.isFinite(v) ? String(+(v / priceScale()).toFixed(3)) : '';
};
export function setPrice(k, shown) {
  const v = parseFloat(String(shown).replace(',', '.'));
  filters[k] = Number.isFinite(v) && v > 0 ? String(Math.round(v * priceScale())) : '';
}

/* ------------------------------------------------------ query string ---- */
const defaultSort = () => (app.dealType === 'rent' ? 'pricedesc' : 'score');

/* The filters (+ sort, book, sole) as a query string. `page` adds the
   window; the URL and saved views never carry it. */
export function toParams({ page = null, book = true } = {}) {
  const p = new URLSearchParams();
  if (book) {
    if (app.dealType === 'rent') p.set('type', 'rent');
    if (app.showSole) p.set('sole', '1');
  }
  for (const k of FILTER_KEYS) {
    const v = filters[k];
    if (v !== '' && v != null) p.set(k, String(v).trim());
  }
  if (filters.sort && filters.sort !== defaultSort()) p.set('sort', filters.sort);
  if (page) {
    p.set('limit', String(page.limit));
    if (page.offset) p.set('offset', String(page.offset));
    if (page.facets === false) p.set('facets', '0');
  }
  return p;
}

/* Does this query string carry any filter at all (vs. just ?open=…)? */
export const hasFilterParams = (sp) =>
  FILTER_KEYS.some((k) => sp.has(k)) || sp.has('sort') || sp.has('type') || sp.has('sole');

/* Load filters from a query string (a URL, a saved view). Everything not in
   it is cleared. Returns the book / sole it asks for, which the caller
   applies (switching books clears rows, so it is not done here). */
export function fromParams(sp) {
  if (typeof sp === 'string') sp = new URLSearchParams(sp.replace(/^\?/, ''));
  clearFilters();
  for (const k of FILTER_KEYS) {
    const v = sp.get(k);
    if (v != null && v !== '') filters[k] = v;
  }
  const type = sp.get('type') === 'rent' ? 'rent' : 'sale';
  filters.sort = sp.get('sort') || (type === 'rent' ? 'pricedesc' : 'score');
  return { type, sole: sp.get('sole') === '1' };
}

/* ------------------------------------------------------------- chips ---- */
export const MANDATE_TXT = { open: 'Open', probably_open: 'Probably open', unknown: 'Unknown',
  probably_sole: 'Probably sole', sole: 'Sole' };
const LEAD_TXT = { untracked: 'Not tracked', tracked: 'Tracked' };
const LIFE_TXT = { active: 'Active', delisted: 'Delisted', relisted: 'Relisted' };
const ERF_TXT = { resolved: 'Erf resolved', candidates: 'Erf candidates', unresolved: 'Erf unresolved' };
const nice = (s) => String(s).replace(/_/g, ' ');
const R = (v) => {
  const n = +v;
  if (!Number.isFinite(n)) return v;
  return n >= 1e6 ? 'R' + +(n / 1e6).toFixed(2) + 'm' : n >= 1e3 ? 'R' + +(n / 1e3).toFixed(1) + 'k' : 'R' + n;
};
const range = (lo, hi, fmt = (x) => x, unit = '') =>
  lo && hi && +lo === +hi ? `${fmt(lo)}${unit}` :
  lo && hi ? `${fmt(lo)}–${fmt(hi)}${unit}` : lo ? `${fmt(lo)}+${unit}` : `≤ ${fmt(hi)}${unit}`;

/* [{ keys, label }] for every active filter — one chip per idea (a range
   is one chip, not two). The chip's ✕ clears all its keys. */
export function chips() {
  const out = [];
  const on = (k) => filters[k] !== '' && filters[k] != null;
  const add = (keys, label) => out.push({ keys, label });
  if (on('q')) add(['q'], `“${filters.q}”`);
  if (on('tier')) add(['tier'], 'Tier: ' + listOf('tier').join(', '));
  if (on('mandate')) add(['mandate'], 'Mandate: ' + listOf('mandate').map((m) => MANDATE_TXT[m] || m).join(', '));
  if (on('region')) add(['region'], listOf('region').join(', '));
  if (on('suburb')) add(['suburb'], listOf('suburb').join(', '));
  if (on('source')) add(['source'], 'On ' + listOf('source').join(', '));
  if (on('agency')) add(['agency'], 'Agency ~ ' + filters.agency);
  if (on('ptype')) add(['ptype'], listOf('ptype').join(', '));
  if (on('price_min') || on('price_max'))
    add(['price_min', 'price_max'], range(filters.price_min, filters.price_max, R, app.dealType === 'rent' ? ' pm' : ''));
  if (on('beds_min') || on('beds_max')) add(['beds_min', 'beds_max'], range(filters.beds_min, filters.beds_max, (x) => x, ' bed'));
  if (on('baths_min')) add(['baths_min'], `${filters.baths_min}+ bath`);
  if (on('floor_min') || on('floor_max')) add(['floor_min', 'floor_max'], 'Floor ' + range(filters.floor_min, filters.floor_max, (x) => x, ' m²'));
  if (on('erf_min') || on('erf_max')) add(['erf_min', 'erf_max'], 'Erf ' + range(filters.erf_min, filters.erf_max, (x) => x, ' m²'));
  if (on('ppm2_min') || on('ppm2_max')) add(['ppm2_min', 'ppm2_max'], range(filters.ppm2_min, filters.ppm2_max, R, '/m²'));
  if (on('gv_min') || on('gv_max')) add(['gv_min', 'gv_max'], 'Asking ' + range(filters.gv_min, filters.gv_max, (x) => x, '× GV'));
  if (on('score_min')) add(['score_min'], `Score ${filters.score_min}+`);
  if (on('cut')) add(['cut'], `Cut ${filters.cut}%+`);
  if (on('reduced')) add(['reduced'], 'Price reduced');
  if (on('dom_min') || on('dom_max')) add(['dom_min', 'dom_max'], range(filters.dom_min, filters.dom_max, (x) => x, ' days listed'));
  if (on('relisted')) add(['relisted'], filters.relisted === '0' ? 'Not relisted' : 'Relisted');
  if (on('off_min')) add(['off_min'], `${filters.off_min}+ days off market`);
  if (on('under_offer')) add(['under_offer'], filters.under_offer === '0' ? 'Not under offer' : 'Under offer');
  if (on('agencies_min')) add(['agencies_min'], `${filters.agencies_min}+ agencies`);
  if (on('portals_min')) add(['portals_min'], `${filters.portals_min}+ portals`);
  if (on('expiry')) add(['expiry'], 'Mandate expiry noted');
  if (on('dev')) add(['dev'], filters.dev === '0' ? 'No developments' : 'Developments');
  if (on('photo')) add(['photo'], filters.photo === '0' ? 'No photo' : 'Has photo');
  if (on('erf')) add(['erf'], ERF_TXT[filters.erf] || filters.erf);
  if (on('life')) add(['life'], listOf('life').map((v) => LIFE_TXT[v] || v).join(', '));
  if (on('lead')) add(['lead'], 'Lead: ' + listOf('lead').map((v) => LEAD_TXT[v] || nice(v)).join(', '));
  if (on('furnished')) add(['furnished'], filters.furnished === 'no' ? 'Unfurnished' : 'Furnished');
  if (on('available')) add(['available'], 'Available now');
  return out;
}

export function clearKeys(keys) {
  for (const k of keys) filters[k] = '';
}

/* ------------------------------------------------------- the query ---- */
export const PAGE = 60;

/* The result lives on app.list (state.svelte.js) so the drawer can find a
   row that came from it. */
let seq = 0;
let lastKey = '';
async function fetchWindow(offset, limit, { append = false, facets = true } = {}) {
  const qs = toParams({ page: { offset, limit, facets } }).toString();
  const mine = ++seq;
  app.list.loading = true;
  try {
    const d = await get('/api/prospects/query?' + qs);
    if (mine !== seq) return;
    if (append) {
      const seen = new Set(app.list.rows.map((r) => r.listing_key));
      app.list.rows = [...app.list.rows, ...d.rows.filter((r) => !seen.has(r.listing_key))];
    } else {
      app.list.rows = d.rows;
    }
    app.list.total = d.total;
    if (d.facets) app.list.facets = d.facets;
    app.list.summary = d.summary;
    app.list.book = d.type;
    app.list.loaded = true;
    app.list.error = null;
  } catch (e) {
    if (mine === seq) app.list.error = e.message || String(e);
  } finally {
    if (mine === seq) app.list.loading = false;
  }
}

/* A new filter set: page one. Identical asks (an effect re-running with
   nothing changed) are dropped. */
export function runQuery(force = false) {
  const key = toParams().toString();
  if (!force && key === lastKey && app.list.loaded) return Promise.resolve();
  lastKey = key;
  return fetchWindow(0, PAGE);
}

export function loadMore() {
  if (app.list.loading || app.list.rows.length >= app.list.total) return;
  return fetchWindow(app.list.rows.length, 120, { append: true, facets: false });
}

/* Refresh what is on screen in place (the poll while a crawl runs). Most of
   the time this is a bodiless 304. */
function refreshWindow() {
  if (!app.list.loaded || app.list.loading) return;
  return fetchWindow(0, Math.max(PAGE, Math.min(app.list.rows.length, 500)));
}

/* A page that shows the query result calls this on mount; the global poll
   then keeps it fresh while a crawl runs, and only while it is mounted. */
export function watchQuery() {
  return onListRefresh(refreshWindow);
}

export const exportUrl = () => '/api/prospects/export.csv?' + toParams().toString();

/* ------------------------------------------------------ saved views ---- */
export const views = $state({ list: [], presets: [], loaded: false });

export async function loadViews() {
  try {
    const d = await get('/api/prospects/views');
    views.list = d.views || [];
    views.presets = d.presets || [];
    views.loaded = true;
  } catch { /* transient: the bar just shows no views */ }
}

export async function saveView(name) {
  const v = await post('/api/prospects/views', { name, params: toParams().toString() });
  views.list = [...views.list.filter((x) => x.name.toLowerCase() !== v.name.toLowerCase()), v];
  return v;
}

export async function deleteView(id) {
  await del('/api/prospects/views/' + encodeURIComponent(id));
  views.list = views.list.filter((v) => v.id !== id);
}

/* Is this view's filter set the one on screen? (its chip lights up) */
export function viewActive(v) {
  const norm = (p) => [...p.entries()].filter(([, val]) => val !== '').map((e) => e.join('=')).sort().join('&');
  return norm(new URLSearchParams(v.params)) === norm(toParams());
}
