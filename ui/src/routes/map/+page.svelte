<script>
  import { onMount, onDestroy } from 'svelte';
  import L from 'leaflet';
  import 'leaflet/dist/leaflet.css';
  import { api } from '$lib/api.js';
  import { fmtR, fmtM, fmtInt, mvLabel, satUrl } from '$lib/format.js';

  /* ——————————————————————————————————————————————————————— constants ——— */

  /* modern pin palette — tier fill, white stroke, blue highlight */
  const TIER_FILL = { hot: '#dc2626', warm: '#d97706', cold: '#9ca3af' };
  const PIN_LINE = 'rgba(255, 255, 255, 0.9)';
  const ACCENT = '#2563eb';                 /* hover / active highlight    */
  const PAGE = 160;                         /* list rows rendered per page */

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
    return {
      radius: radiusFor(p),
      color: PIN_LINE,
      weight: 1.5,
      opacity: approx ? 0.8 : 1,
      dashArray: approx ? '2 3' : null,
      fillColor: TIER_FILL[p.tier] || TIER_FILL.cold,
      fillOpacity: approx ? 0.35 : 0.85
    };
  }

  function paint(p, on) {
    const m = markers.get(p.gid);
    if (!m) return;
    if (on) {
      m.setStyle({ color: ACCENT, weight: 2.2, opacity: 1 });
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
               onerror="this.style.display='none';this.parentNode.classList.add('empty')"></div>`
          : ''}
        <div class="pop-body">
          <div class="pop-top">
            <span class="price">${esc(fmtR(p.price_zar))}</span>
            <span class="pop-score">${esc(Math.round(p.score || 0))}</span>
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
            <a href="${esc(p.url)}" target="_blank" rel="noopener">Listing ↗</a>
            <a href="${esc(satUrl(p.lat, p.lng))}" target="_blank" rel="noopener">Satellite</a>
            ${p.cma ? `<a href="/cma/${encodeURIComponent(p.gid)}">CMA report →</a>` : ''}
            <a href="/leads/properties/${encodeURIComponent(p.gid)}">Lead →</a>
          </div>
        </div>
      </div>`;
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
        minWidth: 250,
        autoPanPadding: [24, 24],
        closeButton: true
      });
      m.on('popupopen', () => (activeGid = p.gid));
      m.on('popupclose', () => {
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
      map.fitBounds(L.latLngBounds(pts.map((p) => [p.lat, p.lng])), {
        padding: [60, 60],
        maxZoom: 14
      });
    }
  }

  /* ——————————————————————————————————————————————————— list actions ——— */

  function focus(p) {
    if (!map) return;
    activeGid = p.gid;
    map.flyTo([p.lat, p.lng], Math.max(map.getZoom(), 16), { duration: 0.7 });
    const m = markers.get(p.gid);
    if (m) {
      m.bringToFront();
      m.openPopup();
    }
  }

  /* ————————————————————————————————————————————————————————— effects ——— */

  onMount(() => {
    map = L.map(mapEl, {
      zoomControl: false,
      preferCanvas: true,
      attributionControl: true,
      center: [-33.95, 18.6],
      zoom: 10
    });
    const dark = document.documentElement.dataset.theme === 'dark';
    L.tileLayer(`https://{s}.basemaps.cartocdn.com/${dark ? 'dark_all' : 'light_all'}/{z}/{x}/{y}{r}.png`, {
      attribution: '© OpenStreetMap © CARTO',
      maxZoom: 19,
      subdomains: 'abcd'
    }).addTo(map);
    L.control.zoom({ position: 'bottomright' }).addTo(map);
    load();
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

  /* reset paging when the result set changes shape */
  $effect(() => {
    filtered.length;
    limit = PAGE;
  });

  /* keep the map sized under the floating chrome */
  $effect(() => {
    panelOpen;
    if (map) setTimeout(() => map && map.invalidateSize(), 220);
  });
</script>

<svelte:head><title>Map · Oblivion</title></svelte:head>

<div class="map" bind:this={mapEl}></div>

{#if loading}<div class="sweep"></div>{/if}

<!-- ————————————————————————————————————————————————— top-left chrome — -->
<div class="chrome">
  <div class="bar sheet">
    <a class="back" href="/prospects">← Prospects</a>
    <div class="mark">
      <span class="dot"></span>
      <span class="word">Oblivion</span>
      <span class="kicker">Map</span>
    </div>
    <div class="count">
      {#if loading}
        <span class="spin"></span>
      {:else if errMsg}
        <span class="err">{errMsg}</span>
      {:else}
        {fmtInt(filtered.length)} of {fmtInt(points.length)} on the map{#if unmapped}<span class="dim"> · {fmtInt(unmapped)} without a location</span>{/if}
      {/if}
    </div>
    <button
      class="collapse"
      aria-label={panelOpen ? 'Hide filters' : 'Show filters'}
      onclick={() => (panelOpen = !panelOpen)}
    >{panelOpen ? '‹' : '›'}</button>
  </div>

  {#if panelOpen}
    <div class="panel-x sheet">
      <div class="filters">
        <input
          type="search"
          placeholder="Search title, suburb, agency…"
          value={q}
          oninput={(e) => (q = e.currentTarget.value)}
        />

        <div class="chips">
          {#each ['hot', 'warm', 'cold'] as t}
            <button
              class="tchip t-{t}"
              class:on={tiers[t]}
              onclick={() => (tiers = { ...tiers, [t]: !tiers[t] })}
            >
              {t}
              <span class="n">{fmtInt(tierCounts[t])}</span>
            </button>
          {/each}
        </div>

        <div class="row">
          <label class="fl">
            <span class="label">Mandate</span>
            <select value={mandate} onchange={(e) => (mandate = e.currentTarget.value)}>
              <option value="any">Any</option>
              <option value="open">Open</option>
              <option value="probably_open">Probably open</option>
              <option value="unknown">Unknown</option>
            </select>
          </label>
        </div>

        <div class="row">
          <label class="fl">
            <span class="label">Min (Rm)</span>
            <input
              type="number" step="0.5" min="0" placeholder="—"
              value={minM} oninput={(e) => (minM = e.currentTarget.value)}
            />
          </label>
          <label class="fl">
            <span class="label">Max (Rm)</span>
            <input
              type="number" step="0.5" min="0" placeholder="—"
              value={maxM} oninput={(e) => (maxM = e.currentTarget.value)}
            />
          </label>
        </div>

        <label class="sole">
          <input type="checkbox" checked={showSole} onchange={toggleSole} />
          <span>Include sole mandates</span>
        </label>
      </div>

      <div class="list">
        {#if !loading && filtered.length === 0}
          <div class="empty-list">
            {points.length ? 'Nothing matches these filters.' : 'Nothing on the map yet.'}
          </div>
        {/if}

        {#each listed as p (p.gid)}
          <button
            class="card"
            class:active={activeGid === p.gid}
            onmouseenter={() => paint(p, true)}
            onmouseleave={() => paint(p, activeGid === p.gid)}
            onfocus={() => paint(p, true)}
            onblur={() => paint(p, activeGid === p.gid)}
            onclick={() => focus(p)}
          >
            <div class="thumb" class:approx={p.loc === 'suburb'}>
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
                <span class="tier {p.tier}">{(p.tier || 'cold').toUpperCase()}</span>
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
          <button class="btn more" onclick={() => (limit += PAGE)}>
            Show more · {fmtInt(listed.length)} of {fmtInt(filtered.length)}
          </button>
        {/if}
      </div>
    </div>
  {/if}
</div>

<style>
  .map {
    position: fixed;
    inset: 0;
    background: var(--bg-4);
  }

  /* thin accent sweep while /api/map is in flight */
  .sweep {
    position: fixed;
    top: 0; left: 0; right: 0;
    height: 2px;
    z-index: 1300;
    overflow: hidden;
    pointer-events: none;
  }
  .sweep::after {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(90deg, transparent, var(--accent), transparent);
    transform: translateX(-100%);
    animation: sweep 1.15s cubic-bezier(0.4, 0, 0.3, 1) infinite;
  }
  @keyframes sweep { to { transform: translateX(100%); } }

  /* ————————————————————————————————————————————————— floating chrome — */
  .chrome {
    position: fixed;
    top: 1rem;
    left: 1rem;
    z-index: 1000;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    width: 360px;
    max-width: calc(100vw - 2rem);
    pointer-events: none;
  }
  .chrome > * { pointer-events: auto; }

  /* a white card floating over the map */
  .sheet {
    background: var(--bg-2);
    border: 1px solid var(--line);
    border-radius: 14px;
    box-shadow: var(--shadow-2);
  }

  .bar {
    display: grid;
    grid-template-columns: auto 1fr auto;
    grid-template-areas: 'back mark collapse' 'count count count';
    align-items: center;
    gap: 0.3rem 0.7rem;
    padding: 0.7rem 0.8rem 0.65rem;
  }
  .back {
    grid-area: back;
    font: 600 0.8rem/1.2 var(--font-ui);
    color: var(--ink-2);
    white-space: nowrap;
    transition: color 0.15s;
  }
  .back:hover { color: var(--accent); }

  .mark { grid-area: mark; display: flex; align-items: center; gap: 0.45rem; min-width: 0; }
  .dot {
    width: 10px; height: 10px; border-radius: 3px;
    background: var(--accent); flex: none;
  }
  .word {
    font-family: var(--font-ui);
    font-weight: 800;
    font-size: 0.95rem;
    letter-spacing: -0.01em;
    color: var(--ink);
  }
  .kicker {
    font: 500 0.78rem/1.2 var(--font-ui);
    color: var(--ink-3);
  }

  .collapse {
    grid-area: collapse;
    width: 30px; height: 30px;
    display: grid; place-items: center;
    border: 1px solid var(--line-2);
    border-radius: 50%;
    background: var(--bg-2);
    color: var(--ink-2);
    font-size: 0.9rem; line-height: 1;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
  }
  .collapse:hover {
    background: var(--accent-soft);
    border-color: var(--accent-line);
    color: var(--accent-2);
  }

  .count {
    grid-area: count;
    font: 400 0.74rem/1.3 var(--font-ui);
    color: var(--ink-3);
    font-variant-numeric: tabular-nums;
    display: flex; align-items: center; gap: 0.4rem;
    min-height: 1.1rem;
  }
  .count .dim { color: var(--ink-3); }
  .count .err { color: var(--bad); }

  /* ————————————————————————————————————————————————————— left panel — */
  .panel-x {
    display: flex;
    flex-direction: column;
    min-height: 0;
    max-height: calc(100vh - 2rem - 84px);
    overflow: hidden;
    animation: fadeup 0.18s ease both;
  }
  @keyframes fadeup { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

  .filters {
    display: flex;
    flex-direction: column;
    gap: 0.65rem;
    padding: 0.85rem 0.85rem 0.9rem;
    border-bottom: 1px solid var(--line);
    flex: 0 0 auto;
  }
  .filters :global(input[type='search']) { width: 100%; }

  /* tier toggles — modern segmented control */
  .chips {
    display: inline-flex;
    align-self: flex-start;
    background: var(--bg-2);
    border: 1px solid var(--line-2);
    border-radius: var(--r-sm);
    padding: 2px;
    gap: 2px;
  }
  .tchip {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    background: none;
    border: none;
    border-radius: 6px;
    padding: 0.36rem 0.7rem;
    font: 600 0.78rem/1.2 var(--font-ui);
    text-transform: capitalize;
    color: var(--ink-2);
    cursor: pointer;
    transition: color 0.15s, background 0.15s;
  }
  .tchip:hover { color: var(--ink); background: var(--bg-3); }
  .tchip .n {
    font-weight: 500;
    font-size: 0.7rem;
    font-variant-numeric: tabular-nums;
    color: var(--ink-3);
  }
  .tchip.on,
  .tchip.on:hover {
    background: var(--tbg);
    color: var(--tfg);
  }
  .tchip.on .n { color: inherit; opacity: 0.7; }
  .tchip.t-hot.on  { --tbg: #fee2e2; --tfg: #b91c1c; }
  .tchip.t-warm.on { --tbg: #fef3c7; --tfg: #92400e; }
  .tchip.t-cold.on { --tbg: #f3f4f6; --tfg: #4b5563; }

  .row { display: flex; gap: 0.7rem; }
  .fl { flex: 1; display: flex; flex-direction: column; gap: 0.28rem; min-width: 0; }
  .fl :global(select), .fl :global(input) { width: 100%; }
  .fl .label {
    font: 500 0.74rem/1.2 var(--font-ui);
    letter-spacing: 0;
    text-transform: none;
    color: var(--ink-2);
  }

  .sole {
    display: flex; align-items: center; gap: 0.5rem;
    font: 400 0.8rem/1.2 var(--font-ui);
    color: var(--ink-2); cursor: pointer;
    user-select: none;
  }
  .sole input { accent-color: var(--accent); width: 15px; height: 15px; cursor: pointer; }
  .sole:hover { color: var(--ink); }

  /* ————————————————————————————————————————————— result list — rows — */
  .list {
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: 0.5rem 0.5rem 0.6rem;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-height: 0;
  }
  .empty-list {
    padding: 1.8rem 0.4rem;
    text-align: center;
    font: 400 0.84rem/1.5 var(--font-ui);
    color: var(--ink-3);
  }

  .card {
    display: flex;
    gap: 0.65rem;
    align-items: stretch;
    text-align: left;
    width: 100%;
    padding: 0.5rem;
    border: 1px solid transparent;
    border-radius: var(--r-sm);
    background: var(--bg-2);
    transition: background 0.13s, border-color 0.13s;
  }
  .card:hover { background: var(--bg-3); }
  .card.active,
  .card.active:hover {
    background: var(--accent-soft);
    border-color: var(--accent-line);
  }

  .thumb {
    flex: 0 0 68px;
    width: 68px; height: 54px;
    border-radius: 6px;
    overflow: hidden;
    background: var(--bg-3);
    border: none;
    position: relative;
  }
  .thumb img {
    position: relative;
    z-index: 1;
    width: 100%; height: 100%;
    object-fit: cover;
    display: block;
    transition: transform 0.45s ease;
  }
  .card:hover .thumb img,
  .card.active .thumb img { transform: scale(1.03); }

  .card-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 0.2rem; }
  .card-top { display: flex; align-items: center; justify-content: space-between; gap: 0.4rem; }
  .card-top .price { font-size: 0.98rem; color: var(--ink); }
  .card-title {
    font: 500 0.82rem/1.3 var(--font-ui);
    color: var(--ink);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .card-meta {
    display: flex; align-items: center; gap: 0.55rem;
    font: 400 0.72rem/1.3 var(--font-ui);
    color: var(--ink-3);
    margin-top: auto;
    padding-top: 0.15rem;
    min-width: 0;
  }
  .card-meta .sub {
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    max-width: 45%;
    color: var(--ink-3);
  }

  .more { margin: 0.6rem 0.05rem 0.2rem; width: calc(100% - 0.1rem); }

  /* ————————————————————————————————————————————————————— narrow screens — */
  @media (max-width: 720px) {
    .chrome { width: calc(100vw - 2rem); }
    .panel-x { max-height: 55vh; }
  }

  /* ———————————————————————————————————————————— leaflet theme overrides — */
  :global(.leaflet-container) {
    background: var(--bg-4);
    font-family: var(--font-ui);
    outline: none;
  }
  :global(.leaflet-control-attribution) {
    background: var(--overlay) !important;
    color: var(--ink-3) !important;
    font-family: var(--font-ui) !important;
    font-size: 10px !important;
    border-radius: 8px 0 0 0 !important;
    border: none;
    padding: 2px 8px !important;
  }
  :global(.leaflet-control-attribution a) { color: var(--ink-2) !important; }

  :global(.leaflet-bar) {
    border: 1px solid var(--line) !important;
    border-radius: 10px !important;
    box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05), 0 4px 12px rgba(16, 24, 40, 0.1) !important;
    overflow: hidden;
  }
  :global(.leaflet-bar a) {
    background: var(--bg-2) !important;
    color: var(--ink-2) !important;
    border-radius: 0 !important;
    border-bottom-color: var(--line) !important;
  }
  :global(.leaflet-bar a:hover) {
    background: var(--bg-3) !important;
    color: var(--ink) !important;
  }

  /* ——————————————————————————————————————————————— popups — white card — */
  :global(.ob-pop .leaflet-popup-content-wrapper) {
    background: var(--bg-2);
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: 12px;
    box-shadow: 0 4px 10px rgba(16, 24, 40, 0.06), 0 12px 32px rgba(16, 24, 40, 0.12);
    padding: 0;
    overflow: hidden;
  }
  :global(.ob-pop .leaflet-popup-content) {
    margin: 0;
    width: auto !important;
    font: 400 13px/1.45 var(--font-ui);
  }
  :global(.ob-pop .leaflet-popup-tip) {
    background: var(--bg-2);
    border: 1px solid var(--line);
    box-shadow: none;
  }
  :global(.ob-pop .leaflet-popup-close-button) {
    color: var(--ink-3) !important;
    font-family: var(--font-ui) !important;
    padding: 7px 8px 0 0 !important;
  }
  :global(.ob-pop .leaflet-popup-close-button:hover) { color: var(--ink) !important; }

  :global(.pop-img) {
    height: 118px;
    background: var(--bg-3);
    border-radius: 12px 12px 0 0;
    overflow: hidden;
  }
  :global(.pop-img img) {
    width: 100%; height: 100%; object-fit: cover; display: block;
    transition: transform 0.45s ease;
  }
  :global(.ob-pop:hover .pop-img img) { transform: scale(1.015); }
  :global(.pop-img.empty) { display: none; }

  :global(.pop-body) { padding: 0.75rem 0.85rem 0.8rem; display: flex; flex-direction: column; gap: 0.45rem; }
  :global(.pop-top) {
    display: flex; align-items: center; justify-content: space-between; gap: 0.5rem;
  }
  :global(.pop-top .price) { font: 700 1.15rem/1.2 var(--font-ui); color: var(--ink); }
  :global(.pop-score) {
    font: 600 0.7rem/1 var(--font-ui);
    color: var(--ink-3);
    background: var(--bg-3);
    border-radius: 999px;
    padding: 0.22rem 0.5rem;
    font-variant-numeric: tabular-nums;
  }
  :global(a.pop-title) {
    color: var(--ink) !important;
    font-family: var(--font-ui);
    font-size: 0.9rem;
    font-weight: 600;
    line-height: 1.35;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  :global(a.pop-title:hover) { color: var(--accent) !important; }
  :global(.pop-meta) {
    font: 400 0.76rem/1.4 var(--font-ui);
    color: var(--ink-3);
  }
  :global(.pop-badges) { display: flex; flex-wrap: wrap; gap: 0.35rem 0.5rem; align-items: center; }
  :global(.pop-pitch) {
    font: 400 0.8rem/1.5 var(--font-ui);
    color: var(--ink-2);
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  :global(.pop-approx) {
    font: 400 0.72rem/1.4 var(--font-ui);
    color: var(--ink-3);
  }
  :global(.pop-links) {
    display: flex;
    flex-wrap: wrap;
    gap: 0.9rem;
    padding-top: 0.55rem;
    border-top: 1px solid var(--line);
    font: 600 0.78rem/1.2 var(--font-ui);
  }
  :global(.pop-links a) { color: var(--accent); }
  :global(.pop-links a:hover) { color: var(--accent-2); }
</style>
