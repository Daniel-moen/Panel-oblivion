<script>
  import { app } from '$lib/state.svelte.js';
  import { page } from '$app/state';
  import { filters, applyFilters, sortRows, isFiltering, clearFilters } from '$lib/filters.svelte.js';
  import FilterBar from '$lib/components/FilterBar.svelte';
  import AiFinder from '$lib/components/AiFinder.svelte';
  import ProspectCard from '$lib/components/ProspectCard.svelte';
  import ProspectList from '$lib/components/ProspectList.svelte';
  import Drawer from '$lib/components/Drawer.svelte';

  const rows = $derived(sortRows(applyFilters(app.prospects)));

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

  const stat = $derived.by(() => {
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
</script>

<svelte:head><title>Oblivion — Prospect Engine</title></svelte:head>

<div class="stats">
  {#each stat as [label, v, cls] (label)}
    <div class="stat panel {cls}">
      <span class="slabel">{label}</span>
      <b>{v ?? '—'}</b>
    </div>
  {/each}
</div>

<AiFinder />

<FilterBar shown={rows.length} total={app.prospects.length} />

{#if !app.loaded}
  <div class="empty panel"><span class="spin"></span>&nbsp; Loading prospects…</div>
{:else if !app.prospects.length}
  <div class="empty panel">
    <p class="big">No prospects yet</p>
    <p>Run your first crawl — pick portals and areas, the engine does the rest.</p>
    <button class="btn primary" onclick={() => (app.runOpen = true)}>+ New crawl</button>
  </div>
{:else if !rows.length}
  <div class="empty panel">
    <p>Nothing matches these filters.</p>
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
