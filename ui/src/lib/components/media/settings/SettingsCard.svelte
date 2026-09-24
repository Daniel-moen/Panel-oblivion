<script>
  /* One settings section: a quiet label, an optional line of explanation, and
     rows. The row vocabulary (.set / .l / .hint / .val / .note) is styled here
     once for every card on the page, scoped under .sc so it cannot leak. */
  let { label, sub = '', children } = $props();
</script>

<section class="sc">
  <span class="mg-label">{label}</span>
  {#if sub}<p class="sub">{sub}</p>{/if}
  {@render children?.()}
</section>

<style>
  .sc { margin-bottom: 24px; min-width: 0; }
  .sc > .mg-label { margin-bottom: 10px; }
  .sub { margin: -4px 2px 10px; font: 400 12.5px/1.55 var(--mg-font); color: var(--mg-i3); }

  .sc :global(.set) {
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    min-height: 56px; padding: 11px 14px; margin-bottom: 6px;
    border-radius: var(--mg-r-in);
  }
  .sc :global(.set:last-child) { margin-bottom: 0; }
  .sc :global(.set .l) { flex: 1 1 200px; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .sc :global(.set .l b) { font: 500 13.5px/1.25 var(--mg-font); letter-spacing: -0.01em; color: var(--mg-i); }
  .sc :global(.hint) { font: 400 12px/1.45 var(--mg-font); color: var(--mg-i3); overflow-wrap: anywhere; }
  .sc :global(.hint code), .sc :global(.note code) { font: 11.5px/1.5 var(--mg-mono); color: var(--mg-i2); }
  .sc :global(.val) { flex: none; font: 500 13px/1 var(--mg-font); color: var(--mg-i); }
  .sc :global(.mono) { font-family: var(--mg-mono); }
  .sc :global(.note) { margin: 10px 2px 0; font: 400 12.5px/1.6 var(--mg-font); color: var(--mg-i3); }
  .sc :global(.field) { display: flex; flex-direction: column; gap: 5px; min-width: 0; flex: 1 1 220px; }
  .sc :global(.fields) { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
  .sc :global(.mg-select) { display: block; }
  .sc :global(.btnrow) { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .sc :global(.set .mg-btn), .sc :global(.btnrow .mg-btn) { min-height: 40px; }
  .sc :global(.pane) { border-radius: var(--mg-r-in); padding: 14px; margin-bottom: 6px; }
</style>
