<script>
  /* A number that arrives rather than appears.

     Eased with a cubic out over ~900ms: long enough to read as motion, short
     enough that nobody waits for it. Skipped when the value is small
     (counting 0→3 looks broken, not lively) and when the viewer asked for
     reduced motion. Only the *first* value animates — re-running on every
     poll would make the dashboard twitch. */

  let { value = 0, format = (n) => String(Math.round(n)), duration = 900 } = $props();

  let shown = $state(0);
  let last = null;

  function run(to) {
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (reduce || !to || Math.abs(to) < 5) { shown = to; return; }
    const t0 = performance.now();
    const tick = (t) => {
      const p = Math.min(1, (t - t0) / duration);
      shown = to * (1 - Math.pow(1 - p, 3));
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
