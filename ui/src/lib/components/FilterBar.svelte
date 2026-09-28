<script>
  /* The bar over the prospect list: book, search, tier, sort, the Filters
     sheet, saved views, CSV export and a chip per active filter. Every
     control edits `filters`; the page re-runs the server query off them. */
  import { app, setDealType, setShowSole, toast } from '$lib/state.svelte.js';
  import { filters, clearFilters, isFiltering, chips, clearKeys, views, loadViews, saveView,
           deleteView, viewActive, fromParams, exportUrl, has, toggle } from '$lib/filters.svelte.js';
  import FilterSheet from './FilterSheet.svelte';
  import Seg from './glass/Seg.svelte';
  import Icon from './glass/Icon.svelte';
  import { fmtInt } from '$lib/format.js';
  import { onMount } from 'svelte';

  let { shown, total } = $props();

  const rent = $derived(app.dealType === 'rent');

  /* Switching books changes what a number means — a price range typed in
     millions is nonsense against a monthly rent, and tier/mandate/erf have
     nothing to say about a rental — so the filters start clean. */
  function pickDeal(v) {
    if (app.dealType === v) return;
    clearFilters();
    filters.sort = v === 'rent' ? 'pricedesc' : 'score';
    setDealType(v);
  }

  let sheetOpen = $state(false);
  const active = $derived(chips());
  /* The bar's own controls (search, tier) show themselves; the badge on
     Filters counts what only the sheet shows. */
  const sheetCount = $derived(active.filter((c) => !['q', 'tier'].includes(c.keys[0])).length + (app.showSole ? 1 : 0));

  /* restore synchronously before the persist effect ever runs */
  const storedView = typeof localStorage === 'undefined' ? null : localStorage.getItem('obv2.view');
  if (storedView === 'list' || storedView === 'cards') filters.view = storedView;
  $effect(() => {
    try { localStorage.setItem('obv2.view', filters.view); } catch { /* private mode */ }
  });

  onMount(() => { if (!views.loaded) loadViews(); });

  /* A view is a query string: load it into the filters, switching book /
     sole if it asks for another one. Tapping the lit view clears it. */
  async function apply(v) {
    if (viewActive(v)) { clearFilters(); return; }
    const want = fromParams(v.params);
    if (want.sole !== app.showSole) setShowSole(want.sole);
    if (want.type !== app.dealType) await setDealType(want.type);
  }

  let naming = $state(false);
  let name = $state('');
  async function save(e) {
    e?.preventDefault();
    const n = name.trim();
    if (!n) return;
    try {
      await saveView(n);
      toast(`Saved view “${n}”`, 'ok');
      naming = false;
      name = '';
    } catch (err) {
      toast('Could not save the view: ' + err.message, 'error');
    }
  }
  async function remove(v) {
    try { await deleteView(v.id); toast(`Deleted “${v.name}”`); }
    catch (err) { toast('Could not delete: ' + err.message, 'error'); }
  }
  function focus(node) { node.focus(); }

  const DEAL = [{ value: 'sale', label: 'For sale' }, { value: 'rent', label: 'To rent' }];
  const VIEW = [{ value: 'cards', label: 'Cards', icon: 'grid' }, { value: 'list', label: 'List', icon: 'list' }];
  const TIERS = ['hot', 'warm', 'cold'];
  const presets = $derived(rent ? [] : views.presets);
</script>

