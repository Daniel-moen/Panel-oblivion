<script>
  import Photo from './Photo.svelte';
  import Signals from './Signals.svelte';
  import ErfPanel from './ErfPanel.svelte';
  import { app, selected, actions, gidOf, trackProspect } from '$lib/state.svelte.js';
  import { fmtR, fmtM, fmtInt, fmtArea, addrOf, mvLabel } from '$lib/format.js';

  const r = $derived(selected());

  const facts = $derived.by(() => {
    if (!r) return [];
    const ppm2 = r.price_per_m2
      ? 'R' + fmtInt(r.price_per_m2)
      : r.price_zar && r.floor_size_m2 ? 'R' + fmtInt(r.price_zar / r.floor_size_m2) : '—';
    return [
      ['Asking price', r.price_zar ? fmtR(r.price_zar) : 'POA'],
      ['Municipal GV', r.gv_value ? `${fmtM(r.gv_value)}${r.gv_roll ? ' · ' + r.gv_roll : ''}` : '—'],
      ['Asking vs GV', r.price_vs_gv ? r.price_vs_gv + '× GV' : '—'],
      ['Days on market', r.days_on_market != null ? r.days_on_market + ' days' : '—'],
      ['Price / m²', ppm2],
      ['Floor / erf', `${fmtArea(r.floor_size_m2) || '—'} / ${fmtArea(r.erf_size_m2) || '—'}`],
      ['Beds / baths', `${r.bedrooms ?? '?'} / ${r.bathrooms ?? '?'}`],
      ['First listed', r.listing_date ? String(r.listing_date).slice(0, 10) : '—']
    ];
  });

  const bars = $derived(r && r.prospect_score != null
    ? [['Prospect', r.prospect_score], ['Luxury fit', r.luxury_fit],
       ['Open mandate', r.open_mandate_confidence], ['Weakness', r.marketing_weakness]]
    : []);

  const proofNote = $derived.by(() => {
    if (!r?.proof_age_hours) return null;
    const h = r.proof_age_hours;
    return h < 72
      ? `Multi-brand proof confirmed ${Math.round(h)}h ago.`
      : `Multi-brand proof is ${Math.round(h / 24)} days stale — worth re-verifying.`;
  });

  const close = () => (app.selectedKey = null);
  const stage = $derived(r ? app.tracked[gidOf(r)] : null);
</script>

