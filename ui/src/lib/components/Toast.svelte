<script>
  /* One line, bottom-centre, above the dock: what just happened.

     A raised plane with a lit hairline, `pointer-events: none` so it can
     never eat the tap that was meant for the dock underneath it, and a red
     dot rather than a red slab when something failed — the message is the
     message. It clears itself (see toast() in $lib/state.svelte.js). */
  import { app } from '$lib/state.svelte.js';
  import { play, fadeUp } from '$lib/motion.js';
</script>

{#if app.toast}
  <div class="host">
    <div class="toast" class:error={app.toast.kind === 'error'} role="status"
         transition:play|global={fadeUp}>
      <span class="mg-dot {app.toast.kind === 'error' ? 'crit' : 'ok'} sm"></span>
      <span class="msg">{app.toast.msg}</span>
    </div>
  </div>
{/if}

<style>
  .host {
    position: fixed; left: 0; right: 0; bottom: var(--mc-dock-clear);
    z-index: 95; pointer-events: none; display: flex; justify-content: center; padding: 0 16px;
  }
  .toast {
    display: flex; align-items: center; gap: 10px;
    max-width: min(560px, calc(100vw - 32px));
    padding: 11px 18px; border-radius: 9999px;
    background: var(--mc-glass-strong); border: 1px solid var(--mc-glass-line);
    box-shadow: var(--mc-sh-2), var(--mc-lit);
    -webkit-backdrop-filter: blur(var(--mc-blur)) saturate(150%); backdrop-filter: blur(var(--mc-blur)) saturate(150%);
    font: 500 13.5px/1.4 var(--mc-font); color: var(--mc-ink);
  }
  .msg { min-width: 0; overflow-wrap: anywhere; }
  .toast.error { border-color: var(--mc-crit-line); }
</style>
