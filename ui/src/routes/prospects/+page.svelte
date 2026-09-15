<script>
  import { app } from '$lib/state.svelte.js';
  import { page } from '$app/state';
  import { filters, applyFilters, sortRows, isFiltering, clearFilters } from '$lib/filters.svelte.js';
  import FilterBar from '$lib/components/FilterBar.svelte';
  import AiFinder from '$lib/components/AiFinder.svelte';
  import ProspectCard from '$lib/components/ProspectCard.svelte';
  import ProspectList from '$lib/components/ProspectList.svelte';
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
  const rentStat = $derived.by(() => {
    const list = app.prospects;
    const rents = list.map(monthlyRent).filter(Boolean).sort((a, b) => a - b);
    const median = rents.length ? rents[Math.floor(rents.length / 2)] : null;
    const suburbs = new Set(list.map((r) => r.suburb).filter(Boolean));
    const furnished = list.filter((r) => /^y/i.test(r.furnished || '')).length;
    return [
      ['Rentals crawled', app.stats?.rentals, 'accent'],
      ['In this view', list.length, ''],
      ['Suburbs', suburbs.size, ''],
      ['Median rent / month', median ? fmtR(Math.round(median)) : null, ''],
      ['Furnished', furnished, 'dim']
    ];
  });

  const saleStat = $derived.by(() => {
    const s = app.stats || {};
    const hot = app.prospects.filter((r) => r.tier === 'hot').length;
    return [
      ['Sellable prospects', s.sellable, 'accent'],
      ['Hot right now', hot, hot ? 'hot' : ''],
      ['Multi-agency proof', s.multi_agency, ''],
      ['Erf resolved', s.erf_ready, ''],
      ['Properties', s.properties, 'dim'],
      ['Listings', s.listings, 'dim']
    ];
  });

  const stat = $derived(rent ? rentStat : saleStat);
</script>

<svelte:head><title>Oblivion — {rent ? 'Rentals' : 'Prospect Engine'}</title></svelte:head>

<div class="stats">
  {#each stat as [label, v, cls] (label)}
    <div class="stat panel {cls}">
      <span class="slabel">{label}</span>
      <b>{v ?? '—'}</b>
    </div>
  {/each}
</div>

{#if !rent}<AiFinder />{/if}

<FilterBar shown={rows.length} total={app.prospects.length} />

{#if !app.loaded}
  <div class="empty panel"><span class="spin"></span>&nbsp; Loading {rent ? 'rentals' : 'prospects'}…</div>
{:else if !app.prospects.length}
  <div class="empty panel">
    {#if rent}
      <p class="big">No rentals yet</p>
      <p>The to-rent book is crawled on request — start a crawl with
        <b>Include rentals</b> ticked, or wait for tonight's full pass.</p>
    {:else}
      <p class="big">No prospects yet</p>
      <p>Run your first crawl — pick portals and areas, the engine does the rest.</p>
    {/if}
    <button class="btn primary" onclick={() => (app.runOpen = true)}>+ New crawl</button>
  </div>
{:else if !rows.length}
  <div class="empty panel">
    <p>{rent ? 'No rentals match these filters.' : 'Nothing matches these filters.'}</p>
    {#if isFiltering()}<button class="btn" onclick={clearFilters}>Clear filters</button>{/if}
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
    <button class="btn" onclick={() => (limit += 120)}>
      Show more · {rows.length - limit} remaining
    </button>
  </div>
{/if}

<Drawer />

<style>
  .stats {
    display: grid; gap: 0.8rem; margin-top: 1.2rem;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  }
  .stat { padding: 0.85rem 1.1rem; }
  .slabel { display: block; font-size: 0.74rem; font-weight: 500; color: var(--ink-3); }
  .stat b { display: block; margin-top: 0.2rem; font-size: 1.55rem; font-weight: 700;
            letter-spacing: -0.02em; line-height: 1.2; color: var(--ink);
            font-variant-numeric: tabular-nums; }
  .stat.accent b { color: var(--accent-2); }
  .stat.hot b { color: var(--hot); }
  .stat.dim b { font-size: 1.2rem; font-weight: 600; color: var(--ink-2); }

  .grid { display: grid; gap: 1rem;
          grid-template-columns: repeat(auto-fill, minmax(285px, 1fr)); }

  .empty {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 0.8rem; text-align: center; color: var(--ink-2);
    padding: 4.5rem 1rem;
  }
  .empty .big { font-size: 1.2rem; font-weight: 700; color: var(--ink); margin: 0; }
  .empty p { margin: 0; font-size: 0.88rem; }

  .more { display: flex; justify-content: center; margin-top: 1.4rem; }
</style>