<div class="bar">
  <div class="row">
    <span class="deal"><Seg options={DEAL} value={app.dealType} onchange={pickDeal} label="Listing type" /></span>

    <label class="mg-search">
      <span class="ic"><Icon name="search" size={16} /></span>
      <input type="search" class="mg-input" data-page-search
             placeholder={rent ? 'Search title, street, agency…' : 'Search title, street, erf, agency, “pool”…'}
             bind:value={filters.q} />
      {#if filters.q}
        <button type="button" class="clear" onclick={() => (filters.q = '')} aria-label="Clear the search"><Icon name="close" size={14} /></button>
      {/if}
    </label>

    {#if !rent}
      <span class="tiers" role="group" aria-label="Tier">
        {#each TIERS as t (t)}
          <button type="button" class="mg-chip tchip" class:on={has('tier', t)} aria-pressed={has('tier', t)}
                  onclick={() => toggle('tier', t)}>
            {t[0].toUpperCase() + t.slice(1)}
            {#if app.list.facets?.tier?.[t] != null}<span class="n mg-tnum">{fmtInt(app.list.facets.tier[t])}</span>{/if}
          </button>
        {/each}
      </span>
    {/if}

    <span class="mg-select sort">
      <select bind:value={filters.sort} title="sort order" aria-label="Sort order">
        {#if !rent}<option value="score">Sort: score</option>{/if}
        <option value="pricedesc">Sort: {rent ? 'rent' : 'price'} high → low</option>
        <option value="priceasc">Sort: {rent ? 'rent' : 'price'} low → high</option>
        <option value="newest">Sort: newest</option>
        <option value="stale">Sort: longest on market</option>
        <option value="beds">Sort: most bedrooms</option>
        {#if !rent}
          <option value="cut">Sort: biggest cut</option>
          <option value="weakness">Sort: weakest marketing</option>
          <option value="agencies">Sort: most agencies</option>
          <option value="gvasc">Sort: lowest vs GV</option>
          <option value="ppm2asc">Sort: lowest R/m²</option>
        {/if}
      </select>
      <span class="ic"><Icon name="chevronDown" size={14} /></span>
    </span>

    <button type="button" class="mg-btn secondary more" class:on={sheetCount > 0}
            onclick={() => (sheetOpen = true)} aria-haspopup="dialog">
      <Icon name="sliders" size={15} /> Filters{#if sheetCount}<b class="cnt mg-tnum">{sheetCount}</b>{/if}
    </button>

  </div>

  <div class="row2">
  <!-- saved views + built-in presets -->
  <div class="views mg-chips" aria-label="Saved views">
    {#if presets.length || views.list.length || isFiltering()}
      <span class="vlabel"><Icon name="star" size={13} /> Views</span>
    {/if}
    {#if naming}
      <form class="naming" onsubmit={save}>
        <input class="mg-input" placeholder="Name this view" bind:value={name} maxlength="60" use:focus
               onkeydown={(e) => e.key === 'Escape' && (naming = false)} />
        <button type="submit" class="mg-btn sm primary" disabled={!name.trim()}>Save</button>
        <button type="button" class="mg-btn sm ghost" onclick={() => (naming = false)}>Cancel</button>
      </form>
    {:else if isFiltering() || app.showSole}
      <button type="button" class="mg-chip add" onclick={() => (naming = true)}><Icon name="plus" size={12} /> Save view</button>
    {/if}
    {#each views.list as v (v.id)}
      <span class="saved" class:on={viewActive(v)}>
        <button type="button" class="mg-chip mine" class:on={viewActive(v)} onclick={() => apply(v)} title={v.params}>{v.name}</button>
        <button type="button" class="x" onclick={() => remove(v)} aria-label="Delete view {v.name}" title="Delete this view"><Icon name="close" size={11} /></button>
      </span>
    {/each}
    {#each presets as v (v.id)}
      <button type="button" class="mg-chip" class:on={viewActive(v)} onclick={() => apply(v)} title={v.params}>{v.name}</button>
    {/each}
  </div>

  <div class="tools">
    <span class="count mg-tnum" aria-live="polite">
      {#if app.list.loading && !app.list.loaded}…{:else}{shown === total
        ? `${fmtInt(shown)} ${rent ? 'rentals' : 'properties'}`
        : `${fmtInt(shown)} of ${fmtInt(total)}`}{/if}
    </span>
    <a class="mg-btn secondary icon sm export" href={exportUrl()} download title="Export these {fmtInt(shown)} as CSV (Excel, Google Sheets)"
       aria-label="Export as CSV"><Icon name="download" size={15} /></a>
    <span class="view"><Seg options={VIEW} value={filters.view} onchange={(v) => (filters.view = v)} label="View" /></span>
  </div>
  </div>

  {#if active.length || app.showSole}
    <div class="active mg-chips" aria-label="Active filters">
      {#each active as c (c.keys.join())}
        <button type="button" class="mg-chip ok fchip" onclick={() => clearKeys(c.keys)} title="Remove this filter">
          {c.label}<Icon name="close" size={11} />
        </button>
      {/each}
      {#if app.showSole}
        <button type="button" class="mg-chip ok fchip" onclick={() => setShowSole(false)} title="Hide sole mandates again">
          Incl. sole mandates<Icon name="close" size={11} />
        </button>
      {/if}
      <button type="button" class="mg-chip clearall" onclick={() => { clearFilters(); if (app.showSole) setShowSole(false); }}>Clear all</button>
    </div>
  {/if}
</div>

<FilterSheet open={sheetOpen} onclose={() => (sheetOpen = false)} />

<style>
  .bar { margin: 14px 0 14px; }
  .row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .mg-search { flex: 1 1 220px; max-width: 420px; }
  .mg-select { flex: none; }
  .mg-select > select { height: 36px; }

  .tiers { display: inline-flex; gap: 6px; flex: none; }
  .tchip { height: 36px; padding: 0 12px; font-size: 12.5px; }
  .n { font-size: 11px; color: var(--mc-ink3); }
  .tchip.on .n { color: inherit; opacity: 0.8; }

  .cnt {
    margin-left: 6px; min-width: 18px; height: 18px; padding: 0 5px; display: inline-flex; align-items: center; justify-content: center;
    border-radius: 9999px; background: var(--mc-accent); color: var(--mc-accent-ink); font-size: 11px;
  }
  .count { font: 400 12.5px/1 var(--mc-font); color: var(--mc-ink3); white-space: nowrap; }
  .export { flex: none; }

  .row2 { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
  .views { flex: 1 1 auto; min-width: 0; margin: 0; }
  .tools { display: flex; align-items: center; gap: 8px; flex: none; }
  .active { margin: 10px 0 0; }
  .vlabel { display: inline-flex; align-items: center; gap: 5px; flex: none; font: 500 12px/1 var(--mc-font); color: var(--mc-ink3); padding-right: 2px; }
  .saved { display: inline-flex; align-items: center; flex: none; position: relative; }
  .saved .mine { padding-right: 26px; }
  .saved .x {
    position: absolute; right: 4px; top: 50%; transform: translateY(-50%);
    width: 20px; height: 20px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;
    border: 0; background: transparent; color: var(--mc-ink3); cursor: pointer;
  }
  .saved .x:hover { background: rgba(255, 255, 255, 0.12); color: var(--mc-ink); }
  .add { border-style: dashed; }
  .naming { display: inline-flex; align-items: center; gap: 6px; flex: none; }
  .naming .mg-input { height: 32px; width: 180px; }
  .fchip { gap: 6px; }
  .clearall { color: var(--mc-ink3); }

  .deal, .view { display: inline-flex; flex: none; max-width: 100%; }

  /* a phone: search on top, then book + view, the tier chips, sort +
     filters + export on one row, the count last */
  @media (max-width: 640px) {
    .row { gap: 8px; }
    .mg-search { flex-basis: 100%; max-width: none; order: 0; }
    .deal { order: 1; }
    .tiers { order: 3; flex-basis: 100%; }
    .tiers .tchip { flex: 1; justify-content: center; }
    .sort { order: 4; flex: 1 1 auto; }
    .sort select { width: 100%; }
    .more { order: 5; }
    .row2 { flex-direction: column-reverse; align-items: stretch; }
    .tools { justify-content: space-between; }
    .views { width: 100%; }
  }
</style>
