<script>
  /* The map — every located prospect as a pin, on a dark basemap.

     The layout hands /map a fixed, non-scrolling pane (`.edge`) under the
     status strip. Everything here is absolute INSIDE that pane, and the whole
     page sits in one isolated stacking context (`.stage`) so Leaflet's own
     z-indices (panes at 400+, controls at 1000) can never climb over the
     phone dock, the chat panel or a sheet.

     Floating chrome, all solid raised planes (no blur over the map — the map
     has to keep 60fps while it pans):
       · the bar      search + the filters toggle + the count
       · the panel    tier chips, mandate, price band, sole switch, and the
                      result list (click a row → fly to the pin, open it)
       · the legend   what a pin's fill and ring mean
       · Leaflet's    zoom and attribution, re-dressed to the tokens
     On a phone the panel starts folded and folds itself again when you pick a
     row, so the popup it opens is not hidden behind it. */
  import { onMount, onDestroy } from 'svelte';
  import L from 'leaflet';
  import 'leaflet/dist/leaflet.css';
  import { api } from '$lib/api.js';
  import { fmtR, fmtM, fmtInt, mvLabel, satUrl } from '$lib/format.js';
  import { slide } from '$lib/motion.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';

  /* ——————————————————————————————————————————————————————— constants ——— */

  /* Pin colour is state: hot red, warm amber, cold neutral — the mc.css
     state hues (canvas needs literal colours, not variables). An open
     mandate gets a green ring; the pin you are looking at a white one. */
  const TIER_FILL = { hot: '#f26d64', warm: '#f0b429', cold: '#8b8b96' };
  const PIN_LINE = 'rgba(12, 12, 14, 0.85)';
  const OPEN_LINE = '#3ecf8e';
  const ACTIVE_LINE = '#f3f3f4';            /* hover / active highlight    */
  const PAGE = 160;                         /* list rows rendered per page */
  const TIERS = [
    ['hot', 'Hot', 'crit'],
    ['warm', 'Warm', 'warn'],
    ['cold', 'Cold', 'cold']
  ];

  /* ——————————————————————————————————————————————————————————— state ——— */

  let points     = $state([]);
  let unmapped   = $state(0);
  let loading    = $state(true);
  let errMsg     = $state('');

  let q          = $state('');
  let tiers      = $state({ hot: true, warm: true, cold: true });
  let mandate    = $state('any');
  let minM       = $state('');
  let maxM       = $state('');
  let showSole   = $state(false);
  let panelOpen  = $state(true);
  let limit      = $state(PAGE);
  let activeGid  = $state(null);
  let narrow     = $state(false);           /* phone: panel folds on pick  */

  /* non-reactive leaflet handles — deliberately plain, not $state */
  let mapEl;
  let map = null;
  let layer = null;
  let markers = new Map();                  /* gid -> circleMarker         */
  let didFit = false;

  /* ————————————————————————————————————————————————————————— helpers ——— */

  const esc = (v) =>
    String(v ?? '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

  const photoUrl = (key) => '/api/photo/' + encodeURIComponent(key) + '?fetch=0';

  const num = (v) => {
    const n = parseFloat(v);
    return Number.isFinite(n) ? n : null;
  };

  const hasPhoto = (p) => p.has_photo !== false && !!p.key;
  const isOpenMandate = (p) => p.verdict === 'open';

  /* ————————————————————————————————————————————————————————— derived ——— */

  /* everything except the tier chips — so the chips can show live counts */
  const base = $derived.by(() => {
    const needle = q.trim().toLowerCase();
    const lo = num(minM), hi = num(maxM);
    const loZ = lo == null ? null : lo * 1e6;
    const hiZ = hi == null ? null : hi * 1e6;

    return points.filter((p) => {
      if (p.lat == null || p.lng == null) return false;
      if (mandate !== 'any' && p.verdict !== mandate) return false;
      if (loZ != null && !(p.price_zar >= loZ)) return false;
      if (hiZ != null && !(p.price_zar <= hiZ)) return false;
      if (needle) {
        const hay = (
          (p.title || '') + ' ' +
          (p.suburb || '') + ' ' +
          (p.region || '') + ' ' +
          (p.agencies || []).join(' ')
        ).toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    });
  });

  const tierCounts = $derived.by(() => {
    const c = { hot: 0, warm: 0, cold: 0 };
    for (const p of base) if (c[p.tier] !== undefined) c[p.tier]++;
    return c;
  });

  const filtered = $derived(
    base
      .filter((p) => tiers[p.tier] !== false)
      .slice()
      .sort((a, b) => (b.score || 0) - (a.score || 0))
  );

  const maxScore = $derived(points.reduce((m, p) => Math.max(m, p.score || 0), 0));
  const listed = $derived(filtered.slice(0, limit));

  /* how many filters differ from the defaults — the badge on the toggle */
  const activeFilters = $derived(
    (mandate !== 'any' ? 1 : 0) +
    (num(minM) != null ? 1 : 0) +
    (num(maxM) != null ? 1 : 0) +
    (showSole ? 1 : 0) +
    (TIERS.some(([t]) => !tiers[t]) ? 1 : 0)
  );

  function clearFilters() {
    q = '';
    tiers = { hot: true, warm: true, cold: true };
    mandate = 'any';
    minM = '';
    maxM = '';
    if (showSole) toggleSole();
  }

  /* ——————————————————————————————————————————————————————— data load ——— */

  async function load() {
    loading = true;
    errMsg = '';
    try {
      const d = await api.mapPoints(showSole);
      points = (d && d.points) || [];
      unmapped = (d && d.unmapped) || 0;
    } catch (e) {
      errMsg = e?.message || 'Could not reach the engine';
      points = [];
      unmapped = 0;
    } finally {
      loading = false;
    }
  }

  function toggleSole() {
    showSole = !showSole;
    didFit = false;
    load();
  }

  /* ————————————————————————————————————————————————————— marker style ——— */

  function radiusFor(p) {
    const s = maxScore > 0 ? Math.min(1, Math.max(0, (p.score || 0) / maxScore)) : 0;
    return 5 + s * 4;
  }

  function baseStyle(p) {
    const approx = p.loc === 'suburb';
    const open = isOpenMandate(p);
    return {
      radius: radiusFor(p),
      color: open ? OPEN_LINE : PIN_LINE,
      weight: open ? 2 : 1.25,
      opacity: approx ? 0.8 : 1,
      dashArray: approx ? '2 3' : null,
      fillColor: TIER_FILL[p.tier] || TIER_FILL.cold,
      fillOpacity: approx ? 0.4 : 0.9
    };
  }

  function paint(p, on) {
    const m = markers.get(p.gid);
    if (!m) return;
    if (on) {
      m.setStyle({ color: ACTIVE_LINE, weight: 2.5, opacity: 1 });
      m.bringToFront();
    } else {
      m.setStyle(baseStyle(p));
    }
  }

  /* —————————————————————————————————————————————————————————— popups ——— */

  function popupHtml(p) {
    const sig = [];
    if (p.under_offer) sig.push('<span class="sig uo">under offer</span>');
    if (p.total_cut_pct > 0)
      sig.push(`<span class="sig cut">▼ ${esc(p.total_cut_pct)}% cut</span>`);
    if (p.relisted) sig.push('<span class="sig rel">relisted</span>');
    if (p.brand_count > 1)
      sig.push(`<span class="sig multi">${esc(p.brand_count)} agencies</span>`);
    if (p.days_on_market != null)
      sig.push(`<span class="sig trk">${esc(fmtInt(p.days_on_market))} days on market</span>`);
    if (p.price_vs_gv)
      sig.push(`<span class="sig">${esc(Number(p.price_vs_gv).toFixed(2))}× GV</span>`);

    const meta = [p.suburb, p.bedrooms ? p.bedrooms + ' bed' : null, p.property_type]
      .filter(Boolean)
      .map(esc)
      .join(' · ');

    return `
      <div class="pop">
        ${hasPhoto(p)
          ? `<div class="pop-img"><img src="${esc(photoUrl(p.key))}" alt=""
               onerror="this.parentNode.classList.add('empty')"></div>`
          : ''}
        <div class="pop-body">
          <div class="pop-top">
            <span class="price">${esc(fmtR(p.price_zar))}</span>
            <span class="pop-score" title="Prospect score">${esc(Math.round(p.score || 0))}</span>
          </div>
          <a class="pop-title" href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title || 'Untitled listing')}</a>
          ${meta ? `<div class="pop-meta">${meta}</div>` : ''}
          <div class="pop-badges">
            <span class="mv ${esc(p.verdict || 'unknown')}">${esc(mvLabel(p.verdict))}</span>
            <span class="tier ${esc(p.tier || 'cold')}">${esc((p.tier || 'cold').toUpperCase())}</span>
          </div>
          ${sig.length ? `<div class="pop-badges">${sig.join('')}</div>` : ''}
          ${p.pitch ? `<div class="pop-pitch">${esc(p.pitch)}</div>` : ''}
          ${p.loc === 'suburb'
            ? '<div class="pop-approx">Approximate — suburb level</div>'
            : ''}
          <div class="pop-links">
            <a class="mg-btn sm primary" href="/leads/properties/${encodeURIComponent(p.gid)}">Open lead</a>
            ${p.cma ? `<a class="mg-btn sm secondary" href="/cma/${encodeURIComponent(p.gid)}">CMA report</a>` : ''}
            <a class="mg-btn sm ghost" href="${esc(p.url)}" target="_blank" rel="noopener">Listing ↗</a>
            <a class="mg-btn sm ghost" href="${esc(satUrl(p.lat, p.lng))}" target="_blank" rel="noopener">Satellite ↗</a>
          </div>
        </div>
      </div>`;
  }

  /* Keep a popup clear of the floating chrome and the dock. Leaflet reads
     these arrays each time it auto-pans, so they are mutated in place as the
     panel opens and closes — no marker rebuild needed. */
  const PAD_TL = [16, 24];
  const PAD_BR = [16, 24];
  const CHROME_W = 360;
  function syncPad() {
    const beside = panelOpen && !narrow;
    PAD_TL[0] = beside ? CHROME_W + 32 : 16;
    PAD_TL[1] = narrow ? 150 : (beside ? 24 : 120);
    PAD_BR[1] = narrow ? 110 : 56;
  }

  /* —————————————————————————————————————————————————— marker rebuild ——— */

  function rebuild(pts) {
    if (!map) return;
    if (layer) layer.remove();
    markers = new Map();

    const list = [];
    for (const p of pts) {
      const m = L.circleMarker([p.lat, p.lng], baseStyle(p));
      m.bindPopup(() => popupHtml(p), {
        className: 'ob-pop',
        maxWidth: 300,
        minWidth: 260,
        autoPanPaddingTopLeft: PAD_TL,
        autoPanPaddingBottomRight: PAD_BR,
        closeButton: true
      });
      m.on('popupopen', () => {
        activeGid = p.gid;
        paint(p, true);
      });
      m.on('popupclose', () => {
        paint(p, false);
        if (activeGid === p.gid) activeGid = null;
      });
      markers.set(p.gid, m);
      list.push(m);
    }

    layer = L.layerGroup(list).addTo(map);

    const want = new URLSearchParams(location.search).get('focus');
    if (want && !didFit) {
      const hit = pts.find((p) => String(p.gid) === want);
      if (hit) { didFit = true; setTimeout(() => focus(hit), 50); }
    }
    if (!didFit && list.length) {
      didFit = true;
      map.fitBounds(L.latLngBounds(coreBounds(pts)), {
        padding: [60, 60],
        maxZoom: 14
      });
    }
  }

  /* The first fit frames where the book actually is: a handful of pins in
     Johannesburg or Durban must not zoom the Cape out to the whole country,
     so the 4th–96th percentile of latitude and longitude sets the frame. */
  function coreBounds(all) {
    if (all.length < 20) return all.map((p) => [p.lat, p.lng]);
    const q = (arr, f) => arr[Math.min(arr.length - 1, Math.max(0, Math.floor(arr.length * f)))];
    const lats = all.map((p) => p.lat).sort((a, b) => a - b);
    const lngs = all.map((p) => p.lng).sort((a, b) => a - b);
    const lat0 = q(lats, 0.04), lat1 = q(lats, 0.96), lng0 = q(lngs, 0.04), lng1 = q(lngs, 0.96);
    const core = all.filter((p) => p.lat >= lat0 && p.lat <= lat1 && p.lng >= lng0 && p.lng <= lng1);
    return (core.length ? core : all).map((p) => [p.lat, p.lng]);
  }

  /* ——————————————————————————————————————————————————— list actions ——— */

  function focus(p) {
    if (!map) return;
    activeGid = p.gid;
    /* on a phone the panel covers the map — fold it so the pin shows */
    if (narrow) panelOpen = false;
    /* land the pin right of the panel and low in the frame, so the popup
       that opens above it fits in the clear part of the map */
    const z = Math.max(map.getZoom(), 16);
    const size = map.getSize();
    const dx = panelOpen && !narrow ? (CHROME_W + 16) / 2 : 0;
    const dy = size.y * 0.22;
    const target = map.unproject(map.project([p.lat, p.lng], z).subtract([dx, dy]), z);
    map.flyTo(target, z, { duration: 0.7 });
    const m = markers.get(p.gid);
    if (m) {
      m.bringToFront();
      /* open once the flight lands, or the popup's auto-pan fights it */
      map.once('moveend', () => { if (activeGid === p.gid) m.openPopup(); });
    }
  }

  /* ————————————————————————————————————————————————————————— effects ——— */

  onMount(() => {
    const mq = matchMedia('(max-width: 719px)');
    narrow = mq.matches;
    panelOpen = !narrow;
    const syncNarrow = () => (narrow = mq.matches);
    mq.addEventListener('change', syncNarrow);

    const coarse = matchMedia('(pointer: coarse)').matches;
    map = L.map(mapEl, {
      zoomControl: false,
      preferCanvas: true,
      /* a fingertip needs a bigger hit area than a 5px pin */
      renderer: L.canvas({ padding: 0.5, tolerance: coarse ? 10 : 4 }),
      attributionControl: true,
      center: [-33.95, 18.6],
      zoom: 10
    });
    /* The app is always dark. Esri's keyless dark-grey canvas: a base layer
       and a separate label layer on top (CARTO's free tiles now answer with
       an "API key required" placeholder). Native tiles stop at z16; Leaflet
       upscales from there. */
    const esri = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/';
    L.tileLayer(esri + 'World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
      attribution: 'Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors',
      maxNativeZoom: 16,
      maxZoom: 19
    }).addTo(map);
    /* labels ride between the basemap and the pins */
    map.createPane('labels');
    map.getPane('labels').style.zIndex = 350;
    map.getPane('labels').style.pointerEvents = 'none';
    L.tileLayer(esri + 'World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
      maxNativeZoom: 16,
      maxZoom: 19,
      pane: 'labels'
    }).addTo(map);
    L.control.zoom({ position: 'bottomright' }).addTo(map);
    map.attributionControl.setPrefix(false);
    load();

    return () => mq.removeEventListener('change', syncNarrow);
  });

  onDestroy(() => {
    if (map) map.remove();
    map = null;
  });

  /* rebuild the single layer group whenever the filtered set changes */
  $effect(() => {
    const pts = filtered;
    if (map) rebuild(pts);
  });

  $effect(() => {
    panelOpen; narrow;
    syncPad();
  });

  /* reset paging when the result set changes shape */
  $effect(() => {
    filtered.length;
    limit = PAGE;
  });
