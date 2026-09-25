<script>
  /* The shell — one for the whole app.

     Every route lands inside the same furniture: the StatusStrip along the
     top, and either the Dock over the bottom edge (a phone, an iPad held
     upright) or the Rail down the left (an iPad on its side, a desktop).
     The switch is a CSS breakpoint at 1024px, the panel's own, so the two
     never fight over the same pixels.

     The page scrolls the document (not an inner pane): sticky table heads,
     iOS's rubber-banding and the home-screen app's status bar all behave
     when the body is the scroller. Two exceptions:

       /map   Leaflet needs the whole rectangle, so the scene is locked to
              the viewport and the page fills what the strip leaves.

     Page transitions fade on the SECTION, not the exact path: sub-navigation
     inside Media or Leads must not remount their segmented rows, or the
     highlight would jump instead of gliding. Those layouts fade their own
     children. */
  import '../app.css';
  import '$lib/mc.css';
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { fade } from '$lib/motion.js';
  import { app, startPolling, stopPolling } from '$lib/state.svelte.js';
  import { startChat } from '$lib/chat.svelte.js';
  import { loadMe } from '$lib/me.svelte.js';
  import StatusStrip from '$lib/components/glass/StatusStrip.svelte';
  import Dock from '$lib/components/glass/Dock.svelte';
  import Rail from '$lib/components/glass/Rail.svelte';
  import RunPanel from '$lib/components/RunPanel.svelte';
  import Toast from '$lib/components/Toast.svelte';
  import ChatWidget from '$lib/components/ChatWidget.svelte';

  let { children } = $props();

  const path = $derived(page.url.pathname);
  const section = $derived('/' + (path.split('/')[1] || ''));
  const isMap = $derived(path.startsWith('/map'));

  onMount(() => {
    /* Who is signed in, once for the whole app: the Dock, the Rail and the
       strip read it to decide which buttons are worth drawing. Fire and
       forget — the chrome renders complete until the answer lands. */
    loadMe();
    startPolling();
    const stopChat = startChat();
    return () => {
      stopPolling();
      stopChat();
    };
  });

  /* One Escape handler for the app's own overlays; Sheet, Drawer and
     ChatWidget own theirs, and stop the event before it reaches here. */
  function onKey(e) {
    if (e.key === 'Escape') {
      if (app.selectedKey) app.selectedKey = null;
      else if (app.runOpen) app.runOpen = false;
    }
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="mg-scene" class:map={isMap}>
  <Rail />

  <div class="col">
    <StatusStrip />

    {#if isMap}
      <!-- edge to edge: the map is the page -->
      <main class="edge">{@render children()}</main>
    {:else}
      <main class="mg-page">
        {#key section}
          <div class="view" in:fade={{ duration: 180, delay: 40 }}>{@render children()}</div>
        {/key}
      </main>
    {/if}
  </div>

  <Dock />

  <!-- Global, on every route: the crawl setup sheet, the one-line toast and
       the team-chat panel (its launcher lives in the strip). -->
  <RunPanel />
  <Toast />
  <ChatWidget />
</div>

<style>
  .mg-scene { display: flex; flex-direction: column; }
  .col { flex: 1; min-height: 0; display: flex; flex-direction: column; min-width: 0; }
  main { position: relative; }
  .view { display: flex; flex-direction: column; min-height: 0; flex: 1; }
  main.mg-page { flex: 1; display: flex; flex-direction: column; }

  /* the map route does not scroll: the page owns the viewport */
  .mg-scene.map { height: 100vh; height: 100dvh; overflow: hidden; }
  .mg-scene.map .col { height: 100%; }
  .edge { flex: 1; min-height: 0; width: 100%; position: relative; overflow: hidden; }

  /* from the rail breakpoint the column clears the rail and the dock's
     bottom clearance is no longer needed */
  @media (min-width: 1024px) {
    .col { padding-left: var(--mc-rail-w); }
    main.mg-page { padding-bottom: calc(var(--sab) + 32px); }
  }
</style>
