<script>
  import { onMount } from 'svelte';
  import { app, setDealType, setShowSole } from '$lib/state.svelte.js';
  import { page } from '$app/state';
  import { goto, replaceState } from '$app/navigation';
  import { get, propertyPath } from '$lib/api.js';
  import { filters, isFiltering, clearFilters, toParams, fromParams, hasFilterParams,
           runQuery, loadMore, watchQuery } from '$lib/filters.svelte.js';
  import { finder } from '$lib/finder.svelte.js';
  import FilterBar from '$lib/components/FilterBar.svelte';
  import AiFinder from '$lib/components/AiFinder.svelte';
  import CrawlSchedule from '$lib/components/CrawlSchedule.svelte';
  import ProspectCard from '$lib/components/ProspectCard.svelte';
  import ProspectList from '$lib/components/ProspectList.svelte';
  import JobStrip from '$lib/components/JobStrip.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import { fmtR, fmtInt } from '$lib/format.js';

  /* The page no longer holds the whole book: the server filters, sorts and
     pages it (/api/prospects/query, filters.svelte.js), and this shows one
     window of the result plus its facet counts. */
  const rows = $derived(app.list.rows);
  const rent = $derived(app.dealType === 'rent');
  const summary = $derived(app.list.summary);

  /* Old deep links (/prospects?open=<listing_key>) now land on the property
     page; replaceState so Back skips this hop. */
  let leaving = false;
  $effect(() => {
    const key = page.url.searchParams.get('open');
    if (key) { leaving = true; goto(propertyPath(key), { replaceState: true }); }
  });

  /* The URL is the filter set, so a view can be bookmarked or pasted to a
     colleague. On arrival a URL that carries filters wins; a bare
     /prospects keeps whatever was set before (the map hop and back). */
  let ready = $state(false);
  onMount(() => {
    const sp = page.url.searchParams;
    if (!sp.get('open') && hasFilterParams(sp)) {
      const want = fromParams(sp);
      if (want.sole !== app.showSole) setShowSole(want.sole);
      if (want.type !== app.dealType) setDealType(want.type);
    }
    ready = true;
    return watchQuery();
  });

  /* Any filter / sort / book change: fetch page one (debounced so typing in
     the search box is one request, not six) and mirror it into the URL. */
  let timer = null;
  let first = true;
  $effect(() => {
    const qs = toParams().toString();
    if (!ready || leaving) return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      runQuery();
      const url = qs ? '?' + qs : page.url.pathname;
      if (!leaving && location.search !== (qs ? '?' + qs : '')) {
        try { replaceState(url, page.state); } catch { /* router not ready */ }
      }
    }, first ? 0 : 220);
    first = false;
    return () => clearTimeout(timer);
  });

  /* The finder names listing_keys the current page may not hold: fetch just
     those rows (by key) so its picks can render without the whole book. */
  $effect(() => {
    const picks = finder.result?.picks || [];
    const have = new Set([...app.list.rows, ...app.prospects].map((r) => r.listing_key));
    const missing = picks.map((p) => p.listing_key).filter((k) => k && !have.has(k) && !app.extraRows[k]);
    if (!missing.length) return;
    const p = new URLSearchParams({ keys: missing.join(','), limit: '100', facets: '0', sole: '1' });
    if (app.dealType === 'rent') p.set('type', 'rent');
    get('/api/prospects/query?' + p).then((d) => {
      const next = { ...app.extraRows };
      for (const r of d.rows) next[r.listing_key] = r;
      app.extraRows = next;
    }).catch(() => { /* the picks just stay hidden */ });
  });

  /* Rental tiles come from the book summary the query sends along. */
  const rentInfo = $derived({
    count: app.stats?.rentals ?? summary?.total ?? null,
    suburbs: summary?.suburbs ?? null,
    median: summary?.median_rent ?? null,
    furnished: summary?.furnished ?? null
  });

  const saleInfo = $derived.by(() => {
    const s = app.stats || {};
    return { hot: summary?.hot ?? s.hot ?? null, sellable: s.sellable, multi: s.multi_agency, erf: s.erf_ready };
  });

  const crawling = $derived(!!app.status.running);
  const share = (a, b) => (a != null && b ? (100 * a) / b : null);

  const tiles = $derived.by(() => {
    if (rent)
      return [{ k: 'Rentals', v: rentInfo.count, sub: 'in the to-rent book' },
              { k: 'Suburbs', v: rentInfo.suburbs, sub: 'with stock' },
              { k: 'Median rent', v: rentInfo.median ? fmtR(rentInfo.median) : null, sub: 'a month' },
              { k: 'Furnished', v: rentInfo.furnished, sub: 'ready to move in' }];
    const s = app.stats || {};
    const hot = saleInfo.hot;
    return [
      { k: 'Hot', v: hot, tone: hot ? 'crit' : '', sub: 'call these first', live: crawling,
        pct: share(hot, s.sellable), pctDetail: `${hot ?? '—'} of ${s.sellable ?? '—'} sellable` },
      { k: 'Sellable', v: s.sellable ?? null, sub: s.properties != null ? `of ${fmtInt(s.properties)} properties` : 'scored and deduped',
        pct: share(s.sellable, s.properties), pctDetail: `${s.sellable ?? '—'} of ${s.properties ?? '—'} properties` },
      { k: 'Multi-agency', v: s.multi_agency ?? null, tone: 'ok', sub: 'proven open mandate',
        pct: share(s.multi_agency, s.sellable), pctDetail: `${s.multi_agency ?? '—'} of ${s.sellable ?? '—'} sellable` },
      { k: 'Erf resolved', v: s.erf_ready ?? null, sub: 'matched to cadastre',
        pct: share(s.erf_ready, s.properties), pctDetail: `${s.erf_ready ?? '—'} of ${s.properties ?? '—'} properties` }
    ];
  });

  /* One plain sentence about the book. */
  const line = $derived.by(() => {
    const s = app.status;
    if (s.running) return 'Crawl running — progress below.';
    if (!app.list.loaded) return `Loading the ${rent ? 'rent' : 'sale'} book…`;
    if (rent) {
      if (!rentInfo.count) return 'No rentals yet — crawl with “include rentals” ticked.';
      const where = rentInfo.suburbs ? ` across ${rentInfo.suburbs} suburb${rentInfo.suburbs === 1 ? '' : 's'}` : '';
      const mid = rentInfo.median ? `, median ${fmtR(rentInfo.median)} a month` : '';
      return `${fmtInt(rentInfo.count)} rental${rentInfo.count === 1 ? '' : 's'}${where}${mid}.`;
    }
    const parts = [];
    if (saleInfo.hot) parts.push(`${saleInfo.hot} hot prospect${saleInfo.hot === 1 ? '' : 's'}`);
    if (saleInfo.sellable) parts.push(`${saleInfo.sellable} sellable`);
    if (saleInfo.multi) parts.push(`${saleInfo.multi} proven open by two agencies`);
    if (!parts.length) return 'Nothing crawled yet — pick portals and areas to start.';
    return parts.join(', ') + '.';
  });

  const bookEmpty = $derived(app.list.loaded && summary && summary.total === 0);
  const remaining = $derived(Math.max(0, app.list.total - rows.length));
