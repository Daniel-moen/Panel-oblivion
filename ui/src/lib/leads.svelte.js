/* Lead-management state: the Today payload is shared between the sidebar
   badge and the Today page, and refreshed after every action. */

import { api } from './api.js';
import { toast } from './state.svelte.js';

export const leads = $state({ today: null, meta: null });

export async function loadToday() {
  try { leads.today = await api.panelToday(); } catch { /* transient */ }
  if (!leads.meta) { try { leads.meta = await api.panelMeta(); } catch { /* ignore */ } }
}

export async function taskDone(t) {
  try { await api.taskDone(t.id, !t.done_at); await loadToday(); }
  catch (e) { toast(e.message, 'error'); }
}

export async function snooze(t, days) {
  try { await api.snooze(t.id, days); toast(`Snoozed ${days === 1 ? 'to tomorrow' : days + ' days'}`, 'ok'); await loadToday(); }
  catch (e) { toast(e.message, 'error'); }
}

/* 082 123 4567 → 27821234567 for wa.me; leaves foreign numbers alone */
export function waNumber(phone) {
  if (!phone) return null;
  let d = String(phone).replace(/\D/g, '');
  if (d.startsWith('0') && d.length === 10) d = '27' + d.slice(1);
  return d.length >= 10 ? d : null;
}

export const addrOf = (p) => p?.street_address_raw || p?.official_address || p?.title || p?.group_id || '—';
