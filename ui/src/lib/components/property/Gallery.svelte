<script>
  /* The property page's hero: every photo the data has.

     Wide (≥ 760px): one big frame and a 2×2 of the next four, the last one
     carrying "+N" when there are more. Narrow: a full-bleed scroll-snap
     carousel with a counter. Either opens the lightbox — a plain dark layer
     over everything (no blur: it is not glass, and the blur budget's one
     sheet may be open behind it), arrows / swipe / Esc.

     `photos` are absolute portal URLs ([{url, source}]); until they land (or
     when there are none) the row's own hero stands in via <Photo>. A URL
     that fails to load drops out of the set quietly. */
  import Photo from '../Photo.svelte';
  import Icon from '../glass/Icon.svelte';
  import { holdModal } from '$lib/shell.svelte.js';
  import { tick } from 'svelte';

  let { r, photos = null, alt = '' } = $props();

  let broken = $state(new Set());
  const list = $derived((photos || []).filter((p) => !broken.has(p.url)));
  const drop = (url) => { broken = new Set([...broken, url]); };

  /* ---- the narrow carousel's counter */
  let strip = $state(null);
  let at = $state(0);
  function onScroll() {
    if (!strip) return;
    at = Math.round(strip.scrollLeft / Math.max(1, strip.clientWidth));
  }

  /* ---- lightbox */
  let open = $state(-1);
  let box = $state(null);
  let track = $state(null);
  function show(i) {
    open = i;
    tick().then(() => {
      box?.focus({ preventScroll: true });
      if (track) track.scrollLeft = i * track.clientWidth;
    });
  }
  const close = () => (open = -1);
  function go(d) {
    if (!track) return;
    const n = list.length;
    const i = (open + d + n) % n;
    open = i;
    track.scrollTo({ left: i * track.clientWidth, behavior: Math.abs(d) === 1 && i !== 0 && i !== n - 1 ? 'smooth' : 'auto' });
  }
  function onTrack() {
    if (!track) return;
    open = Math.round(track.scrollLeft / Math.max(1, track.clientWidth));
  }
  function onKey(e) {
    if (e.key === 'Escape') { e.stopPropagation(); close(); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); go(1); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); go(-1); }
  }
  $effect(() => {
    if (open < 0) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const release = holdModal();
    return () => { document.body.style.overflow = prev; release(); };
  });

  function portal(node) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }

  const side = $derived(list.slice(1, 5));
  const more = $derived(Math.max(0, list.length - 5));
</script>

