<script module>
  /* Which tab the drawer opens on, remembered for the session but not the
     browser: an agent working a call list wants every property to open on the
     brief, and tomorrow they are back to reading details. */
  let lastTab = 'details';
</script>

<script>
  /* The property detail.

     From 720px up it is a panel that slides in from the right edge (560px,
     full height, raised plane, hairline on the left, a deep shadow); below
     that it rises from the bottom as a near-full-height sheet with a grab
     handle. Both sit on a dimming scrim. Everything is transform + opacity,
     both directions, on the settle curve.

     Reads `app.selectedKey`; closing clears it (the root layout's Escape
     handler does the same). The page that renders <Drawer /> has nothing
     else to do. */
  import { tick } from 'svelte';
  import Photo from './Photo.svelte';
  import CallBrief from './CallBrief.svelte';
  import Signals from './Signals.svelte';
  import ErfPanel from './ErfPanel.svelte';
  import Icon from './glass/Icon.svelte';
  import Skeleton from './Skeleton.svelte';
  import { fade, slide } from '$lib/motion.js';
  import { api } from '$lib/api.js';
  import { app, selected, actions, gidOf, trackProspect } from '$lib/state.svelte.js';
  import { fmtR, fmtM, fmtInt, fmtArea, addrOf, mvLabel,
           isRent, priceTxt, furnishedTxt } from '$lib/format.js';

  /* The list rows are slim: everything only this drawer reads (reasoning,
     listings, evidence, erf candidates, coordinates …) is left off them. The
     drawer paints at once from the slim row and the full one is fetched and
     laid over it a moment later. */
  let detail = $state(null);
  let detailKey = null;
  let seq = 0;
  $effect(() => {
    const key = app.selectedKey;
    /* Also re-run when the list is replaced: that is how an erf confirm,
       re-evaluate or crawl reaches the UI, and the detail laid over the row
       would otherwise be older than the row under it. The old detail stays
       up until the new one lands, so the drawer doesn't blink. */
    app.prospects;
    const sole = app.showSole;
    const type = app.dealType;
    if (key !== detailKey) { detailKey = key; detail = null; }
    if (!key) return;
    const mine = ++seq;
    api.prospect(key, sole, type)
      .then((d) => { if (mine === seq && app.selectedKey === key) detail = d; })
      .catch(() => { /* the slim row stays up; nothing worth a toast */ });
  });

  const r = $derived.by(() => {
    const base = selected();
    if (!base) return null;
    return detail && detail.listing_key === base.listing_key ? { ...base, ...detail } : base;
  });

  /* A rental is stored and nothing more: no dedupe group, no erf, no GV, no
     score. The drawer drops every widget built on that work and shows the
     letting terms in its place. */
  const rent = $derived(!!r && isRent(r));

  const facts = $derived.by(() => {
    if (!r) return [];
    const ppm2 = r.price_per_m2
      ? 'R' + fmtInt(r.price_per_m2)
      : r.price_zar && r.floor_size_m2 ? 'R' + fmtInt(r.price_zar / r.floor_size_m2) : '—';
    return [
      [rent ? 'Rent' : 'Asking price', r.price_zar ? priceTxt(r) : 'POA'],
      ...(rent
        ? [['Available', r.available_from ? String(r.available_from) : '—'],
           ['Furnished', furnishedTxt(r.furnished) || '—']]
        : [['Municipal GV', r.gv_value ? `${fmtM(r.gv_value)}${r.gv_roll ? ' · ' + r.gv_roll : ''}` : '—'],
           ['Asking vs GV', r.price_vs_gv ? r.price_vs_gv + '× GV' : '—']]),
      ['Days on market', r.days_on_market != null ? r.days_on_market + ' days' : '—'],
      ...(rent
        ? [['Deposit', r.deposit ? fmtR(r.deposit) : '—']]
        : [['Price / m²', ppm2]]),
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

  let tab = $state(lastTab);
  $effect(() => { lastTab = tab; });
  const brief = $derived(!rent && tab === 'brief');

  const close = () => (app.selectedKey = null);
  const stage = $derived(r ? app.tracked[gidOf(r)] : null);

  /* ——— shape: panel from the right, or a sheet from below ——— */
  let wide = $state(true);
  $effect(() => {
    if (typeof matchMedia === 'undefined') return;
    const mq = matchMedia('(min-width: 720px)');
    const sync = () => (wide = mq.matches);
    sync();
    mq.addEventListener('change', sync);
    return () => mq.removeEventListener('change', sync);
  });

  /* Open: lock the page behind, scroll the body to the top for a new
     property, and take focus so Esc and Tab land here. */
  let scroller = $state(null);
  let box = $state(null);
  /* The sections below the fold (score bars, facts, listings, the erf panel)
     are the expensive part of the mount. They come in two frames after the
     panel starts sliding, so the slide itself never waits on them. */
  let ready = $state(false);
  $effect(() => {
    const key = app.selectedKey;
    if (!key) return;
    ready = false;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    tick().then(() => { if (scroller) scroller.scrollTop = 0; box?.focus?.({ preventScroll: true }); });
    let raf = requestAnimationFrame(() => { raf = requestAnimationFrame(() => (ready = true)); });
    return () => { cancelAnimationFrame(raf); document.body.style.overflow = prev; };
  });

  /* ——— the phone throw: only the grab handle starts it ——— */
  let drag = $state(0);
  let from = 0;
  let held = $state(null);
  function grabStart(e) { if (wide) return; from = e.clientY; held = e.currentTarget; held.setPointerCapture?.(e.pointerId); }
  function grabMove(e) { if (held == null) return; drag = Math.max(0, e.clientY - from); }
  function grabEnd() { if (held == null) return; held = null; if (drag > 120) close(); drag = 0; }

  const barTone = (v) => (v >= 70 ? 'ok' : v >= 40 ? 'warn' : 'crit');

  /* Rendered at the end of <body> so no ancestor's stacking context (the
     page's, the strip's) can sit on top of it or clip it. */
  function portal(node) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }
</script>

{#if r}
<div class="mg-portal" use:portal>
  <div class="scrim" onclick={close} role="presentation" transition:fade={{ duration: 200 }}></div>

  {#key wide}
    <aside class="drawer" class:phone={!wide} aria-label="Property detail" role="dialog" aria-modal="true"
           tabindex="-1" bind:this={box}
           style:transform={drag ? `translate3d(0,${drag}px,0)` : null}
           style:transition={held == null ? 'transform 0.28s var(--mc-ease-out)' : 'none'}
           transition:slide={wide ? { x: 72, duration: 320 } : { y: 640, duration: 340, opacity: 1 }}>
      {#if !wide}
        <div class="grab" onpointerdown={grabStart} onpointermove={grabMove}
             onpointerup={grabEnd} onpointercancel={grabEnd} role="presentation"><i></i></div>
      {/if}

      <div class="top">
        <span class="hud">{rent ? 'Rental' : 'Prospect'}{r.suburb ? ` · ${r.suburb}` : ''}</span>
        <button type="button" class="mg-btn secondary icon sm" onclick={close} aria-label="Close" title="Close (Esc)">
          <Icon name="close" size={15} />
        </button>
      </div>

      <div class="scroll mg-noscroll" bind:this={scroller}>
        {#key r.listing_key}
          <div class="hero"><Photo {r} eager alt={r.title || ''} /></div>

          <div class="head">
            <div class="badges">
              {#if rent}
                <span class="mg-chip mgr">To rent</span>
              {:else}
                {#if r.tier}<span class="tier {r.tier}">{r.tier}</span>{/if}
                <span class="mv {r.mandate_verdict || 'unknown'}">{mvLabel(r.mandate_verdict)}</span>
                {#if r.prospect_score != null}<span class="mg-chip">Score <b class="mg-tnum">{r.prospect_score}</b></span>{/if}
              {/if}
            </div>
            <p class="hprice price">{#if r.price_zar}{priceTxt(r)}{:else}<span class="poa">{rent ? 'Rent on application' : 'Price on application'}</span>{/if}</p>
            <h2><a href={r.url} target="_blank" rel="noopener">{r.title || r.source_id} <Icon name="external" size={13} /></a></h2>
            <p class="hsub">{[r.suburb, r.region].filter(Boolean).join(' · ')}{addrOf(r) ? ` · ${addrOf(r)}` : ''}{r.property_type ? ` · ${r.property_type}` : ''}</p>

            {#if !rent}<div class="sigrow"><Signals {r} verdict={false} /></div>{/if}

            <div class="actions">
              {#if rent}
                <a class="mg-btn sm secondary" href={r.url} target="_blank" rel="noopener"><Icon name="external" size={14} /> Open on the portal</a>
              {:else if stage}
                <a class="mg-btn sm accent" href="/leads/properties/{gidOf(r)}" title="Open in lead management">
                  <Icon name="check" size={14} /> Tracked · {stage.replace(/_/g, ' ')}
                </a>
              {:else}
                <button type="button" class="mg-btn sm primary" onclick={() => trackProspect(r)}
                  title="Add to lead management to log contacts, calls and mandates"><Icon name="plus" size={14} /> Track property</button>
              {/if}
              {#if !rent}
                {#if r.reevaluating}
                  <span class="mg-btn sm ghost busy"><span class="mg-spin"></span> Re-evaluating…</span>
                {:else}
                  <button type="button" class="mg-btn sm secondary" onclick={() => actions.reevaluate(r.listing_key)}
                    title="Refetch this listing live from the portal(s), re-score it and re-run the erf match"><Icon name="refresh" size={14} /> Re-evaluate</button>
                {/if}
                <button type="button" class="mg-btn sm secondary" onclick={() => actions.copyRow(String(r.group_id ?? r.listing_key))}
                  title="Copy as a spreadsheet row — paste into Excel or Google Sheets"><Icon name="copy" size={14} /> Copy row</button>
                {#if r.cma_url}
                  <a class="mg-btn sm secondary" href={r.cma_url}><Icon name="list" size={14} /> CMA report</a>
                  <a class="mg-btn sm ghost" href="{r.cma_url}/download" download title="Save the full CMA report as a standalone HTML file"><Icon name="download" size={14} /> Download</a>
                {/if}
              {/if}
            </div>

            {#if r.reeval_error}<div class="mg-strip crit"><span class="ic"><Icon name="alert" size={14} /></span><span>Re-evaluate failed — {r.reeval_error}</span></div>{/if}
            {#if r.mandate_expiry_note}<div class="mg-strip warn"><span class="ic"><Icon name="clock" size={14} /></span><span>{r.mandate_expiry_note}</span></div>{/if}
            {#if proofNote}<div class="mg-strip" class:ok={r.proof_age_hours < 72} class:warn={r.proof_age_hours >= 72}><span class="ic"><Icon name="check" size={14} /></span><span>{proofNote}</span></div>{/if}
          </div>

          {#if !rent}
            <div class="mg-tabs tabs" role="tablist">
              <button type="button" role="tab" aria-selected={!brief} onclick={() => (tab = 'details')}>Details</button>
              <button type="button" role="tab" aria-selected={brief} onclick={() => (tab = 'brief')}>Call brief</button>
            </div>
          {/if}

          {#if !ready}
            <section class="sec" aria-busy="true">
              <Skeleton h="11px" w="30%" />
              <div class="skl"><Skeleton h="14px" lines={4} delay={40} /></div>
            </section>
          {:else if brief}
            <section class="sec"><CallBrief gid={gidOf(r)} /></section>
          {:else}
            {#if bars.length}
              <section class="sec">
                <span class="hud">Score breakdown</span>
                <div class="bars">
                  {#each bars as [name, val] (name)}
                    <div class="bar">
                      <span class="bl">{name}</span>
                      <div class="mg-bar {barTone(val || 0)}"><i style:width="{Math.max(0, Math.min(100, val || 0))}%"></i></div>
                      <span class="bv mg-tnum">{val ?? '—'}</span>
                    </div>
                  {/each}
                </div>
                {#if r.scored_by}<p class="mg-hint">Scored by {String(r.scored_by).split(':')[0]}</p>{/if}
              </section>
            {/if}

            <section class="sec">
              <span class="hud">Key numbers</span>
              <dl class="mg-kv">
                {#each facts as [k, v] (k)}
                  <div><dt>{k}</dt><dd>{v}</dd></div>
                {/each}
              </dl>
            </section>

            <section class="sec">
              <span class="hud">{rent ? 'Listing' : 'Listings'} · {r.brand_count > 1 ? `${r.brand_count} agency brands` : (r.agencies?.[0] || 'agency unknown')}</span>
              <div class="listings">
                {#each r.listings || [] as l (l.url)}
                  <a class="listing" href={l.url} target="_blank" rel="noopener">
                    <span class="src">{l.source}</span>
                    <span class="lag">{l.agency || '—'}</span>
                    <span class="lp price mg-tnum">{rent ? fmtR(l.price_zar) : fmtM(l.price_zar)}</span>
                    <Icon name="external" size={13} class="lx" />
                  </a>
                {/each}
              </div>
              {#if r.evidence?.length}<p class="ev">Matched on: {r.evidence.join('; ')}</p>{/if}
            </section>

            {#if r.pitch_angle}
              <section class="sec">
                <span class="hud">Pitch angle</span>
                <div class="mg-strip ok note"><span class="ic"><Icon name="sparkles" size={14} /></span><span>{r.pitch_angle}</span></div>
              </section>
            {/if}

            {#if r.reasoning}
              <section class="sec">
                <span class="hud">Reasoning</span>
                <p class="prose">{r.reasoning}</p>
              </section>
            {/if}

            {#if r.red_flags}
              <section class="sec">
                <span class="hud">Red flags</span>
                <div class="mg-strip crit note"><span class="ic"><Icon name="alert" size={14} /></span><span>{r.red_flags}</span></div>
              </section>
            {/if}

            {#if !rent}
              <section class="sec">
                <span class="hud">Erf · cadastre</span>
                <ErfPanel {r} />
              </section>
            {/if}
          {/if}
        {/key}
      </div>
    </aside>
  {/key}
</div>
{/if}

<style>
  .scrim { position: fixed; inset: 0; z-index: 80; background: var(--mc-scrim); }

  .drawer {
    position: fixed; top: 0; right: 0; bottom: 0; z-index: 81;
    width: min(560px, 100vw); display: flex; flex-direction: column; outline: none;
    background: var(--mc-glass-strong); border-left: 1px solid var(--mc-glass-line);
    box-shadow: -24px 0 64px -24px rgba(0, 0, 0, 0.65);
    -webkit-backdrop-filter: blur(var(--mc-blur)) saturate(150%); backdrop-filter: blur(var(--mc-blur)) saturate(150%);
    padding-top: var(--sat); will-change: transform;
  }
  .drawer.phone {
    top: auto; left: 0; width: 100%; height: 94dvh;
    border-left: 0; border-top: 1px solid var(--mc-glass-line);
    border-radius: var(--mc-r-lg) var(--mc-r-lg) 0 0;
    box-shadow: 0 -24px 64px -24px rgba(0, 0, 0, 0.65), var(--mc-lit);
    padding-top: 0;
  }
  .grab { flex: none; display: grid; place-items: center; padding: 10px 0 2px; cursor: grab; touch-action: none; }
  .grab > i { display: block; width: 36px; height: 4px; border-radius: 9999px; background: var(--mc-line3); }

  .top { flex: none; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 16px; border-bottom: 1px solid var(--mc-line); }

  .scroll { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding-bottom: calc(var(--sab) + 24px); }

  .hero { aspect-ratio: 16 / 9; background: var(--mc-inset); border-bottom: 1px solid var(--mc-line); }

  .head { padding: 16px 16px 4px; }
  .badges { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .badges .mg-chip { height: 24px; padding: 0 9px; }
  .badges .mg-chip b { color: var(--mc-ink); margin-left: 2px; }
  .hprice { margin: 12px 0 0; font-size: 26px; line-height: 1.1; letter-spacing: -0.02em; }
  h2 { margin: 6px 0 0; font: 500 14.5px/1.4 var(--mc-font); color: var(--mc-ink2); }
  h2 a { display: inline-flex; align-items: center; gap: 5px; }
  h2 a:hover { color: var(--mc-accent); }
  .hsub { margin: 4px 0 0; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink3); }
  .sigrow { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }

  .actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin: 14px 0 12px; }
  .busy { color: var(--mc-mgr); }

  .head .mg-strip { margin: 0 0 8px; }

  .tabs { margin: 4px 16px 0; }

  .sec { padding: 18px 16px 0; }
  .sec > .hud { margin-bottom: 10px; }
  .sec > .mg-hint { margin-top: 8px; }
  .skl { margin-top: 12px; }

  .bars { display: flex; flex-direction: column; gap: 10px; }
  .bar { display: grid; grid-template-columns: 104px 1fr 34px; gap: 12px; align-items: center; }
  .bl { font: 500 12.5px/1.3 var(--mc-font); color: var(--mc-ink2); }
  .bv { font: 600 12.5px/1 var(--mc-mono); text-align: right; color: var(--mc-ink); }

  .listings { display: flex; flex-direction: column; gap: 6px; }
  .listing {
    display: grid; grid-template-columns: 92px 1fr auto auto; gap: 10px; align-items: center;
    min-height: 44px; padding: 8px 12px; border: 1px solid var(--mc-line); border-radius: var(--mc-r-md);
    background: var(--mc-surface); color: var(--mc-ink); transition: border-color var(--mc-t-fast), background var(--mc-t-fast);
  }
  .listing:hover { border-color: var(--mc-line2); background: var(--mc-glass-hover); }
  .src { font: 600 11.5px/1.3 var(--mc-font); color: var(--mc-accent); text-transform: capitalize; }
  .lag { font: 400 12.5px/1.3 var(--mc-font); color: var(--mc-ink2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .lp { font-size: 13px; }
  .listing :global(.lx) { color: var(--mc-ink3); }
  .ev { margin: 10px 0 0; font: 500 12px/1.5 var(--mc-font); color: var(--mc-accent); }

  .note { margin: 0; font-size: 13px; line-height: 1.6; color: var(--mc-ink); }
  .prose { margin: 0; font: 400 13px/1.65 var(--mc-font); color: var(--mc-ink2); }

  @media (max-width: 719px) {
    .hero { aspect-ratio: 16 / 8; }
    .top { padding: 6px 16px 10px; }
  }
</style>
