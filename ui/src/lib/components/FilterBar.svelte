<script>
  import { app, setShowSole, setDealType } from '$lib/state.svelte.js';
  import { filters, clearFilters, isFiltering } from '$lib/filters.svelte.js';
  import Seg from './glass/Seg.svelte';
  import Icon from './glass/Icon.svelte';
  import { play, fadeIn } from '$lib/motion.js';

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
    try { localStorage.setItem('obv2.view', filters.view); } catch { /* private mode */ }
  });

  const DEAL = [{ value: 'sale', label: 'For sale' }, { value: 'rent', label: 'To rent' }];
  const TIER = [{ value: '', label: 'All' }, { value: 'hot', label: 'Hot' }, { value: 'warm', label: 'Warm' }, { value: 'cold', label: 'Cold' }];
  const VIEW = [{ value: 'cards', label: 'Cards', icon: 'grid' }, { value: 'list', label: 'List', icon: 'list' }];
</script>

<div class="bar">
  <div class="row">
    <span class="deal"><Seg options={DEAL} value={app.dealType} onchange={pickDeal} label="Listing type" /></span>

    <label class="mg-search">
      <span class="ic"><Icon name="search" size={16} /></span>
      <input type="search" class="mg-input" data-page-search
             placeholder={rent ? 'Search title, street, agency…' : 'Search title, street, erf, agency…'}
             bind:value={filters.q} />
      {#if filters.q}
        <button type="button" class="clear" onclick={() => (filters.q = '')} aria-label="Clear the search"><Icon name="close" size={14} /></button>
      {/if}
    </label>

    {#if !rent}
      <span class="tierseg"><Seg options={TIER} value={filters.tier} onchange={(v) => (filters.tier = v)} label="Tier" /></span>
    {/if}

    <span class="mg-select sort">
      <select bind:value={filters.sort} title="sort order" aria-label="Sort order">
        {#if !rent}<option value="score">Sort: score</option>{/if}
        <option value="pricedesc">Sort: {rent ? 'rent' : 'price'} high → low</option>
        <option value="priceasc">Sort: {rent ? 'rent' : 'price'} low → high</option>
        <option value="newest">Sort: newest</option>
        {#if !rent}
          <option value="cut">Sort: biggest cut</option>
          <option value="weakness">Sort: weakest marketing</option>
        {/if}
      </select>
      <span class="ic"><Icon name="chevronDown" size={14} /></span>
    </span>

    <button type="button" class="mg-btn secondary more" class:on={refineOpen || refineCount > 0}
            onclick={() => (refineOpen = !refineOpen)} aria-expanded={refineOpen}>
      <Icon name="sliders" size={15} /> Filters{#if refineCount}<b class="cnt mg-tnum">{refineCount}</b>{/if}
    </button>

    <span class="count mg-tnum">{shown === total
      ? `${shown} ${rent ? 'rentals' : 'properties'}`
      : `${shown} of ${total}`}</span>

    <span class="view"><Seg options={VIEW} value={filters.view} onchange={(v) => (filters.view = v)} label="View" /></span>
  </div>

  {#if refineOpen}
    <div class="refine mg-panel" transition:play={fadeIn}>
      <span class="mg-select">
        <select bind:value={filters.suburb} aria-label="Suburb">
          <option value="">All suburbs</option>
          {#each suburbs as s (s)}<option value={s}>{s}</option>{/each}
        </select>
        <span class="ic"><Icon name="chevronDown" size={14} /></span>
      </span>
      {#if !rent}
        <span class="mg-select">
          <select bind:value={filters.mandate} aria-label="Mandate">
            <option value="">Any mandate</option>
            <option value="open">Open</option>
            <option value="probably_open">Probably open</option>
            <option value="unknown">Unknown</option>
          </select>
          <span class="ic"><Icon name="chevronDown" size={14} /></span>
        </span>
        <span class="mg-select">
          <select bind:value={filters.erf} aria-label="Erf status">
            <option value="">Any erf status</option>
            <option value="resolved">Erf resolved</option>
            <option value="candidates">Has candidates</option>
            <option value="unresolved">Unresolved</option>
          </select>
          <span class="ic"><Icon name="chevronDown" size={14} /></span>
        </span>
      {/if}
      <span class="range">
        <input type="number" min="0" placeholder="Min" class="mg-input" bind:value={filters.min} aria-label="Minimum price" />
        <span class="dash">–</span>
        <input type="number" min="0" placeholder="Max" class="mg-input" bind:value={filters.max} aria-label="Maximum price" />
        <span class="unit">{rent ? 'R thousand / period' : 'R million'}</span>
      </span>
      {#if !rent}
        <label class="sole">
          <input type="checkbox" checked={app.showSole} onchange={(e) => setShowSole(e.currentTarget.checked)} />
          Include sole mandates
        </label>
      {/if}
      {#if isFiltering()}
        <button type="button" class="mg-btn sm ghost" onclick={clearFilters}><Icon name="close" size={13} /> Clear all</button>
      {/if}
    </div>
  {/if}
</div>

<style>
  .bar { margin: 14px 0 14px; }
  .row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .mg-search { flex: 1 1 220px; max-width: 420px; }
  .mg-select { flex: none; }
  .mg-select > select { height: 36px; }

  .cnt {
    margin-left: 6px; min-width: 18px; height: 18px; padding: 0 5px; display: inline-flex; align-items: center; justify-content: center;
    border-radius: 9999px; background: var(--mc-accent); color: var(--mc-accent-ink); font-size: 11px;
  }
  .count { margin-left: auto; font: 400 12.5px/1 var(--mc-font); color: var(--mc-ink3); white-space: nowrap; }

  .refine { margin-top: 8px; padding: 10px 12px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .range { display: inline-flex; align-items: center; gap: 6px; }
  .range .mg-input { width: 88px; height: 36px; }
  .dash, .unit { color: var(--mc-ink3); font-size: 12.5px; }

  .sole { display: inline-flex; align-items: center; gap: 8px; min-height: 36px; font: 500 13px/1 var(--mc-font); color: var(--mc-ink2); cursor: pointer; }
  .sole input { width: 16px; height: 16px; margin: 0; }

  .deal, .tierseg, .view { display: inline-flex; flex: none; max-width: 100%; }

  /* a phone: search on top, then the two small segs side by side, the tier
     seg full width, sort + filters on one row, the count last */
  @media (max-width: 640px) {
    .row { gap: 8px; }
    .mg-search { flex-basis: 100%; max-width: none; order: 0; }
    .deal { order: 1; }
    .view { order: 2; margin-left: auto; }
    .tierseg { order: 3; flex-basis: 100%; }
    .tierseg :global(.seg) { display: flex; width: 100%; }
    .tierseg :global(.seg > button) { flex: 1; }
    .sort { order: 4; flex: 1 1 auto; }
    .more { order: 5; }
    .count { flex-basis: 100%; margin-left: 0; order: 6; }
  }
</style>
