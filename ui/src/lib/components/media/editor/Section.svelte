<script>
  /* A collapsible group of controls in the editor's side panel. */
  import Icon from '$lib/components/glass/Icon.svelte';
  let { title, icon = null, open = $bindable(true), badge = null, children, actions } = $props();
</script>

<section class="sec" class:open>
  <div class="hd">
    <button type="button" class="tg" onclick={() => (open = !open)} aria-expanded={open}>
      {#if icon}<Icon name={icon} size={14} />{/if}
      <span>{title}</span>
      {#if badge}<em class="mg-tnum">{badge}</em>{/if}
      <span class="chev" aria-hidden="true"><Icon name="chevronRight" size={14} /></span>
    </button>
    {#if actions}<div class="act">{@render actions()}</div>{/if}
  </div>
  {#if open}<div class="bd">{@render children()}</div>{/if}
</section>

<style>
  .sec { border-bottom: 1px solid var(--mc-line); padding: 4px 0 10px; }
  .sec:last-child { border-bottom: 0; }
  .hd { display: flex; align-items: center; gap: 6px; }
  .tg {
    flex: 1; display: flex; align-items: center; gap: 8px; min-height: 44px;
    border: 0; background: none; padding: 0; color: var(--mc-ink); cursor: pointer;
    font: 600 13px/1 var(--mc-font); text-align: left;
  }
  .tg em { font-style: normal; font-weight: 500; font-size: 11px; color: var(--mc-accent); }
  .chev { margin-left: auto; display: flex; color: var(--mc-ink3); transition: transform var(--mc-t) var(--mc-ease); }
  .open .chev { transform: rotate(90deg); }
  .act { display: flex; gap: 6px; }
  .bd { display: flex; flex-direction: column; gap: 4px; }
</style>
