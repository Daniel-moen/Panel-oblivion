<script>
  /* Home — the overview.

     Order of importance, top to bottom: a greeting and one honest sentence
     about today; the headline figures as stat tiles; what needs YOU,
     answerable inline (overdue follow-ups first, then today's, then mandates
     about to expire); then whatever other features mount here (see
     `slots.home` in $lib/shell.svelte.js — the "My tasks" card lives in that
     column); and the quick links. */
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api.js';
  import { app, toast, ensureProspects } from '$lib/state.svelte.js';
  import { slots } from '$lib/shell.svelte.js';
  import { ago, shortDate, MANDATE_LABEL } from '$lib/panel.js';
  import { rise } from '$lib/motion.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';

  let now = $state(new Date());
  let today = $state(null);
  let todayFailed = $state(false);
  let stats = $state(null);
  let expanded = $state(false);
  let busy = $state(null); // the task id currently being snoozed / ticked off

  async function loadToday() {
    try { today = await api.panelToday(); todayFailed = false; }
    catch { todayFailed = true; }
  }

  onMount(() => {
    const t = setInterval(() => (now = new Date()), 1000 * 15);
    loadToday();
    api.panelStats().then((d) => (stats = d)).catch(() => {});
    /* The hot count reads the prospect list, but the home screen must not
       wait on the heaviest fetch in the app. The list is also the most likely
       next tap, so it is warmed once the greeting is up. */
    const t2 = setTimeout(ensureProspects, 600);
    return () => { clearInterval(t); clearTimeout(t2); };
  });

  const hour = $derived(now.getHours());
  const greeting = $derived(
    hour < 5 ? 'Still up?' : hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  );
  const date = $derived(now.toLocaleDateString('en-ZA', { weekday: 'long', day: 'numeric', month: 'long' }));

  const hot = $derived(app.prospects.filter((r) => r.tier === 'hot').length);
  const overdue = $derived(today ? today.overdue.length : 0);
  const dueCount = $derived(today ? today.overdue.length + today.due_today.length : null);
  const crawling = $derived(!!app.status.running);

  /* One sentence, and it has to be true. */
  const line = $derived.by(() => {
    if (todayFailed) return hot ? `${hot} hot prospect${hot > 1 ? 's' : ''} waiting in the engine.` : 'The engine is up.';
    if (!today) return 'Loading your day…';
    const od = today.overdue.length, dt = today.due_today.length, ex = today.expiring.length;
    if (od) return `${od} follow-up${od > 1 ? 's' : ''} overdue — start there.`;
    if (dt) return `${dt} follow-up${dt > 1 ? 's' : ''} to make today.`;
    if (ex) return `${ex} mandate${ex > 1 ? 's' : ''} expiring soon — time to renew.`;
    if (today.stale.length) return `${today.stale.length} lead${today.stale.length > 1 ? 's have' : ' has'} gone quiet. Worth a call.`;
    if (hot) return `All caught up. ${hot} hot prospect${hot > 1 ? 's' : ''} waiting in the engine.`;
    return 'All caught up.';
  });

  /* The one button. Whatever is most useful right now, and nothing else. */
  const cta = $derived.by(() => {
    if (overdue) return { kind: 'warn', icon: 'clock', label: "Open today's follow-ups", href: '/leads' };
    if (crawling) return { kind: 'secondary', icon: 'clock', label: 'View crawl progress', go: () => { app.logOpen = true; goto('/prospects'); } };
    return { kind: 'primary', icon: 'plus', label: 'New crawl', go: () => (app.runOpen = true) };
  });

  const tracked = $derived(stats?.tracked ?? today?.counts?.tracked ?? null);
  const tiles = $derived([
    { k: 'Hot prospects', v: app.loaded ? hot : null, tone: hot ? 'crit' : '', sub: 'call these first', href: '/prospects', live: crawling },
    { k: 'Sellable', v: app.stats?.sellable ?? null, sub: 'scored and deduped', href: '/prospects' },
    { k: 'Tracked leads', v: tracked, sub: 'in lead management', href: '/leads/pipeline' },
    { k: 'Follow-ups due', v: dueCount, tone: overdue ? 'crit' : dueCount ? 'warn' : '', sub: overdue ? `${overdue} overdue` : 'today', href: '/leads' }
  ]);

  /* ——— the attention list ——— */
  const MAX = 4;
  const items = $derived.by(() => {
    if (!today) return [];
    const out = [];
    for (const t of today.overdue)
      out.push({ key: 'o' + t.id, tone: 'crit', task: t, p: t.property, title: t.title, note: `due ${ago(t.due_at)}` });
    for (const t of today.due_today)
      out.push({ key: 'd' + t.id, tone: 'warn', task: t, p: t.property, title: t.title, note: 'due today' });
    for (const m of today.expiring)
      out.push({ key: 'm' + m.id, tone: 'warn', task: null, p: m.property,
                 title: `${MANDATE_LABEL[m.type] || m.type} mandate expiring`, note: shortDate(m.expires_at) });
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

  const LINKS = [
    { href: '/prospects', icon: 'building', label: 'Prospect engine', sub: 'the scored book' },
    { href: '/map', icon: 'mapPin', label: 'Map', sub: 'prospects by street' },
    { href: '/agent', icon: 'bolt', label: 'Agent Z', sub: 'ask the engine' },
    { href: '/cma', icon: 'list', label: 'CMA reports', sub: 'comps and valuations', ext: true }
  ];
</script>

<svelte:head><title>Oblivion</title></svelte:head>

<div class="home">
  <div class="mg-row hello">
    <div class="titles">
      <span class="hud">{date}</span>
      <h1 class="mg-h1">{greeting}.</h1>
      <p class="mg-sub">{line}</p>
    </div>
    <div class="mg-actions">
      {#if cta.href}
        <a class="mg-btn {cta.kind}" href={cta.href}><Icon name={cta.icon} size={16} />{cta.label}</a>
      {:else}
        <button type="button" class="mg-btn {cta.kind}" onclick={cta.go}><Icon name={cta.icon} size={16} />{cta.label}</button>
      {/if}
    </div>
  </div>

  <div class="tiles">
    {#each tiles as t, i (t.k)}
      <a class="mg-stat-tile mg-rise" style:--i={i} href={t.href}>
        <span class="hud">{t.k}{#if t.live}<span class="mg-dot warn sm mg-pulse"></span>{/if}</span>
        <div class="v {t.tone}">{#if t.v != null}{t.v}{:else if app.loaded && (today || todayFailed)}—{:else}<Skeleton h="26px" w="52px" />{/if}</div>
        <div class="sub" class:warn={t.tone === 'warn' || t.tone === 'crit'}>{t.sub}</div>
      </a>
    {/each}
  </div>

  <div class="cols">
    <section class="mg-section needs mg-rise" style:--i={4}>
      <div class="head">
        <h2>Needs you</h2>
        <span class="mg-count">{items.length || ''}</span>
        <div class="mg-actions">
          <a class="mg-btn sm ghost" href="/leads">Today <Icon name="arrowRight" size={13} /></a>
        </div>
      </div>

      {#if !today && !todayFailed}
        <div class="mg-list">
          {#each Array(3) as _, i (i)}
            <div class="mg-listrow"><Skeleton h="8px" w="8px" r="50%" /><span class="t"><Skeleton h="14px" w="55%" delay={i * 60} /><Skeleton h="11px" w="35%" delay={i * 60 + 40} /></span></div>
          {/each}
        </div>
      {:else if !items.length}
        <div class="mg-empty quiet">
          <span class="ic"><Icon name="check" size={20} /></span>
          <h3>All clear</h3>
          <p>{todayFailed ? 'Lead management is not answering right now.' : 'No follow-ups due and nothing expiring.'}</p>
        </div>
      {:else}
        <div class="mg-list">
          {#each shown as it, i (it.key)}
            <div class="row" in:rise={{ i }}>
              <a class="what" href={where(it.p)}>
                <span class="mg-dot {it.tone}"></span>
                <span class="t">
                  <b>{nameOf(it.p)}</b>
                  <span>{it.title} · {it.note}</span>
                </span>
              </a>
              <div class="acts">
                {#if it.task?.id}
                  <button type="button" class="mg-btn sm ghost" disabled={busy === it.task.id} onclick={() => snooze(it.task)}>Snooze</button>
                  <button type="button" class="mg-btn sm secondary" disabled={busy === it.task.id} onclick={() => done(it.task)}><Icon name="check" size={13} /> Done</button>
                {:else}
                  <a class="mg-btn sm secondary" href={where(it.p)}>Open</a>
                {/if}
              </div>
            </div>
          {/each}
        </div>
        {#if items.length > MAX}
          <button type="button" class="more" onclick={() => (expanded = !expanded)}>
            {expanded ? 'Show less' : `+${more} more`}
          </button>
        {/if}
      {/if}
    </section>

    <!-- Mount point for other features' Home cards (slots.home in
         $lib/shell.svelte.js): the "My tasks" card, a presence card, … Each
         one renders in its own wrapper, in the order it was added. -->
    <div class="slot" data-slot="home-cards">
      {#each slots.home as card, i (card.id)}
        {@const C = card.component}
        <div class="mg-rise" style:--i={5 + i}><C {...card.props || {}} /></div>
      {/each}
    </div>

    <section class="mg-section links mg-rise" style:--i={6 + slots.home.length}>
      <div class="head"><h2>Go to</h2></div>
      <div class="mg-list">
        {#each LINKS as l (l.href)}
          <a class="mg-listrow" href={l.href}>
            <span class="lic"><Icon name={l.icon} size={17} /></span>
            <span class="t"><b>{l.label}</b><span>{l.sub}</span></span>
            <Icon name={l.ext ? 'external' : 'chevronRight'} size={15} class="chev" />
          </a>
        {/each}
      </div>
    </section>
  </div>
</div>

<style>
  .home { display: flex; flex-direction: column; gap: 14px; }

  .hello { margin: 4px 0 2px; align-items: flex-end; }
  @media (max-width: 640px) { .hello .mg-actions { flex-basis: 100%; margin-left: 0; } .hello .mg-actions :global(.mg-btn) { flex: 1; } }
  .titles { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .titles .mg-h1 { font-size: 26px; }
  .titles .mg-sub { font-size: 14px; }

  .tiles { display: grid; gap: 10px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  @media (min-width: 900px) { .tiles { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
  a.mg-stat-tile { transition: border-color var(--mc-t-fast); }
  a.mg-stat-tile:hover { border-color: var(--mc-line2); }
  .mg-stat-tile .hud { display: flex; align-items: center; gap: 8px; }

  .cols { display: grid; gap: 14px; grid-template-columns: minmax(0, 1fr); align-items: start; }
  @media (min-width: 1100px) { .cols { grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); } .needs { grid-row: span 2; } }

  .row { display: flex; align-items: center; gap: 10px; padding: 8px 16px 8px 16px; flex-wrap: wrap; }
  .what { flex: 1 1 220px; min-width: 0; display: flex; align-items: center; gap: 12px; min-height: 40px; border-radius: 8px; }
  .what .t { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .what b { font: 600 13.5px/1.35 var(--mc-font); color: var(--mc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .what span:not(.mg-dot):not(.t) { font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .what:hover b { color: var(--mc-accent); }
  .acts { display: flex; gap: 6px; margin-left: auto; }

  .more { width: 100%; height: 44px; border: 0; border-top: 1px solid var(--mc-line); background: none; color: var(--mc-ink2); font: 500 13px/1 var(--mc-font); cursor: pointer; }
  .more:hover { color: var(--mc-ink); background: rgba(255, 255, 255, 0.03); }

  .quiet { padding: 32px 24px; }
  .quiet .ic { color: var(--mc-accent); }

  .slot { display: flex; flex-direction: column; gap: 14px; }
  .slot:empty { display: none; }

  .lic { flex: none; width: 34px; height: 34px; border-radius: 9px; display: grid; place-items: center; background: var(--mc-raised); border: 1px solid var(--mc-line); color: var(--mc-ink2); }
  .links :global(.chev) { color: var(--mc-ink3); flex: none; }
</style>