{#if list.length}
  <div class="gal" class:solo={list.length === 1} data-gallery={list.length}>
    <!-- wide: a mosaic -->
    <div class="mosaic">
      <button type="button" class="tile main" onclick={() => show(0)} aria-label="Open photo 1 of {list.length}">
        <img src={list[0].url} {alt} loading="eager" decoding="async" onerror={() => drop(list[0].url)} />
      </button>
      {#if side.length}
        <div class="side" class:n1={side.length === 1} class:n2={side.length === 2} class:n3={side.length === 3}>
          {#each side as p, i (p.url)}
            <button type="button" class="tile" onclick={() => show(i + 1)} aria-label="Open photo {i + 2} of {list.length}">
              <img src={p.url} alt="" loading="lazy" decoding="async" onerror={() => drop(p.url)} />
              {#if i === side.length - 1 && more}<span class="more"><Icon name="image" size={16} /> +{more}</span>{/if}
            </button>
          {/each}
        </div>
      {/if}
    </div>

    <!-- narrow: a swipeable strip -->
    <div class="strip mg-noscroll" bind:this={strip} onscroll={onScroll}>
      {#each list as p, i (p.url)}
        <button type="button" class="slide" onclick={() => show(i)} aria-label="Open photo {i + 1} of {list.length}">
          <img src={p.url} alt={i === 0 ? alt : ''} loading={i < 2 ? 'eager' : 'lazy'} decoding="async" onerror={() => drop(p.url)} />
        </button>
      {/each}
    </div>
    {#if list.length > 1}
      <span class="count mg-tnum"><Icon name="image" size={13} /> {at + 1} / {list.length}</span>
    {/if}
    <button type="button" class="all mg-btn sm secondary" onclick={() => show(0)}>
      <Icon name="grid" size={14} /> {list.length === 1 ? 'View photo' : `All ${list.length} photos`}
    </button>
  </div>
{:else if photos !== null && r.has_photo === false}
  <!-- nothing to show: a slim band, not a big empty frame -->
  <div class="gal none" data-gallery="0">
    <Icon name="image" size={18} /><span>No photos published for this listing</span>
  </div>
{:else}
  <div class="gal fallback">
    <Photo {r} eager {alt} />
    {#if photos === null}<span class="loading hud">Loading photos…</span>{/if}
  </div>
{/if}

{#if open >= 0 && list.length}
  <div class="mg-portal lb" use:portal role="dialog" aria-modal="true" aria-label="Photos" tabindex="-1"
       bind:this={box} onkeydown={onKey}>
    <div class="lbtop">
      <span class="mg-tnum lbn">{open + 1} / {list.length}{list[open]?.source ? ` · ${list[open].source}` : ''}</span>
      <button type="button" class="mg-btn secondary icon" onclick={close} aria-label="Close photos" title="Close (Esc)"><Icon name="close" size={16} /></button>
    </div>
    <div class="lbtrack mg-noscroll" bind:this={track} onscroll={onTrack}>
      {#each list as p, i (p.url)}
        <div class="lbslide"><img src={p.url} alt="" loading={Math.abs(i - open) < 2 ? 'eager' : 'lazy'} decoding="async" /></div>
      {/each}
    </div>
    {#if list.length > 1}
      <button type="button" class="nav prev mg-btn secondary icon" onclick={() => go(-1)} aria-label="Previous photo"><Icon name="chevronLeft" size={18} /></button>
      <button type="button" class="nav next mg-btn secondary icon" onclick={() => go(1)} aria-label="Next photo"><Icon name="chevronRight" size={18} /></button>
    {/if}
  </div>
{/if}

<style>
  .gal { position: relative; border-radius: var(--mc-r); overflow: hidden; background: var(--mc-inset); border: 1px solid var(--mc-glass-line); }
  button.tile, button.slide { all: unset; display: block; cursor: zoom-in; position: relative; overflow: hidden; background: var(--mc-inset); }
  button.tile:focus-visible, button.slide:focus-visible { outline: 2px solid var(--mc-accent); outline-offset: -2px; }
  img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .tile img { transition: transform 600ms var(--mc-ease); }
  @media (hover: hover) { .tile:hover img { transform: scale(1.025); } }

  /* ——— wide: mosaic ——— */
  .mosaic { display: none; }
  .strip { display: flex; overflow-x: auto; scroll-snap-type: x mandatory; aspect-ratio: 4 / 3; }
  /* after `all: unset` above, so the button keeps its slide geometry */
  button.slide { flex: 0 0 100%; width: 100%; scroll-snap-align: center; scroll-snap-stop: always; height: 100%; }

  @media (min-width: 760px) {
    .strip { display: none; }
    .count { display: none; }
    .mosaic { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); gap: 4px; height: clamp(300px, 38vw, 460px); }
    .solo .mosaic { grid-template-columns: 1fr; }
    .side { display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; gap: 4px; min-height: 0; }
    .side.n1 { grid-template-columns: 1fr; grid-template-rows: 1fr; }
    .side.n2 { grid-template-columns: 1fr; }
    .side.n3 > :first-child { grid-row: span 2; }
    button.tile { min-height: 0; height: 100%; }
  }
  .more {
    position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; gap: 6px;
    background: rgba(8, 8, 10, 0.55); color: #fff; font: 600 15px/1 var(--mc-font);
  }
  .count {
    position: absolute; left: 12px; bottom: 12px; display: inline-flex; align-items: center; gap: 6px;
    height: 26px; padding: 0 10px; border-radius: 9999px; background: rgba(8, 8, 10, 0.62);
    color: #fff; font: 500 12px/1 var(--mc-font); pointer-events: none;
  }
  .all { position: absolute; right: 12px; bottom: 12px; background: rgba(8, 8, 10, 0.62); border-color: rgba(255, 255, 255, 0.18); }
  .all:hover { background: rgba(8, 8, 10, 0.78); }

  .fallback { aspect-ratio: 16 / 7; }
  @media (max-width: 759px) { .fallback { aspect-ratio: 4 / 3; } }
  .none { display: flex; align-items: center; justify-content: center; gap: 10px; height: 96px; color: var(--mc-ink3); font: 500 13px/1 var(--mc-font); }
  .loading { position: absolute; left: 12px; bottom: 12px; }

  /* ——— lightbox: opaque, never blurred ——— */
  .lb { position: fixed; inset: 0; z-index: 95; background: rgba(4, 4, 6, 0.96); display: flex; flex-direction: column; outline: none; }
  .lbtop { flex: none; display: flex; align-items: center; justify-content: space-between; padding: calc(10px + var(--sat, 0px)) 16px 10px; }
  .lbn { font: 500 13px/1 var(--mc-font); color: var(--mc-ink2); text-transform: capitalize; }
  .lbtrack { flex: 1; min-height: 0; display: flex; overflow-x: auto; scroll-snap-type: x mandatory; }
  .lbslide { flex: 0 0 100%; scroll-snap-align: center; display: grid; place-items: center; padding: 0 0 calc(16px + env(safe-area-inset-bottom, 0px)); }
  .lbslide img { width: auto; height: auto; max-width: 100%; max-height: 100%; object-fit: contain; }
  .nav { position: absolute; top: 50%; transform: translateY(-50%); width: 44px; height: 44px; background: rgba(20, 20, 24, 0.7); }
  .prev { left: 16px; } .next { right: 16px; }
  @media (max-width: 759px) { .nav { display: none; } }
</style>
