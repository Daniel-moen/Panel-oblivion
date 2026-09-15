<script>
  import Photo from './Photo.svelte';
  import Signals from './Signals.svelte';
  import { app, gidOf, trackProspect } from '$lib/state.svelte.js';
  import { fmtR } from '$lib/format.js';

  let { r } = $props();

  const meta = $derived.by(() => {
    const bits = [];
    if (r.bedrooms) bits.push(`${r.bedrooms} bed`);
    if (r.property_type) bits.push(r.property_type.toLowerCase());
    if (r.days_on_market != null) bits.push(`${r.days_on_market} days on market`);
    if (r.price_vs_gv) bits.push(`${r.price_vs_gv}× GV`);
    return bits.join(' · ');
  });

  const open = () => (app.selectedKey = r.listing_key);
  const stage = $derived(app.tracked[gidOf(r)]);
  function track(e) { e.stopPropagation(); trackProspect(r); }
</script>

<article class="card" class:sel={r.listing_key === app.selectedKey}
         onclick={open} onkeydown={(e) => e.key === 'Enter' && open()}
         role="button" tabindex="0">
  <div class="ph">
    <Photo {r} alt={r.title || ''} />
    <div class="over">
      {#if r.tier}<span class="tier {r.tier}">{r.tier}</span>{:else}<span></span>{/if}
      <span class="score" class:wait={r.prospect_score == null}
            title="prospect score">{r.prospect_score ?? '…'}</span>
    </div>
    {#if stage}
      <a class="trk on" href="/leads/properties/{gidOf(r)}" onclick={(e) => e.stopPropagation()}
         title="Tracked · {stage.replace(/_/g, ' ')}">✓ {stage.replace(/_/g, ' ')}</a>
    {:else}
      <button class="trk" onclick={track} title="Add to the management panel">+ Track</button>
    {/if}
  </div>

  <div class="body">
    <div class="topline">
      <span class="price cprice">{#if r.price_zar}{fmtR(r.price_zar)}{:else}<span class="poa">POA</span>{/if}</span>
      <span class="suburb">{r.suburb || ''}</span>
    </div>
    <h3>{r.title || r.source_id}</h3>
    {#if meta}<p class="meta">{meta}</p>{/if}
    <div class="chips"><Signals {r} max={3} /></div>
    {#if r.agencies?.length}
      <p class="ag" title={r.agencies.join(' · ')}>{r.agencies.join(' · ')}</p>
    {/if}
  </div>
</article>

<style>
  .trk { position: absolute; left: 0.6rem; bottom: 0.6rem; z-index: 2;
         font-size: 0.72rem; font-weight: 600; padding: 0.28rem 0.6rem;
         border-radius: 999px; border: 1px solid rgba(255,255,255,0.35);
         background: rgba(0,0,0,0.55); color: #fff; backdrop-filter: blur(4px);
         opacity: 0; transition: opacity 0.15s; text-transform: capitalize; }
  .card:hover .trk, .trk.on { opacity: 1; }
  .trk:hover { background: var(--accent); border-color: var(--accent); }
  .trk.on { background: var(--open); border-color: var(--open); }
  .card {
    display: flex; flex-direction: column; overflow: hidden; cursor: pointer;
    background: var(--bg-2); border: 1px solid var(--line);
    border-radius: var(--r-lg); box-shadow: var(--shadow-1);
    transition: transform 0.15s ease, box-shadow 0.15s, border-color 0.15s;
  }
  .card:hover { transform: translateY(-2px); box-shadow: var(--shadow-2); }
  .card.sel { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent), var(--shadow-1); }
  .card:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

  .ph { position: relative; aspect-ratio: 16 / 10; background: var(--bg-3); }
  .ph :global(img) { transition: transform 0.35s ease; }
  .card:hover .ph :global(img) { transform: scale(1.03); }

  .over { position: absolute; top: 0.6rem; left: 0.6rem; right: 0.6rem;
          display: flex; justify-content: space-between; align-items: flex-start; }
  /* the tier tint is translucent — floating on a photo it needs a backdrop */
  .over .tier { box-shadow: 0 1px 3px rgba(16, 24, 40, 0.18);
                background: var(--overlay); color: var(--hot-ink);
                backdrop-filter: blur(4px); }
  .over .tier.warm { color: var(--warm-ink); }
  .over .tier.cold { color: var(--cold-ink); }
  .score {
    display: inline-flex; align-items: center; justify-content: center;
    min-width: 34px; height: 26px; padding: 0 0.45rem;
    background: var(--overlay); border-radius: 8px;
    font-size: 0.82rem; font-weight: 700; color: var(--ink);
    box-shadow: 0 1px 3px rgba(16, 24, 40, 0.18);
    font-variant-numeric: tabular-nums;
  }
  .score.wait { color: var(--accent); }

  .body { display: flex; flex-direction: column; gap: 0.35rem;
          padding: 0.8rem 0.95rem 0.95rem; flex: 1; }
  .topline { display: flex; justify-content: space-between; align-items: baseline; gap: 0.7rem; }
  .cprice { font-size: 1.12rem; }
  .suburb { font-size: 0.74rem; font-weight: 500; color: var(--ink-3);
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  h3 { margin: 0; font-size: 0.86rem; font-weight: 500; line-height: 1.4; color: var(--ink-2);
       display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
       overflow: hidden; }
  .meta { margin: 0; font-size: 0.74rem; color: var(--ink-3); }
  .chips { display: flex; gap: 0.3rem; flex-wrap: wrap; align-items: center; margin-top: 0.1rem; }
  .ag { margin: 0.1rem 0 0; font-size: 0.72rem; color: var(--ink-3);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
