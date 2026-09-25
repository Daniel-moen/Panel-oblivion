<script>
  /* Five colour dots, Lightroom-style, plus an optional "none".

     Used three ways: in the drawer to label one clip, in the selection bar to
     label many, and in Browse as a filter (where "none" reads "any"). A dot
     that is on draws a ring; picking the dot that is already on clears it
     when `toggle` is set, which is how Lightroom's number keys behave. */
  import { LABELS } from '$lib/media.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';

  let { value = null, onchange, noneLabel = 'No label', showNone = true,
        toggle = true, disabled = false, label = 'Colour label' } = $props();

  function pick(v) {
    if (disabled) return;
    onchange?.(toggle && v === value ? null : v);
  }
</script>

<div class="dots" role="radiogroup" aria-label={label}>
  {#if showNone}
    <button type="button" class="d none" class:on={value == null} role="radio"
            aria-checked={value == null} title={noneLabel} aria-label={noneLabel}
            {disabled} onclick={() => onchange?.(null)}>
      <Icon name="x" size={12} stroke={2.4} />
    </button>
  {/if}
  {#each LABELS as l (l.value)}
    <button type="button" class="d" class:on={value === l.value} role="radio"
            aria-checked={value === l.value} title={l.label} aria-label={l.label}
            style:--c={l.color} {disabled} onclick={() => pick(l.value)}>
      <i></i>
    </button>
  {/each}
</div>

<style>
  .dots { display: inline-flex; align-items: center; gap: 2px; flex-wrap: wrap; }
  .d {
    width: 32px; height: 32px; padding: 0; border: 0; border-radius: 50%;
    background: none; cursor: pointer; display: grid; place-items: center;
    color: var(--mc-ink3); transition: background var(--mc-t-fast);
  }
  .d:hover:not(:disabled) { background: var(--mc-line); }
  .d:disabled { cursor: default; opacity: 0.5; }
  .d i {
    width: 14px; height: 14px; border-radius: 50%; background: var(--c);
    box-shadow: 0 0 0 0 transparent; transition: box-shadow var(--mc-t-fast), transform var(--mc-t-fast);
  }
  .d.on i { box-shadow: 0 0 0 2px var(--mc-bg), 0 0 0 4px var(--c); transform: scale(1.05); }
  .d.none.on { color: var(--mc-ink); background: var(--mc-line2); }
  .d:focus-visible { outline: 2px solid var(--mc-accent); outline-offset: 1px; }
  @media (pointer: coarse) {
    .d { width: 44px; height: 44px; }
  }
</style>
