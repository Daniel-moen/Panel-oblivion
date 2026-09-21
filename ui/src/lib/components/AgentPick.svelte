<script>
  /* One of Agent Z's picks. The prospect card's language — photo, price,
     suburb, title, meta line — with the fit badge and Z's reason under it,
     the way AiFinder pairs a card with its reason.

     It does not open the drawer: the thread can be about the rentals book
     while the engine page holds the sale one, so the row travels with the
     pick and the card opens the listing itself. Sale picks also offer the
     engine's own view of the property, where the drawer does have it. */
  import Photo from './Photo.svelte';
  import { isRent, priceTxt, furnishedTxt } from '$lib/format.js';

  let { pick } = $props();

  const r = $derived(pick.row);
  const rent = $derived(isRent(r));

  const meta = $derived.by(() => {
    const bits = [];
    if (r.bedrooms) bits.push(`${r.bedrooms} bed`);
    if (r.bathrooms) bits.push(`${r.bathrooms} bath`);
    if (r.property_type) bits.push(r.property_type.toLowerCase());
    if (rent) {
      const f = furnishedTxt(r.furnished);
      if (f) bits.push(f.toLowerCase());
    } else if (r.days_on_market != null) {
      bits.push(`${r.days_on_market} days on market`);
    }
    return bits.join(' · ');
  });

  const fitClass = $derived(pick.fit >= 85 ? 'hi' : pick.fit >= 60 ? 'mid' : 'lo');
</script>

<article class="pick">
  <a class="card" href={r.url} target="_blank" rel="noreferrer">
    <div class="ph">
      <Photo {r} alt={r.title || ''} />
      {#if pick.fit != null}
        <span class="fit {fitClass}" title="how well Agent Z rates the fit">{pick.fit}</span>
      {/if}
    </div>
    <div class="body">
      <div class="topline">
        <span class="price cprice">
          {#if r.price_zar}{priceTxt(r)}{:else}<span class="poa">POA</span>{/if}
        </span>
        <span class="suburb">{r.suburb || ''}</span>
      </div>
      <h3>{r.title || r.source_id}</h3>
      {#if meta}<p class="meta">{meta}</p>{/if}
    </div>
  </a>

  {#if pick.why}<p class="why">{pick.why}</p>{/if}

  {#if !rent && r.listing_key}
    <a class="engine" href="/prospects?open={encodeURIComponent(r.listing_key)}">
      Open in the engine →
    </a>
  {/if}
</article>

<style>
  .pick { display: flex; flex-direction: column; gap: 0.4rem; min-width: 0; }

  .card {
    display: flex; flex-direction: column; overflow: hidden; color: inherit;
    background: var(--bg-2); border: 1px solid var(--line);
    border-radius: var(--r-lg); box-shadow: var(--shadow-1);
    transition: transform 0.15s ease, box-shadow 0.15s, border-color 0.15s;
  }
  .card:hover { transform: translateY(-2px); box-shadow: var(--shadow-2);
                border-color: var(--accent-line); color: inherit; }
  .card:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

  .ph { position: relative; aspect-ratio: 16 / 10; background: var(--bg-3); }
  .ph :global(img) { transition: transform 0.35s ease; }
  .card:hover .ph :global(img) { transform: scale(1.03); }

  .fit {
    position: absolute; top: 0.6rem; right: 0.6rem;
    display: inline-flex; align-items: center; justify-content: center;
    min-width: 34px; height: 26px; padding: 0 0.45rem; border-radius: 8px;
    font-size: 0.82rem; font-weight: 700; font-variant-numeric: tabular-nums;
    background: var(--overlay); backdrop-filter: blur(4px);
    box-shadow: 0 1px 3px rgba(16, 24, 40, 0.18);
  }
  .fit.hi { color: var(--open); }
  .fit.mid { color: var(--warm-ink); }
  .fit.lo { color: var(--cold-ink); }

  .body { display: flex; flex-direction: column; gap: 0.3rem;
          padding: 0.75rem 0.9rem 0.85rem; flex: 1; }
  .topline { display: flex; justify-content: space-between; align-items: baseline; gap: 0.7rem; }
  .cprice { font-size: 1.05rem; }
  .suburb { font-size: 0.74rem; font-weight: 500; color: var(--ink-3);
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  h3 { margin: 0; font-size: 0.84rem; font-weight: 500; line-height: 1.4; color: var(--ink-2);
       display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
       overflow: hidden; }
  .meta { margin: 0; font-size: 0.74rem; color: var(--ink-3); }

  .why { margin: 0; padding: 0 0.15rem; font-size: 0.8rem; line-height: 1.45;
         color: var(--ink-2); }
  .engine { padding: 0 0.15rem; font-size: 0.74rem; font-weight: 600;
            color: var(--ink-3); }
  .engine:hover { color: var(--accent-2); }
</style>
