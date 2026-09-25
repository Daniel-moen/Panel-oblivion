<script>
  /* One of Agent Z's picks. The prospect card's language — photo, price,
     suburb, title, meta line — with the fit badge and Z's reason under it,
     the way AiFinder pairs a card with its reason.

     It does not open the drawer: the thread can be about the rentals book
     while the engine page holds the sale one, so the row travels with the
     pick and the card opens the listing itself. Sale picks also offer the
     engine's own view of the property, where the drawer does have it. */
  import Photo from './Photo.svelte';
  import Icon from './glass/Icon.svelte';
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

  {#if pick.why || (!rent && r.listing_key)}
    <div class="foot">
      {#if pick.why}<p class="why">{pick.why}</p>{/if}
      {#if !rent && r.listing_key}
        <a class="engine" href="/prospects?open={encodeURIComponent(r.listing_key)}">
          Open in the engine <Icon name="arrowRight" size={12} />
        </a>
      {/if}
    </div>
  {/if}
</article>

<style>
  /* One card: the photo, the price line, and Z's reason on the same plane
     under a hairline — so a pick reads as one object, not three. */
  .pick {
    display: flex; flex-direction: column; min-width: 0; overflow: hidden;
    background: var(--mc-surface); border: 1px solid var(--mc-line); border-radius: var(--mc-r);
    transition: border-color var(--mc-t-fast);
  }
  .pick:hover { border-color: var(--mc-line2); }

  .card { display: flex; flex-direction: column; color: inherit; }
  .card:focus-visible { outline-offset: -2px; }

  .ph { position: relative; aspect-ratio: 16 / 10; background: var(--mc-inset); overflow: hidden; }
  .ph :global(img) { transition: transform var(--mc-t-slow) var(--mc-ease); }
  .card:hover .ph :global(img) { transform: scale(1.03); }

  .fit {
    position: absolute; top: 8px; right: 8px;
    display: inline-grid; place-items: center; min-width: 32px; height: 24px; padding: 0 7px;
    border-radius: var(--mc-r-sm); background: var(--mc-raised); border: 1px solid var(--mc-line2);
    font: 600 12px/1 var(--mc-mono); font-variant-numeric: tabular-nums; box-shadow: var(--mc-sh-1);
  }
  .fit.hi { color: var(--mc-accent); }
  .fit.mid { color: var(--mc-warn); }
  .fit.lo { color: var(--mc-ink2); }

  .body { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; flex: 1; min-width: 0; }
  .topline { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; min-width: 0; }
  .cprice { font-size: 16px; }
  .suburb { font: 500 12px/1.3 var(--mc-font); color: var(--mc-ink3);
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  h3 { margin: 0; font: 500 13px/1.4 var(--mc-font); color: var(--mc-ink2);
       display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .meta { margin: 0; font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); }

  .foot { display: flex; flex-direction: column; gap: 6px; padding: 10px 14px 12px; border-top: 1px solid var(--mc-line); }
  .why { margin: 0; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink2); }
  .engine { display: inline-flex; align-items: center; gap: 4px; align-self: flex-start;
            font: 600 12px/1.4 var(--mc-font); color: var(--mc-ink3); transition: color var(--mc-t-fast); }
  .engine:hover { color: var(--mc-accent); }

  /* in a narrow thread (a phone) the card lies on its side: a square photo
     left, the facts right — five picks fit a screen instead of one */
  @container (max-width: 520px) {
    .card { flex-direction: row; }
    .ph { flex: none; width: 104px; aspect-ratio: auto; min-height: 104px; }
    .body { padding: 10px 12px; }
    .topline { flex-direction: column; gap: 2px; }
    .cprice { font-size: 15px; }
    .fit { top: 6px; right: auto; left: 6px; min-width: 28px; height: 22px; font-size: 11px; }
    .foot { padding: 8px 12px 10px; }
  }
  @media (pointer: coarse) { .engine { min-height: 32px; } }
</style>
