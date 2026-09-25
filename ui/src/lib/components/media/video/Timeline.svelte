<script>
  /* The main track: clips laid end to end, each as wide as it plays, a
     transition drawn as a notch where one overlaps the next, and the
     playhead over the top.

     Reordering: drag a clip onto another (pointer devices), or select it and
     use the ◀ ▶ buttons that appear on it (touch — HTML drag and drop does
     not exist on a phone). Tap the ruler to move the playhead. */
  import { layout, transAfter, vapi, tc } from '$lib/media/video.js';
  import Icon from '$lib/components/glass/Icon.svelte';

  let {
    project,               // Project data
    selected = null,       // clip id
    time = 0,
    names = {},            // video_id -> filename
    onselect,
    onmove,                // (from, to)
    onseek
  } = $props();

  let zoom = $state(40);   // px per second
  let wrapW = $state(600);
  const lay = $derived(layout(project));
  const clips = $derived(project?.clips || []);

  /* fit short edits to the width the first time we see them */
  let fitted = false;
  $effect(() => {
    if (fitted || !lay.total || !wrapW) return;
    zoom = Math.max(8, Math.min(160, (wrapW - 24) / lay.total));
    fitted = true;
  });

  const W = $derived(Math.max(wrapW - 2, lay.total * zoom + 24));
  const ticks = $derived.by(() => {
    const every = zoom > 60 ? 1 : zoom > 25 ? 2 : zoom > 10 ? 5 : 10;
    const out = [];
    for (let s = 0; s <= lay.total + every; s += every) out.push(s);
    return out;
  });

  let dragFrom = $state(-1);
  let dragOver = $state(-1);

  function frameUrls(c, px) {
    const n = Math.max(1, Math.min(8, Math.floor(px / 70)));
    return Array.from({ length: n }, (_, k) => vapi.frameUrl(c.video_id, c.src_in + ((k + 0.5) / n) * (c.src_out - c.src_in), 120));
  }

  function rulerSeek(e) {
    const r = e.currentTarget.getBoundingClientRect();
    onseek?.(Math.max(0, Math.min(lay.total, (e.clientX - r.left - 12) / zoom)));
  }
</script>

