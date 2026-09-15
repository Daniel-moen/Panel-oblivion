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
