<script>
  /* The scene's photograph — the only decoration in the app.

     One full-bleed image fills the viewport and drifts 1.0 → 1.06 over 90s
     (the only ambient motion anywhere), under a dim veil and two scrims: the
     clock lives up top and the dock down low, so both ends are darker than
     the middle. Body is deep graphite underneath, so a slow or missing photo
     never shows as a white flash.

     Which photo is picked by the hour, the same three files and the same
     thresholds the app has always used — before 10 morning, before 17 day,
     else dusk — so every surface is lit like the hour you opened it. The
     clock ticks every 5 minutes, which is as often as the answer can change.

     Props:
       dim    0–1, the veil over the photo (default 0.2)
       hero   force a photo: 'morning' | 'day' | 'dusk' (default: by hour) */
  import { onMount } from 'svelte';

  let { dim = 0.2, hero = null } = $props();

  let now = $state(new Date());
  onMount(() => {
    const t = setInterval(() => (now = new Date()), 5 * 60 * 1000);
    return () => clearInterval(t);
  });

  const pick = $derived.by(() => {
    if (hero) return hero;
    const h = now.getHours();
    return h < 10 ? 'morning' : h < 17 ? 'day' : 'dusk';
  });
</script>

<div class="backdrop" aria-hidden="true">
  <div class="shot" style:background-image="url(/hero-{pick}.jpg)"></div>
  <div class="dim" style:background="rgba(6, 6, 8, {dim})"></div>
  <div class="top"></div>
  <div class="bot"></div>
</div>

<style>
  .backdrop { position: fixed; inset: 0; z-index: 0; overflow: hidden; pointer-events: none; }
  .shot {
    position: absolute; inset: 0; background-size: cover; background-position: center;
    animation: mg-drift 90s ease-in-out infinite alternate; will-change: transform;
  }
  .dim { position: absolute; inset: 0; }
  .top { position: absolute; left: 0; right: 0; top: 0; height: 32%;
         background: linear-gradient(180deg, rgba(0, 0, 0, 0.55), transparent); }
  .bot { position: absolute; left: 0; right: 0; bottom: 0; height: 42%;
         background: linear-gradient(0deg, rgba(0, 0, 0, 0.7), transparent); }

  @media (prefers-reduced-motion: reduce) {
    .shot { animation: none; }
  }
</style>
