<script>
  /* Compact utilization meter — Mission Control's Meter. The fill carries
     severity (accent → warn → crit, or a fixed `tone`); the unfilled track is
     the SAME hue at 16 %, so the state reads across the whole bar. The value
     is ink, never the data colour; identity comes from the label beside it.
     `width` null lets the bar take the row (flex: 1). */
  let { label = '', pct = 0, detail = '', tone = null, width = 56, height = 8, showPct = true } = $props();

  const TONES = { ok: 'var(--mc-accent)', accent: 'var(--mc-accent)', warn: 'var(--mc-warn)', crit: 'var(--mc-crit)', mgr: 'var(--mc-mgr)' };
  const clamped = $derived(Math.max(0, Math.min(100, Number(pct) || 0)));
  const color = $derived(
    tone ? TONES[tone] || tone
      : clamped >= 90 ? 'var(--mc-crit)' : clamped >= 70 ? 'var(--mc-warn)' : 'var(--mc-accent)'
  );
  const shown = $derived(clamped > 0 && clamped < 1 ? '<1' : String(Math.round(clamped)));
</script>

<div class="meter" class:fluid={width == null}
     title="{label ? label + ' ' : ''}{shown}%{detail ? ' · ' + detail : ''}">
  {#if label}<span class="hud">{label}</span>{/if}
  <div class="track" style:width={width == null ? null : width + 'px'} style:height="{height}px"
       style:background="color-mix(in oklab, {color} 16%, transparent)">
    <i style:width="{clamped}%" style:background={color}
       style:box-shadow="0 0 8px color-mix(in oklab, {color} 55%, transparent)"></i>
  </div>
  {#if showPct}<span class="pct">{shown}%</span>{/if}
</div>

<style>
  .meter { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .meter:not(.fluid) { min-width: 104px; }
  .track { flex: none; overflow: hidden; border-radius: 9999px; }
  .fluid .track { flex: 1; min-width: 0; }
  .track > i { display: block; height: 100%; border-radius: 9999px; transition: width 0.7s var(--mc-ease); }
  .pct { flex: none; font: 600 12px/1 var(--mc-mono); font-variant-numeric: tabular-nums; color: var(--mc-ink2); }
</style>
