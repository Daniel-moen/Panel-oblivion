<script>
  /* Tiny inline sparkline — Mission Control's, point for point: a soft 12 %
     area, a 1.8 line and a dot on the latest value. `data` = numbers. */
  let { data = [], width = 120, height = 34, color = 'var(--mc-accent)', class: cls = '' } = $props();

  const pts = $derived.by(() => {
    const d = (data || []).slice(-24).map((v) => Number(v) || 0);
    if (d.length < 2) return null;
    const P = 3;
    const max = Math.max(...d, 1);
    const p = d.map((v, i) => [
      P + (width - 2 * P) * (i / (d.length - 1)),
      height - P - (height - 2 * P) * (v / max)
    ]);
    const line = p.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(' ');
    return {
      line,
      area: `${P},${height} ${line} ${p[p.length - 1][0].toFixed(1)},${height}`,
      end: p[p.length - 1]
    };
  });
</script>

<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" class={cls} {width} {height} aria-hidden="true">
  {#if pts}
    <polygon points={pts.area} fill={color} opacity="0.12" />
    <polyline points={pts.line} fill="none" stroke={color} stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round" opacity="0.9" />
    <circle cx={pts.end[0]} cy={pts.end[1]} r="2.6" fill={color} />
  {/if}
</svg>

<style>
  svg { display: block; overflow: visible; }
</style>
