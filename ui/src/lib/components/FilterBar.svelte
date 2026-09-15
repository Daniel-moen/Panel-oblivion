<script>
  import { app, setShowSole, setDealType } from '$lib/state.svelte.js';
  import { filters, clearFilters, isFiltering } from '$lib/filters.svelte.js';

  let { shown, total } = $props();

  const rent = $derived(app.dealType === 'rent');

  /* Switching books changes what a number means — a price range typed in
     millions is nonsense against a monthly rent, and tier/mandate/erf have
     nothing to say about a rental — so the filters start clean. */
  function pickDeal(v) {
    if (app.dealType === v) return;
    clearFilters();
    if (v === 'rent' && ['score', 'cut', 'weakness'].includes(filters.sort))
      filters.sort = 'pricedesc';
    setDealType(v);
  }

  let refineOpen = $state(false);
  const suburbs = $derived(
    [...new Set(app.prospects.map((r) => r.suburb).filter(Boolean))].sort());

  const refineCount = $derived(
    (rent
      ? [filters.suburb, filters.min, filters.max]
      : [filters.suburb, filters.mandate, filters.erf, filters.min, filters.max,
         app.showSole ? '1' : '']).filter(Boolean).length);

  /* restore synchronously before the persist effect ever runs */
  const storedView = typeof localStorage === 'undefined' ? null : localStorage.getItem('obv2.view');
  if (storedView === 'list' || storedView === 'cards') filters.view = storedView;
  $effect(() => {
    localStorage.setItem('obv2.view', filters.view);
  });
</script>

<div class="bar">
  <div class="row">
    <div class="seg deal" role="group" aria-label="listing type">
      {#each [['sale', 'For sale'], ['rent', 'To rent']] as [v, l] (v)}
        <button class:on={app.dealType === v} onclick={() => pickDeal(v)}>{l}</button>
      {/each}
    </div>

    <input type="search" class="search"
           placeholder={rent ? 'Search title, street, agency…' : 'Search title, street, erf, agency…'}
           bind:value={filters.q} />

    {#if !rent}
      <div class="seg" role="group" aria-label="tier">
        {#each [['', 'All'], ['hot', 'Hot'], ['warm', 'Warm'], ['cold', 'Cold']] as [v, l] (v)}
          <button class:on={filters.tier === v} class="t-{v || 'all'}"
                  onclick={() => (filters.tier = v)}>{l}</button>
        {/each}
      </div>
    {/if}

    <select bind:value={filters.sort} title="sort order">
      {#if !rent}<option value="score">Sort: score</option>{/if}
      <option value="pricedesc">Sort: {rent ? 'rent' : 'price'} high → low</option>
      <option value="priceasc">Sort: {rent ? 'rent' : 'price'} low → high</option>
      <option value="newest">Sort: newest</option>
      {#if !rent}
        <option value="cut">Sort: biggest cut</option>
        <option value="weakness">Sort: weakest marketing</option>
      {/if}
    </select>

    <button class="btn" class:hasmore={refineCount > 0} onclick={() => (refineOpen = !refineOpen)}>
      Filters{#if refineCount}<b class="cnt">{refineCount}</b>{/if}
    </button>

    <span class="count">{shown === total
      ? `${shown} ${rent ? 'rentals' : 'properties'}`
      : `${shown} of ${total}`}</span>

    <div class="seg view" role="group" aria-label="view">
      <button class:on={filters.view === 'cards'} onclick={() => (filters.view = 'cards')}
              title="card view">▦ Cards</button>
      <button class:on={filters.view === 'list'} onclick={() => (filters.view = 'list')}
              title="list view">☰ List</button>
    </div>
  </div>

  {#if refineOpen}
    <div class="row refine panel">
      <select bind:value={filters.suburb}>
        <option value="">All suburbs</option>
        {#each suburbs as s (s)}<option value={s}>{s}</option>{/each}
      </select>
      {#if !rent}
        <select bind:value={filters.mandate}>
          <option value="">Any mandate</option>
          <option value="open">Open</option>
          <option value="probably_open">Probably open</option>
          <option value="unknown">Unknown</option>
        </select>
        <select bind:value={filters.erf}>
          <option value="">Any erf status</option>
          <option value="resolved">Erf resolved</option>
          <option value="candidates">Has candidates</option>
          <option value="unresolved">Unresolved</option>
        </select>
      {/if}
      <span class="range">
        <input type="number" min="0" placeholder="Min" bind:value={filters.min} />
        <span class="dash">–</span>
        <input type="number" min="0" placeholder="Max" bind:value={filters.max} />
        <span class="unit">{rent ? 'R thousand / period' : 'R million'}</span>
      </span>
      {#if !rent}
        <label class="sole">
          <input type="checkbox" checked={app.showSole}
                 onchange={(e) => setShowSole(e.currentTarget.checked)} />
          Include sole mandates
        </label>
      {/if}
      {#if isFiltering()}
        <button class="clear" onclick={clearFilters}>✕ Clear all</button>
      {/if}
    </div>
  {/if}
</div>

<style>
  .bar { margin: 1.1rem 0 1.2rem; }
  .row { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; }
  .refine { margin-top: 0.6rem; padding: 0.75rem 1rem; }

  .search { flex: 1 1 260px; max-width: 440px; }

  .seg { display: inline-flex; background: var(--bg-2);
         border: 1px solid var(--line-2); border-radius: var(--r-sm);
         overflow: hidden; box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04); }
  .seg button { background: none; border: none; color: var(--ink-2);
                font: 500 0.82rem/1.3 var(--font-ui);
                padding: 0.46rem 0.85rem;
                border-right: 1px solid var(--line); }
  .seg button:last-child { border-right: none; }
  .seg button:hover { color: var(--ink); background: var(--bg-3); }
  .seg button.on { background: var(--accent-soft); color: var(--accent-2); font-weight: 600; }
  .seg button.on.t-hot { background: var(--hot-soft); color: #b91c1c; }
  .seg button.on.t-warm { background: var(--warm-soft); color: #92400e; }
  .seg button.on.t-cold { background: var(--cold-soft); color: #4b5563; }
  .deal button { white-space: nowrap; }

  .cnt { margin-left: 0.45rem; background: var(--accent); color: #fff;
         border-radius: 999px; padding: 0.02rem 0.44rem; font-size: 0.7rem; }
  .hasmore { border-color: var(--accent-line); color: var(--accent-2); }

  .count { margin-left: auto; font-size: 0.76rem; color: var(--ink-3);
           font-variant-numeric: tabular-nums; }

  .range { display: inline-flex; align-items: center; gap: 0.35rem; }
  .range input { width: 4.8rem; }
  .dash, .unit { color: var(--ink-3); font-size: 0.78rem; }

  .sole { display: inline-flex; align-items: center; gap: 0.45rem;
          font-size: 0.82rem; color: var(--ink-2); cursor: pointer; }
  .sole input { accent-color: var(--accent); width: 15px; height: 15px; }

  .clear { background: none; border: none; font: 600 0.78rem/1.3 var(--font-ui);
           color: var(--ink-3); }
  .clear:hover { color: var(--bad); }
</style>
