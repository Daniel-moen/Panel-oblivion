<script>
  import { app, actions } from '$lib/state.svelte.js';
  import Icon from './glass/Icon.svelte';
  import { slide } from '$lib/motion.js';

  /* `inline` — already inside a page's own column, so drop the shell gutters */
  let { inline = false } = $props();

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
  <div class="mg-strip warn aiwarn" class:inline>
    <span class="ic"><Icon name="alert" size={15} /></span>
    <span><b>AI scoring is off</b> — {s.ai_reason}. Scores fall back to the heuristic; mandate
    verdicts still use hard evidence (multi-agency listings, portal mandate flags).</span>
  </div>
{/if}

{#if show}
  <section class="strip mg-panel" class:idle={!s.running} class:inline transition:slide={{ y: -6, duration: 220 }}>
    <div class="row">
      <div class="phase">
        {#if s.running}<span class="mg-dot warn"><i class="mg-ping"></i></span>{/if}
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
        <button type="button" class="mg-btn sm secondary" onclick={() => (app.logOpen = !app.logOpen)}>
          {app.logOpen ? 'Hide log' : 'Activity log'}
        </button>
        {#if s.running}
          <button type="button" class="mg-btn sm danger" onclick={() => actions.stop()}><Icon name="stop" size={13} /> Stop</button>
        {/if}
      </div>
    </div>

    {#if s.running && s.total}
      <div class="mg-bar warn prog"><i style:width="{pct}%"></i></div>
    {/if}

    {#if app.logOpen}
      <pre class="log mg-inset" bind:this={logEl}>{(s.log || []).join('\n')}</pre>
    {/if}
  </section>
{/if}

<style>
  .aiwarn, .strip { max-width: 1200px; margin-left: auto; margin-right: auto; }
  .aiwarn.inline, .strip.inline { max-width: none; }
  .aiwarn { margin-bottom: 14px; }

  .strip { margin-bottom: 14px; padding: 12px 14px; }
  .row { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }

  .phase { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .phase b { font: 600 13px/1.3 var(--mc-font); color: var(--mc-warn); text-transform: capitalize; }
  .strip.idle .phase b { color: var(--mc-ink2); }
  .phase .n { font: 400 12.5px/1.3 var(--mc-mono); color: var(--mc-ink3); font-variant-numeric: tabular-nums; }

  .sources { display: flex; gap: 14px; flex: 1; flex-wrap: wrap; }
  .src {
    position: relative; min-width: 108px; padding-bottom: 9px;
    display: flex; align-items: baseline; justify-content: space-between; gap: 8px;
    font: 500 12px/1.3 var(--mc-font); color: var(--mc-ink2);
  }
  .src::after { content: ''; position: absolute; left: 0; right: 0; bottom: 0; height: 4px; background: var(--mc-inset); border-radius: 999px; }
  .src .sname { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .src .scount { color: var(--mc-ink); font: 600 12px/1.3 var(--mc-mono); }
  .src i { position: absolute; left: 0; bottom: 0; height: 4px; z-index: 1; background: var(--mc-accent); border-radius: 999px; transition: width 0.4s var(--mc-ease); }

  .tools { display: flex; gap: 6px; margin-left: auto; }
  .prog { margin-top: 10px; }

  .log {
    margin: 10px 0 0; height: 200px; overflow-y: auto; border-radius: 8px; padding: 10px 12px;
    font: 400 11.5px/1.6 var(--mc-mono); color: var(--mc-ink2); white-space: pre-wrap;
  }
</style>
