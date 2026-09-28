<script>
  /* Every prospect filter, grouped, in one sheet — a centred dialog from
     640px, a bottom sheet on a phone (glass/Sheet). The counts beside each
     option come from the server's facets for the CURRENT filter set (a
     facet ignores its own filter, so picking a suburb still shows every
     other suburb's count). Nothing here fetches: it edits `filters`, and the
     page's effect re-runs the query, so the "Show N" button is live. */
  import Sheet from './glass/Sheet.svelte';
  import Icon from './glass/Icon.svelte';
  import { app, setShowSole } from '$lib/state.svelte.js';
  import { filters, listOf, has, toggle, priceShown, setPrice, clearFilters, isFiltering,
           MANDATE_TXT } from '$lib/filters.svelte.js';
  import { fmtInt } from '$lib/format.js';

  let { open = false, onclose } = $props();

  const rent = $derived(app.dealType === 'rent');
  const facets = $derived(app.list.facets || {});
  const count = (dim, v) => facets[dim]?.[v];
  const byCount = (dim) =>
    Object.entries(facets[dim] || {}).sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(b[0]));

  const STAGES = ['new', 'researching', 'contact_found', 'contacted', 'meeting', 'valuation_sent',
    'mandate_signed', 'listed', 'sold', 'lost', 'parked'];
  const TYPES = ['House', 'Apartment', 'Townhouse', 'Estate', 'Farm', 'Commercial', 'Other'];
  const BEDS = ['1', '2', '3', '4', '5+'];

  /* Suburbs: there are hundreds (portals spell them freely), so the sheet
     shows the busiest, every picked one, and whatever the search finds. */
  let subQ = $state('');
  const suburbs = $derived.by(() => {
    const all = byCount('suburb');
    const picked = new Set(listOf('suburb'));
    const q = subQ.trim().toLowerCase();
    const hit = q ? all.filter(([s]) => s.toLowerCase().includes(q)) : all.slice(0, 24);
    const shown = new Set(hit.map(([s]) => s));
    const extra = [...picked].filter((s) => !shown.has(s)).map((s) => [s, count('suburb', s) ?? 0]);
    return [...extra, ...hit].slice(0, 60);
  });

  /* Beds: tap one bucket for exactly that, tap another to widen the range. */
  const bedN = (b) => (b === '5+' ? 5 : +b);
  function inBeds(b) {
    const lo = filters.beds_min === '' ? null : +filters.beds_min;
    const hi = filters.beds_max === '' ? null : +filters.beds_max;
    if (lo == null && hi == null) return false;
    const n = bedN(b);
    return (lo == null || n >= lo) && (hi == null || n <= hi || (b === '5+' && hi >= 5));
  }
  function pickBeds(b) {
    const n = bedN(b);
    const lo = filters.beds_min === '' ? null : +filters.beds_min;
    const hi = filters.beds_max === '' ? null : +filters.beds_max;
    const top = (x) => (x >= 5 ? '' : String(x));
    if (lo == null && hi == null) { filters.beds_min = String(n); filters.beds_max = top(n); return; }
    if (lo === n && (hi === n || (n === 5 && hi == null))) { filters.beds_min = ''; filters.beds_max = ''; return; }
    const nlo = Math.min(lo ?? n, n);
    const nhi = hi == null ? null : Math.max(hi, n);
    filters.beds_min = String(nlo);
    filters.beds_max = nhi == null || n >= 5 ? '' : top(nhi);
  }

  /* One-of choices: tap the lit one again to clear it. */
  const one = (k, v) => (filters[k] = filters[k] === v ? '' : v);
  const num = (k) => (e) => (filters[k] = e.currentTarget.value.trim());
  const fmtC = (n) => (n == null ? '' : fmtInt(n));
</script>

