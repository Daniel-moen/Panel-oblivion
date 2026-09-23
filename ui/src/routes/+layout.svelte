<script>
  /* The scene — one shell for the whole app.

     Every route lands inside the same three pieces of furniture: the
     photograph behind everything, the TopBar above it, the Dock over the
     bottom edge. There is no second navigation anywhere: no sidebar, no
     sticky header, no back links. A page draws its own header row INSIDE the
     pane and nothing outside it.

     Two exceptions, both structural:

       /      Home is the resting state. It gets no pane — the greeting, the
              one sentence and the attention cards float straight on the
              photograph.
       /map   Leaflet needs the whole rectangle, so its pane is edge to edge,
              full height, zero padding and no glass (the tiles cover it
              anyway, and a viewport-sized blur is an expensive way to draw
              nothing).

     Page transitions fade on the SECTION, not the exact path: sub-navigation
     inside Media or Leads must not remount their segmented rows, or the
     highlight would jump instead of gliding. Those layouts fade their own
     children. */
  import '../app.css';
  import '$lib/glass.css';
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { fade } from 'svelte/transition';
  import { app, startPolling, stopPolling } from '$lib/state.svelte.js';
  import { startChat } from '$lib/chat.svelte.js';
  import { loadMe } from '$lib/me.svelte.js';
  import Backdrop from '$lib/components/glass/Backdrop.svelte';
  import TopBar from '$lib/components/glass/TopBar.svelte';
  import Dock from '$lib/components/glass/Dock.svelte';
  import RunPanel from '$lib/components/RunPanel.svelte';
  import Toast from '$lib/components/Toast.svelte';
  import ChatWidget from '$lib/components/ChatWidget.svelte';

  let { children } = $props();

  const path = $derived(page.url.pathname);
  const section = $derived('/' + (path.split('/')[1] || ''));
  const isHome = $derived(path === '/');
  const isMap = $derived(path.startsWith('/map'));

  onMount(() => {
    /* Who is signed in, once for the whole app: the Dock and the TopBar read
       it to decide which buttons are worth drawing. Fire and forget — the
       chrome renders complete until the answer lands (me.svelte.js). */
    loadMe();
    startPolling();
    const stopChat = startChat();
    return () => {
      stopPolling();
      stopChat();
    };
  });

  /* One Escape handler for the app's own overlays; Sheet and ChatWidget own
     theirs, and stop the event before it reaches here. */
  function onKey(e) {
    if (e.key === 'Escape') {
      if (app.selectedKey) app.selectedKey = null;
      else if (app.runOpen) app.runOpen = false;
    }
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="mg-scene" class:full={isMap}>
  <Backdrop />
  <TopBar />

  {#if isHome}
    <main class="open">
      {#key section}
        <div class="fill" in:fade={{ duration: 180, delay: 60 }}>{@render children()}</div>
      {/key}
    </main>
  {:else if isMap}
    <!-- edge to edge: the map is the page -->
    <main class="edge">{@render children()}</main>
  {:else}
    <main class="pane mg-glass mg-page">
      {#key section}
        <div in:fade={{ duration: 180, delay: 60 }}>{@render children()}</div>
      {/key}
    </main>
  {/if}

  <Dock />

  <!-- Global, on every route: the crawl setup slide-over, the one-line toast
       and the team-chat panel (its launcher lives in the TopBar). -->
  <RunPanel />
  <Toast />
  <ChatWidget />
</div>

<style>
  .mg-scene { display: flex; flex-direction: column; }
  /* the map route does not scroll: the pane owns the viewport */
  .mg-scene.full { height: 100vh; height: 100svh; overflow: hidden; }

  main { position: relative; z-index: 10; }

  .open, .fill { flex: 1; min-height: 0; display: flex; flex-direction: column; }

  .pane {
    width: calc(100% - clamp(32px, 6vw, 64px));
    max-width: 1400px;
    margin: 0 auto;
  }

  .edge {
    flex: 1; min-height: 0; width: 100%;
    position: relative; overflow: hidden;
  }
</style>