{#if r}
  <div class="scrim" onclick={close} aria-hidden="true"></div>
  <aside class="drawer" aria-label="Prospect detail">
    <button class="close" onclick={close} title="close (Esc)">✕</button>

    <div class="scroll">
      <div class="hero">
        <Photo {r} eager alt={r.title || ''} />
      </div>

      <div class="pad head">
        <div class="badges">
          {#if r.tier}<span class="tier {r.tier}">{r.tier}</span>{/if}
          <span class="mv {r.mandate_verdict || 'unknown'}">{mvLabel(r.mandate_verdict)}</span>
          {#if r.prospect_score != null}
            <span class="scorepill">Score {r.prospect_score}</span>
          {/if}
        </div>
        <p class="hprice price">{#if r.price_zar}{fmtR(r.price_zar)}{:else}<span class="poa">Price on application</span>{/if}</p>
        <h2><a href={r.url} target="_blank" rel="noopener">{r.title || r.source_id} ↗</a></h2>
        <p class="hsub">{[r.suburb, r.region].filter(Boolean).join(' · ')}{addrOf(r) ? ` · ${addrOf(r)}` : ''}{r.property_type ? ` · ${r.property_type}` : ''}</p>

        <div class="sigrow"><Signals {r} verdict={false} /></div>

        <div class="actions">
          {#if stage}
            <a class="act cma" href="/leads/properties/{gidOf(r)}"
               title="Open in the management panel">✓ Tracked · {stage.replace(/_/g, ' ')} →</a>
          {:else}
            <button class="act" onclick={() => trackProspect(r)}
              title="Add to the management panel to log contacts, calls and mandates">+ Track property</button>
          {/if}
          {#if r.reevaluating}
            <span class="act busy"><span class="spin"></span>&nbsp;Re-evaluating…</span>
          {:else}
            <button class="act" onclick={() => actions.reevaluate(r.listing_key)}
              title="Refetch this listing live from the portal(s), re-score it and re-run the erf match">↻ Re-evaluate</button>
          {/if}
          <button class="act" onclick={() => actions.copyRow(String(r.group_id ?? r.listing_key))}
            title="Copy as a spreadsheet row — paste into Excel or Google Sheets">Copy for sheet</button>
          {#if r.cma_url}
            <a class="act cma" href={r.cma_url}>CMA report →</a>
            <a class="act" href="{r.cma_url}/download" download
              title="Save the full CMA report as a standalone HTML file">↓ Download report</a>
          {/if}
        </div>
        {#if r.reeval_error}<p class="note bad">Re-eval failed — {r.reeval_error}</p>{/if}
        {#if r.mandate_expiry_note}<p class="note">{r.mandate_expiry_note}</p>{/if}
        {#if proofNote}<p class="note" class:ok={r.proof_age_hours < 72}>{proofNote}</p>{/if}
      </div>

      {#if bars.length}
        <section class="pad">
          <h3>Score breakdown</h3>
          {#each bars as [name, val] (name)}
            <div class="bar">
              <span class="bl">{name}</span>
              <div class="bt"><i style:width="{Math.max(0, Math.min(100, val || 0))}%"></i></div>
              <span class="bv">{val ?? '—'}</span>
            </div>
          {/each}
          {#if r.scored_by}<p class="dim tiny">Scored by {String(r.scored_by).split(':')[0]}</p>{/if}
        </section>
      {/if}

      <section class="pad">
        <h3>Key numbers</h3>
        <div class="facts">
          {#each facts as [k, v] (k)}
            <div class="fact"><span>{k}</span><b>{v}</b></div>
          {/each}
        </div>
      </section>

      <section class="pad">
        <h3>Listings · {r.brand_count > 1 ? `${r.brand_count} agency brands` : (r.agencies?.[0] || 'agency unknown')}</h3>
        {#each r.listings || [] as l (l.url)}
          <a class="listing" href={l.url} target="_blank" rel="noopener">
            <span class="src">{l.source}</span>
            <span class="lag">{l.agency || '—'}</span>
            <span class="lp price">{fmtM(l.price_zar)}</span>
          </a>
        {/each}
        {#if r.evidence?.length}
          <p class="ev">Matched on: {r.evidence.join('; ')}</p>
        {/if}
      </section>

      {#if r.pitch_angle}
        <section class="pad">
          <h3>Pitch angle</h3>
          <div class="pitch">{r.pitch_angle}</div>
        </section>
      {/if}

      {#if r.reasoning}
        <section class="pad">
          <h3>Reasoning</h3>
          <p class="prose">{r.reasoning}</p>
        </section>
      {/if}

      {#if r.red_flags}
        <section class="pad">
          <h3>Red flags</h3>
          <div class="flags">{r.red_flags}</div>
        </section>
      {/if}

      <section class="pad last">
        <h3>Erf · cadastre</h3>
        <ErfPanel {r} />
      </section>
    </div>
  </aside>
{/if}

<style>
  .scrim { position: fixed; inset: 0; z-index: 45; background: var(--scrim); }
  .drawer {
    position: fixed; top: 0; right: 0; bottom: 0; z-index: 46;
    width: min(540px, 97vw); background: var(--bg-2);
    border-left: 1px solid var(--line); box-shadow: var(--shadow-2);
    animation: slidein 0.2s ease-out; display: flex;
  }
  @keyframes slidein { from { transform: translateX(40px); opacity: 0; } to { transform: none; opacity: 1; } }
  .scroll { flex: 1; overflow-y: auto; padding-bottom: 2.5rem; }

  .close { position: absolute; top: 0.8rem; right: 0.8rem; z-index: 5;
           width: 32px; height: 32px; border-radius: 8px;
           background: var(--overlay); border: 1px solid var(--line-2);
           color: var(--ink-2); box-shadow: var(--shadow-1); }
  .close:hover { color: var(--ink); border-color: var(--line-3); }

  .hero { aspect-ratio: 16 / 9.5; background: var(--bg-3); }

  .pad { padding: 1.1rem 1.4rem 0; }
  .head { padding-top: 1rem; }
  .badges { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; }
  .scorepill { display: inline-flex; padding: 0.16rem 0.6rem; border-radius: 999px;
               background: var(--accent-soft); color: var(--accent-2);
               font-size: 0.72rem; font-weight: 700; }
  .hprice { margin: 0.65rem 0 0; font-size: 1.55rem; letter-spacing: -0.02em; }
  h2 { margin: 0.2rem 0 0; font-size: 0.95rem; font-weight: 500; line-height: 1.45; }
  h2 a { color: var(--ink-2); }
  h2 a:hover { color: var(--accent); }
  .hsub { margin: 0.25rem 0 0; font-size: 0.8rem; color: var(--ink-3); }

  .sigrow { display: flex; gap: 0.3rem; flex-wrap: wrap; margin-top: 0.6rem; }
  .actions { display: flex; gap: 0.45rem; align-items: center; flex-wrap: wrap;
             margin-top: 0.8rem; }
  .act.busy { color: var(--accent-2); border-color: transparent; background: none; }
  .act.cma { color: var(--accent-2); border-color: var(--accent-line); background: var(--accent-soft); }
  .act.cma:hover { background: var(--accent); color: #fff; border-color: var(--accent); }

  .note { margin: 0.6rem 0 0; font-size: 0.79rem; font-weight: 500; color: var(--psole); }
  .note.ok { color: var(--open); }
  .note.bad { color: var(--bad); }

  section.pad { margin-top: 0.6rem; }
  section.last { padding-bottom: 0.5rem; }
  h3 { margin: 0 0 0.65rem; padding-top: 0.9rem; border-top: 1px solid var(--line);
       font-size: 0.82rem; font-weight: 700; color: var(--ink); }

  .bar { display: grid; grid-template-columns: 105px 1fr 34px; gap: 0.7rem;
         align-items: center; margin-bottom: 0.45rem; }
  .bl { font-size: 0.76rem; font-weight: 500; color: var(--ink-2); }
  .bt { height: 6px; background: var(--bg-3); border-radius: 3px; overflow: hidden; }
  .bt i { display: block; height: 100%; border-radius: 3px;
          background: var(--accent); transition: width 0.5s; }
  .bv { font-size: 0.78rem; font-weight: 600; text-align: right;
        font-variant-numeric: tabular-nums; }
  .tiny { font-size: 0.72rem; margin: 0.35rem 0 0; }
  .dim { color: var(--ink-3); }

  .facts { display: grid; grid-template-columns: 1fr 1fr; gap: 0.55rem 1.2rem; }
  .fact span { display: block; font-size: 0.72rem; color: var(--ink-3); }
  .fact b { font-weight: 600; font-size: 0.86rem; }

  .listing { display: grid; grid-template-columns: 100px 1fr auto; gap: 0.7rem;
             align-items: center; padding: 0.5rem 0.7rem;
             border: 1px solid var(--line); border-radius: var(--r-sm);
             margin-bottom: 0.4rem; color: var(--ink); transition: border-color 0.15s, background 0.15s; }
  .listing:hover { border-color: var(--accent-line); background: var(--accent-soft); }
  .src { font-size: 0.72rem; font-weight: 700; color: var(--accent-2);
         text-transform: capitalize; }
  .lag { font-size: 0.78rem; color: var(--ink-2);
         overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .lp { font-size: 0.84rem; }
  .ev { margin: 0.4rem 0 0; font-size: 0.76rem; font-weight: 500; color: var(--open); }

  .pitch { background: var(--accent-soft); border: 1px solid var(--accent-line);
           border-radius: var(--r); padding: 0.75rem 0.9rem;
           font-size: 0.85rem; line-height: 1.6; color: var(--accent-ink); }
  .prose { margin: 0; font-size: 0.84rem; line-height: 1.65; color: var(--ink-2); }
  .flags { background: var(--red-soft); border: 1px solid var(--red-line);
           border-radius: var(--r); padding: 0.7rem 0.9rem;
           font-size: 0.82rem; line-height: 1.6; color: var(--bad-ink); }
</style>