{#snippet opt(label, on, click, n = null, title = '')}
  <button type="button" class="mg-chip opt" class:on onclick={click} {title} aria-pressed={on}>
    {label}{#if n != null}<span class="n mg-tnum">{fmtC(n)}</span>{/if}
  </button>
{/snippet}

{#snippet range(lo, hi, ph1, ph2, unit, step = 'any')}
  <span class="range">
    <input class="mg-input" type="number" inputmode="decimal" min="0" {step} placeholder={ph1}
           value={filters[lo]} oninput={num(lo)} aria-label={ph1 + ' ' + unit} />
    <span class="dash">–</span>
    <input class="mg-input" type="number" inputmode="decimal" min="0" {step} placeholder={ph2}
           value={filters[hi]} oninput={num(hi)} aria-label={ph2 + ' ' + unit} />
    <span class="unit">{unit}</span>
  </span>
{/snippet}

{#snippet tri(k, label, yes = 'Only', no = 'Hide')}
  <div class="tri">
    <span class="lbl">{label}</span>
    <span class="opts">
      {@render opt('Any', filters[k] === '', () => (filters[k] = ''))}
      {@render opt(yes, filters[k] === '1', () => one(k, '1'))}
      {@render opt(no, filters[k] === '0', () => one(k, '0'))}
    </span>
  </div>
{/snippet}

<Sheet {open} title="Filters" size="lg" {onclose}>
  <div class="groups">
    <!-- ------------------------------------------------------------ Deal -->
    <section>
      <h3 class="mg-label">Deal</h3>
      <div class="field">
        <span class="lbl">{rent ? 'Rent a month' : 'Price'}</span>
        <span class="range">
          <input class="mg-input" type="number" inputmode="decimal" min="0" step="any" placeholder="Min"
                 value={priceShown('price_min')} oninput={(e) => setPrice('price_min', e.currentTarget.value)}
                 aria-label="Minimum price" />
          <span class="dash">–</span>
          <input class="mg-input" type="number" inputmode="decimal" min="0" step="any" placeholder="Max"
                 value={priceShown('price_max')} oninput={(e) => setPrice('price_max', e.currentTarget.value)}
                 aria-label="Maximum price" />
          <span class="unit">{rent ? 'R thousand' : 'R million'}</span>
        </span>
      </div>
      {#if !rent}
        <div class="field">
          <span class="lbl">Tier</span>
          <span class="opts">
            {#each ['hot', 'warm', 'cold'] as t (t)}
              {@render opt(t[0].toUpperCase() + t.slice(1), has('tier', t), () => toggle('tier', t), count('tier', t) ?? 0)}
            {/each}
          </span>
        </div>
        <div class="field">
          <span class="lbl">Score</span>
          <span class="opts">
            {#each ['', '50', '65', '80'] as s (s)}
              {@render opt(s ? s + '+' : 'Any', filters.score_min === s, () => (filters.score_min = s))}
            {/each}
          </span>
        </div>
        <label class="check">
          <input type="checkbox" checked={app.showSole} onchange={(e) => setShowSole(e.currentTarget.checked)} />
          Include sole mandates
        </label>
      {:else}
        <div class="field">
          <span class="lbl">Furnished</span>
          <span class="opts">
            {@render opt('Any', filters.furnished === '', () => (filters.furnished = ''))}
            {@render opt('Furnished', filters.furnished === 'yes', () => one('furnished', 'yes'))}
            {@render opt('Unfurnished', filters.furnished === 'no', () => one('furnished', 'no'))}
          </span>
        </div>
        <label class="check">
          <input type="checkbox" checked={filters.available === 'now'}
                 onchange={(e) => (filters.available = e.currentTarget.checked ? 'now' : '')} />
          Available now
        </label>
      {/if}
    </section>

    <!-- -------------------------------------------------------- Property -->
    <section>
      <h3 class="mg-label">Property</h3>
      <div class="field">
        <span class="lbl">Type</span>
        <span class="opts">
          {#each TYPES as t (t)}
            {#if count('property_type', t) || has('ptype', t)}
              {@render opt(t, has('ptype', t), () => toggle('ptype', t), count('property_type', t) ?? 0)}
            {/if}
          {/each}
        </span>
      </div>
      <div class="field">
        <span class="lbl">Bedrooms</span>
        <span class="opts">
          {#each BEDS as b (b)}
            {@render opt(b, inBeds(b), () => pickBeds(b), count('beds', b) ?? 0, 'Tap another to widen the range')}
          {/each}
        </span>
      </div>
      <div class="field">
        <span class="lbl">Bathrooms</span>
        <span class="opts">
          {#each ['', '2', '3', '4'] as s (s)}
            {@render opt(s ? s + '+' : 'Any', filters.baths_min === s, () => (filters.baths_min = s))}
          {/each}
        </span>
      </div>
      <div class="field"><span class="lbl">Floor</span>{@render range('floor_min', 'floor_max', 'Min', 'Max', 'm²')}</div>
      <div class="field"><span class="lbl">Erf size</span>{@render range('erf_min', 'erf_max', 'Min', 'Max', 'm²')}</div>
      {#if !rent}
        <div class="field"><span class="lbl">Asking R/m²</span>{@render range('ppm2_min', 'ppm2_max', 'Min', 'Max', 'R/m²')}</div>
      {/if}
      {@render tri('dev', 'New developments')}
      {@render tri('photo', 'Photo', 'Has one', 'None')}
    </section>

    {#if !rent}
      <!-- ----------------------------------------- Mandate & competition -->
      <section>
        <h3 class="mg-label">Mandate &amp; competition</h3>
        <div class="field">
          <span class="lbl">Mandate</span>
          <span class="opts">
            {#each Object.entries(MANDATE_TXT) as [v, label] (v)}
              {#if count('mandate', v) || has('mandate', v) || v.includes('sole')}
                {@render opt(label, has('mandate', v), () => toggle('mandate', v), count('mandate', v) ?? null)}
              {/if}
            {/each}
          </span>
        </div>
        <div class="field">
          <span class="lbl">Agencies</span>
          <span class="opts">
            {#each ['', '2', '3'] as s (s)}
              {@render opt(s ? s + '+ brands' : 'Any', filters.agencies_min === s, () => (filters.agencies_min = s),
                           null, s === '2' ? 'Two agencies marketing it: the mandate is provably open' : '')}
            {/each}
          </span>
        </div>
        <div class="field">
          <span class="lbl">Portals</span>
          <span class="opts">
            {#each ['', '2', '3'] as s (s)}
              {@render opt(s ? s + '+ portals' : 'Any', filters.portals_min === s, () => (filters.portals_min = s))}
            {/each}
          </span>
        </div>
        <div class="field">
          <span class="lbl">Listed on</span>
          <span class="opts">
            {#each byCount('source') as [s, n] (s)}
              {@render opt(s, has('source', s), () => toggle('source', s), n)}
            {/each}
          </span>
        </div>
        <div class="field">
          <span class="lbl">Agency</span>
          <input class="mg-input grow" type="search" placeholder="Name contains… e.g. Pam Golding"
                 value={filters.agency} oninput={(e) => (filters.agency = e.currentTarget.value)} />
        </div>
        {@render tri('under_offer', 'Under offer')}
        <label class="check">
          <input type="checkbox" checked={filters.expiry === '1'}
                 onchange={(e) => (filters.expiry = e.currentTarget.checked ? '1' : '')} />
          Mandate expiry noted by the scorer
        </label>
      </section>

      <!-- ------------------------------------------------- Market signals -->
      <section>
        <h3 class="mg-label">Market signals</h3>
        <div class="field">
          <span class="lbl">Price cut</span>
          <span class="opts">
            {#each ['', '5', '10', '20'] as s (s)}
              {@render opt(s ? s + '%+' : 'Any', filters.cut === s, () => (filters.cut = s))}
            {/each}
            {@render opt('Any reduction', filters.reduced === '1', () => one('reduced', '1'))}
          </span>
        </div>
        <div class="field">
          <span class="lbl">Days listed</span>
          <span class="opts">
            {@render opt('≤ 7', filters.dom_max === '7' && !filters.dom_min, () => { filters.dom_min = ''; filters.dom_max = filters.dom_max === '7' ? '' : '7'; })}
            {#each ['30', '90', '180'] as s (s)}
              {@render opt(s + '+', filters.dom_min === s && !filters.dom_max, () => { filters.dom_max = ''; filters.dom_min = filters.dom_min === s ? '' : s; })}
            {/each}
          </span>
          {@render range('dom_min', 'dom_max', 'Min', 'Max', 'days', '1')}
        </div>
        <div class="field">
          <span class="lbl">Relisted</span>
          <span class="opts">
            {@render opt('Any', filters.relisted === '', () => { filters.relisted = ''; filters.off_min = ''; })}
            {@render opt('Relisted', filters.relisted === '1', () => one('relisted', '1'), null, 'Came back after being delisted — often a failed mandate')}
            {#each ['14', '60'] as s (s)}
              {@render opt(`${s}+ days off`, filters.off_min === s, () => { filters.relisted = '1'; filters.off_min = filters.off_min === s ? '' : s; })}
            {/each}
          </span>
        </div>
        <div class="field">
          <span class="lbl">On the portals</span>
          <span class="opts">
            {#each [['active', 'Active'], ['relisted', 'Relisted'], ['delisted', 'Delisted']] as [v, l] (v)}
              {@render opt(l, has('life', v), () => toggle('life', v))}
            {/each}
          </span>
        </div>
        <div class="field">
          <span class="lbl">Asking vs GV</span>
          <span class="opts">
            {@render opt('≤ 1.0×', filters.gv_max === '1' && !filters.gv_min, () => { filters.gv_min = ''; filters.gv_max = filters.gv_max === '1' ? '' : '1'; }, null, 'At or under the municipal valuation')}
            {@render opt('≤ 1.2×', filters.gv_max === '1.2' && !filters.gv_min, () => { filters.gv_min = ''; filters.gv_max = filters.gv_max === '1.2' ? '' : '1.2'; })}
            {@render opt('≥ 2×', filters.gv_min === '2' && !filters.gv_max, () => { filters.gv_max = ''; filters.gv_min = filters.gv_min === '2' ? '' : '2'; }, null, 'Priced at double the roll or more')}
          </span>
        </div>
      </section>
    {/if}

    <!-- --------------------------------------------------------- Location -->
    <section>
      <h3 class="mg-label">Location</h3>
      {#if byCount('region').length}
        <div class="field">
          <span class="lbl">Region</span>
          <span class="opts">
            {#each byCount('region') as [r, n] (r)}
              {@render opt(r, has('region', r), () => toggle('region', r), n)}
            {/each}
          </span>
        </div>
      {/if}
      <div class="field">
        <span class="lbl">Suburb</span>
        <label class="mg-search sub">
          <span class="ic"><Icon name="search" size={15} /></span>
          <input class="mg-input" type="search" placeholder="Find a suburb…" bind:value={subQ} />
        </label>
        <span class="opts">
          {#each suburbs as [s, n] (s)}
            {@render opt(s, has('suburb', s), () => toggle('suburb', s), n)}
          {/each}
          {#if !suburbs.length}<span class="mg-hint">No suburb matches.</span>{/if}
        </span>
      </div>
      {#if !rent}
        <div class="field">
          <span class="lbl">Erf</span>
          <span class="opts">
            {#each [['resolved', 'Resolved'], ['candidates', 'Has candidates'], ['unresolved', 'Unresolved']] as [v, l] (v)}
              {@render opt(l, filters.erf === v, () => one('erf', v))}
            {/each}
          </span>
        </div>
      {/if}
    </section>

    {#if !rent}
      <!-- ------------------------------------------------------ Lead status -->
      <section>
        <h3 class="mg-label">Lead status</h3>
        <div class="field">
          <span class="opts">
            {@render opt('Not tracked', has('lead', 'untracked'), () => toggle('lead', 'untracked'))}
            {@render opt('Tracked (any stage)', has('lead', 'tracked'), () => toggle('lead', 'tracked'))}
            {#each STAGES as s (s)}
              {@render opt(s[0].toUpperCase() + s.slice(1).replace(/_/g, ' '), has('lead', s), () => toggle('lead', s))}
            {/each}
          </span>
        </div>
      </section>
    {/if}
  </div>

  {#snippet footer()}
    <div class="foot">
      {#if isFiltering()}
        <button type="button" class="mg-btn ghost" onclick={clearFilters}><Icon name="close" size={14} /> Clear all</button>
      {/if}
      <button type="button" class="mg-btn primary show" onclick={() => onclose?.()}>
        {#if app.list.loading}Counting…{:else}Show {fmtInt(app.list.total)} {rent ? 'rentals' : 'properties'}{/if}
      </button>
    </div>
  {/snippet}
</Sheet>

<style>
  .groups { display: flex; flex-direction: column; gap: 18px; }
  section { display: flex; flex-direction: column; gap: 10px; padding-bottom: 16px; border-bottom: 1px solid var(--mc-line); }
  section:last-child { border-bottom: 0; padding-bottom: 0; }
  section h3 { margin: 0 0 2px; }

  /* label | controls; everything after the label stacks in the second
     column (the suburb search above its chips, day chips above the range) */
  .field, .tri { display: grid; grid-template-columns: 112px minmax(0, 1fr); gap: 8px 10px; align-items: start; }
  .field > :not(.lbl), .tri > :not(.lbl) { grid-column: 2; }
  .field > .opts:first-child { grid-column: 1 / -1; }
  .lbl { padding-top: 9px; font: 500 12.5px/1.3 var(--mc-font); color: var(--mc-ink3); }
  .opts { display: flex; flex-wrap: wrap; gap: 6px; min-width: 0; }
  .opt { height: 32px; text-transform: none; }
  .opt .n { margin-left: 2px; font-size: 11px; color: var(--mc-ink3); }
  .opt.on .n { color: inherit; opacity: 0.8; }


  .range { display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .range .mg-input { width: 96px; height: 36px; }
  .dash, .unit { color: var(--mc-ink3); font-size: 12.5px; }
  .grow { width: 100%; max-width: 420px; height: 36px; }
  .sub { width: 100%; max-width: 360px; }
  .sub .mg-input { height: 36px; }

  .check { display: inline-flex; align-items: center; gap: 8px; min-height: 32px; font: 500 13px/1.3 var(--mc-font); color: var(--mc-ink2); cursor: pointer; }
  .check input { width: 16px; height: 16px; margin: 0; }

  .foot { display: flex; align-items: center; justify-content: flex-end; gap: 8px; width: 100%; }
  .show { min-width: 180px; }

  @media (max-width: 640px) {
    .field, .tri { grid-template-columns: minmax(0, 1fr); gap: 6px; }
    .field > :not(.lbl), .tri > :not(.lbl) { grid-column: 1; }
    .lbl { padding-top: 0; }
    .show { flex: 1; }
  }
</style>
