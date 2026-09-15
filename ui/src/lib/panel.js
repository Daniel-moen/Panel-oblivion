/* Shared helpers for the management panel pages. */

export const STAGE_LABEL = {
  new: 'New', researching: 'Researching', contact_found: 'Contact found',
  contacted: 'Contacted', meeting: 'Meeting', valuation_sent: 'Valuation sent',
  mandate_signed: 'Mandate signed', listed: 'Listed', sold: 'Sold',
  lost: 'Lost', parked: 'Parked'
};
export const STAGE_ORDER = Object.keys(STAGE_LABEL);

export const MANDATE_LABEL = {
  sole: 'Sole', open: 'Open', dual: 'Dual', joint: 'Joint',
  sole_with_exclusion: 'Sole (excl.)', none_lost: 'Lost'
};

export const label = (v) => (v == null ? '' : String(v).replace(/_/g, ' '));

/* "3d ago" / "in 2d" / "today" from an ISO date or datetime */
export function ago(iso) {
  if (!iso) return null;
  const d = new Date(iso.length <= 10 ? iso + 'T00:00:00' : iso.replace(' ', 'T'));
  if (isNaN(d)) return iso;
  const days = Math.round((Date.now() - d.getTime()) / 86400000);
  if (days === 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days === -1) return 'tomorrow';
  if (days > 0) return days < 30 ? `${days}d ago` : `${Math.round(days / 30)}mo ago`;
  return `in ${-days}d`;
}

export const isPast = (iso) =>
  !!iso && new Date(iso.length <= 10 ? iso + 'T23:59:59' : iso.replace(' ', 'T')) < new Date();

export const shortDate = (iso) => (iso ? String(iso).slice(0, 10) : '—');
