<script>
  /* The app's ONE primary action, wherever it is drawn (the strip on a
     phone, the rail's foot on an iPad): whatever the fastest useful thing is
     where you are standing. On /media that is Re-index; everywhere else it is
     a new crawl — and while a crawl is running it becomes "view progress",
     spinner and all, because starting a second one is never what you meant.

     Without the privilege that action needs, nothing is drawn at all: a
     raised button that can only 403 is a lie.

     Props:
       wide   true → a full-width labelled button (the rail); false → a
              round icon button (the strip). */
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import Icon from './Icon.svelte';
  import { app } from '$lib/state.svelte.js';
  import { mstate, runRescan } from '$lib/media.svelte.js';
  import { can } from '$lib/me.svelte.js';

  let { wide = false } = $props();

  const path = $derived(page.url.pathname);
  const onMedia = $derived(path.startsWith('/media'));
  const scanning = $derived(!!mstate.rescan?.running);
  const crawling = $derived(!!app.status.running);
  const mayAct = $derived(onMedia ? can('media') : can('crawl'));

  const primary = $derived(
    onMedia
      ? {
          icon: 'refresh', label: scanning ? 'Indexing…' : 'Re-index',
          title: 'Re-index the library', busy: scanning,
          disabled: mstate.busy || !mstate.ready, go: () => runRescan()
        }
      : {
          icon: crawling ? 'clock' : 'plus',
          label: crawling ? 'Crawl progress' : 'New crawl',
          title: crawling ? 'View crawl progress' : 'Start a new crawl',
          busy: crawling, disabled: false,
          go: () => {
            if (!crawling) { app.runOpen = true; return; }
            app.logOpen = true;
            if (!path.startsWith('/prospects')) goto('/prospects');
          }
        }
  );
</script>

{#if mayAct}
  {#if wide}
    <button type="button" class="mg-btn primary wide" onclick={primary.go} disabled={primary.disabled}
            title={primary.title}>
      {#if primary.busy}<span class="mg-spin"></span>{:else}<Icon name={primary.icon} size={16} stroke={2.2} />{/if}
      {primary.label}
    </button>
  {:else}
    <button type="button" class="go" onclick={primary.go} disabled={primary.disabled}
            aria-label={primary.title} title={primary.title}>
      {#if primary.busy}<span class="mg-spin"></span>{:else}<Icon name={primary.icon} size={20} stroke={2.2} />{/if}
    </button>
  {/if}
{/if}

<style>
  .wide { width: 100%; }
  .go {
    flex: none; width: 40px; height: 40px; border-radius: 9999px; border: 0; padding: 0;
    display: grid; place-items: center; cursor: pointer;
    background: var(--mc-ink); color: var(--mc-bg);
    box-shadow: 0 6px 18px -6px rgba(0, 0, 0, 0.6);
    transition: background var(--mc-t-fast), transform 120ms var(--mc-ease), opacity var(--mc-t-fast);
  }
  .go:hover:not(:disabled) { background: #fff; }
  .go:active:not(:disabled) { transform: scale(0.94); }
  .go:disabled { opacity: 0.4; cursor: default; }
  @media (pointer: coarse) { .go { width: 44px; height: 44px; } }
  @media (prefers-reduced-motion: reduce) { .go:active:not(:disabled) { transform: none; } }
</style>