</script>

<svelte:head><title>Oblivion — {rent ? 'Rentals' : 'Prospect Engine'}</title></svelte:head>

<div class="mg-row head">
  <div class="titles">
    <h1 class="mg-h1">{rent ? 'Rentals' : 'Prospect engine'}</h1>
    <p class="mg-sub line">
      {#if crawling}<span class="mg-dot warn"><i class="mg-ping"></i></span>{/if}{line}
    </p>
  </div>
  <div class="sched"><CrawlSchedule /></div>
</div>

<div class="tiles">
  {#each tiles as t, i (t.k)}
    <StatTile label={t.k} value={t.v} sub={t.sub} tone={t.tone || ''} live={!!t.live}
              pct={t.pct ?? null} pctDetail={t.pctDetail || ''} pctTone={t.tone === 'crit' ? 'crit' : 'ok'} {i}
              loading={rent ? !app.list.loaded : !app.stats || (t.k === 'Hot' && !app.list.loaded)} />
  {/each}
</div>

<JobStrip inline />

<AiFinder />

<FilterBar shown={app.list.total} total={summary?.total ?? app.list.total} />

{#if !app.list.loaded}
  <div class="grid" aria-busy="true">
    {#each Array(6) as _, i (i)}
      <div class="skcard mg-panel" style:--i={i}>
        <Skeleton h="150px" r="0" delay={i * 60} />
        <div class="skbody">
          <Skeleton h="18px" w="40%" delay={i * 60} />
          <Skeleton h="13px" lines={2} delay={i * 60 + 40} />
        </div>
      </div>
    {/each}
  </div>
{:else if bookEmpty}
  <div class="mg-panel">
    <Empty icon="building" title={rent ? 'No rentals yet' : 'No prospects yet'}
           hint={rent
             ? 'The to-rent book is crawled on request — start a crawl with “Include rentals” ticked, or wait for tonight’s full pass.'
             : 'Run your first crawl — pick portals and areas, the engine does the rest.'}>
      <button type="button" class="mg-btn primary" onclick={() => (app.runOpen = true)}>New crawl</button>
    </Empty>
  </div>
{:else if !rows.length}
  <div class="mg-panel">
    <Empty icon="filter" title={rent ? 'No rentals match these filters' : 'Nothing matches these filters'}
           hint="Loosen the search, the tier or the price range — or tap a chip above to drop one filter.">
      {#if isFiltering()}<button type="button" class="mg-btn secondary" onclick={clearFilters}>Clear filters</button>{/if}
    </Empty>
  </div>
{:else if filters.view === 'cards'}
  <div class="grid">
    {#each rows as r, i (r.listing_key)}
      <ProspectCard {r} i={i % 60} />
    {/each}
  </div>
{:else}
  <ProspectList {rows} />
{/if}

{#if app.list.loaded && remaining > 0}
  <div class="more">
    <button type="button" class="mg-btn secondary" onclick={loadMore} disabled={app.list.loading}>
      {app.list.loading ? 'Loading…' : `Show more · ${fmtInt(remaining)} remaining`}
    </button>
  </div>
{/if}
{#if app.list.error}
  <p class="mg-hint err">Could not load the list: {app.list.error}</p>
{/if}

<style>
  .head { margin-bottom: 14px; display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
  .sched { flex: none; }
  .titles { min-width: 0; }
  .line { margin-top: 4px; display: flex; align-items: center; gap: 8px; }

  .tiles { display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-bottom: 16px; }
  @media (min-width: 900px) { .tiles { grid-template-columns: repeat(4, minmax(0, 1fr)); } }

  .grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(270px, 1fr)); }
  @media (max-width: 420px) { .grid { grid-template-columns: 1fr; } }

  .skcard { overflow: hidden; }
  .skbody { padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 10px; }

  .more { display: flex; justify-content: center; margin-top: 20px; }
  .err { margin-top: 12px; text-align: center; color: var(--mc-crit); }
</style>
