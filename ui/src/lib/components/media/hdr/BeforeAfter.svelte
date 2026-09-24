<script>
  /* Before / after with a draggable divider. The "after" picture sits on top
     and is clipped from the left edge to the divider, so dragging right shows
     more of the result. Pointer events cover mouse, pen and a thumb; the
     range input underneath keeps it keyboard-operable. */
  let { before, after, alt = '', labels = ['Before', 'After'] } = $props();

  let pos = $state(50);
  let box = $state(null);
  let dragging = false;

  function at(e) {
    if (!box) return;
    const r = box.getBoundingClientRect();
    pos = Math.max(0, Math.min(100, ((e.clientX - r.left) / r.width) * 100));
  }
  function down(e) { dragging = true; box.setPointerCapture?.(e.pointerId); at(e); }
  function move(e) { if (dragging) at(e); }
  function up() { dragging = false; }
</script>

<div class="ba" bind:this={box}
     onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up}>
  <img class="base" src={before} alt={alt ? `${alt} — ${labels[0]}` : labels[0]} draggable="false" />
  <img class="top" src={after} alt={alt ? `${alt} — ${labels[1]}` : labels[1]} draggable="false"
       style:clip-path="inset(0 {100 - pos}% 0 0)" />
  <span class="lbl l">{labels[0]}</span>
  <span class="lbl r">{labels[1]}</span>
  <span class="bar" style:left="{pos}%"><i></i></span>
  <input class="rng" type="range" min="0" max="100" step="1" bind:value={pos}
         aria-label="Compare {labels[0].toLowerCase()} and {labels[1].toLowerCase()}" />
</div>

<style>
  .ba {
    position: relative; overflow: hidden; border-radius: var(--mg-r-in);
    background: var(--mg-term); touch-action: none; user-select: none; cursor: ew-resize;
  }
  img { display: block; width: 100%; height: auto; pointer-events: none; }
  .top { position: absolute; inset: 0; height: 100%; object-fit: contain; }
  .base { object-fit: contain; }
  /* labels: "after" is on the left because the result is revealed from the left */
  .lbl {
    position: absolute; top: 8px; padding: 4px 9px; border-radius: 9999px;
    background: rgba(0, 0, 0, 0.55); color: #fff; font: 500 11px/1 var(--mg-font); pointer-events: none;
  }
  .lbl.l { right: 8px; }
  .lbl.r { left: 8px; }
  .bar {
    position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px;
    background: rgba(255, 255, 255, 0.9); pointer-events: none;
  }
  .bar i {
    position: absolute; top: 50%; left: 50%; width: 28px; height: 28px; margin: -14px 0 0 -14px;
    border-radius: 50%; background: rgba(255, 255, 255, 0.92); box-shadow: var(--mg-sh-2);
  }
  .rng { position: absolute; left: 0; right: 0; bottom: 0; width: 100%; opacity: 0; height: 1px; pointer-events: none; }
  .rng:focus-visible { opacity: 1; height: auto; pointer-events: auto; }
</style>
