<script>
  /* A segmented control.

     The point of it is the glide: the active state is ONE pill that slides
     from option to option, not four that fade. React does that with a shared
     layout id; here we measure the buttons and transition an absolutely
     positioned pill's transform and width, which is the same motion for a
     fraction of the machinery — and it stays on the compositor. */
  import Icon from './Icon.svelte';

  let { options = [], value, onchange, label = 'View' } = $props();

  let wrap = $state(null);
  let btns = $state([]);
  let pill = $state({ x: 0, w: 0, ready: false });

  function measure() {
    const i = options.findIndex((o) => o.value === value);
    const el = btns[i];
    if (!el || !el.offsetWidth) { pill = { x: 0, w: 0, ready: false }; return; }
    pill = { x: el.offsetLeft, w: el.offsetWidth, ready: true };
  }

  /* Re-measure whenever the selection or the option set changes… */
  $effect(() => {
    value;
    options.length;
    btns.length;
    measure();
  });

  /* …and whenever the row itself is resized (labels wrap, fonts land late). */
  $effect(() => {
    if (!wrap || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => measure());
    ro.observe(wrap);
    return () => ro.disconnect();
  });
</script>

<div class="seg" bind:this={wrap} role="group" aria-label={label}>
  <span class="pill" aria-hidden="true" class:ready={pill.ready}
        style:transform="translateX({pill.x}px)" style:width="{pill.w}px"></span>

  {#each options as o, i (o.value)}
    <button type="button" bind:this={btns[i]} class:on={o.value === value}
            aria-pressed={o.value === value} onclick={() => onchange?.(o.value)}>
      {#if o.icon}<Icon name={o.icon} size={14} />{/if}
      <span class="lb">{o.label}</span>
      {#if o.count != null}<span class="ct mg-tnum">{o.count}</span>{/if}
    </button>
  {/each}
</div>

<style>
  .seg {
    position: relative; display: inline-flex; align-items: center; gap: 2px;
    padding: 3px; flex: none; max-width: 100%;
    background: var(--mc-glass-soft); border: 1px solid var(--mc-glass-line); border-radius: 9999px;
  }

  /* The one highlight. Parked at width 0 until the first measurement lands, so
     it never flashes at the left edge on the first paint. */
  .pill {
    position: absolute; left: 3px; top: 3px; bottom: 3px; width: 0; border-radius: 9999px;
    background: var(--mc-glass-on); border: 0; box-shadow: none;
    opacity: 0;
    transition: transform 0.28s var(--mc-ease), width 0.28s var(--mc-ease), opacity 0.2s;
    will-change: transform, width;
  }
  .pill.ready { opacity: 1; }

  button {
    position: relative; z-index: 1;
    display: inline-flex; align-items: center; justify-content: center; gap: 6px;
    height: 32px; padding: 0 14px; border: 0; background: none; border-radius: 9999px;
    color: var(--mc-ink3); font: 500 12.5px/1 var(--mc-font); white-space: nowrap;
    cursor: pointer; transition: color var(--mc-t-fast);
  }
  button:hover { color: var(--mc-ink2); }
  button.on { color: var(--mc-ink); }
  .ct { font-size: 11px; color: var(--mc-ink3); font-variant-numeric: tabular-nums; }
  button.on .ct { color: var(--mc-ink2); }

  @media (pointer: coarse) { button { height: 40px; padding: 0 14px; } }
  @media (prefers-reduced-motion: reduce) { .pill { transition: opacity 0.06s; } }
</style>
