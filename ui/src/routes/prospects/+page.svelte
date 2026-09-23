<script>
  import { app } from '$lib/state.svelte.js';
  import { page } from '$app/state';
  import { filters, applyFilters, sortRows, isFiltering, clearFilters } from '$lib/filters.svelte.js';
  import FilterBar from '$lib/components/FilterBar.svelte';
  import AiFinder from '$lib/components/AiFinder.svelte';
  import ProspectCard from '$lib/components/ProspectCard.svelte';
  import ProspectList from '$lib/components/ProspectList.svelte';
  import JobStrip from '$lib/components/JobStrip.svelte';
  import Drawer from '$lib/components/Drawer.svelte';
  import { fmtR, monthlyRent } from '$lib/format.js';

  const rows = $derived(sortRows(applyFilters(app.prospects)));
  const rent = $derived(app.dealType === 'rent');

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
     which a rental has. The rent book gets tiles it can actually fill: how
     much stock, where it is, and what the middle of the market asks. */
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

  const tiles = $derived(rent
    ? [['Rentals', rentInfo.count, ''],
       ['Suburbs', rentInfo.suburbs, ''],
       ['Median rent', rentInfo.median ? fmtR(rentInfo.median) : null, ''],
       ['Furnished', rentInfo.furnished, '']]
    : [['Hot right now', saleInfo.hot, 'hot'],
       ['Sellable', saleInfo.sellable, ''],
       ['Multi-agency proof', saleInfo.multi, ''],
       ['Erf resolved', saleInfo.erf, '']]);

  const crawling = $derived(app.status.running);

  /* One plain sentence about the book, the way the landing screen talks. */
  const line = $derived.by(() => {
    const s = app.status;
    if (s.running)
      return `Crawling · ${s.phase}${s.total ? ` · ${s.done}/${s.total} pages` : ''}`;
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

<div class="mg-row">
  <div class="titles">
    <h1 class="mg-h2">{rent ? 'Rentals' : 'Prospect engine'}</h1>
    <p class="line">
      {#if crawling}<span class="mg-dot ok"><i class="mg-ping"></i></span>{/if}{line}
    </p>
  </div>

  <div class="mg-actions">
    {#each tiles as [label, v, cls] (label)}
      <span class="mg-stat pill">
        <b class="v mg-tnum {cls}">{v ?? '—'}</b>
        <span class="k">{label}</span>
      </span>
    {/each}
  </div>
</div>

<!-- the engine's own progress strip; TODO(prospects agent): restyle as
     `.mg-strip` + `.mg-bar` -->
<JobStrip inline />

<AiFinder />

<div class="gap"><FilterBar shown={rows.length} total={app.prospects.length} /></div>

{#if !app.loaded}
  <div class="empty mg-glass-soft"><span class="mg-spin"></span>&nbsp; Loading {rent ? 'rentals' : 'prospects'}…</div>
{:else if !app.prospects.length}
  <div class="empty mg-glass-soft">
    {#if rent}
      <p class="big">No rentals yet</p>
      <p>The to-rent book is crawled on request — start a crawl with
        <b>Include rentals</b> ticked, or wait for tonight's full pass.</p>
    {:else}
      <p class="big">No prospects yet</p>
      <p>Run your first crawl — pick portals and areas, the engine does the rest.</p>
    {/if}
    <button class="mg-btn primary" onclick={() => (app.runOpen = true)}>New crawl</button>
  </div>
{:else if !rows.length}
  <div class="empty mg-glass-soft">
    <p>{rent ? 'No rentals match these filters.' : 'Nothing matches these filters.'}</p>
    {#if isFiltering()}<button class="mg-btn secondary" onclick={clearFilters}>Clear filters</button>{/if}
  </div>
{:else if filters.view === 'cards'}
  <div class="grid">
    {#each visible as r (r.listing_key)}
      <ProspectCard {r} />
    {/each}
  </div>
{:else}
  <ProspectList rows={visible} />
{/if}

{#if rows.length > limit}
  <div class="more">
    <button class="mg-btn secondary" onclick={() => (limit += 120)}>
      Show more · {rows.length - limit} remaining
    </button>
  </div>
{/if}

<Drawer />

<style>
  /* The page header lives inside the app's pane: title, one sentence, and
     the figures on the right. The photograph behind it belongs to the scene.

     TODO(prospects agent): FilterBar, AiFinder, ProspectCard/List, Drawer,
     JobStrip and RunPanel are all still on the old vocabulary. */
  .titles { min-width: 0; }
  .line {
    margin: 4px 0 0; display: flex; align-items: center; gap: 7px;
    font: 400 13px/1.5 var(--mg-font); color: var(--mg-i2);
  }
  .line .mg-dot { margin-top: 1px; }

  .mg-actions .v { color: var(--mg-i); }
  .mg-actions .v.hot { color: var(--mg-crit); }

  .grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(285px, 1fr)); }

  .empty {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 12px; text-align: center; color: var(--mg-i2);
    padding: 64px 16px; border-radius: var(--mg-r-card);
  }
  .empty .big { font: 600 17px/1.3 var(--mg-font); color: var(--mg-i); margin: 0; }
  .empty p { margin: 0; font-size: 13px; }

  .more { display: flex; justify-content: center; margin-top: 20px; }

  .gap { padding-top: 0.3rem; }
</style>
