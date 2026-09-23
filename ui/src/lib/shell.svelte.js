/* The chrome's letterbox.

   The TopBar is global — it is drawn once, by `routes/+layout.svelte`, for
   every route — but what belongs in its right-hand cluster is a page's
   business: Media knows whether it is indexing, the engine knows whether it
   is crawling, a future section will know something else.

   Rather than teach the TopBar about every section, sections post what they
   want it to show here and the TopBar reads it. Two slots, nothing more:

     shell.status   {tone, label, ping, href?, title?} | null
                    The status pill. `tone` is 'ok' (live / green), 'warn'
                    (needs you / amber), 'crit' (broken / red) or 'off'
                    (neutral grey). `ping` adds the expanding ring, and only
                    while something is genuinely happening. null means "you
                    decide" — the TopBar falls back to the engine's own state
                    (AI ready · crawling · AI off).

     shell.actions  [{ id, icon, label, href?, onclick?, tone? }]
                    Page-specific round glass buttons, shown to the LEFT of
                    the permanent ones (team chat, search, home). `icon` is a
                    name from components/glass/Icon.svelte; `label` is the
                    tooltip and the screen-reader name, so it is never
                    optional.

   Both are plain runes state — set them from a layout or page inside an
   `$effect`, and clear them in the effect's teardown so a section never
   leaves its status hanging over another one:

     $effect(() => { setStatus(mine); return clearStatus; });

   Nothing in here fetches or polls; it is a letterbox, not a store. */

export const shell = $state({
  status: null,
  actions: []
});

/** Post the status pill. Pass null (or nothing) to hand it back to the engine. */
export function setStatus(s) {
  shell.status = s || null;
}

/** Hand the pill back to its default. Safe to use as an $effect teardown. */
export function clearStatus() {
  shell.status = null;
}

/** Post the page's own round buttons. Pass [] (or nothing) to remove them. */
export function setActions(a) {
  shell.actions = Array.isArray(a) ? a : [];
}

/** Remove them. Safe to use as an $effect teardown. */
export function clearActions() {
  shell.actions = [];
}

/* The fallback the TopBar shows when no section has posted anything: the
   prospect engine's own state, which is the one thing true on every page.
   Kept here rather than inside the TopBar so a section can reuse it. */
export function engineStatus(status) {
  const s = status || {};
  if (s.running) {
    const n = s.total ? ` · ${s.done}/${s.total}` : '';
    return { tone: 'warn', label: `${s.phase || 'crawling'}${n}`, ping: true };
  }
  if (s.ai_ok) return { tone: 'ok', label: 'Live', ping: false };
  if (s.ai_reason) return { tone: 'off', label: 'AI off', ping: false, title: s.ai_reason };
  return { tone: 'off', label: 'Idle', ping: false };
}
