<script>
  /* The floating dock: the app's ONLY navigation, parked over the bottom edge
     where a thumb already is. There is no nav bar and no sidebar anywhere.

     One highlight pill glides between the six sections — measured, not faded:
     the active link's offset and width are read and the pill's transform and
     width are transitioned, which keeps the motion on the compositor. Below
     900px the labels go and it becomes an icon rail; if even that overflows
     the rail scrolls sideways rather than wrapping, because a dock that
     changes height as you navigate is a dock that moves under your thumb.

     After a hairline divider sits the raised white primary button — the one
     primary fill on screen. It is whatever the fastest useful thing is where
     you are standing: on /media that is Re-index, everywhere else it is a new
     crawl (and while a crawl is running it becomes "view progress", spinner
     and all, because starting a second one is never what you meant). Without
     the privilege that action needs, it is not drawn at all — and neither is
     the Media section for an account that cannot open the library.

     No props: it reads the route and the two pieces of app state it needs. */
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import Icon from './Icon.svelte';
  import { app } from '$lib/state.svelte.js';
  import { mstate, runRescan } from '$lib/media.svelte.js';
  import { can } from '$lib/me.svelte.js';

  /* `need` is a privilege the section cannot be used without at all — only
     Media has one, because without a token there is no library to open. The
     other five are readable by everyone signed in, so they are never hidden;
     the server refuses the writes. */
  const ALL = [
    { href: '/', label: 'Home', icon: 'sparkles' },
    { href: '/prospects', label: 'Prospects', icon: 'building' },
    { href: '/agent', label: 'Agent Z', icon: 'bolt' },
    { href: '/leads', label: 'Leads', icon: 'users' },
    { href: '/map', label: 'Map', icon: 'mapPin' },
    { href: '/media', label: 'Media', icon: 'film', need: 'media' }
  ];

  const ITEMS = $derived(ALL.filter((it) => !it.need || can(it.need)));

  const path = $derived(page.url.pathname);
  const activeIdx = $derived(
    ITEMS.reduce(
      (best, it, i) => ((it.href === '/' ? path === '/' : path.startsWith(it.href)) ? i : best),
      0
    )
  );

  let rail = $state(null);
  let links = $state([]);
  let pill = $state({ x: 0, w: 0, ready: false });

  function measure() {
    const el = links[activeIdx];
    if (!el || !el.offsetWidth) { pill = { x: 0, w: 0, ready: false }; return; }
    pill = { x: el.offsetLeft, w: el.offsetWidth, ready: true };
  }

  $effect(() => { activeIdx; links.length; measure(); });

  $effect(() => {
    if (!rail || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => measure());
    ro.observe(rail);
    return () => ro.disconnect();
  });

  /* ——— the primary button ——— */
  const onMedia = $derived(path.startsWith('/media'));
  const scanning = $derived(!!mstate.rescan?.running);
  const crawling = $derived(!!app.status.running);

  /* The one primary fill on screen is also the one action that always
     WRITES, so it goes away entirely without the privilege behind it —
     a raised white button that can only 403 is a lie. */
  const mayAct = $derived(onMedia ? can('media') : can('crawl'));

  const primary = $derived(
    onMedia
      ? {
          icon: 'refresh',
          label: 'Re-index the library',
          busy: scanning,
          disabled: mstate.busy || !mstate.ready,
          go: () => runRescan()
        }
      : {
          icon: crawling ? 'clock' : 'plus',
          label: crawling ? 'View crawl progress' : 'New crawl',
          busy: crawling,
          disabled: false,
          /* The activity log is the engine page's strip, so "view progress"
             means "take me to the engine" — from anywhere. */
          go: () => {
            if (!crawling) { app.runOpen = true; return; }
            app.logOpen = true;
            if (!path.startsWith('/prospects')) goto('/prospects');
          }
        }
  );
</script>

