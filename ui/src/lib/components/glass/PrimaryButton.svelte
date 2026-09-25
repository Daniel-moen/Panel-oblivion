<script>
  /* The app's ONE primary action — the Dock's raised round button, at every
     width (the panel's mic). Whatever the fastest useful thing is where you
     are standing, for the account you are signed in as:

       /media + may index    Re-index the library
       may crawl             New crawl — and while one is running it becomes
                             "view crawl progress", spinner and all, because
                             starting a second one is never what you meant
       otherwise             Quick log (the global sheet), which every
                             signed-in account may use

     So the dock always has its primary; it never draws a button that can
     only 403.

     The material is the reference's: 44px, the ink (white) fill, the icon in
     the scene's graphite at 20px / stroke 2, shadow-2, and `press` (scale
     .97 on spring.snappy) under a finger. `data-action` names what it will
     do, for the click-through checks. */
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import Icon from './Icon.svelte';
  import { app } from '$lib/state.svelte.js';
  import { mstate, runRescan } from '$lib/media.svelte.js';
  import { openQuickLog } from '$lib/shell.svelte.js';
  import { can } from '$lib/me.svelte.js';
  import { pressable } from '$lib/motion.js';

  const path = $derived(page.url.pathname);
  const scanning = $derived(!!mstate.rescan?.running);
  const crawling = $derived(!!app.status.running);

  /* Quick log about the property you are standing on, if you are on one. */
  function quickLog() {
    const m = path.match(/^\/leads\/properties\/([^/]+)/);
    openQuickLog(m ? decodeURIComponent(m[1]) : null);
  }

  const primary = $derived(
    path.startsWith('/media') && can('media')
      ? {
          action: 'reindex', icon: 'refresh',
          title: scanning ? 'Indexing the library…' : 'Re-index the library', busy: scanning,
          disabled: mstate.busy || !mstate.ready, go: () => runRescan()
        }
      : can('crawl')
        ? {
            action: 'crawl', icon: 'plus',
            title: crawling ? 'View crawl progress' : 'New crawl',
            busy: crawling, disabled: false,
            go: () => {
              if (!crawling) { app.runOpen = true; return; }
              app.logOpen = true;
              if (!path.startsWith('/prospects')) goto('/prospects');
            }
          }
        : { action: 'quicklog', icon: 'pencil', title: 'Quick log', busy: false, disabled: false, go: quickLog }
  );
</script>

<button type="button" class="go" use:pressable onclick={primary.go} disabled={primary.disabled}
        data-testid="dock-primary" data-action={primary.action} aria-busy={primary.busy || undefined}
        aria-label={primary.title} title={primary.title}>
  {#if primary.busy}<span class="mg-spin"></span>{:else}<Icon name={primary.icon} size={20} stroke={2} />{/if}
</button>

<style>
  .go {
    flex: none; width: 44px; height: 44px; border-radius: 9999px; border: 0; padding: 0;
    display: grid; place-items: center; cursor: pointer;
    background: var(--mc-ink); color: var(--mc-bg);
    box-shadow: var(--mc-sh-2);
  }
  .go:hover:not(:disabled) { background: #fff; }
  .go:disabled { opacity: 0.4; cursor: default; }
  .go .mg-spin { width: 18px; height: 18px; }
</style>
