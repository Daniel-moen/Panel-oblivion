<script>
  import Photo from './Photo.svelte';
  import Signals from './Signals.svelte';
  import { app } from '$lib/state.svelte.js';
  import { fmtM, addrOf } from '$lib/format.js';

  let { rows } = $props();
</script>

<div class="list panel">
  <div class="row head">
    <span></span><span>Property</span><span class="r">Price</span>
    <span class="r">Days</span><span>Mandate</span>
    <span class="r" title="luxury fit · open-mandate confidence · marketing weakness">L · O · W</span>
    <span class="r">Score</span>
  </div>
  {#each rows as r (r.listing_key)}
    <div class="row item" class:sel={r.listing_key === app.selectedKey}
         onclick={() => (app.selectedKey = r.listing_key)}
         onkeydown={(e) => e.key === 'Enter' && (app.selectedKey = r.listing_key)}
         role="button" tabindex="0">
      <div class="thumb"><Photo {r} /></div>
      <div class="main">
        <span class="title">{r.title || r.source_id}</span>
        <span class="meta">
          {r.suburb || ''}{r.bedrooms ? ` · ${r.bedrooms} bed` : ''}{addrOf(r) ? ` · ${addrOf(r)}` : ''}
          {#if r.erf_number}&nbsp;· <b class="erf">erf {r.erf_number}</b>{/if}
        </span>
        <span class="ag">{(r.agencies || []).join(' · ') || '—'}</span>
      </div>
      <span class="r price">{fmtM(r.price_zar)}</span>
      <span class="r dom">{r.days_on_market != null ? r.days_on_market + 'd' : '—'}</span>
      <span class="mand"><Signals {r} max={2} /></span>
      <span class="r low">{r.prospect_score == null ? '—'
        : `${r.luxury_fit} · ${r.open_mandate_confidence} · ${r.marketing_weakness}`}</span>
      <span class="r score" class:wait={r.prospect_score == null}>{r.prospect_score ?? '…'}</span>
    </div>
  {/each}
</div>

<style>
  .list { overflow: hidden; }
  .row {
    display: grid; align-items: center; gap: 0.9rem;
    grid-template-columns: 72px minmax(220px, 1fr) 90px 52px minmax(150px, 0.6fr) 92px 52px;
    padding: 0.6rem 1rem;
    border-bottom: 1px solid var(--line);
  }
  .row:last-child { border-bottom: none; }

  .head {
    font-size: 0.7rem; font-weight: 600; letter-spacing: 0.03em;
    text-transform: uppercase; color: var(--ink-3);
    background: var(--bg-3); padding: 0.5rem 1rem;
  }

  .item { cursor: pointer; transition: background 0.15s ease; }
  .item:hover { background: var(--hover); }
  .item.sel { background: var(--accent-soft); }
  .item:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }

  .thumb { width: 72px; height: 54px; overflow: hidden;
           border-radius: var(--r-sm); background: var(--bg-3); }
  .thumb :global(img) { transition: transform 0.3s ease; }
  .item:hover .thumb :global(img) { transform: scale(1.05); }

  .main { display: flex; flex-direction: column; gap: 0.12rem; min-width: 0; }
  .title { font-size: 0.84rem; font-weight: 500; line-height: 1.35; color: var(--ink);
           display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical;
           overflow: hidden; }
  .meta { font-size: 0.74rem; color: var(--ink-3);
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .erf { font-weight: 600; color: var(--accent-2); }
  .ag { font-size: 0.72rem; color: var(--ink-3);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  .r { text-align: right; }
  .price { font-size: 0.92rem; }
  .dom { font-size: 0.78rem; color: var(--ink-2); font-variant-numeric: tabular-nums; }
  .mand { display: flex; gap: 0.3rem; flex-wrap: wrap; align-items: center; }
  .low { font-size: 0.76rem; color: var(--ink-2);
         font-variant-numeric: tabular-nums; white-space: nowrap; }
  .score { font-size: 1.05rem; font-weight: 700; color: var(--ink);
           font-variant-numeric: tabular-nums; }
  .score.wait { color: var(--accent); font-size: 0.9rem; }

  @media (max-width: 1000px) {
    .row { grid-template-columns: 72px minmax(180px, 1fr) 90px 52px; }
    .dom, .mand, .low { display: none; }
    .head span:nth-child(4), .head span:nth-child(5), .head span:nth-child(6) { display: none; }
  }
</style>
