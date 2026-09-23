<script>
  /* One line, bottom-centre, above the dock: what just happened.

     Strong glass so it reads over a photograph, `pointer-events: none` so it
     can never eat the tap that was meant for the dock underneath it, and a
     red dot rather than a red slab when something failed — the message is
     the message. It clears itself (see toast() in $lib/state.svelte.js). */
  import { app } from '$lib/state.svelte.js';
</script>

{#if app.toast}
  <div class="toast mg-glass-strong mg-pill" class:error={app.toast.kind === 'error'} role="status">
    <span class="mg-dot {app.toast.kind === 'error' ? 'crit' : 'ok'} sm"></span>
    <span class="msg">{app.toast.msg}</span>
  </div>
{/if}

<style>
  .toast {
    position: fixed; left: 50%; bottom: calc(var(--mg-sab, 0px) + 88px);
    transform: translateX(-50%);
    z-index: 80; pointer-events: none;
    display: flex; align-items: center; gap: 9px;
    max-width: min(560px, calc(100vw - 32px));
    padding: 10px 18px;
    font: 500 13px/1.4 var(--mg-font); color: var(--mg-i);
    animation: toast-in 0.2s cubic-bezier(0.2, 0.8, 0.2, 1) both;
  }
  .msg { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .toast.error { border-color: rgba(242, 109, 100, 0.35); }

  @keyframes toast-in {
    from { opacity: 0; transform: translate(-50%, 8px); }
    to { opacity: 1; transform: translate(-50%, 0); }
  }
  @media (prefers-reduced-motion: reduce) {
    .toast { animation: none; }
  }
</style>
