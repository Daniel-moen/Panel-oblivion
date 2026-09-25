<script>
  /* The editor's picture.

     The server renders every change (see photoedit.js); this component only
     double-buffers: a new URL is loaded off-screen and swapped in when it has
     arrived, so dragging a slider never blanks the photo. The frame is sized
     explicitly from the stage and the image's own shape, so the overlays —
     crop box, brush, click target — sit on exactly the pixels you see and can
     report where you pointed as 0..1 of the displayed frame.

     Modes:
       view   nothing to do but look
       crop   a crop box with corner handles; `crop` is bindable ([x, y, w, h])
       brush  paint a stroke; onstroke(points, radius) on release, both 0..1
              of the displayed frame (radius as a fraction of its width)
       point  a click target: onpoint(u, v) */
  import Empty from '$lib/components/glass/Empty.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import { play, fadeIn } from '$lib/motion.js';

  let {
    src, before = null, showBefore = false, busy = false,
    mode = 'view', crop = $bindable([0, 0, 1, 1]), cropAspect = 0,
    brush = 0.03, overlay = null, boxes = [],
    onstroke, onpoint
  } = $props();

  let stage = $state(null);
  let sw = $state(0), sh = $state(0);
  let shown = $state(null);          // the URL on screen
  let aspect = $state(1.5);          // of what is on screen
  let loading = $state(false);
  let failed = $state(false);

  /* swap in the new picture once it has loaded */
  let want = 0;
  $effect(() => {
    const url = showBefore && before ? before : src;
    if (!url || url === shown) return;
    const n = ++want;
    loading = true;
    const im = new Image();
    im.onload = () => {
      if (n !== want) return;
      aspect = im.naturalWidth / Math.max(1, im.naturalHeight);
      shown = url;
      loading = false;
      failed = false;
    };
    im.onerror = () => { if (n === want) { loading = false; failed = true; } };
    im.src = url;
  });

  $effect(() => {
    if (!stage || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => { sw = stage.clientWidth; sh = stage.clientHeight; });
    ro.observe(stage);
    sw = stage.clientWidth; sh = stage.clientHeight;
    return () => ro.disconnect();
  });

  const fw = $derived(Math.max(1, Math.min(sw, sh * aspect)));
  const fh = $derived(Math.max(1, fw / aspect));

  let frame = $state(null);
  const uvOf = (e) => {
    const r = frame.getBoundingClientRect();
    return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
            Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
  };

  /* ---------------------------------------------------------------- brush */
  let stroke = $state([]);
  let cursor = $state(null);
  let painting = false;

  function bDown(e) {
    if (mode !== 'brush') return;
    e.preventDefault();
    painting = true;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    stroke = [uvOf(e)];
  }
  function bMove(e) {
    if (mode === 'brush') cursor = uvOf(e);
    if (!painting) return;
    const p = uvOf(e);
    const last = stroke[stroke.length - 1];
    // thin the stroke: one point per ~third of a radius
    if (Math.hypot((p[0] - last[0]) * fw, (p[1] - last[1]) * fh) > brush * fw * 0.33) stroke = [...stroke, p];
  }
  function bUp() {
    if (!painting) return;
    painting = false;
    const pts = stroke;
    stroke = [];
    if (pts.length) onstroke?.(pts, brush);
  }
  const path = $derived(stroke.map((p) => `${p[0] * fw},${p[1] * fh}`).join(' '));

  function click(e) {
    if (mode !== 'point') return;
    const [u, v] = uvOf(e);
    onpoint?.(u, v);
  }

  /* ----------------------------------------------------------------- crop */
  let drag = null;
  function cDown(e, handle) {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    drag = { handle, from: uvOf(e), start: [...crop] };
  }
  function cMove(e) {
    if (!drag) return;
    const [u, v] = uvOf(e);
    const dx = u - drag.from[0], dy = v - drag.from[1];
    let [x, y, w, h] = drag.start;
    const MIN = 0.05;
    const hd = drag.handle;
    if (hd === 'move') {
      x = Math.min(1 - w, Math.max(0, x + dx));
      y = Math.min(1 - h, Math.max(0, y + dy));
    } else {
      let x0 = x, y0 = y, x1 = x + w, y1 = y + h;
      if (hd.includes('l')) x0 = Math.min(x1 - MIN, Math.max(0, x0 + dx));
      if (hd.includes('r')) x1 = Math.max(x0 + MIN, Math.min(1, x1 + dx));
      if (hd.includes('t')) y0 = Math.min(y1 - MIN, Math.max(0, y0 + dy));
      if (hd.includes('b')) y1 = Math.max(y0 + MIN, Math.min(1, y1 + dy));
      if (cropAspect > 0) {
        // keep the chosen shape (in pixels): fit the height to the width
        const k = cropAspect / aspect;          // w_frac / h_frac
        let nw = x1 - x0, nh = nw / k;
        if (hd.includes('t')) { y0 = y1 - nh; if (y0 < 0) { y0 = 0; nh = y1; nw = nh * k; } }
        else { y1 = y0 + nh; if (y1 > 1) { y1 = 1; nh = 1 - y0; nw = nh * k; } }
        if (hd.includes('l')) x0 = x1 - nw; else x1 = x0 + nw;
      }
      [x, y, w, h] = [x0, y0, x1 - x0, y1 - y0];
    }
    crop = [x, y, w, h].map((n) => Math.round(n * 10000) / 10000);
  }
  function cUp() { drag = null; }
