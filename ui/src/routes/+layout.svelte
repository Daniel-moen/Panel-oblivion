<script>
  /* The shell — one for the whole app.

     Every route lands inside the same furniture: the StatusStrip along the
     top and the floating Dock over the bottom edge — at EVERY width. There
     is no sidebar: a phone, an iPad either way up and a desktop navigate
     from the same pill of glass (a copy of Mission Control's dock), so the
     page column is simply centred, with the same gutters everywhere, and
     leaves `--mc-dock-clear` free at its foot for the dock to float over.

     The scene is the photograph (Backdrop) with ONE fixed sheet of glass
     (`.mg-pane`, mc.css) under the page column; the page scrolls over it.
     That keeps the blur budget at strip + dock + one sheet — the pane is a
     pre-blurred photo (Frost), not a live backdrop-filter.

     The page scrolls the document (not an inner pane): sticky table heads,
     iOS's rubber-banding and the home-screen app's status bar all behave
     when the body is the scroller. Two exceptions:

       /map   Leaflet needs the whole rectangle, so the scene is locked to
              the viewport and the page fills what the strip leaves; its
              floating controls keep clear of the dock themselves.
       /      Home is the photograph first: no fixed pane (Home draws its own
              glass one viewport down), no column padding, and the strip
              only while a crawl runs or a section posts a warning — pinned
              over the scene, so its arrival never pushes the greeting.

     Page transitions rise on the SECTION (fadeUp), not the exact path:
     sub-navigation inside Media or Leads must not remount their segmented
     rows, or the highlight would jump instead of gliding. Those layouts
     animate their own children. */
  import '../app.css';
  import '$lib/mc.css';
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { play, fadeUp } from '$lib/motion.js';
  import { app, startPolling, stopPolling } from '$lib/state.svelte.js';
  import { startChat } from '$lib/chat.svelte.js';
  import { loadMe } from '$lib/me.svelte.js';
  import { installTeam } from '$lib/team.svelte.js';
  import { shell, stripWanted } from '$lib/shell.svelte.js';
  import Backdrop from '$lib/components/glass/Backdrop.svelte';
  import Frost from '$lib/components/glass/Frost.svelte';
  import StatusStrip from '$lib/components/glass/StatusStrip.svelte';
  import Dock from '$lib/components/glass/Dock.svelte';
  import RunPanel from '$lib/components/RunPanel.svelte';
  import Toast from '$lib/components/Toast.svelte';
  import ChatWidget from '$lib/components/ChatWidget.svelte';
  import QuickLogSheet from '$lib/components/QuickLogSheet.svelte';

  let { children } = $props();

  const path = $derived(page.url.pathname);
  const section = $derived('/' + (path.split('/')[1] || ''));
  const isMap = $derived(path.startsWith('/map'));
  const isHome = $derived(path === '/');
  const showStrip = $derived(!isHome || stripWanted(app.status, shell.status));

  onMount(() => {
    /* Who is signed in, once for the whole app: the Dock and the strip
       read it to decide which buttons are worth drawing. Fire and
       forget — the chrome renders complete until the answer lands. */
    loadMe();
    startPolling();
    const stopChat = startChat();
    /* The team features (tasks, /online, presence) register their own nav
       and Home cards through shell.svelte.js; this is their only hook. */
    const stopTeam = installTeam(() => path);
    return () => {
      stopPolling();
      stopChat();
      stopTeam();
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

<div class="mg-scene" class:map={isMap} class:home={isHome}>
  <!-- The photograph, and the one sheet of glass the page scrolls over. The
       map is its own scene: Leaflet fills the rectangle, so no pane. -->
  <Backdrop />
  {#if !isMap && !isHome}<div class="mg-pane" aria-hidden="true"><Frost /></div>{/if}

  <div class="col">
    {#if !isHome}
      <StatusStrip />
    {:else if showStrip}
      <div class="scenestrip"><StatusStrip scene /></div>
    {/if}

    {#if isMap}
      <!-- edge to edge: the map is the page -->
      <main class="edge">{@render children()}</main>
    {:else}
      <main class="mg-page">
        {#key section}
          <div class="view" in:play={fadeUp}>{@render children()}</div>
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
  <QuickLogSheet />
</div>

<style>
  .mg-scene { display: flex; flex-direction: column; }
  .col { flex: 1; min-height: 0; display: flex; flex-direction: column; min-width: 0; }
  main { position: relative; z-index: 10; }
  .view { display: flex; flex-direction: column; min-height: 0; flex: 1; }
  main.mg-page { flex: 1; display: flex; flex-direction: column; }

  /* the map route does not scroll: the page owns the viewport */
  .mg-scene.map { height: 100vh; height: 100dvh; overflow: hidden; }
  .mg-scene.map .col { height: 100%; }
  .edge { flex: 1; min-height: 0; width: 100%; position: relative; overflow: hidden; }

  /* Home: the page is the scene, edge to edge; it pads its own overview. */
  .home main.mg-page { padding: 0; max-width: none; }
  .scenestrip { position: fixed; top: 0; left: 0; right: 0; z-index: 40; }
</style>
