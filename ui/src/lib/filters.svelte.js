/* Prospect-list filter state + the filter/sort pipeline. Lives outside the
   page component so the choices survive a hop to the map and back. */

import { app } from './state.svelte.js';

export const filters = $state({
  q: '', suburb: '', tier: '', mandate: '', erf: '',
  min: '', max: '', sort: 'score', view: 'cards'
});

export function clearFilters() {
  Object.assign(filters, { q: '', suburb: '', tier: '', mandate: '', erf: '', min: '', max: '' });
}

export const isFiltering = () =>
  !!(filters.q || filters.suburb || filters.tier || filters.mandate ||
     filters.erf || filters.min || filters.max);

const ERF_RESOLVED = ['ok', 'confirmed', 'check'];

/* The price box counts in millions for a sale and in thousands per period
   for a rental — R3–7m and R30–70k are the two ranges anyone types. */
export const priceScale = () => (app.dealType === 'rent' ? 1e3 : 1e6);

export function applyFilters(rows) {
  const q = filters.q.trim().toLowerCase();
  const scale = priceScale();
  const min = (parseFloat(filters.min) || 0) * scale;
  const max = (parseFloat(filters.max) || Infinity) * scale;
  return rows.filter((r) => {
    if (filters.suburb && r.suburb !== filters.suburb) return false;
    if (filters.tier && r.tier !== filters.tier) return false;
    if (filters.mandate && (r.mandate_verdict || 'unknown') !== filters.mandate) return false;
    if (filters.erf) {
      const st = r.erf_status || 'none';
      if (filters.erf === 'resolved' && !ERF_RESOLVED.includes(st)) return false;
      if (filters.erf === 'candidates' && st !== 'candidates') return false;
      if (filters.erf === 'unresolved' && (ERF_RESOLVED.includes(st) || st === 'candidates')) return false;
    }
    const p = r.price_zar || 0;
    if (p && (p < min || p > max)) return false;
    if (!p && min > 0) return false; /* POA hidden once a floor is set */
    if (q) {
      const hay = [r.title, r.suburb, r.property_type, r.street_address,
        r.street_address_raw, r.official_address, r.erf_number, r.pitch_angle,
        r.agent_name, (r.agencies || []).join(' ')].join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

const CMP = {
  score: (a, b) => ((b.prospect_score ?? -1) - (a.prospect_score ?? -1)) ||
                   ((b.price_zar || 0) - (a.price_zar || 0)),
  pricedesc: (a, b) => (b.price_zar || 0) - (a.price_zar || 0),
  priceasc: (a, b) => (a.price_zar || Infinity) - (b.price_zar || Infinity),
  newest: (a, b) => (a.days_on_market ?? 1e9) - (b.days_on_market ?? 1e9),
  cut: (a, b) => ((b.total_cut_pct ?? -1) - (a.total_cut_pct ?? -1)) ||
                 ((b.prospect_score ?? -1) - (a.prospect_score ?? -1)),
  weakness: (a, b) => ((b.marketing_weakness ?? -1) - (a.marketing_weakness ?? -1)) ||
                      ((b.prospect_score ?? -1) - (a.prospect_score ?? -1))
};

export function sortRows(rows) {
  return [...rows].sort(CMP[filters.sort] || CMP.score);
}
