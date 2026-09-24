<script>
  /* One develop slider: label, the value, a reset, and a range input tall
     enough for a thumb. `oninput` fires while dragging (the page debounces
     its save); `oncommit` fires on release, which is what undo records.
     Double-click the label to put it back to its default. */
  let {
    label, value, min = -1, max = 1, step = 0.01, def = 0,
    fmt = null, disabled = false, track = null, oninput, oncommit
  } = $props();

  const shown = $derived(
    fmt ? fmt(value) : (value > 0 && min < 0 ? '+' : '') + Number(value).toFixed(step >= 1 ? 0 : step >= 0.1 ? 1 : 2)
  );
  const changed = $derived(Math.abs(Number(value) - Number(def)) > 1e-9);
  /* where zero (or the default) sits on the track, for the fill */
  const at = (v) => ((Math.min(max, Math.max(min, v)) - min) / (max - min)) * 100;
  const a = $derived(Math.min(at(def), at(value)));
  const b = $derived(Math.max(at(def), at(value)));

  function reset() {
    if (disabled || !changed) return;
    oninput?.(def);
    oncommit?.(def);
  }
</script>

<div class="sl" class:off={disabled}>
  <div class="top">
    <button type="button" class="lb" ondblclick={reset} title="Double-click to reset" {disabled}>{label}</button>
    {#if changed && !disabled}
      <button type="button" class="rs" onclick={reset} aria-label="Reset {label}" title="Reset">↺</button>
    {/if}
    <span class="v mg-tnum" class:ch={changed}>{shown}</span>
  </div>
  <div class="rail">
    <div class="tr" style:background={track || null}>
      {#if !track}<i style:left="{a}%" style:width="{b - a}%"></i>{/if}
    </div>
    <input type="range" {min} {max} {step} {value} {disabled} aria-label={label}
           oninput={(e) => oninput?.(Number(e.currentTarget.value))}
           onchange={(e) => oncommit?.(Number(e.currentTarget.value))} />
  </div>
</div>

<style>
  .sl { padding: 2px 0; }
  .sl.off { opacity: 0.45; }
  .top { display: flex; align-items: center; gap: 6px; min-height: 20px; }
  .lb {
    border: 0; background: none; padding: 0; color: var(--mg-i2);
    font: 500 12.5px/1.2 var(--mg-font); cursor: default; text-align: left;
  }
  .rs {
    border: 0; background: none; color: var(--mg-i3); cursor: pointer; padding: 0 4px;
    font-size: 13px; line-height: 1;
  }
  .rs:hover { color: var(--mg-i); }
  .v { margin-left: auto; font: 500 12px/1 var(--mg-font); color: var(--mg-i3); }
  .v.ch { color: var(--mg-i); }
  .rail { position: relative; height: 30px; }
  .tr {
    position: absolute; left: 0; right: 0; top: 50%; height: 4px; margin-top: -2px;
    border-radius: 9999px; background: rgba(255, 255, 255, 0.1); overflow: hidden;
  }
  .tr > i { position: absolute; top: 0; bottom: 0; background: var(--mg-ok); opacity: 0.8; }
  input[type='range'] {
    position: absolute; inset: 0; width: 100%; height: 100%; margin: 0;
    -webkit-appearance: none; appearance: none; background: transparent; cursor: pointer;
    touch-action: pan-y;
  }
  input[type='range']:disabled { cursor: not-allowed; }
  input[type='range']::-webkit-slider-runnable-track { height: 30px; background: transparent; }
  input[type='range']::-moz-range-track { height: 30px; background: transparent; }
  input[type='range']::-webkit-slider-thumb {
    -webkit-appearance: none; appearance: none; width: 18px; height: 18px; margin-top: 6px;
    border-radius: 50%; background: var(--mg-i); border: 0;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.5);
  }
  input[type='range']::-moz-range-thumb {
    width: 18px; height: 18px; border-radius: 50%; background: var(--mg-i); border: 0;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.5);
  }
  input[type='range']:focus-visible { outline: none; }
  input[type='range']:focus-visible::-webkit-slider-thumb { box-shadow: 0 0 0 3px rgba(62, 207, 142, 0.6); }
</style>