</script>

<svelte:head><title>Map · Oblivion</title></svelte:head>

<div class="stage">
  <div class="map" bind:this={mapEl}></div>

  {#if loading}<div class="sweep" aria-hidden="true"></div>{/if}

  <!-- ———————————————————————————————————————————————— floating chrome — -->
  <div class="chrome" class:open={panelOpen}>
    <div class="bar mg-glass">
      <div class="barrow">
        <label class="mg-search find">
          <span class="ic"><Icon name="search" size={15} /></span>
          <input class="mg-input" type="search" placeholder="Search title, suburb, agency…"
                 aria-label="Search the map" value={q}
                 oninput={(e) => (q = e.currentTarget.value)} />
          {#if q}
            <button type="button" class="clear" aria-label="Clear search" onclick={() => (q = '')}>
              <Icon name="close" size={14} />
            </button>
          {/if}
        </label>
        <button type="button" class="mg-btn secondary icon toggle" class:on={panelOpen}
                aria-expanded={panelOpen}
                aria-label={panelOpen ? 'Hide filters' : 'Show filters'}
                title={panelOpen ? 'Hide filters and list' : 'Filters and list'}
                onclick={() => (panelOpen = !panelOpen)}>
          <Icon name={panelOpen ? 'chevronUp' : 'sliders'} size={16} />
          {#if activeFilters && !panelOpen}<i class="badge mg-tnum">{activeFilters}</i>{/if}
        </button>
      </div>
      <div class="count mg-tnum" aria-live="polite">
        {#if loading}
          <span class="mg-spin"></span><span>Loading pins…</span>
        {:else if errMsg}
          <span class="err">Map data unavailable</span>
        {:else}
          <span><b>{fmtInt(filtered.length)}</b> of {fmtInt(points.length)} on the map</span>
          {#if unmapped}<span class="dim">· {fmtInt(unmapped)} without a location</span>{/if}
        {/if}
      </div>
    </div>

    {#if panelOpen}
      <div class="panel mg-glass" transition:slide={{ y: -10, duration: 220 }}>
        <div class="filters">
          <div class="tiers" role="group" aria-label="Tiers">
            {#each TIERS as [t, label, tone] (t)}
              <button type="button" class="mg-chip tchip {tone}" class:off={!tiers[t]}
                      aria-pressed={tiers[t]}
                      onclick={() => (tiers = { ...tiers, [t]: !tiers[t] })}>
                <span class="dot"></span>{label}
                <span class="n mg-tnum">{fmtInt(tierCounts[t])}</span>
              </button>
            {/each}
          </div>

          <div class="row">
            <label class="fl wide">
              <span class="hud">Mandate</span>
              <span class="mg-select">
                <select value={mandate} onchange={(e) => (mandate = e.currentTarget.value)}>
                  <option value="any">Any</option>
                  <option value="open">Open</option>
                  <option value="probably_open">Probably open</option>
                  <option value="unknown">Unknown</option>
                </select>
                <span class="ic"><Icon name="chevronDown" size={14} /></span>
              </span>
            </label>
          </div>

          <div class="row">
            <label class="fl">
              <span class="hud">Min (Rm)</span>
              <input class="mg-input mg-tnum" type="number" inputmode="decimal" step="0.5" min="0"
                     placeholder="—" value={minM} oninput={(e) => (minM = e.currentTarget.value)} />
            </label>
            <label class="fl">
              <span class="hud">Max (Rm)</span>
              <input class="mg-input mg-tnum" type="number" inputmode="decimal" step="0.5" min="0"
                     placeholder="—" value={maxM} oninput={(e) => (maxM = e.currentTarget.value)} />
            </label>
          </div>

          <div class="swrow">
            <label class="sw">
              <input type="checkbox" checked={showSole} onchange={toggleSole} />
              <i aria-hidden="true"></i>
              <span>Include sole mandates</span>
            </label>
            {#if activeFilters || q}
              <button type="button" class="mg-btn ghost sm" onclick={clearFilters}>Clear</button>
            {/if}
          </div>
        </div>

        <div class="list">
          {#if errMsg}
            <div class="mg-strip crit">
              <span class="ic"><Icon name="alert" size={15} /></span>
              <div class="grow"><b>Could not load the map.</b> {errMsg}</div>
              <button type="button" class="mg-btn secondary sm" onclick={load}>Retry</button>
            </div>
          {:else if loading && !points.length}
            {#each [0, 1, 2, 3] as i (i)}
              <div class="card skel">
                <Skeleton h="54px" w="68px" r="8px" delay={i * 80} />
                <div class="grow"><Skeleton lines={3} delay={i * 80} /></div>
              </div>
            {/each}
          {:else if filtered.length === 0}
            <Empty icon="mapPin"
                   title={points.length ? 'Nothing matches' : 'Nothing on the map yet'}
                   hint={points.length
                     ? 'Loosen the filters or clear the search to see pins again.'
                     : 'Prospects appear here once a crawl has placed them.'}>
              {#if points.length}
                <button type="button" class="mg-btn secondary sm" onclick={clearFilters}>Clear filters</button>
              {/if}
            </Empty>
          {/if}

          {#each listed as p (p.gid)}
            <button
              type="button"
              class="card"
              class:active={activeGid === p.gid}
              onmouseenter={() => paint(p, true)}
              onmouseleave={() => paint(p, activeGid === p.gid)}
              onfocus={() => paint(p, true)}
              onblur={() => paint(p, activeGid === p.gid)}
              onclick={() => focus(p)}
            >
              <div class="thumb" class:approx={p.loc === 'suburb'}>
                <Icon name="image" size={16} />
                {#if hasPhoto(p)}
                  <img
                    src={photoUrl(p.key)}
                    alt=""
                    loading="lazy"
                    onerror={(e) => (e.currentTarget.style.display = 'none')}
                  />
                {/if}
              </div>
              <div class="card-body">
                <div class="card-top">
                  <span class="price">{fmtM(p.price_zar)}</span>
                  <span class="tier {p.tier || 'cold'}">{(p.tier || 'cold').toUpperCase()}</span>
                </div>
                <div class="card-title">{p.title || 'Untitled listing'}</div>
                <div class="card-meta">
                  <span class="sub">{p.suburb || p.region || '—'}</span>
                  <span class="mv {p.verdict || 'unknown'}">{mvLabel(p.verdict)}</span>
                </div>
              </div>
            </button>
          {/each}

          {#if filtered.length > listed.length}
            <button type="button" class="mg-btn secondary more" onclick={() => (limit += PAGE)}>
              Show more · <span class="mg-tnum">{fmtInt(listed.length)} of {fmtInt(filtered.length)}</span>
            </button>
          {/if}
        </div>
      </div>
    {/if}
  </div>

  <!-- ——————————————————————————————————————————————————————— legend — -->
  <div class="legend mg-raised" aria-label="Pin legend">
    <span><i class="pin hot"></i>Hot</span>
    <span><i class="pin warm"></i>Warm</span>
    <span><i class="pin cold"></i>Cold</span>
    <span><i class="pin ring"></i>Open</span>
  </div>
</div>

<style>
  /* One stacking context for the whole page, so nothing Leaflet does can
     paint over the dock, the strip or an overlay. */
  .stage {
    position: absolute; inset: 0; isolation: isolate; z-index: 0; overflow: hidden;
    --gap: 12px;
    /* the floor the floating chrome must stay above: the dock on a phone */
    --floor: calc(var(--mc-dock-h) + var(--sab) + 12px);
  }
  @media (min-width: 1024px) { .stage { --floor: 16px; --gap: 16px; } }

  .map { position: absolute; inset: 0; background: var(--mc-bg); }

  /* thin accent sweep while /api/map is in flight */
  .sweep {
    position: absolute; top: 0; left: 0; right: 0; height: 2px;
    z-index: 1200; overflow: hidden; pointer-events: none;
  }
  .sweep::after {
    content: ''; position: absolute; inset: 0;
    background: linear-gradient(90deg, transparent, var(--mc-accent), transparent);
    transform: translateX(-100%);
    animation: mg-sweep 1.15s var(--mc-ease) infinite;
  }

  /* ————————————————————————————————————————————————— floating chrome — */
  .chrome {
    position: absolute; z-index: 1100;
    top: var(--gap); left: var(--gap);
    width: 360px; max-width: calc(100% - 2 * var(--gap));
    /* the column never runs under the dock / off the pane */
    max-height: calc(100% - var(--gap) - var(--floor));
    display: flex; flex-direction: column; gap: 8px;
    pointer-events: none;
  }
  .chrome > * { pointer-events: auto; }

  .bar { padding: 10px; border-radius: var(--mc-r); flex: none; }
  .barrow { display: flex; align-items: center; gap: 8px; }
  .find { flex: 1; }
  .find :global(input[type='search']::-webkit-search-cancel-button) { display: none; }
  .toggle { position: relative; }
  .toggle.on { color: var(--mc-ink); border-color: var(--mc-line2); }
  .badge {
    position: absolute; top: -5px; right: -5px; min-width: 18px; height: 18px; padding: 0 5px;
    display: grid; place-items: center; border-radius: 9999px;
    background: var(--mc-accent); color: var(--mc-accent-ink);
    font: 700 10.5px/1 var(--mc-font); font-style: normal;
  }

  .count {
    display: flex; align-items: center; flex-wrap: wrap; gap: 4px 6px;
    padding: 8px 2px 0; min-height: 26px;
    font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3);
  }
  .count b { color: var(--mc-ink); font-weight: 600; }
  .count .err { color: var(--mc-crit); font-weight: 500; }
  .count .mg-spin { width: 12px; height: 12px; color: var(--mc-ink3); }

  /* ——————————————————————————————————————————————————— filter panel — */
  .panel {
    flex: 0 1 auto; min-height: 0;
    display: flex; flex-direction: column; overflow: hidden;
    border-radius: var(--mc-r);
    will-change: transform, opacity;
  }

  .filters {
    flex: none; display: flex; flex-direction: column; gap: 12px;
    padding: 12px; border-bottom: 1px solid var(--mc-line);
  }

  .tiers { display: flex; gap: 6px; flex-wrap: wrap; }
  .tchip { height: 34px; padding: 0 12px; }
  .tchip .n { color: inherit; opacity: 0.7; font-weight: 500; }
  .tchip.crit { background: var(--mc-crit-soft); border-color: var(--mc-crit-line); color: var(--mc-crit); }
  .tchip.warn { background: var(--mc-warn-soft); border-color: var(--mc-warn-line); color: var(--mc-warn); }
  .tchip.cold { background: rgba(255, 255, 255, 0.06); border-color: var(--mc-line2); color: var(--mc-ink); }
  .tchip.cold .dot { background: #8b8b96; }
  .tchip.off { background: var(--mc-raised); border-color: var(--mc-line); color: var(--mc-ink3); }
  .tchip.off .dot { background: transparent; box-shadow: inset 0 0 0 1.5px currentColor; }
  .tchip.off:hover { color: var(--mc-ink2); }

  .row { display: flex; gap: 10px; }
  .fl { flex: 1; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .fl .mg-select { display: block; width: 100%; }
  .fl input[type='number'] { -moz-appearance: textfield; appearance: textfield; }
  .fl input::-webkit-outer-spin-button, .fl input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }

  .swrow { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 36px; }

  /* switch — the same one the crawl sheet uses */
  .sw {
    display: inline-flex; align-items: center; gap: 10px; min-height: 36px; cursor: pointer;
    font: 500 13px/1.3 var(--mc-font); color: var(--mc-ink2); user-select: none; -webkit-user-select: none;
  }
  .sw:hover { color: var(--mc-ink); }
  .sw { position: relative; }
  .sw input { position: absolute; left: 0; top: 50%; margin: 0; opacity: 0; width: 1px; height: 1px; pointer-events: none; }
  .sw i {
    position: relative; flex: none; width: 36px; height: 22px; border-radius: 9999px;
    background: var(--mc-line2); transition: background var(--mc-t-fast);
  }
  .sw i::after {
    content: ''; position: absolute; top: 3px; left: 3px; width: 16px; height: 16px; border-radius: 50%;
    background: var(--mc-ink); transition: transform var(--mc-t) var(--mc-ease);
  }
  .sw input:checked + i { background: var(--mc-accent); }
  .sw input:checked + i::after { transform: translateX(14px); background: var(--mc-accent-ink); }
  .sw input:focus-visible + i { outline: 2px solid rgba(62, 207, 142, 0.7); outline-offset: 2px; }

  /* ————————————————————————————————————————————— result list — rows — */
  .list {
    flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain;
    padding: 6px; display: flex; flex-direction: column; gap: 2px;
  }
  .list :global(.mg-empty) { padding: 28px 12px; }
  .list .mg-strip { margin: 6px; align-items: center; }
  .grow { flex: 1; min-width: 0; }

  .card {
    flex: none; /* a row never shrinks: the title would collapse to 0px */
    display: flex; gap: 10px; align-items: stretch; text-align: left; width: 100%;
    padding: 8px; border: 1px solid transparent; border-radius: var(--mc-r-md);
    background: none; color: inherit; font: inherit; cursor: pointer;
    transition: background var(--mc-t-fast), border-color var(--mc-t-fast);
  }
  .card:hover { background: rgba(255, 255, 255, 0.04); }
  .card.active, .card.active:hover { background: var(--mc-ok-soft); border-color: var(--mc-ok-line); }
  .card.skel { cursor: default; }

  .thumb {
    flex: 0 0 68px; width: 68px; height: 54px; position: relative; overflow: hidden;
    display: grid; place-items: center;
    border-radius: var(--mc-r-sm); background: var(--mc-inset); border: 1px solid var(--mc-line);
    color: var(--mc-line3);
  }
  .thumb.approx { border-style: dashed; }
  .thumb img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; display: block; }

  .card-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .card-top { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
  .card-top .price { font-size: 14.5px; }
  .card-title {
    font: 500 12.5px/1.35 var(--mc-font); color: var(--mc-ink2);
    display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  }
  .card.active .card-title { color: var(--mc-ink); }
  .card-meta {
    display: flex; align-items: center; gap: 8px; min-width: 0; margin-top: auto; padding-top: 2px;
    font: 400 11.5px/1.3 var(--mc-font); color: var(--mc-ink3);
  }
  .card-meta .sub { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 50%; }

  .more { margin: 6px 2px 2px; width: calc(100% - 4px); }

  /* ———————————————————————————————————————————————————————— legend — */
  .legend {
    position: absolute; z-index: 1000;
    left: var(--gap); bottom: var(--floor);
    display: flex; align-items: center; gap: 12px; height: 34px; padding: 0 12px;
    border-radius: 9999px;
    font: 500 11.5px/1 var(--mc-font); color: var(--mc-ink2);
    pointer-events: none;
    /* small and on the map's floor: dark fill, no blur (the budget) */
    background: rgba(14, 14, 18, 0.8); -webkit-backdrop-filter: none; backdrop-filter: none; box-shadow: var(--mc-sh-1);
  }
  .legend span { display: inline-flex; align-items: center; gap: 6px; }
  .pin { width: 10px; height: 10px; border-radius: 50%; flex: none; box-shadow: inset 0 0 0 1px rgba(12, 12, 14, 0.85); }
  .pin.hot { background: #f26d64; }
  .pin.warm { background: #f0b429; }
  .pin.cold { background: #8b8b96; }
  .pin.ring { background: transparent; box-shadow: inset 0 0 0 2px var(--mc-accent); }
  /* with the panel open on a desktop the legend moves out from under it */
  @media (min-width: 720px) {
    .chrome.open ~ .legend { left: calc(var(--gap) + 360px + 12px); }
  }
  /* on a phone the open panel covers the lower map anyway */
  @media (max-width: 719px) {
    .chrome.open ~ .legend { opacity: 0; }
    .legend { transition: opacity var(--mc-t-fast); }
  }

  /* ————————————————————————————————————————————————————— touch sizes — */
  @media (pointer: coarse) {
    .tchip { height: 44px; padding: 0 14px; }
    .card { min-height: 72px; }
    .sw { min-height: 44px; }
    .find :global(.mg-input), .fl .mg-input, .fl .mg-select > select { height: 44px; }
    .toggle { width: 44px; height: 44px; }
    .list .mg-btn.sm, .swrow .mg-btn.sm { height: 40px; }
  }

  /* ———————————————————————————————————————————— leaflet theme overrides — */
  .stage :global(.leaflet-container) {
    background: var(--mc-bg); font-family: var(--mc-font); outline: none;
  }
  /* controls clear the phone dock and the rail's gutter */
  .stage :global(.leaflet-bottom) { bottom: calc(var(--floor) - 12px); }
  .stage :global(.leaflet-right .leaflet-control) { margin-right: var(--gap); }
  .stage :global(.leaflet-bottom .leaflet-control) { margin-bottom: 12px; }

  .stage :global(.leaflet-control-attribution) {
    background: rgba(12, 12, 14, 0.72);
    color: var(--mc-ink3);
    font: 400 10px/1.5 var(--mc-font);
    border-radius: 8px;
    padding: 1px 8px;
    margin-bottom: 0 !important;
  }
  .stage :global(.leaflet-bottom .leaflet-control-attribution) { margin-bottom: 0; }
  .stage :global(.leaflet-control-attribution a) { color: var(--mc-ink2); }

  .stage :global(.leaflet-control-zoom.leaflet-bar) {
    border: 1px solid var(--mc-glass-line);
    border-radius: var(--mc-r-md);
    background: var(--mc-glass-strong);
    box-shadow: var(--mc-sh-2);
    -webkit-backdrop-filter: blur(16px) saturate(150%); backdrop-filter: blur(16px) saturate(150%);
    overflow: hidden;
  }
  .stage :global(.leaflet-control-zoom a) {
    width: 40px; height: 40px; line-height: 40px;
    background: transparent;
    color: var(--mc-ink2);
    font: 400 20px/40px var(--mc-font);
    border-radius: 0;
    border-bottom: 1px solid var(--mc-line);
    transition: background var(--mc-t-fast), color var(--mc-t-fast);
  }
  .stage :global(.leaflet-control-zoom a:last-child) { border-bottom: 0; }
  .stage :global(.leaflet-control-zoom a:hover) { background: rgba(255, 255, 255, 0.1); color: var(--mc-ink); }
  .stage :global(.leaflet-control-zoom a.leaflet-disabled) { background: transparent; color: var(--mc-line3); }
  @media (pointer: coarse) {
    .stage :global(.leaflet-control-zoom a) { width: 44px; height: 44px; line-height: 44px; }
  }

  /* ————————————————————————————————————————————— popups — raised card — */
  .stage :global(.ob-pop .leaflet-popup-content-wrapper) {
    background: var(--mc-glass-strong);
    color: var(--mc-ink);
    border: 1px solid var(--mc-glass-line);
    border-radius: var(--mc-r);
    box-shadow: var(--mc-sh-2), var(--mc-lit);
    -webkit-backdrop-filter: blur(var(--mc-blur)) saturate(150%); backdrop-filter: blur(var(--mc-blur)) saturate(150%);
    padding: 0;
    overflow: hidden;
  }
  .stage :global(.ob-pop .leaflet-popup-content) {
    margin: 0; width: auto !important; min-width: 260px;
    font: 400 13px/1.45 var(--mc-font); color: var(--mc-ink);
  }
  .stage :global(.ob-pop .leaflet-popup-content p) { margin: 0; }
  .stage :global(.ob-pop .leaflet-popup-tip) {
    background: rgba(14, 14, 18, 0.92);
    border: 1px solid var(--mc-glass-line);
    box-shadow: none;
  }
  .stage :global(.ob-pop .leaflet-popup-close-button) {
    top: 8px; right: 8px; width: 32px; height: 32px;
    display: grid; place-items: center; z-index: 2;
    border-radius: 9999px;
    background: rgba(12, 12, 14, 0.72);
    color: var(--mc-ink2);
    font: 400 18px/1 var(--mc-font);
    transition: background var(--mc-t-fast), color var(--mc-t-fast);
  }
  .stage :global(.ob-pop .leaflet-popup-close-button span) { line-height: 1; }
  .stage :global(.ob-pop .leaflet-popup-close-button:hover) { background: var(--mc-inset); color: var(--mc-ink); }

  .stage :global(.pop-img) {
    height: 128px; background: var(--mc-inset); border-bottom: 1px solid var(--mc-line); overflow: hidden;
  }
  .stage :global(.pop-img img) { width: 100%; height: 100%; object-fit: cover; display: block; }
  .stage :global(.pop-img.empty) { display: none; }

  .stage :global(.pop-body) { padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 8px; }
  /* without a photo the close button sits over the price row — leave it room */
  .stage :global(.pop > .pop-body:first-child .pop-top) { padding-right: 36px; }
  .stage :global(.pop-top) { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .stage :global(.pop-top .price) { font: 650 18px/1.2 var(--mc-font); letter-spacing: -0.015em; color: var(--mc-ink); }
  .stage :global(.pop-score) {
    font: 600 11px/1 var(--mc-font); font-variant-numeric: tabular-nums;
    color: var(--mc-ink2); background: var(--mc-inset); border: 1px solid var(--mc-line);
    border-radius: 9999px; padding: 4px 8px;
  }
  .stage :global(a.pop-title) {
    color: var(--mc-ink); font: 600 14px/1.35 var(--mc-font);
    display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  }
  .stage :global(a.pop-title:hover) { color: var(--mc-accent-bright); }
  .stage :global(.pop-meta) { font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); }
  .stage :global(.pop-badges) { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .stage :global(.pop-pitch) {
    font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink2);
    display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
  }
  .stage :global(.pop-approx) { font: 400 11.5px/1.4 var(--mc-font); color: var(--mc-warn); }
  .stage :global(.pop-links) {
    display: flex; flex-wrap: wrap; gap: 6px;
    margin-top: 2px; padding-top: 10px; border-top: 1px solid var(--mc-line);
  }
  .stage :global(.pop-links .mg-btn.primary) { color: var(--mc-bg); }
  .stage :global(.pop-links .mg-btn.ghost) { padding: 0 8px; }
  @media (pointer: coarse) {
    .stage :global(.pop-links .mg-btn) { height: 40px; }
    .stage :global(.ob-pop .leaflet-popup-close-button) { width: 40px; height: 40px; top: 6px; right: 6px; }
  }
</style>
