<script>
  import { app, actions } from '$lib/state.svelte.js';

  const s = $derived(app.status);
  const busyNote = $derived.by(() => {
    const parts = [];
    if (app.busy.resolving) parts.push('resolving erf numbers');
    if (app.busy.locating.length) parts.push(`AI locating ${app.busy.locating.length}`);
    if (app.busy.reevaluating.length) parts.push(`re-evaluating ${app.busy.reevaluating.length}`);
    return parts.join(' · ');
  });
  const show = $derived(s.running || app.logOpen || !!busyNote);
  const pct = $derived(s.total ? Math.min(100, (100 * s.done) / s.total) : 0);

  let logEl = $state(null);
  $effect(() => {
    s.log;
    if (logEl) logEl.scrollTop = logEl.scrollHeight;
  });
</script>

{#if !s.ai_ok && s.ai_reason}
  <div class="aiwarn">
    AI scoring is off — {s.ai_reason}. Scores fall back to the heuristic; mandate
    verdicts still use hard evidence (multi-agency listings, portal mandate flags).
  </div>
{/if}

{#if show}
  <section class="strip" class:idle={!s.running}>
    <div class="row">
      <div class="phase">
        {#if s.running}<span class="spin"></span>{/if}
        <b>{s.running ? s.phase : busyNote || 'idle'}</b>
        {#if s.total}<span class="n">{s.done} / {s.total} pages</span>{/if}
      </div>

      <div class="sources">
        {#each Object.entries(s.per_source || {}) as [name, v] (name)}
          <div class="src" title="{v.done}/{v.found} pages · {v.stored} stored">
            <span class="sname">{name}</span>
            <span class="scount">{v.stored}</span>
            <i style:width="{v.found ? Math.min(100, (100 * v.done) / v.found) : 0}%"></i>
          </div>
        {/each}
      </div>

      <div class="tools">
        <button class="act" onclick={() => (app.logOpen = !app.logOpen)}>
          {app.logOpen ? 'Hide log' : 'Activity log'}
        </button>
        {#if s.running}
          <button class="act stop" onclick={() => actions.stop()}>Stop</button>
        {/if}
      </div>
    </div>

    {#if s.running && s.total}
      <div class="bar"><i style:width="{pct}%"></i></div>
    {/if}

    {#if app.logOpen}
      <pre class="log" bind:this={logEl}>{(s.log || []).join('\n')}</pre>
    {/if}
  </section>
{/if}

<style>
  .aiwarn, .strip {
    max-width: 1480px;
    margin-left: clamp(1rem, 3vw, 2rem);
    margin-right: clamp(1rem, 3vw, 2rem);
  }
  @media (min-width: 1544px) { .aiwarn, .strip { margin-left: auto; margin-right: auto; } }

  /* —————————————————————————————————————————— soft amber notice ——— */
  .aiwarn {
    margin-top: 0.9rem;
    padding: 0.65rem 0.85rem;
    background: var(--warn-bg); border: 1px solid var(--warn-line); border-radius: 10px;
    font: 400 0.8rem/1.55 var(--font-ui);
    color: var(--warn-ink);
  }

  /* ————————————————————————————————————————————— status card ——— */
  .strip {
    margin-top: 0.9rem; padding: 0.7rem 1rem;
    background: var(--bg-2);
    border: 1px solid var(--line); border-radius: var(--r-lg);
    box-shadow: var(--shadow-1);
  }
  .strip.idle { box-shadow: none; }

  .row { display: flex; align-items: center; gap: 1.4rem; flex-wrap: wrap; }

  .phase { display: flex; align-items: center; gap: 0.5rem; min-width: 0; }
  .phase b {
    font: 600 0.82rem/1.3 var(--font-ui); color: var(--accent-2);
  }
  .strip.idle .phase b { color: var(--ink-2); }
  .phase .n {
    font: 400 0.76rem/1.3 var(--font-ui); color: var(--ink-3);
    font-variant-numeric: tabular-nums;
  }

  .sources { display: flex; gap: 1.1rem; flex: 1; flex-wrap: wrap; }
  .src {
    position: relative; min-width: 108px; padding-bottom: 8px;
    display: flex; align-items: baseline; justify-content: space-between; gap: 0.6rem;
    font: 500 0.74rem/1.3 var(--font-ui); color: var(--ink-2);
  }
  .src::after {
    content: ''; position: absolute; left: 0; right: 0; bottom: 0; height: 3px;
    background: var(--bg-3); border-radius: 999px;
  }
  .src .sname { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .src .scount { color: var(--ink); font-weight: 700; font-variant-numeric: tabular-nums; }
  .src i {
    position: absolute; left: 0; bottom: 0; height: 3px; z-index: 1;
    background: var(--accent); border-radius: 999px; transition: width 0.4s;
  }

  .tools { display: flex; gap: 0.4rem; }
  .stop:hover { background: var(--red-soft); border-color: var(--red-line); color: var(--red); }

  .bar {
    height: 5px; background: var(--bg-3); border-radius: 999px;
    overflow: hidden; margin-top: 0.65rem;
  }
  .bar i { display: block; height: 100%; border-radius: 999px;
           background: var(--accent); transition: width 0.4s; }

  /* ——————————————————————————————————————————— activity log ——— */
  .log {
    margin: 0.7rem 0 0; height: 200px; overflow-y: auto;
    background: var(--bg-3); border: 1px solid var(--line); border-radius: var(--r-sm);
    padding: 0.6rem 0.75rem;
    font: 400 0.68rem/1.65 var(--font-mono);
    color: var(--ink-2); white-space: pre-wrap;
  }
</style>
