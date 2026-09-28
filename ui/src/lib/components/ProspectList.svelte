<script>
  import Photo from './Photo.svelte';
  import Signals from './Signals.svelte';
  import { goto } from '$app/navigation';
  import { app } from '$lib/state.svelte.js';
  import { propertyPath } from '$lib/api.js';
  import { recent } from './property/recent.svelte.js';
  import { addrOf, furnishedTxt, priceShort } from '$lib/format.js';
  import { staggerIn } from '$lib/motion.js';

  let { rows } = $props();

  /* The rent book carries none of the scored columns, so the last three
     become what a letting states: when it is free, and how it comes. */
  const rent = $derived(app.dealType === 'rent');
  /* A row opens the property page (/property/<listing_key>). */
  const pick = (r, e) => (e?.metaKey || e?.ctrlKey
    ? window.open(propertyPath(r.listing_key), '_blank', 'noopener')
    : goto(propertyPath(r.listing_key)));
</script>

<div class="mg-panel wrap">
  <table class="mg-table list" class:rentcols={rent}>
    <thead>
      <tr>
        <th class="th-ph"></th>
        <th>Property</th>
        <th class="r">{rent ? 'Rent' : 'Price'}</th>
        <th class="r c-dom">Days</th>
        {#if rent}
          <th class="c-avail">Available</th>
          <th class="r c-furn">Furnished</th>
        {:else}
          <th class="c-mand">Mandate</th>
          <th class="r c-low" title="luxury fit · open-mandate confidence · marketing weakness">L · O · W</th>
          <th class="r">Score</th>
        {/if}
      </tr>
    </thead>
    <tbody>
      {#each rows as r, i (r.listing_key)}
        <tr class="item" class:sel={r.listing_key === recent.key} data-prospect={r.listing_key}
            in:staggerIn|global={{ i }}
            onclick={(e) => pick(r, e)} onkeydown={(e) => e.key === 'Enter' && pick(r, e)} role="button" tabindex="0">
          <td class="td-ph"><div class="thumb"><Photo {r} w={80} /></div></td>
          <td class="main">
            <span class="title">{r.title || r.source_id}</span>
            <span class="meta">
              {r.suburb || ''}{r.bedrooms ? ` · ${r.bedrooms} bed` : ''}{addrOf(r) ? ` · ${addrOf(r)}` : ''}
              {#if !rent && r.erf_number}&nbsp;· <b class="erf">erf {r.erf_number}</b>{/if}
            </span>
            <span class="ag">{(r.agencies || []).join(' · ') || '—'}</span>
          </td>
          <td class="r price">{priceShort(r)}</td>
          <td class="r dom mg-mono c-dom">{r.days_on_market != null ? r.days_on_market + 'd' : '—'}</td>
          {#if rent}
            <td class="c-avail">{r.available_from || '—'}</td>
            <td class="r c-furn">{furnishedTxt(r.furnished) || '—'}</td>
          {:else}
            <td class="c-mand"><span class="mand"><Signals {r} max={2} /></span></td>
            <td class="r low mg-mono c-low">{r.prospect_score == null ? '—'
              : `${r.luxury_fit} · ${r.open_mandate_confidence} · ${r.marketing_weakness}`}</td>
            <td class="r score mg-mono" class:wait={r.prospect_score == null}>{r.prospect_score ?? '…'}</td>
          {/if}
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .wrap { overflow: auto; -webkit-overflow-scrolling: touch; }
  .list { min-width: 0; }
  /* the sticky head clears the sticky strip above the page */
  .list th { top: 0; }

  .th-ph, .td-ph { width: 72px; padding-right: 0; }
  .thumb { width: 64px; height: 48px; overflow: hidden; border-radius: 8px; background: var(--mc-inset); }
  .thumb :global(img) { transition: transform 0.3s var(--mc-ease); }
  .item:hover .thumb :global(img) { transform: scale(1.05); }

  .item { cursor: pointer; }
  .item:focus-visible { outline: 2px solid var(--mc-accent); outline-offset: -2px; }

  .main { min-width: 200px; }
  .main > span { display: block; }
  .title { font: 500 13.5px/1.35 var(--mc-font); color: var(--mc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 46ch; }
  .meta { margin-top: 2px; font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 52ch; }
  .erf { font-weight: 600; color: var(--mc-accent); }
  .ag { margin-top: 1px; font: 400 11.5px/1.4 var(--mc-font); color: var(--mc-ink3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 52ch; }

  .price { font-size: 14px; white-space: nowrap; }
  .dom { font-size: 12.5px; }
  .mand { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
  .low { font-size: 12px; white-space: nowrap; }
  .score { font-size: 15px; font-weight: 700; color: var(--mc-ink); }
  .score.wait { color: var(--mc-accent); font-size: 13px; }
  .c-avail, .c-furn { white-space: nowrap; font-size: 13px; }

  /* columns leave as the pane narrows: L·O·W first, then days, then the
     mandate chips; price and score stay to the last */
  @media (max-width: 1400px) { .c-low { display: none; } }
  @media (max-width: 1200px) { .c-dom { display: none; } .title, .meta, .ag { max-width: 34ch; } }
  @media (max-width: 760px) { .c-mand, .c-avail, .c-furn { display: none; } .title, .meta, .ag { max-width: 24ch; } }
</style>
