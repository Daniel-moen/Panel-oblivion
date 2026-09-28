<script>
  import Photo from './Photo.svelte';
  import Signals from './Signals.svelte';
  import Icon from './glass/Icon.svelte';
  import { goto } from '$app/navigation';
  import { app, gidOf, trackProspect } from '$lib/state.svelte.js';
  import { propertyPath } from '$lib/api.js';
  import { recent } from './property/recent.svelte.js';
  import { isRent, priceTxt, rentChips } from '$lib/format.js';
  import { staggerIn, pressable } from '$lib/motion.js';

  /* `i` staggers the card's entrance in a grid (only the first dozen wait). */
  let { r, i = 0 } = $props();

  /* A rental has no score, no tier, no mandate verdict and no GV — none of
     that is computed for the rent book — so the card drops those widgets and
     shows what a letting actually states instead. */
  const rent = $derived(isRent(r));

  const meta = $derived.by(() => {
    const bits = [];
    if (r.bedrooms) bits.push(`${r.bedrooms} bed`);
    if (r.property_type) bits.push(r.property_type.toLowerCase());
    if (r.days_on_market != null) bits.push(`${r.days_on_market} days on market`);
    if (!rent && r.price_vs_gv) bits.push(`${r.price_vs_gv}× GV`);
    return bits.join(' · ');
  });

  /* The whole card opens the property page (/property/<listing_key>);
     ⌘/Ctrl-click opens it in a new tab, as a link would. */
  const open = (e) => (e?.metaKey || e?.ctrlKey
    ? window.open(propertyPath(r.listing_key), '_blank', 'noopener')
    : goto(propertyPath(r.listing_key)));
  const stage = $derived(app.tracked[gidOf(r)]);
  function track(e) { e.stopPropagation(); trackProspect(r); }
</script>

<article class="card" class:sel={r.listing_key === recent.key}
         in:staggerIn|global={{ i }} use:pressable={'lift'}
         onclick={open} onkeydown={(e) => e.key === 'Enter' && open(e)}
         role="button" tabindex="0" data-prospect={r.listing_key}>
  <div class="ph">
    <Photo {r} w={320} alt={r.title || ''} />
    {#if !rent}
      <div class="over">
        {#if r.tier}<span class="tier {r.tier}">{r.tier}</span>{:else}<span></span>{/if}
        <span class="score mg-tnum" class:wait={r.prospect_score == null} title="prospect score">{r.prospect_score ?? '…'}</span>
      </div>
      {#if stage}
        <a class="trk on" href="/leads/properties/{gidOf(r)}" onclick={(e) => e.stopPropagation()}
           title="Tracked · {stage.replace(/_/g, ' ')}"><Icon name="check" size={12} stroke={2.5} /> {stage.replace(/_/g, ' ')}</a>
      {:else}
        <button type="button" class="trk" onclick={track} title="Add to lead management"><Icon name="plus" size={12} stroke={2.5} /> Track</button>
      {/if}
    {/if}
  </div>

  <div class="body">
    <div class="topline">
      <span class="price cprice">{#if r.price_zar}{priceTxt(r)}{:else}<span class="poa">POA</span>{/if}</span>
      <span class="suburb">{r.suburb || ''}</span>
    </div>
    <h3>{r.title || r.source_id}</h3>
    {#if meta}<p class="meta">{meta}</p>{/if}
    <div class="chips">
      {#if rent}
        {#each rentChips(r) as [text, title] (text)}<span class="sig" {title}>{text}</span>{/each}
      {:else}
        <Signals {r} max={3} />
      {/if}
    </div>
    {#if r.agencies?.length}
      <p class="ag" title={r.agencies.join(' · ')}>{r.agencies.join(' · ')}</p>
    {/if}
  </div>
</article>

<style>
  .card {
    position: relative; display: flex; flex-direction: column; overflow: hidden; cursor: pointer;
    background: var(--mc-surface); border: 1px solid var(--mc-line); border-radius: var(--mc-r);
    /* transform: hoverLift on spring.snappy (use:pressable, lib/motion.js) */
    transition: border-color var(--mc-t-fast), transform var(--mg-spring-snappy), box-shadow var(--mc-t);
  }
  .card:hover { border-color: var(--mc-line2); background: var(--mc-glass-hover); }
  .card.sel { border-color: var(--mc-accent); box-shadow: 0 0 0 1px var(--mc-accent); }
  .card:focus-visible { outline: 2px solid var(--mc-accent); outline-offset: 2px; }

  .ph { position: relative; aspect-ratio: 16 / 10; background: var(--mc-inset); border-bottom: 1px solid var(--mc-line); }
  .ph :global(img) { transition: transform 0.4s var(--mc-ease); }
  .card:hover .ph :global(img) { transform: scale(1.03); }

  .over { position: absolute; top: 10px; left: 10px; right: 10px; display: flex; justify-content: space-between; align-items: flex-start; }
  .over .tier { background: rgba(12, 12, 14, 0.82); border-color: rgba(255, 255, 255, 0.12); }
  .score {
    display: inline-flex; align-items: center; justify-content: center; min-width: 34px; height: 26px; padding: 0 8px;
    background: rgba(12, 12, 14, 0.82); border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 9999px;
    font: 700 13px/1 var(--mc-mono); color: var(--mc-ink);
  }
  .score.wait { color: var(--mc-accent); }

  .trk {
    position: absolute; left: 10px; bottom: 10px; z-index: 2;
    display: inline-flex; align-items: center; gap: 4px; height: 28px; padding: 0 10px; border-radius: 9999px;
    border: 1px solid rgba(255, 255, 255, 0.18); background: rgba(12, 12, 14, 0.82); color: #fff;
    font: 600 11.5px/1 var(--mc-font); text-transform: capitalize;
    opacity: 0; transition: opacity var(--mc-t-fast), background var(--mc-t-fast), border-color var(--mc-t-fast);
  }
  .card:hover .trk, .card:focus-within .trk, .trk.on { opacity: 1; }
  .trk:hover { background: var(--mc-ink); color: var(--mc-bg); border-color: var(--mc-ink); }
  .trk.on { background: var(--mc-accent); border-color: var(--mc-accent); color: var(--mc-accent-ink); }
  @media (pointer: coarse) { .trk { opacity: 1; } }

  .body { display: flex; flex-direction: column; gap: 6px; padding: 12px 14px 14px; flex: 1; }
  .topline { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }
  .cprice { font-size: 17px; }
  .suburb { font: 500 12px/1.3 var(--mc-font); color: var(--mc-ink3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  h3 { margin: 0; font: 500 13.5px/1.4 var(--mc-font); color: var(--mc-ink2);
       display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .meta { margin: 0; font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); }
  .chips { display: flex; gap: 5px; flex-wrap: wrap; align-items: center; margin-top: 2px; }
  .ag { margin: 2px 0 0; font: 400 11.5px/1.4 var(--mc-font); color: var(--mc-ink3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

</style>
