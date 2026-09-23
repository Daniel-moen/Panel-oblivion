<script>
  /* Home — the resting state.

     No pane, no doors, no footer links: the dock is the navigation and the
     photograph is the page. What is left is the only thing worth saying when
     you open the app — a greeting, one honest sentence about today, ONE
     button doing the most useful thing available right now, and a quiet row
     of figures.

     Bottom-left: the things actually waiting on you, as frosted cards with
     inline answers. Overdue follow-ups first, then today's, then mandates
     about to expire — at most three, with a "+N more" that opens the rest.
     Snooze and Done are one tap here; anything more opens the lead. */
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { fly } from 'svelte/transition';
  import { api } from '$lib/api.js';
  import { app, toast } from '$lib/state.svelte.js';
  import { ago, shortDate, MANDATE_LABEL } from '$lib/panel.js';
  import Icon from '$lib/components/glass/Icon.svelte';

  let now = $state(new Date());
  let today = $state(null);
  let stats = $state(null);
  let expanded = $state(false);
  let busy = $state(null); // the task id currently being snoozed / ticked off

  async function loadToday() {
    try { today = await api.panelToday(); } catch { /* the panel is optional */ }
  }

  onMount(() => {
    const t = setInterval(() => (now = new Date()), 1000 * 15);
    loadToday();
    api.panelStats().then((d) => (stats = d)).catch(() => {});
    return () => clearInterval(t);
  });

  const hour = $derived(now.getHours());
  const greeting = $derived(
    hour < 5 ? 'Still up?' : hour < 12 ? 'Good morning.' : hour < 17 ? 'Good afternoon.' : 'Good evening.'
  );

  const hot = $derived(app.prospects.filter((r) => r.tier === 'hot').length);
  const overdue = $derived(today ? today.overdue.length : 0);
  const dueCount = $derived(today ? today.overdue.length + today.due_today.length : null);
  const crawling = $derived(!!app.status.running);

  /* One sentence, and it has to be true. */
  const line = $derived.by(() => {
    if (!today) return 'Loading your day…';
    const od = today.overdue.length, dt = today.due_today.length, ex = today.expiring.length;
    if (od) return `${od} follow-up${od > 1 ? 's' : ''} overdue — start there.`;
    if (dt) return `${dt} follow-up${dt > 1 ? 's' : ''} to make today.`;
    if (ex) return `${ex} mandate${ex > 1 ? 's' : ''} expiring soon — time to renew.`;
    if (today.stale.length) return `${today.stale.length} lead${today.stale.length > 1 ? 's have' : ' has'} gone quiet. Worth a call.`;
    if (hot) return `All caught up. ${hot} hot prospect${hot > 1 ? 's' : ''} waiting in the engine.`;
    return 'All caught up. Enjoy the view.';
  });

  /* The one button. Whatever is most useful right now, and nothing else. */
  const cta = $derived.by(() => {
    if (overdue)
      return { kind: 'warn', icon: 'clock', label: "Open today's follow-ups", href: '/leads' };
    if (crawling)
      return {
        kind: 'secondary', icon: 'clock', label: 'View crawl progress',
        /* the log is the engine page's strip, so this is a trip there */
        go: () => { app.logOpen = true; goto('/prospects'); }
      };
    return { kind: 'primary', icon: 'plus', label: 'New crawl', go: () => (app.runOpen = true) };
  });

  /* Figures, only the ones with something in them. */
  const pills = $derived.by(() => {
    const t = stats?.tracked ?? today?.counts?.tracked;
    return [
      hot ? { k: 'hot prospects', v: hot, tone: 'crit' } : null,
      app.stats?.sellable ? { k: 'sellable', v: app.stats.sellable } : null,
      t ? { k: 'tracked leads', v: t } : null,
      dueCount ? { k: 'follow-ups due', v: dueCount, tone: overdue ? 'crit' : 'warn' } : null
    ].filter(Boolean);
  });

  /* ——— the attention cards ——— */
  const MAX = 3;

  const items = $derived.by(() => {
    if (!today) return [];
    const out = [];
    for (const t of today.overdue)
      out.push({ key: 'o' + t.id, tone: 'crit', task: t, p: t.property,
                 title: t.title, note: `due ${ago(t.due_at)}` });
    for (const t of today.due_today)
      out.push({ key: 'd' + t.id, tone: 'warn', task: t, p: t.property,
                 title: t.title, note: 'due today' });
    for (const m of today.expiring)
      out.push({ key: 'm' + m.id, tone: 'warn', task: null, p: m.property,
                 title: `${MANDATE_LABEL[m.type] || m.type} mandate expiring`,
                 note: shortDate(m.expires_at) });
    return out;
  });

  const shown = $derived(expanded ? items : items.slice(0, MAX));
  const more = $derived(items.length - shown.length);

  const where = (p) => (p?.group_id ? '/leads/properties/' + p.group_id : '/leads');
  const nameOf = (p) => p?.street_address_raw || p?.official_address || p?.title || 'Untracked property';

  async function snooze(t) {
    busy = t.id;
    try { await api.snooze(t.id, 1); toast('Snoozed to tomorrow'); await loadToday(); }
    catch (e) { toast(e.message || String(e), 'error'); }
    busy = null;
  }

  async function done(t) {
    busy = t.id;
    try { await api.taskDone(t.id); toast('Done — nice one'); await loadToday(); }
    catch (e) { toast(e.message || String(e), 'error'); }
    busy = null;
  }
</script>

<svelte:head><title>Oblivion</title></svelte:head>