</script>

<div class="stage" bind:this={stage}>
  {#if shown}
    <div class="frame" bind:this={frame} style:width="{fw}px" style:height="{fh}px"
         class:brush={mode === 'brush'} class:point={mode === 'point'}
         onpointerdown={bDown} onpointermove={bMove} onpointerup={bUp} onpointercancel={bUp}
         onpointerleave={() => (cursor = null)} onclick={click} role="presentation">
      <img src={shown} alt="Photo being edited" draggable="false" />

      {#if overlay && !showBefore}
        <div class="ov" style:mask-image="url({overlay})" style:-webkit-mask-image="url({overlay})"></div>
      {/if}

      {#each boxes as b, i (i)}
        <div class="box" style:left="{b[0] * 100}%" style:top="{b[1] * 100}%"
             style:width="{b[2] * 100}%" style:height="{b[3] * 100}%"></div>
      {/each}

      {#if mode === 'brush'}
        <svg class="paint" width={fw} height={fh} aria-hidden="true">
          {#if stroke.length}
            <polyline points={path} fill="none" stroke="rgba(242,109,100,0.55)"
                      stroke-width={brush * fw * 2} stroke-linecap="round" stroke-linejoin="round" />
          {/if}
          {#if cursor}
            <circle cx={cursor[0] * fw} cy={cursor[1] * fh} r={brush * fw}
                    fill="none" stroke="#fff" stroke-width="1.5" stroke-opacity="0.9" />
          {/if}
        </svg>
      {/if}

      {#if mode === 'crop'}
        <div class="crop" style:left="{crop[0] * 100}%" style:top="{crop[1] * 100}%"
             style:width="{crop[2] * 100}%" style:height="{crop[3] * 100}%"
             onpointerdown={(e) => cDown(e, 'move')} onpointermove={cMove} onpointerup={cUp}
             onpointercancel={cUp} role="presentation">
          <i class="g1"></i><i class="g2"></i><i class="g3"></i><i class="g4"></i>
          {#each ['tl', 'tr', 'bl', 'br', 't', 'b', 'l', 'r'] as hd (hd)}
            <span class="h {hd}" onpointerdown={(e) => cDown(e, hd)} onpointermove={cMove}
                  onpointerup={cUp} onpointercancel={cUp} role="presentation"></span>
          {/each}
        </div>
      {/if}
    </div>
  {:else if failed}
    <Empty icon="image" title="The preview could not be rendered"
           hint="The server did not return a picture for this edit. Try another tool, or reload the photo." />
  {:else}
    <div class="skel" aria-busy="true" aria-label="Loading"><Skeleton h="100%" r="var(--mc-r-md)" /></div>
  {/if}

  {#if (loading || busy) && shown}
    <span class="rend mg-chip" transition:play={fadeIn}><span class="mg-spin"></span>Rendering</span>
  {/if}
  {#if showBefore}<span class="tag mg-chip" transition:play={fadeIn}>Before</span>{/if}
</div>

<style>
  .stage {
    position: relative; width: 100%; height: 100%; min-height: 220px;
    display: grid; place-items: center; overflow: hidden;
  }
  .frame { position: relative; touch-action: pan-y pinch-zoom; user-select: none; -webkit-user-select: none; }
  .frame.brush { cursor: none; touch-action: none; }
  .frame.point { cursor: crosshair; }
  img { display: block; width: 100%; height: 100%; object-fit: fill; pointer-events: none; border-radius: 4px; }
  .ov {
    position: absolute; inset: 0; background: rgba(62, 207, 142, 0.55); pointer-events: none;
    mask-size: 100% 100%; -webkit-mask-size: 100% 100%; mask-mode: luminance;
  }
  .box { position: absolute; border: 1px dashed rgba(255, 255, 255, 0.7); pointer-events: none; }
  .paint { position: absolute; inset: 0; pointer-events: none; }
  .crop {
    position: absolute; box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.55); outline: 1px solid rgba(255, 255, 255, 0.9);
    cursor: move; touch-action: none;
  }
  .crop > i { position: absolute; background: rgba(255, 255, 255, 0.3); pointer-events: none; }
  .g1, .g2 { top: 0; bottom: 0; width: 1px; }
  .g1 { left: 33.33%; } .g2 { left: 66.66%; }
  .g3, .g4 { left: 0; right: 0; height: 1px; }
  .g3 { top: 33.33%; } .g4 { top: 66.66%; }
  .h { position: absolute; width: 28px; height: 28px; touch-action: none; }
  .h::after { content: ''; position: absolute; inset: 9px; background: var(--mc-ink); border-radius: 3px; box-shadow: 0 1px 4px rgba(0,0,0,.6); }
  .tl { left: -14px; top: -14px; cursor: nwse-resize; }
  .tr { right: -14px; top: -14px; cursor: nesw-resize; }
  .bl { left: -14px; bottom: -14px; cursor: nesw-resize; }
  .br { right: -14px; bottom: -14px; cursor: nwse-resize; }
  .t { left: 50%; top: -14px; margin-left: -14px; cursor: ns-resize; }
  .b { left: 50%; bottom: -14px; margin-left: -14px; cursor: ns-resize; }
  .l { top: 50%; left: -14px; margin-top: -14px; cursor: ew-resize; }
  .r { top: 50%; right: -14px; margin-top: -14px; cursor: ew-resize; }
  .rend { position: absolute; top: 10px; right: 10px; gap: 8px; font-size: 11.5px; }
  .rend .mg-spin { width: 11px; height: 11px; }
  .tag { position: absolute; top: 10px; left: 10px; }
  .rend, .tag { background: var(--mc-raised); border-color: var(--mc-line2); color: var(--mc-ink); box-shadow: var(--mc-sh-2); }
  .skel { position: absolute; inset: 0; display: flex; }
  .skel > :global(.mg-skel) { flex: 1; }
  /* crop handles: a 44px target for a finger */
  @media (pointer: coarse) {
    .h { width: 44px; height: 44px; }
    .h::after { inset: 16px; }
    .tl, .bl, .l { left: -22px; } .tr, .br, .r { right: -22px; }
    .tl, .tr, .t { top: -22px; } .bl, .br, .b { bottom: -22px; }
    .t, .b { margin-left: -22px; } .l, .r { margin-top: -22px; }
  }
</style>
