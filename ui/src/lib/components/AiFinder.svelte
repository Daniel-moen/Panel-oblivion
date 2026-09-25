<script>
  /* "Find me…" — a plain-English brief in, recommended areas and properties
     out. The answer panel sits above the normal filter bar; area chips feed
     the suburb filter so a recommendation turns into a browse in one click.

     It briefs against whichever book is open: for sale, or to rent — where
     the budget is a monthly rent and the asks are a tenant's. */
  import { onMount } from 'svelte';
  import { app } from '$lib/state.svelte.js';
  import { filters } from '$lib/filters.svelte.js';
  import { finder, runFinder, clearFinder, restoreFinder, syncFinderBook,
           pickedRows } from '$lib/finder.svelte.js';
  import ProspectCard from './ProspectCard.svelte';
  import { fmtM, fmtR } from '$lib/format.js';
  import Icon from './glass/Icon.svelte';
  import { play, fadeUp } from '$lib/motion.js';

  const SALE_EXAMPLES = [
    '2 bedroom in a quiet area under R3m',
    'family home with a pool and garden, secure estate, R4–7m',
    'lock-up-and-go apartment with sea views, Atlantic Seaboard',
    'retirement-friendly single-level house near the beach'
  ];

  const RENT_EXAMPLES = [
    'furnished 3-bed in Camps Bay under R60k pm',
    'pet-friendly 2 bed with parking, under R25k a month',
    'unfurnished family house with a garden, available immediately',
    'bachelor flat near the university, R12k pm, fibre'
  ];

  const rent = $derived(app.dealType === 'rent');
  const examples = $derived(rent ? RENT_EXAMPLES : SALE_EXAMPLES);
  const placeholder = $derived(
    rent
      ? "Describe the rental you're after — e.g. furnished 3-bed in Camps Bay under R60k pm"
      : "Describe what you're looking for — e.g. 2 bedroom in a quiet area under R3m");

  onMount(() => restoreFinder(app.dealType));
  /* Toggling For sale / To rent clears the answer: it was about other stock.
     shown is a plain let, not state — the effect watches the toggle only. */
  let shown = app.dealType;
  $effect(() => {
    const deal = app.dealType;
    if (deal === shown) return;
    shown = deal;
    syncFinderBook(deal);
  });

  const picks = $derived(pickedRows());
  const res = $derived(finder.result);

  /* A rent is quoted in full rand a month; only a sale compresses to R3.2m. */
  const money = (v) => (rent ? fmtR(v) + ' pm' : fmtM(v));

  const critChips = $derived.by(() => {
    const c = res?.criteria;
    if (!c) return [];
    const out = [];
    if (c.bedrooms_min != null || c.bedrooms_max != null) {
      const lo = c.bedrooms_min, hi = c.bedrooms_max;
      out.push(lo != null && hi != null && lo === hi ? `${lo} bed`
             : lo != null && hi != null ? `${lo}–${hi} bed`
             : lo != null ? `${lo}+ bed` : `≤${hi} bed`);
    }
    if (c.bathrooms_min) out.push(`${c.bathrooms_min}+ bath`);
    if (c.price_min_zar || c.price_max_zar) {
      out.push(c.price_min_zar && c.price_max_zar ? `${money(c.price_min_zar)} – ${money(c.price_max_zar)}`
             : c.price_max_zar ? `under ${money(c.price_max_zar)}` : `over ${money(c.price_min_zar)}`);
    }
    if (c.furnished) out.push(c.furnished === 'no' ? 'unfurnished' : 'furnished');
    for (const t of c.property_types || []) out.push(t);
    for (const s of c.suburbs || []) out.push(s);
    for (const w of c.wishes || []) out.push(w);
    return out;
  });

  function submit(e) { e.preventDefault(); runFinder(); }
  function pickArea(s) { filters.suburb = filters.suburb === s ? '' : s; }
  function fitClass(f) { return f >= 85 ? 'hi' : f >= 60 ? 'mid' : 'lo'; }
</script>

