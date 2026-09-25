/* The chrome's letterbox, and its extension points.

   The StatusStrip and the Dock are global — drawn once, by
   `routes/+layout.svelte`, for every route — but what belongs in the strip's
   right-hand cluster is a page's business: Media knows whether it is
   indexing, the engine knows whether it is crawling.

   Rather than teach the chrome about every section, sections post what they
   want it to show here and the chrome reads it:

     shell.status   {tone, label, ping, href?, title?} | null
                    The status readout. `tone` is 'ok' (live / green), 'warn'
                    (needs you / amber), 'crit' (broken / red) or 'off'
                    (neutral grey). `ping` adds the expanding ring, and only
                    while something is genuinely happening. null means "you
                    decide" — the chrome falls back to the engine's own state.

     shell.actions  [{ id, icon, label, href?, onclick?, tone? }]
                    Page-specific icon buttons in the strip, shown to the
                    LEFT of the permanent ones (team chat, account). `icon`
                    is a name from components/glass/Icon.svelte; `label` is
                    the tooltip and the screen-reader name, so it is never
                    optional.

   Both are plain runes state — set them from a layout or page inside an
   `$effect`, and clear them in the effect's teardown:

     $effect(() => { setStatus(mine); return clearStatus; });

   ——— extension points (other features drop in here) ———

     slots.nav      [{ href, label, icon, need? }]
                    Extra top-level sections. They render after the built-in
                    six in the Dock, in the same style (the dock is sized to
                    fit seven on a 390px phone — see glass/Dock.svelte). `need`
                    is a privilege flag (see me.svelte.js `can`) without
                    which the item is not drawn. Example, from a module that
                    runs at startup or a layout's onMount:

                      addNav({ href: '/online', label: 'Online', icon: 'users' });

     slots.home     [{ id, component, props? }]
                    Cards mounted on the Home route, in the column under the
                    figures (the "My tasks" card lives here). `component` is
                    a Svelte component; it is rendered inside a plain
                    wrapper and can style itself with the `.mg-*` vocabulary
                    or by reading the `--mc-*` CSS variables.

                      addHomeCard({ id: 'tasks', component: MyTasks });

   Nothing in here fetches or polls; it is a letterbox, not a store. */

import { untrack } from 'svelte';

export const shell = $state({
  status: null,
  actions: []
});

export const slots = $state({
  nav: [],
  home: []
});

/** Post the status readout. Pass null (or nothing) to hand it back to the engine. */
export function setStatus(s) {
  shell.status = s || null;
}

/** Hand the readout back to its default. Safe to use as an $effect teardown. */
export function clearStatus() {
  shell.status = null;
}

/** Post the page's own icon buttons. Pass [] (or nothing) to remove them. */
export function setActions(a) {
  shell.actions = Array.isArray(a) ? a : [];
}

/** Remove them. Safe to use as an $effect teardown. */
export function clearActions() {
  shell.actions = [];
}

/** Add a top-level section to the Dock (idempotent by href). */
export function addNav(item) {
  if (!item?.href) return;
  if (!slots.nav.some((n) => n.href === item.href)) slots.nav = [...slots.nav, item];
}

/** Remove a section added with addNav. */
export function removeNav(href) {
  slots.nav = slots.nav.filter((n) => n.href !== href);
}

/** Mount a card on Home (idempotent by id). */
export function addHomeCard(card) {
  if (!card?.id || !card.component) return;
  if (!slots.home.some((c) => c.id === card.id)) slots.home = [...slots.home, card];
}

/** Remove a card added with addHomeCard. */
export function removeHomeCard(id) {
  slots.home = slots.home.filter((c) => c.id !== id);
}

/* The fallback the chrome shows when no section has posted anything: the
   prospect engine's own state, which is the one thing true on every page. */
export function engineStatus(status) {
  const s = status || {};
  if (s.running) {
    /* Sentence case, like the panel: "Crawling portals", not "Crawling Portals". */
    const p = String(s.phase || 'crawling');
    const n = s.total ? ` · ${s.done}/${s.total}` : '';
    return { tone: 'warn', label: `${p[0].toUpperCase()}${p.slice(1)}${n}`, ping: true };
  }
  if (s.ai_ok) return { tone: 'ok', label: 'Live', ping: false };
  if (s.ai_reason) return { tone: 'off', label: 'AI off', ping: false, title: s.ai_reason };
  return { tone: 'off', label: 'Idle', ping: false };
}

/* The built-in sections, in dock order. `need` hides a section from an
   account without the privilege (only Media: without a token there is no
   library to open). Everything else is readable by everyone signed in. */
export const SECTIONS = [
  { href: '/', label: 'Home', icon: 'home' },
  { href: '/prospects', label: 'Prospects', icon: 'building' },
  { href: '/agent', label: 'Agent Z', icon: 'bolt' },
  { href: '/leads', label: 'Leads', icon: 'users' },
  { href: '/map', label: 'Map', icon: 'mapPin' },
  { href: '/media', label: 'Media', icon: 'film', need: 'media' }
];

/** True when `path` is inside the section at `href`. */
export const inSection = (href, path) => (href === '/' ? path === '/' : path.startsWith(href));

/* ——— the scene (Home) and the two global tools ———

     chrome.quiet     true when the Dock should step out of the way (Home,
                      after 3 s without input, at every width). It slides
                      off with a transform + fade only; any tap, scroll or
                      key brings it back. Never set for prefers-reduced-motion.
     chrome.frost     the url glass/Frost.svelte shows (the hour's pre-blurred
                      photo), set by Backdrop; `frostLive` when it is a
                      custom photo that has to be blurred by a filter.
     chrome.quickLog  { open, gid } — the global Quick log sheet
                      (components/QuickLogSheet.svelte, mounted once by the
                      layout). gid null = pick a property first.

   Home owns `quiet` (armed on mount, cleared on destroy). The layout decides
   the scene itself, from the route, so the first frame is already right. */
export const chrome = $state({
  quiet: false,
  frost: '',
  frostLive: false,
  quickLog: { open: false, gid: null },
  modal: 0
});

/* ——— modals and the dock ———
     The dock floats above everything (z-60), sheets included, as the
     panel's does. But while a modal (aria-modal) sheet or drawer is open the
     page behind is out of reach, so the dock must be too: each modal holds
     `chrome.modal` while it is open and the dock goes inert (and dims) until
     the count is back to zero. Returns the release; use it as an $effect
     teardown. */
export function holdModal() {
  /* untracked: called from an $effect, a tracked read of the count it
     writes would make that effect re-run itself forever */
  untrack(() => (chrome.modal += 1));
  let held = true;
  return () => {
    if (!held) return;
    held = false;
    untrack(() => (chrome.modal = Math.max(0, chrome.modal - 1)));
  };
}

/** Open the Quick log sheet, optionally already about one property group. */
export function openQuickLog(gid = null) {
  chrome.quickLog = { open: true, gid: gid == null ? null : String(gid) };
}

export function closeQuickLog() {
  chrome.quickLog = { open: false, gid: null };
}

/** The strip is worth drawing on the scene only while something is happening. */
export function stripWanted(status, posted) {
  if (status?.running) return true;
  return !!posted && (posted.tone === 'warn' || posted.tone === 'crit');
}
