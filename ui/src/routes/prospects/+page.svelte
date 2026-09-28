<script>
  import { onMount } from 'svelte';
  import { app, watchProspects } from '$lib/state.svelte.js';
  import { page } from '$app/state';
  import { filters, applyFilters, sortRows, isFiltering, clearFilters } from '$lib/filters.svelte.js';
  import FilterBar from '$lib/components/FilterBar.svelte';
  import AiFinder from '$lib/components/AiFinder.svelte';
  import ProspectCard from '$lib/components/ProspectCard.svelte';
  import ProspectList from '$lib/components/ProspectList.svelte';
  import JobStrip from '$lib/components/JobStrip.svelte';
  import Drawer from '$lib/components/Drawer.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import { fmtR, fmtInt, monthlyRent } from '$lib/format.js';

  const rows = $derived(sortRows(applyFilters(app.prospects)));
  const rent = $derived(app.dealType === 'rent');

  /* The list is no longer fetched on boot (state.svelte.js), so this page
     asks for it — a no-op when it is already in memory or on the way. */
  onMount(watchProspects);

  /* Deep link from lead management: /prospects?open=<listing_key> */
  let opened = false;
  $effect(() => {
    const key = page.url.searchParams.get('open');
    if (key && app.loaded && !opened) { opened = true; app.selectedKey = key; }
  });

  /* big grids paint in slices so filtering stays instant on ~1k properties */
  let limit = $state(60);
  $effect(() => { rows.length; filters.view; limit = 60; });
  const visible = $derived(rows.slice(0, limit));

  /* The sale tiles all count scored, deduped, erf-resolved work — none of
     which a rental has. The rent book gets tiles it can actually fill. */
  const rentInfo = $derived.by(() => {
    const list = app.prospects;
    const rents = list.map(monthlyRent).filter(Boolean).sort((a, b) => a - b);
    return {
      count: app.stats?.rentals ?? list.length,
      suburbs: new Set(list.map((r) => r.suburb).filter(Boolean)).size,
      median: rents.length ? Math.round(rents[Math.floor(rents.length / 2)]) : null,
      furnished: list.filter((r) => /^y/i.test(r.furnished || '')).length
    };
  });

  const saleInfo = $derived.by(() => {
    const s = app.stats || {};
    return {
      hot: app.prospects.filter((r) => r.tier === 'hot').length,
      sellable: s.sellable, multi: s.multi_agency, erf: s.erf_ready
    };
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
    const hot = app.loaded ? saleInfo.hot : null;
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
    if (!app.loaded) return `Loading the ${rent ? 'rent' : 'sale'} book…`;
    if (rent) {
      if (!rentInfo.count) return 'No rentals yet — crawl with “include rentals” ticked.';
      const where = rentInfo.suburbs ? ` across ${rentInfo.suburbs} suburb${rentInfo.suburbs === 1 ? '' : 's'}` : '';
      const mid = rentInfo.median ? `, median ${fmtR(rentInfo.median)} a month` : '';
      return `${rentInfo.count} rental${rentInfo.count === 1 ? '' : 's'}${where}${mid}.`;
    }
    const parts = [];
    if (saleInfo.hot) parts.push(`${saleInfo.hot} hot prospect${saleInfo.hot === 1 ? '' : 's'}`);
    if (saleInfo.sellable) parts.push(`${saleInfo.sellable} sellable`);
    if (saleInfo.multi) parts.push(`${saleInfo.multi} proven open by two agencies`);
    if (!parts.length) return 'Nothing crawled yet — pick portals and areas to start.';
    return parts.join(', ') + '.';
  });
</script>

<svelte:head><title>Oblivion — {rent ? 'Rentals' : 'Prospect Engine'}</title></svelte:head>

<div class="mg-row head">
  <div class="titles">
    <h1 class="mg-h1">{rent ? 'Rentals' : 'Prospect engine'}</h1>
    <p class="mg-sub line">
      {#if crawling}<span class="mg-dot warn"><i class="mg-ping"></i></span>{/if}{line}
    </p>
  </div>
</div>

<div class="tiles">
  {#each tiles as t, i (t.k)}
    <StatTile label={t.k} value={t.v} sub={t.sub} tone={t.tone || ''} live={!!t.live}
              pct={t.pct ?? null} pctDetail={t.pctDetail || ''} pctTone={t.tone === 'crit' ? 'crit' : 'ok'} {i}
              loading={rent ? !app.loaded : !app.stats || (t.k === 'Hot' && !app.loaded)} />
  {/each}
</div>

<JobStrip inline />

<AiFinder />

<FilterBar shown={rows.length} total={app.prospects.length} />

{#if !app.loaded}
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
{:else if !app.prospects.length}
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
           hint="Loosen the search, the tier or the price range.">
      {#if isFiltering()}<button type="button" class="mg-btn secondary" onclick={clearFilters}>Clear filters</button>{/if}
    </Empty>
  </div>
{:else if filters.view === 'cards'}
  <div class="grid">
    {#each visible as r, i (r.listing_key)}
      <ProspectCard {r} {i} />
    {/each}
  </div>
{:else}
  <ProspectList rows={visible} />
{/if}

{#if rows.length > limit}
  <div class="more">
    <button type="button" class="mg-btn secondary" onclick={() => (limit += 120)}>
      Show more · {rows.length - limit} remaining
    </button>
  </div>
{/if}

<Drawer />

<style>
  .head { margin-bottom: 14px; }
  .titles { min-width: 0; }
  .line { margin-top: 4px; display: flex; align-items: center; gap: 8px; }

  .tiles { display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-bottom: 16px; }
  @media (min-width: 900px) { .tiles { grid-template-columns: repeat(4, minmax(0, 1fr)); } }

  .grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(270px, 1fr)); }
  @media (max-width: 420px) { .grid { grid-template-columns: 1fr; } }

  .skcard { overflow: hidden; }
  .skbody { padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 10px; }

  .more { display: flex; justify-content: center; margin-top: 20px; }
</style>
