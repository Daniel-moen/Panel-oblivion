<script>
  /* A number that arrives rather than appears.

     It runs on spring.gentle — Mission Control's spring for numbers and
     large moves (lib/motion.js), over the time that spring takes to settle.
     Skipped when the value is small
     (counting 0→3 looks broken, not lively) and when the viewer asked for
     reduced motion. Only the *first* value animates — re-running on every
     poll would make the dashboard twitch. */

  import { spring, springEase, springMs, prefersReduced } from '$lib/motion.js';

  let { value = 0, format = (n) => String(Math.round(n)) } = $props();

  const ease = springEase(spring.gentle);
  const duration = springMs(spring.gentle);

  let shown = $state(0);
  let last = null;

  function run(to) {
    if (prefersReduced() || !to || Math.abs(to) < 5) { shown = to; return; }
    const t0 = performance.now();
    const tick = (t) => {
      const p = Math.min(1, (t - t0) / duration);
      shown = to * ease(p);
      if (p < 1) requestAnimationFrame(tick);
      else shown = to;
    };
    requestAnimationFrame(tick);
  }

  $effect(() => {
    const v = value ?? 0;
    if (last === null) { last = v; run(v); }
    else if (v !== last) { last = v; shown = v; }
  });
</script>

<span class="n">{format(shown)}</span>

<style>
  .n { font-variant-numeric: tabular-nums; }
</style>