<div class="tl mg-glass-soft">
  <div class="tools">
    <span class="mg-label">Timeline · <span class="mg-tnum">{tc(lay.total)}</span></span>
    <span class="sp"></span>
    <button type="button" class="mg-btn ghost icon sm" aria-label="Zoom out" onclick={() => (zoom = Math.max(4, zoom / 1.5))}>−</button>
    <button type="button" class="mg-btn ghost icon sm" aria-label="Zoom in" onclick={() => (zoom = Math.min(240, zoom * 1.5))}>+</button>
  </div>

  <div class="scroll" bind:clientWidth={wrapW}>
    <div class="inner" style:width="{W}px">
      <div class="ruler" onpointerdown={rulerSeek} role="presentation">
        {#each ticks as s (s)}
          <span class="tk mg-tnum" style:left="{12 + s * zoom}px">{Math.round(s)}s</span>
        {/each}
      </div>

      <div class="track">
        {#each clips as c, i (c.id)}
          {@const L = lay.items[i]}
          {@const px = Math.max(24, L.len * zoom)}
          {@const d = transAfter(project, i)}
          <div class="clip" class:on={c.id === selected} class:over={dragOver === i && dragFrom !== i}
               class:muted={c.mute}
               style:left="{12 + L.start * zoom}px" style:width="{px}px"
               draggable="true"
               ondragstart={(e) => { dragFrom = i; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(i)); }}
               ondragover={(e) => { e.preventDefault(); dragOver = i; }}
               ondragleave={() => { if (dragOver === i) dragOver = -1; }}
               ondrop={(e) => { e.preventDefault(); if (dragFrom >= 0 && dragFrom !== i) onmove?.(dragFrom, i); dragFrom = -1; dragOver = -1; }}
               ondragend={() => { dragFrom = -1; dragOver = -1; }}
               onclick={() => onselect?.(c.id)}
               onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onselect?.(c.id); } }}
               role="button" tabindex="0" aria-pressed={c.id === selected}
               aria-label="Clip {i + 1}: {names[c.video_id] || 'clip'}">
            <div class="fr">
              {#each frameUrls(c, px) as u (u)}<img src={u} alt="" loading="lazy" draggable="false" />{/each}
            </div>
            <div class="lab">
              <span class="nm">{i + 1}. {names[c.video_id] || `#${c.video_id}`}</span>
              <span class="du mg-tnum">{L.len.toFixed(1)}s{c.speed !== 1 ? ` · ${c.speed}×` : ''}</span>
            </div>
            {#if c.grade?.lut}<span class="badge">LUT</span>{/if}
            {#if c.id === selected}
              <div class="mv">
                <button type="button" class="mg-btn secondary icon sm" disabled={i === 0} aria-label="Move earlier"
                        onclick={(e) => { e.stopPropagation(); onmove?.(i, i - 1); }}>
                  <Icon name="chevronLeft" size={14} />
                </button>
                <button type="button" class="mg-btn secondary icon sm" disabled={i === clips.length - 1} aria-label="Move later"
                        onclick={(e) => { e.stopPropagation(); onmove?.(i, i + 1); }}>
                  <Icon name="chevronRight" size={14} />
                </button>
              </div>
            {/if}
          </div>
          {#if d > 0}
            <span class="tr" style:left="{12 + (L.start + L.len - d) * zoom}px" style:width="{d * zoom}px"
                  title="{c.trans} {d.toFixed(2)}s"></span>
          {/if}
        {/each}
      </div>

      <span class="ph" style:left="{12 + Math.min(time, lay.total) * zoom}px"></span>
    </div>
  </div>
</div>

<style>
  .tl { border-radius: var(--mc-r-md); padding: 10px 10px 12px; min-width: 0; }
  .tools { display: flex; align-items: center; gap: 4px; margin-bottom: 6px; padding: 0 4px; }
  .tools .sp { flex: 1; }
  .scroll { overflow-x: auto; overflow-y: hidden; padding-bottom: 6px; }
  .inner { position: relative; height: 128px; }
  .ruler { position: absolute; left: 0; right: 0; top: 0; height: 22px; cursor: pointer; border-bottom: 1px solid var(--mc-line); }
  .tk { position: absolute; top: 4px; font: 400 10.5px/1 var(--mc-font); color: var(--mc-ink3); transform: translateX(-2px); }
  .tk::before { content: ''; position: absolute; left: 0; top: 12px; width: 1px; height: 6px; background: var(--mc-line2); }
  .track { position: absolute; left: 0; right: 0; top: 30px; height: 92px; }
  .clip {
    position: absolute; top: 0; height: 84px; border-radius: 10px; overflow: hidden;
    border: 2px solid rgba(255, 255, 255, 0.14); background: var(--mc-inset); cursor: grab;
    box-sizing: border-box; transition: border-color 0.15s, transform 0.15s;
  }
  .clip:active { cursor: grabbing; }
  .clip.on { border-color: var(--mc-accent); z-index: 2; }
  .clip.over { border-color: var(--mc-mgr); transform: translateY(-3px); }
  .clip.muted .lab::after { content: ' · muted'; color: var(--mc-warn); }
  .fr { position: absolute; inset: 0; display: flex; }
  .fr img { flex: 1 1 0; min-width: 0; height: 100%; object-fit: cover; opacity: 0.75; pointer-events: none; }
  .lab {
    position: absolute; left: 0; right: 0; bottom: 0; padding: 14px 7px 5px; display: flex; flex-direction: column;
    background: linear-gradient(transparent, rgba(0, 0, 0, 0.75)); font: 500 11px/1.25 var(--mc-font); color: #fff;
  }
  .nm, .du { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .du { color: rgba(255, 255, 255, 0.7); font-size: 10.5px; }
  .badge {
    position: absolute; top: 5px; left: 5px; padding: 2px 5px; border-radius: 5px;
    background: rgba(167, 139, 250, 0.85); color: #fff; font: 600 9.5px/1 var(--mc-font);
  }
  .mv { position: absolute; top: 4px; right: 4px; display: flex; gap: 3px; }
  .tr {
    position: absolute; top: 66px; height: 14px; z-index: 3; pointer-events: none; min-width: 6px;
    background: repeating-linear-gradient(135deg, rgba(62, 207, 142, 0.7) 0 4px, rgba(62, 207, 142, 0.25) 4px 8px);
    border-radius: 6px;
  }
  .ph { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: #fff; z-index: 4; pointer-events: none; }
  .ph::before { content: ''; position: absolute; top: 0; left: -5px; border: 6px solid transparent; border-top-color: #fff; }
</style>
