<script>
  /* The property dossier — one prospect, a whole page.

     Paints from GET /api/prospect/<key> (the full scored row, asked from the
     right book: /api/property/<key>/extra says sale or rent, sole or not)
     plus the extras only this page needs (every portal listing with its
     agent and lifecycle, price history, contacts, activity), then the photo
     gallery and the parcel outline lazily.

     Layout: gallery → title, price and the key facts → actions → two
     columns from 1000px (the case for the property on the left: why it is a
     prospect, market signals, listings, location & erf, call brief; the
     work on the right: lead status, owner & deed, activity). On a phone the
     two columns dissolve into one ordered stack (display: contents + order)
     so the owner & deed sits right under "why".

     Everything inside is glass-soft on the one pane the layout draws; the
     only other layer this page can add is the photo lightbox, which is
     opaque, not blurred. */
  import { untrack } from 'svelte';
  import { page } from '$app/state';
  import { afterNavigate, goto } from '$app/navigation';
  import { api, propertyApi, propertyPath } from '$lib/api.js';
  import { app, actions, gidOf, trackProspect, toast } from '$lib/state.svelte.js';
  import { openChannelForProperty } from '$lib/chat.svelte.js';
  import { openQuickLog } from '$lib/shell.svelte.js';
  import { fmtR, fmtM, fmtInt, fmtArea, addrOf, mvLabel, isRent, priceTxt,
           furnishedTxt, photoSrc } from '$lib/format.js';
  import { STAGE_LABEL, ago, shortDate, label } from '$lib/panel.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Sparkline from '$lib/components/glass/Sparkline.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Signals from '$lib/components/Signals.svelte';
  import ErfPanel from '$lib/components/ErfPanel.svelte';
  import CallBrief from '$lib/components/CallBrief.svelte';
  import Gallery from '$lib/components/property/Gallery.svelte';
  import ParcelMap from '$lib/components/property/ParcelMap.svelte';
  import OwnerDeed from '$lib/components/property/OwnerDeed.svelte';
  import { recent } from '$lib/components/property/recent.svelte.js';

  const key = $derived(page.params.key);

  let r = $state(null);          // the full prospect row
  let extra = $state(null);      // /api/property/<key>/extra
  let photos = $state(null);     // null while loading, [] for none
  let err = $state(null);
  let lead = $state(null);       // /api/tracked/<gid> when tracked
  let showBrief = $state(false);

  /* ---- where "back" goes: the page we came from (history keeps its query
     string and scroll, so the list comes back exactly as it was left), or
     the prospect list on a cold open. */
  let from = $state(null);
  afterNavigate(({ from: f }) => {
    if (f?.url && f.url.pathname !== page.url.pathname) from = f.url;
  });
  const backLabel = $derived.by(() => {
    const p = from?.pathname || '/prospects';
    if (p.startsWith('/prospects')) return 'Prospects';
    if (p.startsWith('/map')) return 'Map';
    if (p.startsWith('/leads')) return 'Leads';
    if (p.startsWith('/mia')) return 'Mia';
    if (p.startsWith('/reports')) return 'Reports';
    if (p === '/') return 'Home';
    return 'Back';
  });
  function back(e) {
    if (from && window.history.length > 1) { e.preventDefault(); window.history.back(); }
  }

  /* ---- loading */
  let seq = 0;
  async function fetchRow(k, book) {
    /* Ask the book the row lives in first; a sole-mandate row is only in
       the sole-inclusive book, a rental only in the rent one. A non-best
       member of a group is not a row of its own: fall through to the
       members, richest first. */
    const type = book?.type === 'rent' ? 'rent' : 'sale';
    /* the member the list itself shows, first (a map pin or a chat card may
       carry a sibling's key) */
    let best = k;
    const g = extra?.group_id;
    if (g && !String(g).startsWith('solo-') && (extra?.listings || []).length > 1) {
      try { best = (await propertyApi.byGroup(g))?.listing_key || k; } catch { /* k it is */ }
    }
    const tries = [[best, !!book?.sole, type]];
    if (type === 'sale') tries.push([best, !book?.sole, 'sale']);
    for (const l of extra?.listings || []) if (l.listing_key !== best) tries.push([l.listing_key, !!book?.sole, type]);
    for (const [kk, sole, t] of tries) {
      try { return await api.prospect(kk, sole, t); }
      catch (e) { if (e.status !== 404) throw e; }
    }
    return null;
  }

  async function load(k, quiet = false) {
    const mine = ++seq;
    if (!quiet) { r = null; extra = null; photos = null; err = null; lead = null; showBrief = false; }
    try {
      /* /property/<group id> (or solo-<key>) is accepted too: resolve it to
         the listing key and settle on that URL. */
      if (/^\d+$/.test(k) || k.startsWith('solo-')) {
        const b = await propertyApi.byGroup(k);
        if (mine !== seq) return;
        if (b?.listing_key) goto(propertyPath(b.listing_key), { replaceState: true });
        else err = 'notfound';
        return;
      }
      const x = await propertyApi.extra(k);
      if (mine !== seq) return;
      extra = x;
      const row = await fetchRow(k, x.book);
      if (mine !== seq) return;
      if (!row) { err = 'notfound'; return; }
      r = row;
      recent.key = row.listing_key;
    } catch (e) {
      if (mine !== seq) return;
      err = e.status === 404 ? 'notfound' : e.message;
      return;
    }
    if (!quiet) loadPhotos(k);
  }
  /* Its own guard (the URL), not `seq`: a quiet re-read of the row while a
     re-evaluate runs must not orphan the gallery. */
  async function loadPhotos(k) {
    const still = () => key === k;
    try {
      const cached = await propertyApi.photos(k);
      if (!still()) return;
      photos = cached.photos || [];
      /* Nothing cached beyond the heroes: let the server fetch one page. */
      if (!cached.from_pages) {
        const fresh = await propertyApi.photos(k, true);
        if (still() && (fresh.photos || []).length >= photos.length) photos = fresh.photos || [];
      }
    } catch { if (still() && photos === null) photos = []; }
  }
  $effect(() => { const k = key; untrack(() => load(k)); });

  const gid = $derived(r ? gidOf(r) : extra?.group_id || null);
  const stage = $derived(gid ? app.tracked[gid] : null);
  async function loadLead() {
    if (!gid || !stage) { lead = null; return; }
    try { lead = await api.trackedOne(gid); } catch { lead = null; }
  }
  $effect(() => { gid; stage; untrack(loadLead); });

  /* A re-evaluate or AI locate runs in the background: re-read the row
     until it settles. */
  const working = $derived(!!(r && (r.reevaluating || r.erf_ai_running)));
  $effect(() => {
    if (!working) return;
    const k = key;
    const t = setInterval(() => load(k, true), 4000);
    return () => clearInterval(t);
  });

  async function reevaluate() {
    if (await actions.reevaluate(r.listing_key)) r = { ...r, reevaluating: true };
  }
  async function track() {
    await trackProspect(r);
  }
  async function setStage(v) {
    if (!gid || v === stage) return;
    const prev = app.tracked[gid];
    app.tracked[gid] = v;
    try { await api.updateTracked(gid, { stage: v }); toast('Moved to ' + STAGE_LABEL[v], 'ok'); loadLead(); }
    catch (e) { app.tracked[gid] = prev; toast(e.message, 'error'); }
  }

  /* ---- derived presentation */
  const rent = $derived(!!r && isRent(r));
  const title = $derived(r ? (addrOf(r) || r.title || r.source_id) : '');
  const ppm2 = $derived(r ? (r.price_per_m2 || (r.price_zar && r.floor_size_m2 ? Math.round(r.price_zar / r.floor_size_m2) : null)) : null);

  const facts = $derived.by(() => {
    if (!r) return [];
    const f = [
      ['Beds', r.bedrooms != null ? fmtInt(r.bedrooms) : '—', 'home'],
      ['Baths', r.bathrooms != null ? fmtInt(r.bathrooms) : '—', 'layers'],
      ['Floor', fmtArea(r.floor_size_m2) || '—', 'ruler'],
    ];
    if (rent) {
      f.push(['Available', r.available_from ? String(r.available_from).slice(0, 10) : '—', 'calendar']);
      f.push(['Furnished', furnishedTxt(r.furnished) || '—', 'box']);
      f.push(['Deposit', r.deposit ? fmtR(r.deposit) : '—', 'banknote']);
    } else {
      f.push(['Erf', fmtArea(r.erf_size_m2) || '—', 'mapPin']);
      f.push(['Per m²', ppm2 ? 'R' + fmtInt(ppm2) : '—', 'dollar']);
      f.push(['On market', r.days_on_market != null ? r.days_on_market + ' days' : '—', 'clock']);
    }
    return f;
  });

  const bars = $derived(r && r.prospect_score != null
    ? [['Luxury fit', r.luxury_fit, 'How well it fits the luxury book'],
       ['Open mandate', r.open_mandate_confidence, 'Confidence the mandate is open'],
       ['Marketing weakness', r.marketing_weakness, 'How poorly it is being marketed']]
    : []);
  const barTone = (v) => (v >= 70 ? 'ok' : v >= 40 ? 'warn' : 'crit');

  const proofNote = $derived.by(() => {
    if (!r?.proof_age_hours) return null;
    const h = r.proof_age_hours;
    return h < 72 ? `Multi-brand proof confirmed ${Math.round(h)}h ago.`
                  : `Multi-brand proof is ${Math.round(h / 24)} days stale — worth re-verifying.`;
  });

  /* Asking price over time, the whole group as one line: each observation
     is one portal's asking at that moment. */
  const priceHist = $derived.by(() => {
    const h = extra?.price_history || [];
    const out = [];
    const last = {};
    for (const p of h) {
      if (!p.price_zar) continue;
      const prev = last[p.listing_key];
      last[p.listing_key] = p.price_zar;
      if (prev === p.price_zar) continue;
      out.push({ ...p, prev, source: p.listing_key.split(':')[0] });
    }
    return out;
  });
  const moves = $derived(priceHist.filter((p) => p.prev != null));
  const series = $derived(priceHist.map((p) => p.price_zar));

  const signalTiles = $derived.by(() => {
    if (!r || rent) return [];
    const t = [];
    t.push({ k: 'Days on market', v: r.days_on_market != null ? String(r.days_on_market) : '—',
             sub: r.listing_date ? 'listed ' + String(r.listing_date).slice(0, 10) : 'first listing date unknown',
             tone: r.days_on_market > 120 ? 'warn' : '' });
    t.push({ k: 'Price cuts', v: r.total_cut_pct ? `−${r.total_cut_pct}%` : 'None',
             sub: r.total_cut_pct ? `${r.price_changes || 1} change${(r.price_changes || 1) === 1 ? '' : 's'}` : (r.price_reduced ? 'marked reduced on a portal' : 'asking has held'),
             tone: r.total_cut_pct ? 'ok' : '' });
    t.push({ k: 'Asking vs GV', v: r.price_vs_gv ? r.price_vs_gv + '×' : '—',
             sub: r.gv_value ? `GV ${fmtM(r.gv_value)}${r.gv_roll ? ' · ' + r.gv_roll : ''}` : 'no municipal value',
             tone: r.price_vs_gv >= 2 ? 'warn' : '' });
    t.push({ k: 'Price per m²', v: ppm2 ? 'R' + fmtInt(ppm2) : '—', sub: r.floor_size_m2 ? `${fmtArea(r.floor_size_m2)} floor` : 'floor size unknown' });
    t.push({ k: 'Relisted', v: r.relisted ? 'Yes' : 'No',
             sub: r.relisted ? (r.days_off_market ? `${r.days_off_market} days off market` : 'came back after a delist') : 'continuous listing',
             tone: r.relisted ? 'ok' : '' });
    t.push({ k: 'Agencies', v: String(r.brand_count || (r.agencies || []).length || 1),
             sub: r.brand_count > 1 ? 'brands marketing it — open' : 'one brand', tone: r.brand_count > 1 ? 'ok' : '' });
    return t;
  });

  /* One timeline: market events from the listings, and — when tracked —
     every contact attempt, note and stage change. */
  const timeline = $derived.by(() => {
    const out = [];
    for (const l of extra?.listings || []) {
      const at = l.listing_date || l.first_seen;
      if (at) out.push({ t: String(at), icon: 'plus', text: `Listed on ${l.source}${l.agency ? ' by ' + l.agency : ''}${l.price_zar ? ' at ' + fmtM(l.price_zar) : ''}` });
      if (l.delisted_at) out.push({ t: String(l.delisted_at), icon: 'eyeOff', text: `Dropped off ${l.source}` });
      if (l.relisted_at) out.push({ t: String(l.relisted_at), icon: 'refresh', text: `Back on ${l.source}` });
    }
    for (const p of moves) {
      out.push({ t: String(p.observed_at), icon: 'dollar', tone: p.price_zar < p.prev ? 'ok' : '',
                 text: `${p.source}: ${fmtM(p.prev)} → ${fmtM(p.price_zar)}` });
    }
    const acts = lead?.activities || extra?.activities || [];
    for (const a of acts) {
      const p = a.payload || {};
      let text = label(a.kind);
      if (a.kind === 'stage_change') text = `Moved to ${STAGE_LABEL[p.to] || p.to}`;
      else if (a.kind === 'tracked') text = 'Started tracking';
      else if (a.kind === 'contact_added') text = `Contact added: ${p.name || '—'}`;
      else if (['price_cut', 'delisted', 'relisted'].includes(a.kind)) continue;   // already above
      out.push({ t: String(a.occurred_at), icon: 'arrowRight', text: text + (a.actor ? ` · ${a.actor}` : '') });
    }
    for (const i of lead?.interactions || []) {
      out.push({ t: String(i.occurred_at), icon: 'phone', tone: ['spoke', 'interested', 'meeting_set'].includes(i.outcome) ? 'ok' : '',
                 text: `${label(i.channel)} · ${label(i.outcome)}${i.contact_name ? ' with ' + i.contact_name : ''}${i.summary ? ' — ' + i.summary : ''}` });
    }
    for (const n of lead?.notes || []) out.push({ t: String(n.created_at), icon: 'pencil', text: n.body });
    return out.sort((a, b) => b.t.localeCompare(a.t)).slice(0, 30);
  });

  const openTasks = $derived((lead?.tasks || []).filter((t) => !t.done_at).slice(0, 4));
  const FLOW = ['new', 'researching', 'contact_found', 'contacted', 'meeting', 'valuation_sent', 'mandate_signed', 'listed', 'sold', 'lost', 'parked'];
  const erfResolved = $derived(!!r && ['ok', 'confirmed', 'check'].includes(r.erf_status));
