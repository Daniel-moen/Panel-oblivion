<script>
  /* Home — the scene, then the overview.

     Above the fold it is the photograph and nothing else, like Daniel's
     reference: the date and a big thin clock top-left; a small "view"
     dropdown and the round glass buttons (Search, Quick log, team chat, the
     account) top-right; and dead centre a greeting, ONE honest sentence
     about what needs you ($lib/suggest.js picks it from what is fetched
     here) and ONE pill that goes and does it. No pane, no strip (unless a
     crawl runs — the layout decides), and the floating Dock steps out of
     the way after 3 s idle, at every width.

     One viewport down, the overview sits in a single sheet of glass — the
     stat tiles, the 14-day bars, what needs you (answerable inline), the
     `slots.home` cards (see $lib/shell.svelte.js), the activity feed and the
     quick links. The chevron under the pill (or any scroll) reveals it, and
     it rises into place on spring.smooth the first time it comes into view;
     scrolling back up returns to the clean scene.

     No layout shift: the greeting, the sentence and the pill each own a
     fixed box from the first frame, and their text rises in (fadeUp,
     staggered) when it lands — once. The 30 s / 5 s refreshes and a change
     of view swap the words in place; only a new pill (a different action)
     rises again. */
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api.js';
  import { app, toast, ensureProspects } from '$lib/state.svelte.js';
  import { slots, chrome, shell, openQuickLog, stripWanted } from '$lib/shell.svelte.js';
  import { chat, toggleChat, chatBadge } from '$lib/chat.svelte.js';
  import { me } from '$lib/me.svelte.js';
  import { filters } from '$lib/filters.svelte.js';
  import { openSearch, searchKey } from '$lib/search.js';
  import { suggest, VIEWS } from '$lib/suggest.js';
  import { ago, shortDate, MANDATE_LABEL } from '$lib/panel.js';
  import { rise, play, fadeUp, staggerDelay, spring, springCss, prefersReduced } from '$lib/motion.js';
  import { leads } from '$lib/leads.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Frost from '$lib/components/glass/Frost.svelte';
  import AccountButton from '$lib/components/glass/AccountButton.svelte';
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
  let meWaited = $state(false);   // /api/me had its chance; greet without a name
  let overview = $state(null);    // the glass pane one viewport down
  let scene = $state(null);       // the photograph's one viewport
  let mounted = $state(false);    // the greeting block may rise in
  let firstPaint = $state(true);  // the first paint's stagger is still running
  let risen = $state(false);      // the overview has come into view once
  let armed = $state(false);      // …and there is an observer to say so

  /* Which question the sentence answers. Per viewer, per browser. */
  const VIEW_KEY = 'obv2.homeView';
  let view = $state('needs');
  try { const v = localStorage.getItem(VIEW_KEY); if (VIEWS.some((x) => x.value === v)) view = v; } catch { /* private mode */ }
  function pickView(v) {
    view = v;
    try { localStorage.setItem(VIEW_KEY, v); } catch { /* private mode */ }
  }

  async function loadToday() {
    try {
      today = await api.panelToday(); todayFailed = false;
      /* The same payload the Leads section keeps: the dock's follow-ups
         badge reads it from there, so Home shares what it fetched. */
      leads.today = today;
    }
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
    /* The clock: re-read at every minute boundary (then every 15 s), and at
       once when the tab comes back, so the minute is never wrong. */
    let t = 0;
    const tick = () => (now = new Date());
    const t0 = setTimeout(() => { tick(); t = setInterval(tick, 15000); }, 60000 - (Date.now() % 60000) + 50);
    loadToday();
    loadHome();
    /* Every 30 s while the tab is in view, every 5 s while a crawl runs. */
    const t3 = setInterval(() => {
      if (document.hidden) return;
      const gap = app.status.running ? 5000 : 30000;
      if (Date.now() - homeAt >= gap - 250) loadHome();
    }, 5000);
    const onVis = () => { if (document.hidden) return; tick(); if (Date.now() - homeAt > 5000) loadHome(); };
    document.addEventListener('visibilitychange', onVis);
    /* Nothing here waits on the prospect list any more, but it is the most
       likely next tap, so it is warmed once the greeting is up. */
    const t2 = setTimeout(ensureProspects, 600);
    const t4 = setTimeout(() => (meWaited = true), 1200);
    const stopIdle = quietChrome();
    /* The greeting, sentence and pill rise in once, on the first paint. */
    mounted = true;
    const t5 = setTimeout(() => (firstPaint = false), 900);
    const stopRise = riseOverview();
    return () => {
      clearTimeout(t0); clearInterval(t); clearInterval(t3); clearTimeout(t2); clearTimeout(t4); clearTimeout(t5);
      document.removeEventListener('visibilitychange', onVis);
      stopIdle();
      stopRise();
    };
  });

  /* The Dock is the navigation, so it stays — but on the scene it slides
     away after 3 s without input (at every width) and comes back on any
     tap, scroll or key. Once the overview is in view it stays put (you are
     reading, and may want to go somewhere). Reduced motion: never hidden. */
  function quietChrome() {
    const still = matchMedia('(prefers-reduced-motion: reduce)');
    let timer = 0, raf = 0;
    const inScene = () => window.scrollY < window.innerHeight * 0.5;
    /* Never pull the navigation out from under a resting cursor or a
       keyboard focus: that is someone using it. */
    const inUse = () =>
      !!document.activeElement?.closest?.('.dock') ||
      !!document.querySelector('.dock:hover');
    const arm = () => {
      clearTimeout(timer);
      if (chrome.quiet) chrome.quiet = false;
      if (still.matches) return;
      timer = setTimeout(() => { if (inScene() && !inUse()) chrome.quiet = true; }, 3000);
    };
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => { raf = 0; arm(); });
    };
    const onMove = (e) => { if (e.pointerType === 'mouse') onScroll(); };
    arm();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('pointerdown', arm, { passive: true });
    window.addEventListener('pointermove', onMove, { passive: true });
    window.addEventListener('keydown', arm);
    window.addEventListener('focusin', arm);
    still.addEventListener?.('change', arm);
    return () => {
      clearTimeout(timer); cancelAnimationFrame(raf);
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('pointerdown', arm);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('keydown', arm);
      window.removeEventListener('focusin', arm);
      still.removeEventListener?.('change', arm);
      chrome.quiet = false;
    };
  }

  /* The overview rises (y + opacity on spring.smooth) the first time any of
     it scrolls into view — a one-shot class, transform and opacity only, so
     its Frost is never re-blurred. Without an IntersectionObserver it is
     simply there. Reduced motion: it fades. */
  function riseOverview() {
    if (!overview || typeof IntersectionObserver === 'undefined') { risen = true; return () => {}; }
    armed = true;
    const io = new IntersectionObserver((es) => {
      if (es.some((e) => e.isIntersecting)) { risen = true; io.disconnect(); }
    }, { threshold: 0, rootMargin: '0px 0px -8% 0px' });
    io.observe(overview);
    return () => io.disconnect();
  }
  const RISE = springCss(spring.smooth);

  function reveal() {
    if (!scene) return;
    /* The overview starts where the scene ends; measured off the scene so
       the overview's own rise (a transform) never skews the target. */
    const still = prefersReduced();
    window.scrollTo({ top: scene.getBoundingClientRect().bottom + window.scrollY, behavior: still ? 'auto' : 'smooth' });
  }

  /* The clock: the browser's own locale (en-ZA when it has none worth
     trusting), always 24-hour. Formatters are built once. */
  const LOCALES = (() => { try { return [navigator.language, 'en-ZA'].filter(Boolean); } catch { return ['en-ZA']; } })();
  const fmtDate = new Intl.DateTimeFormat(LOCALES, { weekday: 'long', day: 'numeric', month: 'long' });
  const fmtTime = new Intl.DateTimeFormat(LOCALES, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  const fmtDateShort = new Intl.DateTimeFormat(LOCALES, { weekday: 'short', day: 'numeric', month: 'short' });
  const date = $derived(fmtDate.format(now));
  const dateShort = $derived(fmtDateShort.format(now));
  const clock = $derived(fmtTime.format(now));

  const hour = $derived(now.getHours());
  /* First name only, capitalised: an account named after its login
     ("daniel") still reads like a greeting. */
  const first = $derived.by(() => {
    const f = String(me.display_name || '').trim().split(/\s+/)[0] || '';
    return f ? f[0].toUpperCase() + f.slice(1) : '';
  });
  const greeting = $derived(
    (hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening') + (first ? `, ${first}!` : '!')
  );
  const greetReady = $derived(me.loaded || meWaited);

  /* The one sentence and the one pill. null = still loading: the boxes stay
     reserved and empty, so nothing below them moves when it lands. */
  const sug = $derived(suggest({ view, now, today, todayFailed, home, homeFailed, status: app.status }));
  /* The live region follows the rule that fired, so a running crawl's
     progress does not re-announce every 5 s. */
  let announce = $state('');
  let announcedKey = '';
  $effect(() => {
    const k = sug ? view + ':' + sug.key : '';
    if (k && k !== announcedKey) { announcedKey = k; announce = sug.text; }
  });
  const viewLabel = $derived(VIEWS.find((v) => v.value === view)?.label || '');

  function act(c) {
    if (c.filters) Object.assign(filters, c.filters);
    if (c.log) app.logOpen = true;
    if (c.run) app.runOpen = true;
    goto(c.href);
  }

  const stats = $derived(home?.stats ?? app.stats ?? null);
  const listHot = $derived(app.prospects.filter((r) => r.tier === 'hot').length);
  const hot = $derived(home?.hot ?? (homeFailed && app.loaded ? listHot : null));
  const overdue = $derived(today ? today.overdue.length : 0);
  const dueCount = $derived(today ? today.overdue.length + today.due_today.length : null);
  const crawling = $derived(!!app.status.running);
  const series = $derived(home?.series ?? null);

  const share = (a, b) => (a != null && b ? (100 * a) / b : null);
  const badge = $derived(chatBadge());
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
<!-- the strip owns "/" everywhere else; on the scene there is no strip -->
<svelte:window onkeydown={searchKey} />

<div class="home" class:striped={stripWanted(app.status, shell.status)}>
  <section class="scene" data-home-scene aria-label="Today" bind:this={scene}>
    <div class="top">
      <div class="when">
        <div class="date"><span class="long">{date}</span><span class="short">{dateShort}</span></div>
        <div class="clock mg-tnum">{clock}</div>
      </div>
      <div class="tools">
        <label class="view" title="What the sentence talks about">
          <span class="vis">{viewLabel}<Icon name="chevronsUpDown" size={11} stroke={2.2} /></span>
          <select data-home-view aria-label="What should Home talk about?" value={view} onchange={(e) => pickView(e.currentTarget.value)}>
            {#each VIEWS as v (v.value)}<option value={v.value}>{v.label}</option>{/each}
          </select>
        </label>
        <button type="button" class="mg-round" aria-label="Search" title="Search" onclick={openSearch}><Icon name="search" size={18} /></button>
        <button type="button" class="mg-round" aria-label="Quick log" title="Quick log" onclick={() => openQuickLog()}><Icon name="pencil" size={17} /></button>
        <!-- the strip carries team chat everywhere else; the scene has no strip -->
        <button type="button" class="mg-round chat" class:on={chat.open} onclick={toggleChat} aria-expanded={chat.open}
                data-testid="chat-launcher" aria-label={badge.label} title="Team chat">
          <Icon name="message" size={18} />
          {#if badge.show}<i class="count" class:mention={badge.kind === 'mention'} data-testid="chat-badge"
                              data-kind={badge.kind} aria-hidden="true">{badge.txt}</i>{/if}
        </button>
        <AccountButton />
      </div>
    </div>

    <div class="centre">
      <h1 data-home-greeting class:in={mounted && greetReady}>
        {#if mounted && greetReady}<span in:play|global={{ v: fadeUp, delay: firstPaint ? staggerDelay(0) : 0 }}>{greeting}</span>{/if}
      </h1>
      <p class="line" data-home-line class:in={mounted && !!sug}>
        {#if mounted && sug}<span in:play|global={{ v: fadeUp, delay: firstPaint ? staggerDelay(1) : 0 }}>{sug.text}</span>{/if}
      </p>
      <!-- read out when the suggestion changes kind, not on every crawl tick -->
      <span class="mg-sr" aria-live="polite">{announce}</span>
      <div class="cta">
        {#if mounted && sug}
          {#key sug.cta.label + sug.cta.href}
            <button type="button" class="pill" data-home-cta onclick={() => act(sug.cta)}
                    in:play|global={{ v: fadeUp, delay: firstPaint ? staggerDelay(2) : 0 }}>{sug.cta.label}</button>
          {/key}
        {/if}
      </div>
      <button type="button" class="reveal" data-home-reveal onclick={reveal} aria-label="Show the overview" title="Overview">
        <Icon name="chevronDown" size={20} stroke={1.8} />
      </button>
    </div>
  </section>

  <section class="overview" class:armed class:risen data-home-overview bind:this={overview} aria-label="Overview"
           style:--rise={RISE}>
  <Frost />
  <div class="inner">
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
  </section>
</div>

<style>
  .home { display: flex; flex-direction: column; }

  /* ——— the scene: one viewport of photograph ——— */
  .scene {
    position: relative; height: 100vh; height: 100svh; min-height: 480px;
    color: #fff; overflow: hidden;
  }
  .top {
    position: absolute; left: 0; right: 0; top: 0;
    display: flex; align-items: flex-start; gap: 12px;
    padding: calc(var(--sat) + 22px) calc(var(--sar, 0px) + 18px) 0 calc(var(--sal) + 20px);
    transition: transform 260ms var(--mc-ease);
  }
  .when { min-width: 0; }
  .date { font: 400 13px/1.3 var(--mc-font); color: rgba(255, 255, 255, 0.92); text-shadow: 0 1px 12px rgba(0, 0, 0, 0.35); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .date .short { display: none; }
  .clock { margin-top: 2px; font: 300 30px/1 var(--mc-font); letter-spacing: -0.01em; font-variant-numeric: tabular-nums; text-shadow: 0 1px 16px rgba(0, 0, 0, 0.35); }

  .tools { margin-left: auto; display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex: none; }
  /* A phone has no room for the date, the view and two buttons on one row:
     the view drops under the buttons, still right-aligned. */
  @media (max-width: 559px) {
    .tools { flex-wrap: wrap; max-width: 60%; row-gap: 10px; }
    .view { order: 3; margin-right: 0; }
  }
  /* Four round buttons (search, quick log, chat, account) beside the clock:
     below 420 the date goes short ("Wed 30 Sep", as the strip does) and the
     buttons close up so they hold one row down to 360. */
  @media (max-width: 419.98px) {
    .date .long { display: none; }
    .date .short { display: inline; }
    .tools { gap: 6px; max-width: 66%; }
  }
  .chat { position: relative; }
  .count {
    position: absolute; top: -3px; right: -3px; min-width: 16px; height: 16px; padding: 0 4px;
    display: inline-flex; align-items: center; justify-content: center; border-radius: 9999px;
    background: #3a3a42; color: var(--mc-ink); border: 2px solid rgba(0, 0, 0, 0.5);
    font: 700 9.5px/1 var(--mc-font); font-style: normal; font-variant-numeric: tabular-nums;
  }
  .count.mention { background: var(--mc-accent); color: var(--mc-accent-ink); }
  .view { position: relative; display: inline-flex; align-items: center; height: 32px; margin-right: 4px; }
  .view .vis {
    display: inline-flex; align-items: center; gap: 4px; height: 30px; padding: 0 11px;
    border-radius: 9999px; background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.14);
    font: 600 12.5px/1 var(--mc-font); color: #fff; white-space: nowrap; pointer-events: none;
  }
  .view select {
    position: absolute; inset: 0; width: 100%; opacity: 0; cursor: pointer;
    font-size: 16px; /* iOS: no zoom on focus */ -webkit-appearance: none; appearance: none;
  }
  .view:has(select:focus-visible) .vis { outline: 2px solid rgba(255, 255, 255, 0.7); outline-offset: 2px; }
  .view:hover .vis { background: rgba(255, 255, 255, 0.14); }

  /* The greeting block hangs from a fixed line a little above the middle, so
     a sentence that wraps (or arrives late) only ever pushes DOWN. */
  .centre {
    --gs: 36px;
    position: absolute; left: 0; right: 0; top: calc(40% - 2.2 * var(--gs));
    display: flex; flex-direction: column; align-items: center; text-align: center;
    padding: 0 calc(var(--sar, 0px) + 20px) 0 calc(var(--sal) + 20px);
  }
  /* Two lines are reserved and the text sits at the bottom of them: a name
     that arrives late, or a long one that wraps, never moves what is below. */
  h1 {
    margin: 0; max-width: 16ch; height: 2.2em;
    display: flex; align-items: flex-end; justify-content: center;
    font: 700 var(--gs)/1.1 var(--mc-font); letter-spacing: -0.025em; color: #fff;
    text-shadow: 0 2px 28px rgba(0, 0, 0, 0.35);
  }
  h1 span, .line span { display: block; }
  .line {
    margin: 10px 0 0; max-width: 30ch; min-height: 2.5em;
    font: 400 19px/1.25 var(--mc-font); color: rgba(255, 255, 255, 0.94);
    text-shadow: 0 1px 18px rgba(0, 0, 0, 0.4);
  }
  .cta { height: 34px; margin-top: 14px; display: flex; justify-content: center; }
  .pill {
    height: 34px; padding: 0 16px; border-radius: 9999px; cursor: pointer;
    background: rgba(38, 38, 42, 0.62); border: 1px solid rgba(255, 255, 255, 0.10); color: #fff;
    font: 500 13px/1 var(--mc-font); white-space: nowrap;
    transition: background var(--mc-t-fast), transform 120ms var(--mc-ease);
  }
  .pill:hover { background: rgba(58, 58, 64, 0.72); }
  .pill:active { transform: scale(0.96); }
  .reveal {
    margin-top: 22px; width: 44px; height: 44px; border: 0; border-radius: 9999px; background: none; cursor: pointer;
    display: grid; place-items: center; color: rgba(255, 255, 255, 0.7);
    transition: color var(--mc-t-fast), transform 160ms var(--mc-ease);
  }
  .reveal:hover { color: #fff; transform: translateY(2px); }

  @media (min-width: 640px) {
    .top { padding: calc(var(--sat) + 44px) calc(var(--sar, 0px) + 44px) 0 calc(var(--sal) + 48px); }
    .date { font-size: 15px; }
    .clock { font-size: 34px; }
    .centre { --gs: 56px; top: calc(44% - 2.2 * var(--gs)); }
    h1 { max-width: 20ch; }
    .line { font-size: 24px; max-width: 34ch; }
    .cta { margin-top: 22px; }
  }
  @media (min-width: 1100px) {
    .centre { --gs: 64px; }
    .line { font-size: 28px; max-width: none; }
  }
  /* A short landscape phone: tighter, so the pill never meets the dock. */
  @media (max-height: 560px) { .centre { --gs: 32px; top: 18%; } .line { font-size: 17px; } }

  /* A crawl brings the strip back over the scene (the layout pins it to the
     top); the date and tools step down under it — a transform, not a reflow. */
  .striped .top { transform: translateY(var(--mc-strip-h)); }

  /* ——— the overview: ONE sheet of glass, one viewport down ———
     Frosted by glass/Frost (the photo pre-blurred, cut to this box), not a
     live backdrop-filter: a live blur moving across the photo on every
     scrolled frame is what made the reveal stutter on an iPad. */
  .overview {
    position: relative; z-index: 1; isolation: isolate;
    min-height: 100vh; min-height: 100svh;
    border: 1px solid var(--mc-glass-line); border-bottom: 0;
    border-radius: var(--mc-r-lg) var(--mc-r-lg) 0 0;
    box-shadow: var(--mc-sh-3);
    --frost-r: var(--mc-r-lg) var(--mc-r-lg) 0 0;
  }
  /* Its rise: the content, parked 32px low until the pane first comes into
     view. The content, not the pane: a transform on the pane would make it
     the containing block of the Frost's fixed layer, which then jumps when
     the rise ends. Transform only: fading a layer this size costs a
     full-size compositing pass on every scrolled frame; its sections fade up
     on their own (.mg-rise), so the pane still arrives rather than appears. */
  .overview.armed .inner { transition: transform var(--rise); }
  .overview.armed:not(.risen) .inner { transform: translateY(32px); }
  .inner {
    position: relative; z-index: 1;
    display: flex; flex-direction: column; gap: 16px;
    padding: 20px 16px var(--mc-dock-clear);
    max-width: 1200px; margin: 0 auto;
  }
  /* From 640 it floats like the app's pane: centred, the same gutters at
     every width, rounded all round; the dock floats over its foot. */
  @media (min-width: 640px) {
    .overview {
      margin: 0 var(--mc-gutter) var(--mc-gutter); --frost-tint: var(--mc-glass);
      border-bottom: 1px solid var(--mc-glass-line); border-radius: var(--mc-r-lg); --frost-r: var(--mc-r-lg);
    }
    .inner { padding: 28px 20px var(--mc-dock-clear); }
  }
  @media (min-width: 1024px) { .inner { padding-left: 24px; padding-right: 24px; } }

  @media (prefers-reduced-motion: reduce) {
    .top { transition: none; }
    .overview.armed:not(.risen) .inner { transform: none; opacity: 0; }
    .overview.armed .inner { transition: opacity 200ms; }
  }

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

  .lic { flex: none; width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; background: var(--mc-glass-soft); border: 1px solid var(--mc-glass-line); color: var(--mc-ink2); }
  .links :global(.chev) { color: var(--mc-ink3); flex: none; }
</style>