<section class="finder mg-panel" class:answered={!!res}>
  <form class="ask" onsubmit={submit}>
    <label class="mg-search">
      <span class="ic spark"><Icon name="sparkles" size={16} /></span>
      <input type="text" class="mg-input brief" {placeholder}
             bind:value={finder.brief} disabled={finder.busy}
             aria-label="What are you looking for?" />
    </label>
    <button type="submit" class="mg-btn primary" disabled={finder.busy || finder.brief.trim().length < 3}>
      {#if finder.busy}<span class="mg-spin"></span> Thinking…{:else}Find{/if}
    </button>
    {#if res}
      <button type="button" class="mg-btn secondary" onclick={clearFinder}>Clear</button>
    {/if}
  </form>

  {#if !res && !finder.busy}
    <div class="examples mg-noscroll">
      <span class="try">Try</span>
      {#each examples as ex (ex)}
        <button type="button" class="mg-chip" onclick={() => runFinder(ex)}>{ex}</button>
      {/each}
    </div>
  {/if}

  {#if finder.busy}
    <p class="working">Reading the brief, shortlisting from {app.prospects.length}
      {rent ? 'rentals' : 'properties'}, then ranking the closest fits…</p>
  {/if}

  {#if res && !finder.busy}
    <div class="answer" in:play={fadeUp}>
      <p class="summary">{res.summary}</p>

      {#if critChips.length}
        <div class="crit">
          <span class="hud">Understood as</span>
          {#each critChips as c (c)}<span class="mg-chip">{c}</span>{/each}
          {#if res.relaxed}<span class="mg-chip warn" title="Too few strict matches — suburb and bedroom limits were loosened">loosened</span>{/if}
        </div>
      {/if}

      {#if res.areas.length}
        <div class="areas">
          <span class="hud">Areas that fit</span>
          <ul>
            {#each res.areas as a (a.suburb)}
              <li>
                <button type="button" class="mg-chip ok area" class:on={filters.suburb === a.suburb}
                        onclick={() => pickArea(a.suburb)} title="Filter the list to {a.suburb}">
                  {a.suburb}
                </button>
                <span class="why">{a.why}</span>
              </li>
            {/each}
          </ul>
        </div>
      {/if}

      {#if picks.length}
        <div class="hud picks-lbl">
          Best fits · {picks.length}
          <span class="src">{res.ai ? 'ranked by AI' : 'keyword match — no AI credentials set'}</span>
        </div>
        <div class="grid">
          {#each picks as { pick, r }, i (pick.listing_key)}
            <div class="pick">
              <ProspectCard {r} {i} />
              <div class="reason">
                <b class="fit {fitClass(pick.fit)}">{pick.fit}</b>
                <span>{pick.why}</span>
              </div>
            </div>
          {/each}
        </div>
      {:else if res.candidates === 0}
        <p class="none">
          {#if rent}
            No rental in the database passes those hard limits. Loosen the rent,
            bedrooms or area — or crawl more suburbs with rentals included.
          {:else}
            No property in the database passes those hard limits. Loosen the budget,
            bedrooms or area — or crawl more suburbs.
          {/if}
        </p>
      {/if}
    </div>
  {/if}
</section>

<style>
  .finder { margin-bottom: 14px; padding: 12px 14px; }
  .finder.answered { border-color: var(--mc-ok-line); }

  .ask { display: flex; align-items: center; gap: 8px; }
  .ask .mg-search { flex: 1 1 160px; min-width: 0; }
  .ask .mg-btn { padding: 0 14px; }
  .spark { color: var(--mc-accent); }

  .examples { display: flex; align-items: center; gap: 6px; margin-top: 10px; overflow-x: auto; padding-bottom: 2px; }
  .try { flex: none; font: 500 12px/1 var(--mc-font); color: var(--mc-ink3); margin-right: 2px; }
  .examples .mg-chip { height: 28px; }

  .working { margin: 10px 0 0; font: 400 13px/1.5 var(--mc-font); color: var(--mc-ink2); }

  .answer { margin-top: 14px; display: flex; flex-direction: column; gap: 14px; }
  .summary { margin: 0; font: 400 14px/1.55 var(--mc-font); color: var(--mc-ink); }

  .crit { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
  .crit .hud { margin-right: 4px; }
  .crit .mg-chip { height: 26px; text-transform: none; }

  .areas ul { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
  .areas li { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; font-size: 13px; }
  .area { height: 28px; font-weight: 600; }
  .area:hover, .area.on { background: var(--mc-accent); color: var(--mc-accent-ink); border-color: var(--mc-accent); }
  .why { color: var(--mc-ink2); flex: 1 1 280px; font-size: 13px; line-height: 1.5; }

  .picks-lbl { display: flex; align-items: baseline; gap: 8px; }
  .src { font-weight: 500; text-transform: none; letter-spacing: 0; }

  .grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(270px, 1fr)); }
  .pick { display: flex; flex-direction: column; gap: 8px; }
  .reason { display: flex; align-items: flex-start; gap: 8px; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink2); padding: 0 2px; }
  .fit { flex: none; min-width: 34px; text-align: center; border-radius: 6px; padding: 2px 6px; font: 600 12px/1.4 var(--mc-mono); }
  .fit.hi { background: var(--mc-ok-soft); color: var(--mc-accent); }
  .fit.mid { background: var(--mc-warn-soft); color: var(--mc-warn); }
  .fit.lo { background: var(--mc-raised); color: var(--mc-ink2); }

  .none { margin: 0; font: 400 13px/1.55 var(--mc-font); color: var(--mc-ink2); }
</style>
