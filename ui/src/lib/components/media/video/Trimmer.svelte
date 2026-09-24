<script>
  /* The scrubber: a player over a filmstrip, with an in and an out handle.

     Used twice — trimming a clip on the timeline and marking sub-clips on a
     library clip — so it knows nothing about either. It plays the proxy
     stream (streamUrl falls back to the master when there is no proxy) and
     paints the strip from /api/video-edit/frame grabs, which the backend
     caches per tenth of a second.

     Touch: the handles are 40px wide hit areas around a 4px line; dragging
     the bare track scrubs. Keys (when the scrubber has focus): Space plays,
     I / O set the points, ←/→ step a frame (with Shift, a second). */
  import { untrack } from 'svelte';
  import { streamUrl } from '$lib/media.js';
  import { vapi, tc } from '$lib/media/video.js';
  import Icon from '$lib/components/glass/Icon.svelte';

  let {
    video,                 // { id, duration }
    inPt = 0,
    outPt = null,
    fps = 25,
    ranges = [],           // [{start, end, id}] drawn as bands (existing sub-clips)
    onchange,              // (inPt, outPt) => void
    compact = false
  } = $props();

  const dur = $derived(Math.max(0.1, Number(video?.duration) || 0.1));
  const outV = $derived(outPt == null ? dur : outPt);

  let el = $state(null);
  let track = $state(null);
  let t = $state(0);
  let paused = $state(true);
  let loopRange = $state(false);
  let trackW = $state(600);

  const src = $derived(video ? streamUrl(video) : '');
  const nFrames = $derived(Math.max(4, Math.min(14, Math.round(trackW / 80))));
  const frames = $derived(
    video ? Array.from({ length: nFrames }, (_, i) => vapi.frameUrl(video.id, ((i + 0.5) / nFrames) * dur, 160)) : []
  );

  const pct = (x) => `${(Math.max(0, Math.min(dur, x)) / dur) * 100}%`;

  $effect(() => {
    // new clip: park on its in point
    video?.id;
    el;
    untrack(() => {
      t = inPt || 0;
      if (el) el.currentTime = t;
    });
  });

  function seek(x) {
    t = Math.max(0, Math.min(dur, x));
    if (el) el.currentTime = t;
  }

  function onTime() {
    if (!el) return;
    t = el.currentTime;
    if (loopRange && !el.paused && t >= outV) {
      el.pause();
      el.currentTime = inPt;
      loopRange = false;
    }
  }

  function toggle() {
    if (!el) return;
    if (el.paused) el.play().catch(() => {});
    else el.pause();
  }

  function playRange() {
    if (!el) return;
    loopRange = true;
    el.currentTime = inPt;
    el.play().catch(() => {});
  }

  const step = (n) => seek(t + n / (fps || 25));

  function setIn(x = t) {
    let a = Math.max(0, Math.min(x, dur - 0.1));
    let b = outV;
    if (b - a < 0.1) b = Math.min(dur, a + 0.1);
    onchange?.(round(a), round(b));
  }
  function setOut(x = t) {
    let b = Math.max(0.1, Math.min(x, dur));
    let a = inPt;
    if (b - a < 0.1) a = Math.max(0, b - 0.1);
    onchange?.(round(a), round(b));
  }
  const round = (x) => Math.round(x * 1000) / 1000;

  /* ——— dragging: which thing is held ——— */
  let held = null;
  function xToT(clientX) {
    const r = track.getBoundingClientRect();
    return ((clientX - r.left) / Math.max(1, r.width)) * dur;
  }
  function down(e, what) {
    e.preventDefault();
    e.stopPropagation();
    held = what;
    track.setPointerCapture?.(e.pointerId);
    move(e);
  }
  function move(e) {
    if (!held) return;
    const x = xToT(e.clientX);
    if (held === 'in') { setIn(x); seek(Math.max(0, Math.min(x, outV - 0.1))); }
    else if (held === 'out') { setOut(x); seek(Math.max(inPt + 0.1, Math.min(x, dur))); }
    else seek(x);
  }
  function up() { held = null; }

  function key(e) {
    if (e.target.closest('input, select, textarea')) return;
    const k = e.key.toLowerCase();
    if (k === ' ') { e.preventDefault(); toggle(); }
    else if (k === 'i') { e.preventDefault(); setIn(); }
    else if (k === 'o') { e.preventDefault(); setOut(); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); step(e.shiftKey ? -(fps || 25) : -1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); step(e.shiftKey ? fps || 25 : 1); }
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div class="trim" class:compact tabindex="0" onkeydown={key} role="group" aria-label="Scrubber">
  <div class="screen">
    {#if src}
      <!-- svelte-ignore a11y_media_has_caption -->
      <video bind:this={el} {src} preload="metadata" playsinline
             ontimeupdate={onTime} onplay={() => (paused = false)} onpause={() => (paused = true)}
             onclick={toggle}></video>
    {/if}
  </div>

  <div class="strip" bind:this={track} bind:clientWidth={trackW}
       onpointerdown={(e) => down(e, 'scrub')} onpointermove={move} onpointerup={up} onpointercancel={up}
       role="slider" aria-label="Position" aria-valuemin="0" aria-valuemax={dur} aria-valuenow={t} tabindex="-1">
    <div class="frames">
      {#each frames as f, i (i + f)}
        <img src={f} alt="" loading="lazy" draggable="false" />
      {/each}
    </div>
    {#each ranges as r (r.id)}
      <span class="band" style:left={pct(r.start)} style:width="calc({pct(r.end)} - {pct(r.start)})"></span>
    {/each}
    <span class="shade" style:left="0" style:width={pct(inPt)}></span>
    <span class="shade" style:left={pct(outV)} style:right="0"></span>
    <span class="sel" style:left={pct(inPt)} style:width="calc({pct(outV)} - {pct(inPt)})"></span>
    <span class="head" style:left={pct(t)}></span>
    <button type="button" class="h in" style:left={pct(inPt)} aria-label="In point"
            onpointerdown={(e) => down(e, 'in')}><i></i></button>
    <button type="button" class="h out" style:left={pct(outV)} aria-label="Out point"
            onpointerdown={(e) => down(e, 'out')}><i></i></button>
  </div>

  <div class="bar">
    <button type="button" class="mg-btn secondary icon" onclick={toggle} aria-label={paused ? 'Play' : 'Pause'}>
      <Icon name={paused ? 'play' : 'stop'} size={15} />
    </button>
    <button type="button" class="mg-btn ghost icon" onclick={() => step(-1)} aria-label="Back one frame">
      <Icon name="chevronLeft" size={15} />
    </button>
    <span class="now mg-tnum">{tc(t)}</span>
    <button type="button" class="mg-btn ghost icon" onclick={() => step(1)} aria-label="Forward one frame">
      <Icon name="chevronRight" size={15} />
    </button>
    <span class="sp"></span>
    <button type="button" class="mg-btn secondary sm pt" onclick={() => setIn()} title="Set in (I)">
      In <b class="mg-tnum">{tc(inPt)}</b>
    </button>
    <button type="button" class="mg-btn secondary sm pt" onclick={() => setOut()} title="Set out (O)">
      Out <b class="mg-tnum">{tc(outV)}</b>
    </button>
    <button type="button" class="mg-btn ghost sm" onclick={playRange} title="Play from in to out">
      <Icon name="play" size={13} />Range <span class="mg-tnum">{(outV - inPt).toFixed(2)}s</span>
    </button>
  </div>
</div>

<style>
  .trim { display: flex; flex-direction: column; gap: 10px; outline: none; min-width: 0; }
  .trim:focus-visible { outline: 2px solid rgba(62, 207, 142, 0.5); outline-offset: 4px; border-radius: 14px; }
  .screen {
    background: var(--mg-term); border-radius: var(--mg-r-in); overflow: hidden;
    aspect-ratio: 16 / 9; max-height: 46vh; display: grid; place-items: center;
  }
  .compact .screen { max-height: 30vh; }
  video { width: 100%; height: 100%; object-fit: contain; display: block; background: #000; }

  .strip {
    position: relative; height: 56px; border-radius: 10px; overflow: visible;
    background: rgba(255, 255, 255, 0.05); touch-action: none; cursor: pointer; user-select: none;
    margin: 0 10px;
  }
  .frames { position: absolute; inset: 0; display: flex; overflow: hidden; border-radius: 10px; }
  .frames img { flex: 1 1 0; min-width: 0; height: 100%; object-fit: cover; pointer-events: none; opacity: 0.85; }
  .band { position: absolute; bottom: 0; height: 5px; background: var(--mg-mgr); opacity: 0.8; border-radius: 3px; pointer-events: none; }
  .shade { position: absolute; top: 0; bottom: 0; background: rgba(8, 8, 10, 0.62); pointer-events: none; }
  .sel {
    position: absolute; top: -2px; bottom: -2px; border: 2px solid var(--mg-ok);
    border-radius: 8px; pointer-events: none; box-sizing: border-box;
  }
  .head {
    position: absolute; top: -6px; bottom: -6px; width: 2px; margin-left: -1px;
    background: #fff; box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.4); pointer-events: none; border-radius: 2px;
  }
  .h {
    position: absolute; top: -4px; bottom: -4px; width: 40px; margin-left: -20px;
    border: 0; background: none; padding: 0; cursor: ew-resize; touch-action: none; z-index: 2;
    display: grid; place-items: center;
  }
  .h i { width: 10px; height: 100%; border-radius: 5px; background: var(--mg-ok); box-shadow: 0 2px 8px rgba(0, 0, 0, 0.5); }

  .bar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .bar .sp { flex: 1; }
  .now { font: 500 13px/1 var(--mg-mono); color: var(--mg-i); min-width: 64px; text-align: center; }
  .pt b { font: 500 12px/1 var(--mg-mono); color: var(--mg-ok); margin-left: 4px; }
  @media (max-width: 560px) {
    .bar .sp { flex-basis: 100%; height: 0; }
    .strip { height: 48px; }
  }
</style>