<div class="dock-wrap">
  <nav class="dock mg-glass" aria-label="Sections">
    <!-- The rail scrolls; the highlight is inside it so it travels with it. -->
    <div class="rail mg-noscroll" bind:this={rail}>
      <span class="pill mg-pill" aria-hidden="true" class:ready={pill.ready}
            style:transform="translateX({pill.x}px)" style:width="{pill.w}px"></span>
      {#each ITEMS as it, i (it.href)}
        <a href={it.href} bind:this={links[i]} class:on={i === activeIdx}
           aria-label={it.label} aria-current={i === activeIdx ? 'page' : undefined}>
          <Icon name={it.icon} size={18} />
          <span class="lb">{it.label}</span>
        </a>
      {/each}
    </div>

    {#if mayAct}
      <span class="div" aria-hidden="true"></span>

      <button type="button" class="go" onclick={primary.go} disabled={primary.disabled}
              aria-label={primary.label} title={primary.label}>
        {#if primary.busy}<span class="mg-spin"></span>{:else}<Icon name={primary.icon} size={19} stroke={2} />{/if}
      </button>
    {/if}
  </nav>
</div>

<style>
  .dock-wrap {
    position: fixed; left: 0; right: 0; bottom: 0; z-index: 60;
    display: flex; justify-content: center;
    padding: 0 12px calc(var(--mg-sab, 0px) + 14px);
    pointer-events: none;
  }
  .dock {
    pointer-events: auto;
    display: flex; align-items: center; gap: 4px;
    padding: 6px; border-radius: 9999px; max-width: 100%;
    animation: dock-in 0.42s cubic-bezier(0.2, 0.8, 0.2, 1) both;
  }
  @keyframes dock-in { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: none; } }

  .rail {
    position: relative; display: flex; align-items: center; gap: 2px;
    min-width: 0; overflow-x: auto; overscroll-behavior-x: contain;
  }

  /* The one highlight. Parked at width 0 until the first measurement lands,
     so it never flashes at the left edge on the first paint. */
  .pill {
    position: absolute; left: 0; top: 0; bottom: 0; width: 0;
    background: rgba(255, 255, 255, 0.14); opacity: 0;
    transition: transform 0.32s cubic-bezier(0.2, 0.8, 0.2, 1),
                width 0.32s cubic-bezier(0.2, 0.8, 0.2, 1), opacity 0.2s;
    will-change: transform, width;
  }
  .pill.ready { opacity: 1; }

  .rail a {
    position: relative; z-index: 1; flex: none;
    display: inline-flex; align-items: center; gap: 8px;
    height: 44px; padding: 0 16px; border-radius: 9999px;
    color: var(--mg-i2); font: 500 13px/1 var(--mg-font); white-space: nowrap;
    transition: color 0.18s;
  }
  .rail a:hover, .rail a.on { color: var(--mg-i); }
  .rail a:active { transform: scale(0.97); }

  .div { flex: none; width: 1px; height: 24px; margin: 0 5px; background: rgba(255, 255, 255, 0.15); }

  .go {
    flex: none; width: 44px; height: 44px; border-radius: 50%; border: 0; padding: 0;
    display: grid; place-items: center; cursor: pointer;
    background: var(--mg-i); color: #111113;
    box-shadow: var(--mg-sh-2);
    transition: background 0.18s, transform 0.12s, opacity 0.18s;
  }
  .go:hover:not(:disabled) { background: #fff; }
  .go:active:not(:disabled) { transform: scale(0.94); }
  .go:disabled { opacity: 0.4; cursor: default; }

  /* Below 900px the labels go: six icons fit a phone, six words do not. */
  @media (max-width: 900px) {
    .dock { padding: 5px; }
    .rail { gap: 0; }
    .rail a { padding: 0 12px; height: 40px; }
    .lb { display: none; }
  }
  @media (prefers-reduced-motion: reduce) {
    .dock { animation: none; }
    .pill { transition: opacity 0.06s; }
    .rail a:active, .go:active:not(:disabled) { transform: none; }
  }
</style>
