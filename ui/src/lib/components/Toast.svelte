<script>
  import { app } from '$lib/state.svelte.js';
</script>

{#if app.toast}
  <div class="toast" class:error={app.toast.kind === 'error'} role="status">
    {app.toast.msg}
  </div>
{/if}

<style>
  .toast {
    position: fixed; left: 50%; bottom: 1.6rem; transform: translateX(-50%);
    z-index: 100; max-width: min(560px, 90vw);
    background: var(--ink); color: #fff;
    border-radius: 10px; padding: 0.6rem 1.2rem;
    font: 500 0.82rem/1.5 var(--font-ui);
    box-shadow: var(--shadow-2);
    animation: fadeup 0.18s ease-out;
  }
  .toast.error { background: var(--bad); }
</style>
