/* Who is signed in, for the chrome.

   One fetch of /api/me, done once by the root layout, held here so the Dock
   and the TopBar can read it without each asking. It is a COURTESY, not a
   control: every privilege is enforced server-side (auth.require_priv), and
   this only decides whether a button is worth drawing. A stale or missing
   `me` therefore has to fail OPEN — hiding the crawl button because a fetch
   was slow would be a worse bug than showing a button that 403s.

   Shape, straight from /api/me:
     id · username · display_name · role ('owner' | 'admin' | 'member')
     privileges (the EFFECTIVE list) · is_owner · via · passkeys

   `loaded` is how the chrome knows the answer has arrived; until then `can()`
   says yes to everything, which is the fail-open rule above. */

import { api } from './api.js';

export const me = $state({
  loaded: false,
  id: null,
  username: '',
  display_name: '',
  role: 'owner',
  privileges: [],
  is_owner: true,
  via: '',
  passkeys: 0
});

/** Fetch /api/me once. Safe to call again — a later call just refreshes it. */
export async function loadMe() {
  try {
    const got = await api.me();
    Object.assign(me, got, { loaded: true });
  } catch {
    /* Signed out, or the engine is down: api.js already sends the browser to
       /login on a 401. Leaving `loaded` false keeps the chrome complete. */
  }
  return me;
}

/** True when the signed-in account holds `flag` — or when we do not know yet. */
export function can(flag) {
  if (!me.loaded) return true;
  return me.privileges.includes(flag);
}

/** Admins and the owner see People and Invites. */
export const isAdmin = () => can('admin');