</script>

<svelte:head><title>{r ? title : 'Property'} — Oblivion</title></svelte:head>

<div class="top">
  <a class="mg-btn ghost sm back" href={from ? from.pathname + from.search : '/prospects'} onclick={back} data-property-back>
    <Icon name="chevronLeft" size={15} /> {backLabel}
  </a>
  {#if r}<span class="crumb">{[r.region, r.suburb].filter(Boolean).join(' · ')}</span>{/if}
</div>

{#if err === 'notfound'}
  <div class="mg-panel">
    <Empty icon="building" title="Property not found" hint="It may have left the book, or the link is from another deploy.">
      <a class="mg-btn secondary" href="/prospects">All prospects</a>
    </Empty>
  </div>
{:else if err}
  <div class="mg-strip crit"><span class="ic"><Icon name="alert" size={15} /></span><span><b>Couldn't load this property</b> — {err}</span></div>
  <button type="button" class="mg-btn secondary" onclick={() => load(key)}><Icon name="refresh" size={15} /> Try again</button>
{:else if !r}
  <div class="skel" aria-busy="true">
    <Skeleton h="clamp(260px, 38vw, 460px)" r="16px" />
    <div class="skh"><Skeleton h="14px" w="140px" /><Skeleton h="34px" w="240px" /><Skeleton h="16px" w="60%" /></div>
    <div class="skf">{#each Array(6) as _, i (i)}<Skeleton h="58px" r="12px" delay={i * 40} />{/each}</div>
  </div>
{:else}
  <div class="dossier" data-property={r.listing_key}>
    <div class="mg-rise"><Gallery {r} {photos} alt={title} /></div>

    <header class="mg-rise hd" style:--i={1}>
      <div class="badges">
        {#if rent}
          <span class="mg-chip mgr">To rent</span>
        {:else}
          {#if r.tier}<span class="tier {r.tier}">{r.tier}</span>{/if}
          <span class="mv {r.mandate_verdict || 'unknown'}">{mvLabel(r.mandate_verdict)}</span>
          {#if stage}<a class="mg-chip ok" href="/leads/properties/{gid}"><Icon name="check" size={12} /> {STAGE_LABEL[stage] || label(stage)}</a>{/if}
        {/if}
      </div>
      <div class="hrow">
        <div class="hl">
          <h1 class="mg-h1 ttl">{title}</h1>
          <p class="mg-sub">{[r.property_type, r.suburb, r.region].filter(Boolean).join(' · ')}{r.erf_number ? ` · Erf ${r.erf_number}` : ''}</p>
        </div>
        <div class="hp">
          <p class="price big mg-tnum">{#if r.price_zar}{priceTxt(r)}{:else}<span class="poa">{rent ? 'Rent on application' : 'Price on application'}</span>{/if}</p>
          {#if !rent && r.prospect_score != null}
            <span class="score" title="Prospect score"><b class="mg-tnum">{r.prospect_score}</b><span>score</span></span>
          {/if}
        </div>
      </div>
      {#if !rent}<div class="sigs"><Signals {r} verdict={false} /></div>{/if}
    </header>

    <div class="facts mg-rise" style:--i={2}>
      {#each facts as [k, v, ic] (k)}
        <div class="fact"><span class="fi"><Icon name={ic} size={15} /></span><span class="fv mg-tnum">{v}</span><span class="fk">{k}</span></div>
      {/each}
    </div>

    <div class="acts mg-rise" style:--i={3}>
      {#if rent}
        <a class="mg-btn primary" href={r.url} target="_blank" rel="noopener"><Icon name="external" size={15} /> Open on the portal</a>
      {:else if stage}
        <a class="mg-btn accent" href="/leads/properties/{gid}"><Icon name="check" size={15} /> Open lead</a>
        <button type="button" class="mg-btn secondary" onclick={() => openQuickLog(gid)}><Icon name="phone" size={15} /> Log a call</button>
      {:else}
        <button type="button" class="mg-btn primary" onclick={track} data-track-property><Icon name="plus" size={15} /> Track property</button>
      {/if}
      {#if !rent}
        <a class="mg-btn secondary" href="#owner"><Icon name="key" size={15} /> Owner &amp; deed</a>
        {#if r.group_id != null}
          <button type="button" class="mg-btn secondary" data-testid="discuss-property"
                  onclick={() => openChannelForProperty(String(r.group_id), { label: title, suburb: r.suburb, price_zar: r.price_zar, tier: r.tier, photo_url: photoSrc(r) })}>
            <Icon name="chat" size={15} /> Discuss</button>
        {/if}
        <a class="mg-btn secondary" href="/mia?about={encodeURIComponent(gid)}"><Icon name="sparkles" size={15} /> Ask Mia</a>
        {#if r.cma_url}<a class="mg-btn secondary" href={r.cma_url}><Icon name="ruler" size={15} /> CMA report</a>{/if}
        {#if r.reevaluating}
          <span class="mg-btn ghost busy"><span class="mg-spin"></span> Re-evaluating…</span>
        {:else}
          <button type="button" class="mg-btn ghost" onclick={reevaluate} title="Refetch live from the portal(s), re-score, re-match the erf"><Icon name="refresh" size={15} /> Re-evaluate</button>
        {/if}
        <button type="button" class="mg-btn ghost" onclick={() => actions.copyRow(String(r.group_id ?? r.listing_key))} title="Copy as a spreadsheet row"><Icon name="copy" size={15} /> Copy row</button>
      {/if}
    </div>

    {#if r.reeval_error}<div class="mg-strip crit"><span class="ic"><Icon name="alert" size={14} /></span><span>Re-evaluate failed — {r.reeval_error}</span></div>{/if}

    <div class="cols">
      <div class="col main">
        {#if !rent}
          <section class="mg-section mg-rise o-why" style:--i={4}>
            <div class="head"><h2>Why this is a prospect</h2>{#if r.scored_by}<span class="mg-count">scored by {String(r.scored_by).split(':')[0]}</span>{/if}</div>
            <div class="body why">
              <div class="verdict">
                <span class="mv {r.mandate_verdict || 'unknown'} lg">{mvLabel(r.mandate_verdict)}</span>
                <p>{r.mandate_expiry_note || (r.brand_count > 1 ? `${r.brand_count} agency brands market it — the mandate cannot be sole.` : 'One agency brand markets it; the verdict rests on the listing text.')}</p>
              </div>
              {#if proofNote}<div class="mg-strip" class:ok={r.proof_age_hours < 72} class:warn={r.proof_age_hours >= 72}><span class="ic"><Icon name="check" size={14} /></span><span>{proofNote}</span></div>{/if}
              {#if r.prospect_score != null}
                <div class="scorebox">
                  <div class="dial {barTone(r.prospect_score)}" style:--p={Math.max(0, Math.min(100, r.prospect_score))}>
                    <b class="mg-tnum">{r.prospect_score}</b><span>of 100</span>
                  </div>
                  <div class="bars">
                    {#each bars as [name, val, hint] (name)}
                      <div class="bar" title={hint}>
                        <span class="bl">{name}</span>
                        <div class="mg-bar {barTone(val || 0)}"><i style:width="{Math.max(0, Math.min(100, val || 0))}%"></i></div>
                        <span class="bv mg-tnum">{val ?? '—'}</span>
                      </div>
                    {/each}
                  </div>
                </div>
              {/if}
              {#if r.pitch_angle}
                <div class="blk"><span class="hud">Pitch angle</span>
                  <div class="mg-strip ok note"><span class="ic"><Icon name="sparkles" size={14} /></span><span>{r.pitch_angle}</span></div></div>
              {/if}
              {#if r.reasoning}<div class="blk"><span class="hud">Reasoning</span><p class="prose">{r.reasoning}</p></div>{/if}
              {#if r.red_flags}
                <div class="blk"><span class="hud">Red flags</span>
                  <div class="mg-strip crit note"><span class="ic"><Icon name="alert" size={14} /></span><span>{r.red_flags}</span></div></div>
              {/if}
            </div>
          </section>

          <section class="mg-section mg-rise o-market" style:--i={5}>
            <div class="head"><h2>Market signals</h2></div>
            <div class="body">
              <div class="tiles">
                {#each signalTiles as t (t.k)}
                  <div class="tile {t.tone || ''}"><span class="hud">{t.k}</span><b class="mg-tnum">{t.v}</b><span class="ts">{t.sub}</span></div>
                {/each}
              </div>
              {#if priceHist.length}
                <div class="hist">
                  <div class="hh"><span class="hud">Asking price history</span>
                    {#if new Set(series).size > 1}<Sparkline data={series} width={160} height={30} />{/if}</div>
                  {#if moves.length}
                    <div class="mg-list">
                      {#each moves.slice().reverse() as p (p.listing_key + p.observed_at)}
                        <div class="hrow2 mg-tnum"><span class="d">{shortDate(p.observed_at)}</span><span class="s">{p.source}</span>
                          <span class="mv2">{fmtM(p.prev)} → <b class:down={p.price_zar < p.prev}>{fmtM(p.price_zar)}</b></span></div>
                      {/each}
                    </div>
                  {:else}
                    <p class="mg-hint">No price moves seen since {shortDate(priceHist[0].observed_at)} — asking has held at {fmtM(priceHist[priceHist.length - 1].price_zar)}.</p>
                  {/if}
                </div>
              {/if}
            </div>
          </section>
        {/if}

        <section class="mg-section mg-rise o-listings" style:--i={6}>
          <div class="head"><h2>{(extra?.listings || []).length > 1 ? 'Every listing of this home' : 'Listing'}</h2><span class="mg-count">{(extra?.listings || []).length || ''}</span></div>
          {#if !extra}
            <div class="body"><Skeleton h="44px" lines={2} /></div>
          {:else}
            <div class="mg-list">
              {#each extra.listings as l (l.listing_key)}
                <a class="lrow" href={l.url} target="_blank" rel="noopener">
                  <span class="src">{l.source}</span>
                  <span class="lm">
                    <b>{l.agency || 'Agency not stated'}</b>
                    <span>{[l.agent_name, l.listing_date ? 'listed ' + shortDate(l.listing_date) : null, l.last_seen ? 'seen ' + ago(l.last_seen) : null].filter(Boolean).join(' · ')}</span>
                  </span>
                  <span class="lchips">
                    {#if l.lifecycle && l.lifecycle !== 'active'}<span class="mg-chip xs {l.lifecycle === 'relisted' ? 'ok' : 'warn'}">{l.lifecycle}</span>{/if}
                    {#if l.under_offer}<span class="mg-chip xs warn">under offer</span>{/if}
                    {#if l.mandate_explicit === 'sole'}<span class="mg-chip xs crit">sole</span>{/if}
                  </span>
                  <span class="lp price mg-tnum">{l.price_zar ? (rent ? fmtR(l.price_zar) : fmtM(l.price_zar)) : 'POA'}</span>
                  <Icon name="external" size={13} class="lx" />
                </a>
              {/each}
            </div>
            {#if r.evidence?.length}<p class="ev">Matched on: {r.evidence.join('; ')}</p>{/if}
          {/if}
        </section>

        {#if r.lat != null && r.lng != null || !rent}
          <section class="mg-section mg-rise o-loc" style:--i={7}>
            <div class="head"><h2>{rent ? 'Location' : 'Location & erf'}</h2></div>
            <div class="body loc">
              {#if r.lat != null && r.lng != null}
                <ParcelMap lat={r.lat} lng={r.lng} loc={r.loc} listingKey={r.listing_key} erfNumber={r.erf_number} />
              {:else}
                <p class="mg-hint">No coordinates published for this listing.</p>
              {/if}
              {#if !rent}<ErfPanel {r} deed={false} />{/if}
            </div>
          </section>
        {/if}

        {#if r.description}
          <section class="mg-section mg-rise o-about" style:--i={8}>
            <div class="head"><h2>From the listing</h2></div>
            <div class="body"><p class="prose">{r.description}{r.description.length >= 299 ? '…' : ''}</p>
              <a class="mg-btn ghost sm more" href={r.url} target="_blank" rel="noopener">Read it on {r.source || 'the portal'} <Icon name="external" size={12} /></a></div>
          </section>
        {/if}

        {#if !rent}
          <section class="mg-section mg-rise o-brief" style:--i={9}>
            {#if showBrief}
              <div class="body"><CallBrief gid={gid} /></div>
            {:else}
              <div class="head"><h2>Call brief</h2>
                <div class="mg-actions"><button type="button" class="mg-btn secondary sm" onclick={() => (showBrief = true)}><Icon name="list" size={14} /> Show call brief</button></div>
              </div>
            {/if}
          </section>
        {/if}
      </div>

      <aside class="col side">
        {#if !rent}
          <section class="mg-section mg-rise o-lead" style:--i={4}>
            <div class="head"><h2>Lead status</h2>
              {#if stage}<div class="mg-actions"><a class="mg-btn ghost sm" href="/leads/properties/{gid}">Open <Icon name="arrowRight" size={13} /></a></div>{/if}
            </div>
            <div class="body">
              {#if stage}
                <label class="stg"><span class="hud">Stage</span>
                  <div class="mg-select full"><select value={stage} onchange={(e) => setStage(e.currentTarget.value)} aria-label="Stage">
                    {#each FLOW as s (s)}<option value={s}>{STAGE_LABEL[s] || label(s)}</option>{/each}
                  </select><span class="ic"><Icon name="chevronDown" size={14} /></span></div></label>
                {#if lead}
                  <dl class="mg-kv">
                    <div><dt>Contacts</dt><dd>{lead.contacts?.length || 0}</dd></div>
                    <div><dt>Contact attempts</dt><dd>{lead.interactions?.length || 0}{lead.interactions?.[0] ? ` · last ${ago(lead.interactions[0].occurred_at)}` : ''}</dd></div>
                    {#if lead.mandates?.[0]}<div><dt>Mandate</dt><dd>{label(lead.mandates[0].type)}</dd></div>{/if}
                  </dl>
                  {#if openTasks.length}
                    <span class="hud tk">Open tasks</span>
                    <ul class="tasks">{#each openTasks as t (t.id)}<li><Icon name="clock" size={12} /> {t.title}{t.due_at ? ` · ${ago(t.due_at)}` : ''}</li>{/each}</ul>
                  {/if}
                {/if}
                <button type="button" class="mg-btn secondary sm full" onclick={() => openQuickLog(gid)}><Icon name="phone" size={14} /> Log a contact attempt</button>
              {:else}
                <p class="none">Not in lead management yet. Track it to log calls, contacts and the mandate.</p>
                <button type="button" class="mg-btn primary sm" onclick={track}><Icon name="plus" size={14} /> Track property</button>
              {/if}
            </div>
          </section>

          <div class="mg-rise o-owner" style:--i={5}>
            <OwnerDeed gid={gid} listingKey={r.listing_key} {erfResolved} contacts={lead?.contacts || extra?.contacts || []} onchange={loadLead} />
          </div>
        {/if}

        <section class="mg-section mg-rise o-activity" style:--i={6}>
          <div class="head"><h2>Activity</h2><span class="mg-count">{timeline.length || ''}</span></div>
          {#if !extra}
            <div class="body"><Skeleton h="14px" lines={4} /></div>
          {:else if !timeline.length}
            <p class="none pad">Nothing recorded yet.</p>
          {:else}
            <ol class="tl">
              {#each timeline as e, i (i)}
                <li class={e.tone || ''}><span class="ti"><Icon name={e.icon} size={12} /></span><span class="tt">{e.text}</span><span class="tw" title={e.t}>{ago(e.t)}</span></li>
              {/each}
            </ol>
          {/if}
        </section>
      </aside>
    </div>
  </div>
{/if}

<style>
  .top { display: flex; align-items: center; gap: 10px; margin: -4px 0 12px -8px; min-width: 0; }
  .crumb { font: 500 12.5px/1 var(--mc-font); color: var(--mc-ink3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  .skel { display: flex; flex-direction: column; gap: 16px; }
  .skh { display: flex; flex-direction: column; gap: 10px; }
  .skf { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; }

  .dossier { display: flex; flex-direction: column; gap: 16px; min-width: 0; }

  /* ——— headline ——— */
  .hd { display: flex; flex-direction: column; gap: 10px; }
  .badges { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .badges .mg-chip { height: 24px; padding: 0 9px; }
  .hrow { display: flex; gap: 16px; align-items: flex-end; justify-content: space-between; flex-wrap: wrap; }
  .hl { min-width: 0; flex: 1 1 320px; display: flex; flex-direction: column; gap: 4px; }
  .ttl { font-size: clamp(22px, 3.2vw, 30px); overflow-wrap: anywhere; text-transform: none; }
  .hp { display: flex; align-items: center; gap: 14px; flex: none; }
  .big { margin: 0; font-size: clamp(26px, 3.6vw, 36px); line-height: 1.05; letter-spacing: -0.02em; }
  .score { display: flex; flex-direction: column; align-items: center; justify-content: center; width: 56px; height: 56px; border-radius: 16px;
           background: var(--mc-ok-soft); border: 1px solid var(--mc-ok-line); color: var(--mc-accent); }
  .score b { font: 650 22px/1 var(--mc-mono); }
  .score span { font: 500 10px/1.2 var(--mc-font); color: var(--mc-ink3); }
  .sigs { display: flex; gap: 6px; flex-wrap: wrap; }

  .facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
  @media (min-width: 760px) { .facts { grid-template-columns: repeat(6, minmax(0, 1fr)); } }
  .fact { display: grid; grid-template-columns: auto 1fr; grid-template-rows: auto auto; column-gap: 10px; align-items: center;
          padding: 10px 12px; border-radius: var(--mc-r-md); background: var(--mc-glass-soft); border: 1px solid var(--mc-glass-line); min-width: 0; }
  .fi { grid-row: span 2; width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center; background: rgba(255, 255, 255, 0.06); color: var(--mc-ink2); }
  .fv { font: 600 15px/1.2 var(--mc-font); color: var(--mc-ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .fk { font: 400 11.5px/1.3 var(--mc-font); color: var(--mc-ink3); }
  @media (max-width: 420px) { .fi { display: none; } .fact { grid-template-columns: 1fr; padding: 9px 10px; } }

  .acts { display: flex; gap: 8px; flex-wrap: wrap; }
  .busy { color: var(--mc-mgr); }
  @media (max-width: 639px) {
    .acts { flex-wrap: nowrap; overflow-x: auto; margin: 0 -16px; padding: 0 16px 2px; scrollbar-width: none; }
    .acts::-webkit-scrollbar { display: none; }
    .acts > * { flex: none; }
  }

  /* ——— the two columns ——— */
  .cols { display: flex; flex-direction: column; gap: 16px; }
  .col { display: contents; }
  /* phone / narrow: one stack, the owner right after "why" */
  .o-why { order: 1; } .o-owner { order: 2; } .o-lead { order: 3; } .o-market { order: 4; }
  .o-listings { order: 5; } .o-loc { order: 6; } .o-about { order: 7; } .o-brief { order: 8; } .o-activity { order: 9; }
  @media (min-width: 1000px) {
    .cols { display: grid; grid-template-columns: minmax(0, 1fr) 360px; align-items: start; }
    .col { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
    .side { position: sticky; top: calc(var(--mc-strip-h, 52px) + 16px); }
  }
  @media (min-width: 1280px) { .cols { grid-template-columns: minmax(0, 1fr) 400px; } }

  .mg-section > .head { align-items: center; min-height: 46px; padding-top: 8px; padding-bottom: 8px; }
  .none { margin: 0 0 12px; font: 400 13px/1.5 var(--mc-font); color: var(--mc-ink3); }
  .none.pad { padding: 14px 16px; margin: 0; }
  .mg-chip.xs { height: 22px; padding: 0 8px; font-size: 11px; }

  /* why */
  .why { display: flex; flex-direction: column; gap: 14px; }
  .why .mg-strip { margin: 0; }
  .verdict { display: flex; gap: 12px; align-items: flex-start; }
  .verdict p { margin: 0; font: 400 13.5px/1.5 var(--mc-font); color: var(--mc-ink); }
  .mv.lg { flex: none; }
  .scorebox { display: grid; grid-template-columns: 92px minmax(0, 1fr); gap: 18px; align-items: center; }
  .dial {
    --c: var(--mc-accent);
    width: 92px; height: 92px; border-radius: 50%; display: flex; flex-direction: column; align-items: center; justify-content: center;
    background: radial-gradient(closest-side, rgba(20, 20, 24, 0.9) 78%, transparent 80% 100%),
                conic-gradient(var(--c) calc(var(--p) * 1%), rgba(255, 255, 255, 0.08) 0);
  }
  .dial.warn { --c: var(--mc-warn); } .dial.crit { --c: var(--mc-crit); }
  .dial b { font: 650 26px/1 var(--mc-mono); color: var(--mc-ink); }
  .dial span { font: 400 10.5px/1.4 var(--mc-font); color: var(--mc-ink3); }
  .bars { display: flex; flex-direction: column; gap: 12px; }
  .bar { display: grid; grid-template-columns: 132px 1fr 30px; gap: 12px; align-items: center; }
  .bl { font: 500 12.5px/1.3 var(--mc-font); color: var(--mc-ink2); }
  .bv { font: 600 12.5px/1 var(--mc-mono); text-align: right; color: var(--mc-ink); }
  @media (max-width: 479px) {
    .scorebox { grid-template-columns: 1fr; justify-items: start; }
    .bar { grid-template-columns: 1fr 1.2fr 28px; }
  }
  .blk { display: flex; flex-direction: column; gap: 8px; }
  .note { margin: 0; font-size: 13px; line-height: 1.6; color: var(--mc-ink); }
  .prose { margin: 0; font: 400 13.5px/1.65 var(--mc-font); color: var(--mc-ink2); white-space: pre-line; }

  /* market */
  .tiles { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  @media (min-width: 640px) { .tiles { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
  .tile { display: flex; flex-direction: column; gap: 3px; padding: 12px; border-radius: var(--mc-r-md); background: rgba(255, 255, 255, 0.035); border: 1px solid var(--mc-glass-line); min-width: 0; }
  .tile b { font: 600 20px/1.2 var(--mc-font); color: var(--mc-ink); letter-spacing: -0.01em; }
  .tile.ok b { color: var(--mc-accent); } .tile.warn b { color: var(--mc-warn); }
  .ts { font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); overflow-wrap: anywhere; }
  .hist { margin-top: 16px; display: flex; flex-direction: column; gap: 8px; }
  .hh { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .hrow2 { display: grid; grid-template-columns: 92px 110px 1fr; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--mc-line-soft); font: 400 12.5px/1.4 var(--mc-font); color: var(--mc-ink2); }
  .hrow2 .s { text-transform: capitalize; color: var(--mc-ink3); }
  .hrow2 b { color: var(--mc-ink); font-weight: 600; } .hrow2 b.down { color: var(--mc-accent); }

  /* listings */
  .lrow {
    display: grid; grid-template-columns: 104px minmax(0, 1fr) auto auto auto; gap: 12px; align-items: center;
    padding: 12px 16px; border-bottom: 1px solid var(--mc-line-soft); color: var(--mc-ink); transition: background var(--mc-t-fast);
  }
  .lrow:last-child { border-bottom: 0; }
  .lrow:hover { background: var(--mc-glass-hover); }
  .src { font: 600 12px/1.3 var(--mc-font); color: var(--mc-accent); text-transform: capitalize; overflow: hidden; text-overflow: ellipsis; }
  .lm { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .lm b { font: 500 13px/1.35 var(--mc-font); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .lm span { font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .lchips { display: flex; gap: 4px; }
  .lp { font-size: 13.5px; }
  .lrow :global(.lx) { color: var(--mc-ink3); }
  @media (max-width: 639px) {
    .lrow { grid-template-columns: minmax(0, 1fr) auto; row-gap: 4px; }
    .src { grid-column: 1; } .lp { grid-column: 2; grid-row: 1; text-align: right; }
    .lm { grid-column: 1 / -1; } .lchips { grid-column: 1 / -1; } .lchips:empty { display: none; }
    .lrow :global(.lx) { display: none; }
  }
  .ev { margin: 0; padding: 10px 16px 14px; font: 500 12px/1.5 var(--mc-font); color: var(--mc-accent); border-top: 1px solid var(--mc-line-soft); }

  .loc { display: flex; flex-direction: column; gap: 14px; }
  .more { margin-top: 10px; margin-left: -8px; }

  /* side */
  .stg { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
  .mg-select.full { display: block; }
  .mg-select.full select { width: 100%; }
  .tk { margin-top: 10px; }
  .tasks { list-style: none; margin: 6px 0 10px; padding: 0; display: flex; flex-direction: column; gap: 6px; font: 400 13px/1.4 var(--mc-font); color: var(--mc-ink2); }
  .tasks li { display: flex; gap: 6px; align-items: center; }
  .full { width: 100%; justify-content: center; margin-top: 8px; }

  .tl { list-style: none; margin: 0; padding: 6px 0; max-height: 520px; overflow-y: auto; }
  .tl li { display: grid; grid-template-columns: 24px minmax(0, 1fr) auto; gap: 10px; align-items: start; padding: 8px 16px; font: 400 12.5px/1.45 var(--mc-font); color: var(--mc-ink2); }
  .ti { width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center; background: rgba(255, 255, 255, 0.06); color: var(--mc-ink3); }
  .tl li.ok .ti { background: var(--mc-ok-soft); color: var(--mc-accent); }
  .tt { padding-top: 3px; overflow-wrap: anywhere; text-transform: none; }
  .tw { padding-top: 3px; font-size: 11.5px; color: var(--mc-ink3); white-space: nowrap; }
</style>
