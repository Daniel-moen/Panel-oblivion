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
  import StatTile from '$lib/components/StatTile.svelte';
  import ActivityFeed from '$lib/components/ActivityFeed.svelte';
  import { fmtInt } from '$lib/format.js';

  let now = $state(new Date());
  let today = $state(null);
  let todayFailed = $state(false);
  let home = $state(null);        // /api/home — hot, stats, series, events, crawl
  let homeFailed = $state(false); // an old server without /api/home, or offline
  let panelStats = $state(null);  // only fetched when /api/home is missing
  let expanded = $state(false);
  let busy = $state(null); // the task id currently being snoozed / ticked off

  async function loadToday() {
    try { today = await api.panelToday(); todayFailed = false; }
    catch { todayFailed = true; }
  }

  /* No toast on failure: Home falls back to what the app already polls
     (/api/stats) and the feed shows its empty state. */
  let homeAt = 0;
  let homeBusy = false;
  async function loadHome() {
    if (homeBusy) return;
    homeBusy = true;
    homeAt = Date.now();
    try { home = await api.home(); homeFailed = false; }
    catch {
      if (!home) {
        homeFailed = true;
        if (!panelStats) api.panelStats().then((d) => (panelStats = d)).catch(() => {});
      }
    }
    homeBusy = false;
  }

  onMount(() => {
    const t = setInterval(() => (now = new Date()), 1000 * 15);
    loadToday();
    loadHome();
    /* Every 30 s while the tab is in view, every 5 s while a crawl runs. */
    const t3 = setInterval(() => {
      if (document.hidden) return;
      const gap = app.status.running ? 5000 : 30000;
      if (Date.now() - homeAt >= gap - 250) loadHome();
    }, 5000);
    const onVis = () => { if (!document.hidden && Date.now() - homeAt > 5000) loadHome(); };
    document.addEventListener('visibilitychange', onVis);
    /* Nothing here waits on the prospect list any more, but it is the most
       likely next tap, so it is warmed once the greeting is up. */
    const t2 = setTimeout(ensureProspects, 600);
    return () => {
      clearInterval(t); clearInterval(t3); clearTimeout(t2);
      document.removeEventListener('visibilitychange', onVis);
    };
  });

  const hour = $derived(now.getHours());
  const greeting = $derived(
    hour < 5 ? 'Still up?' : hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  );
  const date = $derived(now.toLocaleDateString('en-ZA', { weekday: 'long', day: 'numeric', month: 'long' }));

  const stats = $derived(home?.stats ?? app.stats ?? null);
  const listHot = $derived(app.prospects.filter((r) => r.tier === 'hot').length);
  const hot = $derived(home?.hot ?? (homeFailed && app.loaded ? listHot : null));
  const overdue = $derived(today ? today.overdue.length : 0);
  const dueCount = $derived(today ? today.overdue.length + today.due_today.length : null);
  const crawling = $derived(!!app.status.running);
  const series = $derived(home?.series ?? null);

  /* One sentence, and it has to be true. `null` = still loading (skeleton). */
  const line = $derived.by(() => {
    if (todayFailed) return hot ? `${hot} hot prospect${hot > 1 ? 's' : ''} waiting in the engine.` : 'The engine is up.';
    if (!today) return null;
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

  const share = (a, b) => (a != null && b ? (100 * a) / b : null);
  const tracked = $derived(home?.tracked ?? panelStats?.tracked ?? today?.counts?.tracked ?? null);
  const trackedActive = $derived(home?.tracked_active ?? null);
  const tilesLoading = $derived(!home && !(homeFailed && (app.stats || app.loaded)));
  const tiles = $derived([
    { k: 'Hot prospects', v: hot, tone: hot ? 'crit' : '', sub: 'call these first', href: '/prospects', live: crawling,
      pct: share(hot, stats?.sellable), pctDetail: `${hot ?? '—'} of ${stats?.sellable ?? '—'} sellable`,
      spark: series?.price_cuts, sparkColor: 'var(--mc-crit)', sparkTitle: 'price cuts per day, 14 days', loading: tilesLoading },
    { k: 'Sellable', v: stats?.sellable ?? null,
      sub: stats?.properties != null ? `of ${fmtInt(stats.properties)} properties` : 'scored and deduped', href: '/prospects',
      pct: share(stats?.sellable, stats?.properties), pctDetail: `${stats?.sellable ?? '—'} of ${stats?.properties ?? '—'} properties`,
      spark: series?.new_listings, sparkTitle: 'new listings per day, 14 days', loading: tilesLoading },
    { k: 'Tracked leads', v: tracked, href: '/leads/pipeline',
      sub: trackedActive != null ? `${trackedActive} in play` : 'in lead management',
      pct: trackedActive != null ? share(trackedActive, tracked) : null, pctDetail: `${trackedActive ?? '—'} of ${tracked ?? '—'} in play`,
      loading: tilesLoading && !panelStats },
    { k: 'Follow-ups due', v: dueCount, tone: overdue ? 'crit' : dueCount ? 'warn' : '', sub: overdue ? `${overdue} overdue` : 'today',
      href: '/leads', loading: !today && !todayFailed }
  ]);

  /* ——— the engine, last 14 days ——— */
  const LETTER = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
  const bars = $derived.by(() => {
    const days = series?.days || [], vals = series?.new_listings || [];
    if (!days.length) return [];
    const max = Math.max(1, ...vals.map((v) => +v || 0));
    return days.map((d, i) => {
      const [y, m, dd] = String(d).split('-').map(Number);
      const n = +vals[i] || 0;
      return { d, n, h: n ? Math.max(4, (100 * n) / max) : 0, letter: LETTER[new Date(y, m - 1, dd).getDay()] ?? '', last: i === days.length - 1 };
    });
  });
  const newSum = $derived(bars.reduce((t, b) => t + b.n, 0));
  const showEngine = $derived(bars.length > 0 && (newSum > 0 || crawling));

  /* "12m ago". The crawl stamps (app_state) are naive LOCAL ISO times, so a
     bare one is parsed as local; one that carries Z or an offset is honoured. */
  function since(t) {
    if (!t) return null;
    const v = String(t).replace(' ', 'T');
    const ms = now.getTime() - new Date(v).getTime();
    if (isNaN(ms)) return null;
    const m = Math.max(0, Math.round(ms / 60000));
    if (m < 1) return 'just now';
    if (m < 60) return `${m}m ago`;
    const h = Math.round(m / 60);
    if (h < 48) return `${h}h ago`;
    return `${Math.round(h / 24)}d ago`;
  }
  const lastSweep = $derived(since(home?.crawl?.last_sweep || home?.crawl?.last_full));

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
      {#if line == null}<span class="skline"><Skeleton h="14px" w="46%" /></span>{:else}<p class="mg-sub">{line}</p>{/if}
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
      <StatTile label={t.k} value={t.v} sub={t.sub} tone={t.tone || ''} href={t.href} live={!!t.live}
                pct={t.pct ?? null} pctDetail={t.pctDetail || ''} pctTone={t.tone === 'crit' ? 'crit' : 'ok'} spark={t.spark || null}
                sparkColor={t.sparkColor || 'var(--mc-accent)'} sparkTitle={t.sparkTitle || ''} {i} loading={t.loading} />
    {/each}
  </div>

  {#if showEngine}
    <section class="mg-section engine mg-rise" style:--i={4}>
      <div class="head">
        <h2>New listings</h2>
        <span class="mg-count">{fmtInt(newSum)} in 14 days</span>
        <div class="mg-actions">
          {#if crawling}
            <span class="mg-chip ok live"><span class="mg-dot ok sm"><i class="mg-ping"></i></span>crawling{#if app.status.total}{' · '}<span class="mg-mono">{fmtInt(app.status.done)}/{fmtInt(app.status.total)}</span>{/if}</span>
          {:else if lastSweep}
            <span class="mg-count">last sweep {lastSweep}</span>
          {/if}
        </div>
      </div>
      <div class="body chart">
        <div class="bars">
          {#each bars as b (b.d)}
            <span class="col" title="{b.d} · {b.n}">
              <i class:today={b.last} class:zero={!b.n} style:height="{b.h}%"></i>
            </span>
          {/each}
        </div>
        <div class="days">
          {#each bars as b (b.d)}<span class:today={b.last}>{b.letter}</span>{/each}
        </div>
      </div>
    </section>
  {/if}

  <div class="cols">
    <div class="left">
    <section class="mg-section needs mg-rise" style:--i={5}>
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

    <section class="mg-section links mg-rise" style:--i={6}>
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

    <div class="right">
    <!-- Mount point for other features' Home cards (slots.home in
         $lib/shell.svelte.js): the "My tasks" card, a presence card, … Each
         one renders in its own wrapper, in the order it was added. -->
    <div class="slot" data-slot="home-cards">
      {#each slots.home as card, i (card.id)}
        {@const C = card.component}
        <div class="mg-rise" style:--i={7 + i}><C {...card.props || {}} /></div>
      {/each}
    </div>

      <div class="feedwrap mg-rise" style:--i={7 + slots.home.length}>
        <ActivityFeed events={home?.events || []} loading={!home && !homeFailed} />
      </div>
    </div>
  </div>
</div>

<style>
  .home { display: flex; flex-direction: column; gap: 16px; }

  .hello { margin: 4px 0 2px; align-items: flex-end; }
  @media (max-width: 640px) { .hello .mg-actions { flex-basis: 100%; margin-left: 0; } .hello .mg-actions :global(.mg-btn) { flex: 1; } }
  .titles { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .skline { display: block; padding: 4px 0 3px; }

  .tiles { display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  @media (min-width: 900px) { .tiles { grid-template-columns: repeat(4, minmax(0, 1fr)); } }

  /* Two columns from 1100px: what needs you + the links on the left, the
     feature cards + the activity feed on the right. Narrower, one column in
     order of importance: needs you, feature cards, activity, links. */
  .cols { display: flex; flex-direction: column; gap: 16px; }
  .left, .right { display: contents; }
  .needs { order: 1; } .slot { order: 2; } .feedwrap { order: 3; } .links { order: 4; }
  @media (min-width: 1100px) {
    .cols { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); align-items: start; }
    .left, .right { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
  }

  /* Engine · last 14 days: one bar per day, today in full accent */
  .engine .head { flex-wrap: wrap; row-gap: 6px; }
  .engine .live { height: 26px; gap: 7px; }
  .engine .live .mg-mono { font-size: 11.5px; }
  .chart { padding-top: 16px; padding-bottom: 12px; }
  .bars { display: flex; align-items: flex-end; gap: 4px; height: 56px; }
  .bars .col { flex: 1; height: 100%; display: flex; align-items: flex-end; min-width: 0; }
  .bars i {
    display: block; width: 100%; border-radius: 4px; background: var(--mc-accent); opacity: 0.7;
    transform-origin: bottom; animation: bar-grow 0.7s var(--mc-ease) both;
  }
  .bars i.today { opacity: 1; }
  .bars i.zero { height: 2px !important; background: var(--mc-line2); opacity: 1; }
  .bars .col:hover i:not(.zero) { opacity: 1; }
  .days { display: flex; gap: 4px; margin-top: 6px; }
  .days span { flex: 1; text-align: center; font: 400 10px/1 var(--mc-mono); color: var(--mc-ink3); }
  .days span.today { color: var(--mc-ink2); }
  @keyframes bar-grow { from { transform: scaleY(0); } to { transform: none; } }

  .row { display: flex; align-items: center; gap: 10px; padding: 8px 16px; flex-wrap: wrap; }
  @media (min-width: 640px) { .row { padding: 8px 20px; } }
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

  .slot { display: flex; flex-direction: column; gap: 16px; }
  .slot:empty { display: none; }

  .lic { flex: none; width: 34px; height: 34px; border-radius: 9px; display: grid; place-items: center; background: var(--mc-raised); border: 1px solid var(--mc-line); color: var(--mc-ink2); }
  .links :global(.chev) { color: var(--mc-ink3); flex: none; }
</style>
