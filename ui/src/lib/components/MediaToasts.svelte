<script>
  /* A stack, not a single line: the media section fires several at once
     (a queue finishing, a tag saved) and one replacing another loses the
     first. Same plane as the app's own Toast — raised, hairline, a state dot
     rather than a red slab — and it sits ABOVE the dock on a phone. */
  import { flip } from 'svelte/animate';
  import { rise, fade } from '$lib/motion.js';

  let { items = [] } = $props();
</script>

<div class="stack" role="status" aria-live="polite">
  {#each items as t (t.id)}
    <div class="toast {t.kind}"
         animate:flip={{ duration: 220 }}
         in:rise={{ y: 12, duration: 280 }}
         out:fade={{ duration: 160 }}>
      <span class="mg-dot sm {t.kind === 'error' ? 'crit' : t.kind === 'warn' ? 'warn' : 'ok'}"></span>
      <span class="msg">{t.msg}</span>
    </div>
  {/each}
</div>

<style>
  .stack {
    position: fixed; left: 0; right: 0; bottom: calc(var(--sab) + var(--mc-dock-h) + 16px);
    z-index: 120; padding: 0 16px;
    display: flex; flex-direction: column; align-items: center; gap: 8px;
    pointer-events: none;
  }
  .toast {
    display: flex; align-items: center; gap: 10px;
    max-width: min(560px, calc(100vw - 32px));
    padding: 11px 18px; border-radius: 9999px; pointer-events: auto;
    background: var(--mc-glass-strong); border: 1px solid var(--mc-glass-line); box-shadow: var(--mc-sh-2), var(--mc-lit);
    -webkit-backdrop-filter: blur(var(--mc-blur)) saturate(150%); backdrop-filter: blur(var(--mc-blur)) saturate(150%);
    font: 500 13.5px/1.4 var(--mc-font); color: var(--mc-ink);
  }
  .msg { min-width: 0; overflow-wrap: anywhere; }
  .toast.error { border-color: var(--mc-crit-line); }
  @media (min-width: 1024px) {
    .stack { left: var(--mc-rail-w); bottom: calc(var(--sab) + 24px); }
  }
</style>
