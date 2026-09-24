<script>
  /* The Media section, re-homed.

     The photograph, the clock, the status pill and the dock are the app's
     now — routes/+layout.svelte draws them for every route, and this file
     draws only what is Media's own: the two strips that explain a missing
     drive or a dead backend, the row of eight sub-sections, and the page.

     The sub-sections used to be a dock of their own. They are a segmented
     row at the top of the pane now (the Library pattern), because there is
     one dock in this app and it belongs to the sections, not to Media's
     insides. Under 720px the row scrolls sideways rather than wrapping — a
     control that changes height as you navigate moves under your thumb.

     What Media still owns in the chrome is its status: Live · n jobs ·
     Indexing. It posts that to `$lib/shell.svelte.js` and the global TopBar
     reads it, handing the pill back to the engine on the way out. */
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { fade } from 'svelte/transition';
  import { mstate, mtoast, boot, watchJobs } from '$lib/media.svelte.js';
  import { setStatus, clearStatus } from '$lib/shell.svelte.js';
  import MediaToasts from '$lib/components/MediaToasts.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';

  let { children } = $props();
  const path = $derived(page.url.pathname);

  onMount(() => { boot(); return watchJobs(); });

  const SECTIONS = [
    { value: '/media', label: 'Overview', icon: 'sparkles' },
    { value: '/media/browse', label: 'Browse', icon: 'grid' },
    { value: '/media/search', label: 'Search', icon: 'search' },
    { value: '/media/shoots', label: 'Shoots', icon: 'camera' },
    { value: '/media/calendar', label: 'Calendar', icon: 'calendar' },
    { value: '/media/edit', label: 'Photo editor', icon: 'sliders' },
    { value: '/media/hdr', label: 'HDR & Looks', icon: 'sun' },
    { value: '/media/video', label: 'Video editor', icon: 'film' },
    { value: '/media/tags', label: 'Tags', icon: 'tag' },
    { value: '/media/duplicates', label: 'Duplicates', icon: 'copy' },
    { value: '/media/shares', label: 'Portals', icon: 'share' },
    { value: '/media/files', label: 'Files', icon: 'folder' },
    { value: '/media/settings', label: 'Settings', icon: 'settings' }
  ];

  const here = $derived(
    SECTIONS.reduce(
      (best, s) => ((s.value === '/media' ? path === '/media' : path.startsWith(s.value)) ? s.value : best),
      '/media'
    )
  );

  /* One line describing whatever the backend is doing, for the status pill. */
  const working = $derived.by(() => {
    if (mstate.rescan?.running) return mstate.rescan.message || 'Indexing…';
    const n = mstate.jobs?.running?.length || 0;
    if (n) return `${n} job${n === 1 ? '' : 's'} running`;
    const q = mstate.proxies?.pending || 0;
    if (q) return `${q} prox${q === 1 ? 'y' : 'ies'} queued`;
    return null;
  });

  const status = $derived.by(() => {
    if (mstate.error) return { tone: 'crit', label: 'Offline', ping: false, href: '/media/settings' };
    if (working) return { tone: 'warn', label: working, ping: true, href: '/media/settings' };
    if (mstate.ready) return { tone: 'ok', label: 'Live', ping: false, href: '/media/settings' };
    return { tone: 'off', label: 'Connecting…', ping: true, href: '/media/settings' };
  });

  $effect(() => {
    setStatus(status);
    return clearStatus;
  });

  /* The backend sends this sentence already punctuated; the template supplies
     its own full stop, so strip a trailing one rather than print two. */
  const noDriveMsg = $derived(
    String(mstate.status?.media_root?.message ?? '').replace(/\.$/, '')
  );
</script>

<svelte:head><title>Media · Oblivion</title></svelte:head>

{#if mstate.error}
  <div class="mg-strip crit">
    <span class="ic"><Icon name="alert" size={15} /></span>
    <span>
      <b>Media library unavailable</b> — {mstate.error}
      {#if mstate.status?.backend_error}<br /><code>{mstate.status.backend_error}</code>{/if}
    </span>
  </div>
{:else if mstate.status && !mstate.status.media_root?.ok}
  <div class="mg-strip warn">
    <span class="ic"><Icon name="alert" size={15} /></span>
    <span>
      <b>No footage drive on this deployment</b> — {noDriveMsg}.
      The file store and share links still work; only the video catalogue needs the drive.
    </span>
  </div>
{/if}

<div class="sections mg-noscroll">
  <Seg options={SECTIONS} value={here} onchange={(v) => goto(v)} label="Media sections" />
</div>

{#key path}
  <div in:fade={{ duration: 180, delay: 60 }}>{@render children()}</div>
{/key}

<MediaToasts items={mtoast.items} />

<style>
  .sections { display: flex; margin-bottom: 16px; overflow-x: auto; padding-bottom: 2px; }
  @media (max-width: 720px) {
    /* the row keeps one line and scrolls; the pane's gutter stays clear */
    .sections { margin-left: -2px; margin-right: -2px; }
  }
</style>
