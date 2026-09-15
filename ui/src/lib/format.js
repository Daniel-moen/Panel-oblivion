export const fmtInt = (n) =>
  Math.round(n).toLocaleString('en-ZA').replace(/,/g, ' ');

export const fmtR = (p) => (p ? 'R' + fmtInt(p) : 'POA');

/* R28.5m — compact price for tight spots */
export const fmtM = (p) =>
  p ? 'R' + (p / 1e6).toFixed(p < 1e7 ? 2 : 1).replace(/\.?0+$/, '') + 'm' : 'POA';

/* 22 ha reads as 2.2 ha, not 22 000 m² */
export const fmtArea = (v) =>
  v == null
    ? null
    : v >= 10000
      ? (v / 10000).toLocaleString('en-ZA', { maximumFractionDigits: 1 }) + ' ha'
      : fmtInt(v) + ' m²';

/* ------------------------------------------------------------- rentals ---
   A rental's price is meaningless without its period: the same R25 000 is a
   bargain per month and a fortune per day. */
export const isRent = (r) => r.listing_type === 'rent';

/* R45 000/month for a rental, R12 500 000 for a sale. */
export const priceTxt = (r) =>
  isRent(r) && r.price_zar
    ? fmtR(r.price_zar) + (r.rent_period ? '/' + r.rent_period : '')
    : fmtR(r.price_zar);

/* Tight table cells: sales compress to R28.5m, a rent never should. */
export const priceShort = (r) => (isRent(r) ? priceTxt(r) : fmtM(r.price_zar));

/* Rent on one scale, so a per-day holiday let and a long let compare.
   365/12 and 52/12 rather than 30 and 4 — same basis as sources/base.py. */
const PER_MONTH = { month: 1, week: 52 / 12, day: 365 / 12 };
export const monthlyRent = (r) =>
  r.price_zar ? r.price_zar * (PER_MONTH[r.rent_period] ?? 1) : null;

/* furnished is stored as the portal printed it — 'Yes', 'No', or prose. */
export function furnishedTxt(v) {
  if (!v) return null;
  const s = String(v).trim();
  if (/^y/i.test(s)) return 'Furnished';
  if (/^n/i.test(s)) return 'Unfurnished';
  return s;
}

/* What a rental actually tells you, where a sale shows mandate proof. */
export function rentChips(r) {
  const out = [];
  if (r.available_from)
    out.push([`Available ${r.available_from}`, 'occupation date as the portal printed it']);
  const f = furnishedTxt(r.furnished);
  if (f) out.push([f, 'as advertised']);
  if (r.deposit) out.push([`Deposit ${fmtR(r.deposit)}`, '']);
  return out;
}

/* street_address is squashed for matching; _raw is what the portal printed */
export const addrOf = (r) => r.street_address_raw || r.street_address;

export const domTxt = (r) =>
  r.days_on_market != null ? r.days_on_market + ' days' : null;

export const mvLabel = (v) => (v || 'unknown').replace(/_/g, ' ');

export const satUrl = (lat, lng) =>
  `https://www.google.com/maps/place/${lat},${lng}/@${lat},${lng},110m/data=!3m1!1e3`;

/* Hero-photo src for a prospect row; null means "no photo known". */
export function photoSrc(r) {
  if (r.photo_url && r.photo_url !== '-') return r.photo_url;
  if (r.photo_url === '-' && !r.photo_key) return null;
  if (r.has_photo === false) return null;
  const key = r.photo_key || r.listing_key;
  return '/api/photo/' + encodeURIComponent(key);
}
