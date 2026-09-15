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

<section class="finder panel" class:answered={!!res}>
  <form class="ask" onsubmit={submit}>
    <span class="spark" aria-hidden="true">✦</span>
    <input type="text" class="brief" {placeholder}
           bind:value={finder.brief} disabled={finder.busy}
           aria-label="What are you looking for?" />
    <button type="submit" class="btn primary" disabled={finder.busy || finder.brief.trim().length < 3}>
      {#if finder.busy}<span class="spin light"></span>&nbsp; Thinking…{:else}Find{/if}
    </button>
    {#if res}
      <button type="button" class="btn" onclick={clearFinder}>Clear</button>
    {/if}
  </form>

  {#if !res && !finder.busy}
    <div class="examples">
      <span>Try:</span>
      {#each examples as ex (ex)}
        <button type="button" class="ex" onclick={() => runFinder(ex)}>{ex}</button>
      {/each}
    </div>
  {/if}

  {#if finder.busy}
    <p class="working">Reading the brief, shortlisting from {app.prospects.length}
      {rent ? 'rentals' : 'properties'}, then ranking the closest fits…</p>
  {/if}

  {#if res && !finder.busy}
    <div class="answer">
      <p class="summary">{res.summary}</p>

      {#if critChips.length}
        <div class="crit">
          <span class="lbl">Understood as</span>
          {#each critChips as c (c)}<span class="chip">{c}</span>{/each}
          {#if res.relaxed}<span class="chip warn" title="Too few strict matches — suburb and bedroom limits were loosened">loosened</span>{/if}
        </div>
      {/if}

      {#if res.areas.length}
        <div class="areas">
          <span class="lbl">Areas that fit</span>
          <ul>
            {#each res.areas as a (a.suburb)}
              <li>
                <button type="button" class="area" class:on={filters.suburb === a.suburb}
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
        <div class="lbl picks-lbl">
          Best fits · {picks.length}
          <span class="src">{res.ai ? 'ranked by AI' : 'keyword match — no AI credentials set'}</span>
        </div>
        <div class="grid">
          {#each picks as { pick, r } (pick.listing_key)}
            <div class="pick">
              <ProspectCard {r} />
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
  .finder { margin-top: 1.2rem; padding: 0.9rem 1rem; }
  .finder.answered { border-color: var(--accent-line); }

  .ask { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; }
  .spark { color: var(--accent); font-size: 1.05rem; }
  .brief { flex: 1 1 320px; font-size: 0.92rem; padding: 0.55rem 0.8rem; }
  .spin.light { border-top-color: #fff; border-color: rgba(255,255,255,0.35); border-top-color: #fff; }

  .examples { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem;
              margin-top: 0.6rem; font-size: 0.76rem; color: var(--ink-3); }
  .ex { background: var(--bg-3); border: 1px solid var(--line); color: var(--ink-2);
        border-radius: 999px; padding: 0.2rem 0.65rem; font: 500 0.75rem/1.4 var(--font-ui); }
  .ex:hover { color: var(--accent-2); border-color: var(--accent-line); background: var(--accent-soft); }

  .working { margin: 0.7rem 0 0; font-size: 0.82rem; color: var(--ink-2); }

  .answer { margin-top: 0.9rem; display: flex; flex-direction: column; gap: 0.8rem; }
  .summary { margin: 0; font-size: 0.9rem; line-height: 1.5; color: var(--ink); }

  .lbl { font-size: 0.72rem; font-weight: 600; text-transform: uppercase;
         letter-spacing: 0.04em; color: var(--ink-3); }
  .crit { display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem; }
  .crit .chip { text-transform: none; }
  .chip.warn { background: var(--warm-soft); color: var(--warm-ink); }

  .areas ul { list-style: none; margin: 0.35rem 0 0; padding: 0;
              display: flex; flex-direction: column; gap: 0.3rem; }
  .areas li { display: flex; align-items: baseline; gap: 0.6rem; flex-wrap: wrap;
              font-size: 0.83rem; }
  .area { background: var(--accent-soft); color: var(--accent-2); border: 1px solid var(--accent-line);
          border-radius: 999px; padding: 0.18rem 0.7rem; font: 600 0.78rem/1.4 var(--font-ui);
          white-space: nowrap; }
  .area:hover, .area.on { background: var(--accent); color: #fff; border-color: var(--accent); }
  .why { color: var(--ink-2); flex: 1 1 280px; }

  .picks-lbl { display: flex; align-items: baseline; gap: 0.6rem; }
  .src { font-weight: 500; text-transform: none; letter-spacing: 0; }

  .grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fill, minmax(285px, 1fr)); }
  .pick { display: flex; flex-direction: column; gap: 0.45rem; }
  .reason { display: flex; align-items: flex-start; gap: 0.5rem; font-size: 0.8rem;
            line-height: 1.45; color: var(--ink-2); padding: 0 0.15rem; }
  .fit { flex: none; min-width: 2rem; text-align: center; border-radius: var(--r-sm);
         padding: 0.05rem 0.35rem; font-variant-numeric: tabular-nums; font-size: 0.76rem; }
  .fit.hi { background: var(--open-soft); color: var(--open); }
  .fit.mid { background: var(--warm-soft); color: var(--warm-ink); }
  .fit.lo { background: var(--cold-soft); color: var(--cold-ink); }

  .none { margin: 0; font-size: 0.85rem; color: var(--ink-2); }
</style>