<div class="home">
  <section class="stage">
    <h1>{greeting}</h1>
    <p class="line">{line}</p>

    <div class="cta">
      {#if cta.href}
        <a class="mg-btn lg {cta.kind}" href={cta.href}>
          <Icon name={cta.icon} size={18} />{cta.label}
        </a>
      {:else}
        <button type="button" class="mg-btn lg {cta.kind}" onclick={cta.go}>
          <Icon name={cta.icon} size={18} />{cta.label}
        </button>
      {/if}
    </div>

    {#if pills.length}
      <div class="figures">
        {#each pills as s (s.k)}
          <span class="mg-stat pill">
            <b class="v mg-tnum {s.tone || ''}">{s.v}</b>
            <span class="k">{s.k}</span>
          </span>
        {/each}
      </div>
    {/if}
  </section>

  <div class="low">
    <div class="cards">
      {#each shown as it (it.key)}
        <article class="mg-glass card" in:fly={{ y: 14, duration: 260 }}>
          <a class="what" href={where(it.p)}>
            <span class="mg-dot {it.tone}"></span>
            <span class="txt">
              <b>{nameOf(it.p)}</b>
              <span class="sub">{it.title} · {it.note}</span>
            </span>
            <Icon name="chevronRight" size={15} class="go" />
          </a>

          <div class="acts">
            <a class="mg-btn sm secondary" href={where(it.p)}>Open</a>
            {#if it.task?.id}
              <button type="button" class="mg-btn sm ghost" disabled={busy === it.task.id}
                      onclick={() => snooze(it.task)}>Snooze 1d</button>
              <button type="button" class="mg-btn sm ghost" disabled={busy === it.task.id}
                      onclick={() => done(it.task)}>Done</button>
            {/if}
          </div>
        </article>
      {/each}

      {#if items.length > MAX}
        <button type="button" class="mg-btn sm secondary self"
                onclick={() => (expanded = !expanded)}>
          {expanded ? 'Show less' : `+${more} more`}
        </button>
      {/if}
    </div>

    <!-- the CMA suite is a Flask page, so it is a plain link out -->
    <a class="mg-btn sm ghost cma" href="/cma">CMA reports</a>
  </div>
</div>

<style>
  .home { flex: 1; min-height: 0; display: flex; flex-direction: column; }

  /* ————————————————————————————————————————————————— the centre ——— */
  .stage {
    flex: 1; min-height: 0;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    text-align: center; padding: 3vh 24px 2vh;
  }

  h1 {
    margin: 0; max-width: 16ch;
    font: 700 42px/1.02 var(--mg-font); letter-spacing: -0.035em; color: #fff;
    text-shadow: 0 2px 18px rgba(0, 0, 0, 0.5);
    animation: mg-fadeup 0.5s cubic-bezier(0.2, 0.8, 0.2, 1) both;
  }
  .line {
    margin: 14px 0 0; max-width: 40ch;
    font: 300 17px/1.35 var(--mg-font); letter-spacing: -0.01em;
    color: rgba(255, 255, 255, 0.75);
    text-shadow: 0 1px 14px rgba(0, 0, 0, 0.5);
    animation: mg-fadeup 0.5s cubic-bezier(0.2, 0.8, 0.2, 1) 0.06s both;
  }

  .cta { margin-top: 28px; animation: mg-fadeup 0.5s cubic-bezier(0.2, 0.8, 0.2, 1) 0.12s both; }
  .cta :global(.mg-btn) { padding: 0 28px; box-shadow: var(--mg-sh-2); }
  /* amber, not red: something needs you, nothing is broken */
  .cta :global(.mg-btn.warn) {
    background: rgba(240, 180, 41, 0.18);
    border-color: rgba(240, 180, 41, 0.45);
    color: #f7d58a;
    font-weight: 600;
  }
  .cta :global(.mg-btn.warn:hover) { background: rgba(240, 180, 41, 0.26); }

  .figures {
    margin-top: 34px; display: flex; flex-wrap: wrap; gap: 8px; justify-content: center;
    animation: mg-fadeup 0.5s cubic-bezier(0.2, 0.8, 0.2, 1) 0.18s both;
  }
  .figures .v { color: #fff; }
  .figures .v.crit { color: var(--mg-crit); }
  .figures .v.warn { color: var(--mg-warn); }
  .figures .k { color: rgba(255, 255, 255, 0.5); }

  /* ——————————————————————————————————————————— the bottom row ——— */
  .low {
    flex: none; display: flex; align-items: flex-end; gap: 16px;
    padding: 0 clamp(16px, 3vw, 28px) calc(var(--mg-sab, 0px) + 96px);
  }
  .cards { display: flex; flex-direction: column; gap: 10px; width: min(380px, 100%); }
  .card { padding: 14px 14px 12px; }

  .what { display: flex; align-items: flex-start; gap: 10px; }
  .what .mg-dot { margin-top: 5px; }
  .txt { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }
  .txt b {
    font: 600 14px/1.3 var(--mg-font); letter-spacing: -0.01em; color: var(--mg-i);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .sub { font: 400 12.5px/1.4 var(--mg-font); color: var(--mg-i2); }
  .what :global(.go) { margin-top: 3px; color: var(--mg-i3); }

  .acts { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; }
  .self { align-self: flex-start; }

  .cma { margin-left: auto; flex: none; color: rgba(255, 255, 255, 0.55); }

  @media (min-width: 720px) {
    h1 { font-size: 60px; }
    .line { font-size: 21px; }
  }
  @media (min-width: 1100px) {
    h1 { font-size: 68px; }
    .line { font-size: 24px; }
  }
  @media (max-width: 640px) {
    .low { flex-direction: column; align-items: stretch; gap: 10px; padding-bottom: calc(var(--mg-sab, 0px) + 92px); }
    .cards { width: 100%; }
    .cma { margin-left: 0; align-self: flex-start; }
  }
  @media (prefers-reduced-motion: reduce) {
    h1, .line, .cta, .figures { animation: none; }
  }
</style>
