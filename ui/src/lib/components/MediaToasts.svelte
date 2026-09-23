<script>
  /* A stack, not a single line: the media section fires several at once
     (a queue finishing, a tag saved) and one replacing another loses the
     first. Slides in from the bottom edge, which is also where the thumb is
     on a phone — so it sits ABOVE the dock rather than under it. */
  import { flip } from 'svelte/animate';
  import { fly } from 'svelte/transition';

  let { items = [] } = $props();
</script>

<div class="stack" role="status" aria-live="polite">
  {#each items as t (t.id)}
    <div class="toast mg-glass-strong mg-pill {t.kind}"
         animate:flip={{ duration: 220 }}
         in:fly={{ y: 14, duration: 220 }}
         out:fly={{ y: 8, duration: 160 }}>
      {t.msg}
    </div>
  {/each}
</div>

<style>
  .stack {
    position: fixed; left: 50%; bottom: calc(var(--mg-sab, 0px) + 78px);
    transform: translateX(-50%); z-index: 120;
    display: flex; flex-direction: column; align-items: center; gap: 7px;
    pointer-events: none; max-width: min(560px, 92vw);
  }
  .toast {
    padding: 9px 18px; pointer-events: auto;
    font: 500 12.5px/1.5 var(--mg-font); color: var(--mg-i); text-align: center;
  }
  /* Error keeps the crit tone rather than a red plane: still a pill, still glass. */
  .toast.error { border-color: rgba(242, 109, 100, 0.4); color: var(--mg-crit); }
  .toast.ok { color: var(--mg-i); }
</style>
