<script>
  /* A small map of where the property is: the erf outline when the cadastre
     resolved one (GET /api/property/<key>/parcel), else a pin — marked
     approximate when it is only the portal's (often fuzzed) point.

     Leaflet is imported on mount so the property page's first paint never
     waits for it. Satellite by default (a property is judged from above),
     the map page's dark canvas one tap away. The page scrolls over it, so on
     touch it does not grab one-finger drags or the wheel. */
  import { onMount } from 'svelte';
  import { propertyApi } from '$lib/api.js';
  import Icon from '../glass/Icon.svelte';

  let { lat, lng, loc = null, listingKey, erfNumber = null } = $props();

  let el = $state(null);
  let mode = $state('sat');
  let parcel = $state(null);   // null = not asked / none
  let failed = $state(false);
  let map = null;
  let L = null;
  let layers = {};

  const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/';

  onMount(() => {
    let dead = false;
    (async () => {
      try {
        L = (await import('leaflet')).default;
        await import('leaflet/dist/leaflet.css');
      } catch { failed = true; return; }
      if (dead || !el) return;
      const coarse = matchMedia('(pointer: coarse)').matches;
      map = L.map(el, {
        zoomControl: false, attributionControl: true, scrollWheelZoom: false,
        dragging: !coarse,
        center: [lat, lng], zoom: loc === 'erf' ? 18 : 16
      });
      map.attributionControl.setPrefix(false);
      layers.sat = L.tileLayer(ESRI + 'World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Imagery © Esri', maxNativeZoom: 17, maxZoom: 20
      });
      layers.dark = L.tileLayer(ESRI + 'Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles © Esri', maxNativeZoom: 16, maxZoom: 20
      });
      map.createPane('labels');
      map.getPane('labels').style.zIndex = 350;
      map.getPane('labels').style.pointerEvents = 'none';
      layers.labels = L.tileLayer(ESRI + 'Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', {
        maxNativeZoom: 17, maxZoom: 20, pane: 'labels'
      });
      layers.darkLabels = L.tileLayer(ESRI + 'Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
        maxNativeZoom: 16, maxZoom: 20, pane: 'labels'
      });
      setMode(mode);
      L.control.zoom({ position: 'bottomright' }).addTo(map);

      if (loc === 'erf') {
        try {
          const p = await propertyApi.parcel(listingKey);
          if (!dead && p?.rings?.length) {
            parcel = p;
            const poly = L.polygon(p.rings, {
              color: '#3ecf8e', weight: 2.5, fillColor: '#3ecf8e', fillOpacity: 0.16
            }).addTo(map);
            map.fitBounds(poly.getBounds(), { padding: [36, 36], maxZoom: 18 });
            return;
          }
        } catch { /* a pin will do */ }
      }
      if (dead) return;
      L.circleMarker([lat, lng], {
        radius: loc === 'suburb' ? 18 : 8, color: '#fff', weight: 2,
        fillColor: loc === 'erf' ? '#3ecf8e' : '#f0b429', fillOpacity: loc === 'suburb' ? 0.25 : 0.9
      }).addTo(map);
    })();
    return () => { dead = true; map?.remove(); map = null; };
  });

  function setMode(m) {
    mode = m;
    if (!map) return;
    for (const k of ['sat', 'labels', 'dark', 'darkLabels']) layers[k]?.remove();
    if (m === 'sat') { layers.sat.addTo(map); layers.labels.addTo(map); }
    else { layers.dark.addTo(map); layers.darkLabels.addTo(map); }
  }

  const gmaps = $derived(`https://www.google.com/maps/search/?api=1&query=${lat},${lng}`);
  const where = $derived(
    loc === 'erf' ? (parcel ? `Erf ${parcel.erf || erfNumber || ''} · cadastre outline` : `Erf ${erfNumber || ''} · parcel centre`)
      : loc === 'listing' ? 'Portal pin · approximate' : 'Suburb · approximate');
</script>

<div class="pm">
  <div class="map" bind:this={el} aria-label="Map of the property"></div>
  {#if failed}<div class="fail mg-hint">Map could not load.</div>{/if}
  <div class="bar">
    <span class="where"><span class="mg-dot" class:ok={loc === 'erf'} class:warn={loc !== 'erf'}></span>{where}</span>
    <div class="seg" role="group" aria-label="Map style">
      <button type="button" class:on={mode === 'sat'} onclick={() => setMode('sat')}>Satellite</button>
      <button type="button" class:on={mode === 'map'} onclick={() => setMode('map')}>Map</button>
    </div>
  </div>
  <div class="links">
    <a class="mg-btn sm ghost" href={gmaps} target="_blank" rel="noopener"><Icon name="mapPin" size={14} /> Google Maps <Icon name="external" size={12} /></a>
  </div>
</div>

<style>
  .pm { position: relative; }
  .map { height: 300px; border-radius: var(--mc-r-md); overflow: hidden; background: var(--mc-inset); border: 1px solid var(--mc-glass-line); }
  @media (max-width: 639px) { .map { height: 240px; } }
  .fail { position: absolute; inset: 0; display: grid; place-items: center; }
  .bar { position: absolute; top: 10px; left: 10px; right: 10px; z-index: 500; display: flex; justify-content: space-between; gap: 8px; pointer-events: none; }
  .where, .seg { pointer-events: auto; background: rgba(8, 8, 10, 0.72); border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 9999px; }
  .where { display: inline-flex; align-items: center; gap: 8px; height: 28px; padding: 0 12px; font: 500 12px/1 var(--mc-font); color: var(--mc-ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  .mg-dot.ok { background: var(--mc-accent); } .mg-dot.warn { background: var(--mc-warn); }
  .seg { display: inline-flex; padding: 2px; flex: none; }
  .seg button { all: unset; cursor: pointer; height: 24px; padding: 0 10px; border-radius: 9999px; font: 500 12px/24px var(--mc-font); color: var(--mc-ink2); }
  .seg button.on { background: rgba(255, 255, 255, 0.16); color: var(--mc-ink); }
  .links { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
  .map :global(.leaflet-control-attribution) { background: rgba(8, 8, 10, 0.6); color: var(--mc-ink3); font-size: 10px; }
  .map :global(.leaflet-control-attribution a) { color: var(--mc-ink2); }
  .map :global(.leaflet-bar a) { background: rgba(20, 20, 24, 0.85); color: var(--mc-ink); border-color: rgba(255, 255, 255, 0.12); }
</style>
