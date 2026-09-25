<script>
  /* A labelled slider row: name, value, range. Double-click (or the ↺) puts
     it back to its default. */
  let { label, value = $bindable(0), min = 0, max = 1, step = 0.01, def = null,
        fmt = (v) => (Math.round(v * 100) / 100).toString(), hint = '', disabled = false } = $props();
  const id = 'r' + Math.random().toString(36).slice(2, 8);
</script>

<div class="rg" class:off={disabled}>
  <div class="top">
    <label for={id}>{label}</label>
    <span class="v mg-tnum">{fmt(Number(value))}</span>
    {#if def != null && Number(value) !== def}
      <button type="button" class="rs" title="Reset" aria-label="Reset {label}" onclick={() => (value = def)}>↺</button>
    {/if}
  </div>
  <input {id} type="range" {min} {max} {step} {disabled}
         value={value} oninput={(e) => (value = Number(e.currentTarget.value))}
         ondblclick={() => def != null && (value = def)} />
  {#if hint}<p class="h">{hint}</p>{/if}
</div>

<style>
  .rg { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .rg.off { opacity: 0.45; }
  .top { display: flex; align-items: center; gap: 8px; }
  label { font: 500 12.5px/1.3 var(--mc-font); color: var(--mc-ink2); }
  .v { margin-left: auto; font: 500 12px/1 var(--mc-font); color: var(--mc-ink); }
  .rs { border: 0; background: none; color: var(--mc-ink3); cursor: pointer; font-size: 13px; padding: 0 2px; }
  .rs:hover { color: var(--mc-ink); }
  input { width: 100%; height: 28px; accent-color: var(--mc-accent); margin: 0; }
  @media (pointer: coarse) { input { height: 44px; } .rs { min-width: 32px; min-height: 32px; } }
  .h { margin: 0; font: 400 11.5px/1.4 var(--mc-font); color: var(--mc-ink3); }
</style>
