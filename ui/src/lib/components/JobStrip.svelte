<script>
  /* The crawl / background-work strip. Compact by construction: ONE top row
     (state dot · phase · pages · progress bar · % · tools) and, while a crawl
     runs, ONE horizontally scrolling row of per-portal chips. Its height never
     depends on how many portals are crawling — twenty portals scroll sideways,
     they do not stack (the old `.sources` block wrapped into a tall column and
     pushed the list off screen).

     Below 640px the top row breaks into exactly two lines: dot · phase · pages,
     then bar · % · tools. */
  import { app, actions } from '$lib/state.svelte.js';
  import Icon from './glass/Icon.svelte';
  import { play, fadeIn } from '$lib/motion.js';
  import { fmtInt } from '$lib/format.js';

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
  const running = $derived(!!s.running);
  const total = $derived(running ? s.total || 0 : 0);
  const pct = $derived(total ? Math.min(100, (100 * (s.done || 0)) / total) : 0);
  const indeterminate = $derived((running && !total) || (!running && !!busyNote));
  const hasBar = $derived(running || !!busyNote);

  const sentence = (t) => { const v = String(t || '').trim(); return v ? v[0].toUpperCase() + v.slice(1) : v; };
  const phase = $derived(sentence(running ? s.phase || 'working' : busyNote || 'Idle'));

  /* in progress first, then not started, then finished; by name inside each */
  const portals = $derived.by(() => {
    if (!running) return [];
    const rank = (v) => (v.done > 0 && v.done < v.found ? 0 : !v.done ? 1 : 2);
    return Object.entries(s.per_source || {})
      .map(([name, v]) => {
        const done = +v?.done || 0, found = +v?.found || 0, stored = +v?.stored || 0;
        const state = rank({ done, found });
        return { name, done, found, stored, state, pct: found ? Math.min(100, (100 * done) / found) : 0 };
      })
      .sort((a, b) => a.state - b.state || a.name.localeCompare(b.name));
  });

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
  <section class="strip mg-panel" class:idle={!running} class:inline transition:play={fadeIn}
           aria-label="Background work">
    <div class="top">
      <div class="lead">
        <span class="mg-dot {running ? 'warn' : ''}">{#if running}<i class="mg-ping"></i>{/if}</span>
        <b class="phase" title={phase}>{phase}</b>
        {#if total}<span class="pages mg-mono">{fmtInt(s.done || 0)} / {fmtInt(total)} pages</span>{/if}
      </div>

      <div class="prog">
        <div class="bar" class:indeterminate class:blank={!hasBar} role="progressbar"
             aria-valuemin="0" aria-valuemax="100" aria-valuenow={indeterminate ? undefined : Math.round(pct)}>
          {#if hasBar}<i style:width={indeterminate ? null : pct + '%'}></i>{/if}
        </div>
        {#if total}<span class="pct mg-mono">{Math.floor(pct)}%</span>{/if}
        <div class="tools">
          <button type="button" class="mg-btn sm ghost" onclick={() => (app.logOpen = !app.logOpen)}
                  aria-label={app.logOpen ? 'Hide log' : 'Activity log'} title={app.logOpen ? 'Hide log' : 'Activity log'}>
            <Icon name="list" size={14} /><span class="lbl">{app.logOpen ? 'Hide log' : 'Activity log'}</span>
          </button>
          {#if running}
            <button type="button" class="mg-btn sm danger" onclick={() => actions.stop()} aria-label="Stop crawl" title="Stop crawl">
              <Icon name="stop" size={13} /><span class="lbl">Stop</span>
            </button>
          {/if}
        </div>
      </div>
    </div>

    {#if portals.length}
      <div class="portals mg-noscroll" aria-label="Portals">
        {#each portals as p (p.name)}
          <span class="portal" class:going={p.state === 0} class:waiting={p.state === 1} class:finished={p.state === 2}
                title="{p.name}: {p.done}/{p.found} pages · {p.stored} stored">
            <span class="name">{p.name}</span>
            <i class="mini"><i style:width="{p.pct}%"></i></i>
            <span class="n mg-mono">{fmtInt(p.stored)}</span>
          </span>
        {/each}
      </div>
    {/if}

    {#if app.logOpen}
      <pre class="log mg-inset" bind:this={logEl}>{(s.log || []).join('\n')}</pre>
    {/if}
  </section>
{/if}

<style>
  /* width: 100% — auto side margins switch off flex stretching, and the
     strip would otherwise grow to its max-content width */
  .aiwarn, .strip { width: 100%; max-width: 1200px; margin-left: auto; margin-right: auto; box-sizing: border-box; }
  .aiwarn.inline, .strip.inline { max-width: none; }
  .aiwarn { margin-bottom: 14px; }

  .strip { margin-bottom: 16px; padding: 7px 8px 7px 14px; min-width: 0; border-radius: var(--mc-r-md); }

  /* ONE row from 640px; below it, exactly two (see the media query). */
  .top { display: flex; align-items: center; gap: 12px; min-width: 0; min-height: 28px; }
  .lead { display: flex; align-items: center; gap: 10px; min-width: 0; flex: 0 1 auto; }
  .phase {
    min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    font: 600 13px/1 var(--mc-font); color: var(--mc-warn);
  }
  .strip.idle .phase { color: var(--mc-ink2); }
  .pages { flex: none; font-size: 12px; line-height: 1; color: var(--mc-ink3); white-space: nowrap; }

  .prog { flex: 1 1 auto; min-width: 0; display: flex; align-items: center; gap: 12px; }
  .bar {
    flex: 1; min-width: 80px; height: 6px; border-radius: 9999px; overflow: hidden;
    background: rgba(240, 180, 41, 0.14);
  }
  .strip.idle .bar { background: rgba(255, 255, 255, 0.06); }
  .bar.blank { background: none; }
  .bar > i { display: block; height: 100%; width: 0; border-radius: 9999px; background: var(--mc-warn); transition: width 0.7s var(--mc-ease); }
  .strip.idle .bar > i { background: var(--mc-ink3); }
  .bar.indeterminate > i { width: 36%; animation: mg-slide 1.5s ease-in-out infinite; }
  .pct { flex: none; min-width: 30px; text-align: right; font-size: 12px; font-weight: 600; line-height: 1; color: var(--mc-ink2); }

  .tools { flex: none; display: flex; gap: 6px; }
  .tools .mg-btn.sm { height: 28px; padding: 0 10px; gap: 6px; border-radius: 8px; }

  /* the portals: one row, scrolls sideways, fades out at the right edge */
  .portals {
    display: flex; flex-wrap: nowrap; gap: 6px; margin-top: 6px; overflow-x: auto; overflow-y: hidden;
    -webkit-mask-image: linear-gradient(90deg, #000 calc(100% - 28px), transparent);
    mask-image: linear-gradient(90deg, #000 calc(100% - 28px), transparent);
    padding-right: 24px;
  }
  .portal {
    flex: none; display: inline-flex; align-items: center; gap: 7px; height: 18px; padding: 0 8px;
    border-radius: 6px; background: rgba(255, 255, 255, 0.025); border: 1px solid var(--mc-line);
  }
  .portal .name { font: 500 11.5px/1 var(--mc-font); color: var(--mc-ink2); white-space: nowrap; }
  .portal.going .name { color: var(--mc-ink); }
  .portal.finished .name { color: var(--mc-ink3); }
  .mini { flex: none; display: block; width: 34px; height: 3px; border-radius: 9999px; background: var(--mc-inset); overflow: hidden; }
  .mini > i { display: block; height: 100%; border-radius: 9999px; background: var(--mc-accent); transition: width 0.7s var(--mc-ease); }
  .portal.going .mini > i { background: var(--mc-warn); }
  .portal.waiting .mini > i { background: var(--mc-ink3); }
  .portal .n { font-size: 11px; line-height: 1; color: var(--mc-ink3); }

  .log {
    margin: 8px 0 0; height: 180px; overflow-y: auto; border-radius: 8px; padding: 10px 12px;
    font: 400 11.5px/1.6 var(--mc-mono); color: var(--mc-ink2); white-space: pre-wrap;
  }

  /* phone: row 1 = dot · phase · pages, row 2 = bar · % · tools */
  @media (max-width: 639.98px) {
    .strip { padding: 7px 8px 7px 12px; }
    .top { flex-wrap: wrap; row-gap: 4px; min-height: 0; }
    .lead { flex: 1 1 100%; height: 16px; }
    .prog { flex: 1 1 100%; }
  }
  /* very narrow: the tools go icon-only */
  @media (max-width: 479.98px) {
    .tools .lbl { display: none; }
    .tools .mg-btn.sm { width: 28px; padding: 0; }
  }
</style>
