<script>
  /* The scene's photograph — the only decoration in the app (the panel's
     shell/Backdrop.jsx, in Svelte).

     One full-bleed image fills the viewport and drifts 1.0 → 1.06 over 90s
     (the only ambient motion anywhere), under a dim veil and two scrims: the
     strip lives up top and the dock down low, so both ends are darker than
     the middle. <body> is deep graphite underneath (app.css), so a slow or
     missing photo never shows as a white flash — the glass simply frosts the
     gradient until the JPEG lands, and the photo fades in over it.

     Which photo: by the hour, the same four files and thresholds auth.py
     uses for the sign-in page (20:00–05:00 night, before 10 morning, before
     17 day, else dusk),
     so every surface is lit like the hour you opened it. The clock ticks
     every 5 minutes, which is as often as the answer can change.

     Override: the panel's own `mc.backdrop` localStorage key is honoured
     ({ dim, url }), and a `mc:backdrop` event re-reads it — so a backdrop
     chosen in Mission Control on the same origin carries across.

     Props:
       dim    0–1, the veil over the photo (default 0.2)
       hero   force a photo: 'morning' | 'day' | 'dusk' | 'night' (default: by hour) */
  import { onMount } from 'svelte';
  import { heroFor, heroSrc, frostSrc, readBackdropOverride } from '$lib/hero.js';
  import { chrome } from '$lib/shell.svelte.js';

  let { dim = 0.2, hero = null } = $props();

  let now = $state(new Date());
  let override = $state({});
  let loaded = $state(false);
  let scrolling = $state(false);

  const readOverride = readBackdropOverride;

  onMount(() => {
    override = readOverride();
    const sync = () => (override = readOverride());
    window.addEventListener('mc:backdrop', sync);
    window.addEventListener('storage', sync);
    const t = setInterval(() => (now = new Date()), 5 * 60 * 1000);
    /* Pause the drift while anything scrolls: the blurred strip, pane and
       dock would otherwise re-sample a moving photo on every scrolled frame.
       A 90-second drift frozen for 300 ms is invisible; the frames are not. */
    let idle = 0;
    const onScroll = () => {
      scrolling = true;
      clearTimeout(idle);
      idle = setTimeout(() => (scrolling = false), 300);
    };
    window.addEventListener('scroll', onScroll, { passive: true, capture: true });
    return () => {
      clearInterval(t);
      clearTimeout(idle);
      window.removeEventListener('scroll', onScroll, { capture: true });
      window.removeEventListener('mc:backdrop', sync);
      window.removeEventListener('storage', sync);
    };
  });

  const pick = $derived(hero || heroFor(now));
  const src = $derived(override.url || heroSrc(pick));
  const veil = $derived(typeof override.dim === 'number' ? override.dim : dim);

  /* The glass (glass/Frost.svelte) shows this photo's pre-blurred twin. */
  $effect(() => {
    chrome.frost = override.url || frostSrc(pick);
    chrome.frostLive = !!override.url;
  });

  /* The photo paints only once it is decoded: no half-loaded progressive
     frame, no flash — it fades in over the graphite. */
  $effect(() => {
    const url = src;
    loaded = false;
    const img = new Image();
    img.onload = () => { if (src === url) loaded = true; };
    img.src = url;
    return () => { img.onload = null; };
  });
</script>

<div class="backdrop" aria-hidden="true">
  {#key src}
    <div class="shot" class:in={loaded} class:hold={scrolling} style:background-image="url({src})"></div>
  {/key}
  <div class="dim" style:background="rgba(6, 6, 8, {veil})"></div>
  <div class="top"></div>
  <div class="bot"></div>
</div>

<style>
  .backdrop { position: fixed; inset: 0; z-index: 0; overflow: hidden; pointer-events: none; }
  .shot {
    position: absolute; inset: 0; background-size: cover; background-position: center;
    opacity: 0; transition: opacity 0.9s ease;
    animation: mg-drift 90s ease-in-out infinite alternate; will-change: transform;
  }
  .shot.in { opacity: 1; }
  .shot.hold { animation-play-state: paused; }
  .dim { position: absolute; inset: 0; }
  .top { position: absolute; left: 0; right: 0; top: 0; height: 32%;
         background: linear-gradient(180deg, rgba(0, 0, 0, 0.55), transparent); }
  .bot { position: absolute; left: 0; right: 0; bottom: 0; height: 42%;
         background: linear-gradient(0deg, rgba(0, 0, 0, 0.7), transparent); }

  @media (prefers-reduced-motion: reduce) {
    .shot { animation: none; transition: none; }
  }
</style>
