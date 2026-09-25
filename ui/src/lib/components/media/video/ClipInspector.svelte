<script>
  /* Everything about the selected clip that the backend's Clip model holds:
     trim (via the scrubber), speed, sound (volume, mute, fades), framing,
     the transition into the next clip, and an optional LUT of its own.
     Mutates the clip in place (it is part of the page's $state project) and
     calls onchange so the page can autosave. */
  import { TRANSITIONS, SPEEDS, FLAT_GRADE, clipLen } from '$lib/media/video.js';
  import Trimmer from './Trimmer.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';

  let {
    clip,
    info = null,          // probe: { duration, fps, has_audio, filename }
    project,
    luts = [],
    isLast = false,
    index = 0,
    count = 1,
    onchange,
    onremove,
    onmove,
    onduplicate
  } = $props();

  const video = $derived({ id: clip.video_id, duration: info?.duration || clip.src_out });
  const set = (fn) => { fn(); onchange?.(); };

  function setLut(name) {
    set(() => {
      if (!name) clip.grade = null;
      else clip.grade = { ...(project.grade || FLAT_GRADE), lut: name, lut_mix: clip.grade?.lut_mix ?? 1 };
    });
  }
</script>

<div class="insp">
  <div class="hd">
    <b>Clip {index + 1} of {count}</b>
    <span class="fn">{info?.filename || `#${clip.video_id}`}</span>
    <span class="sp"></span>
    <button type="button" class="mg-btn ghost icon" disabled={index === 0} onclick={() => onmove?.(index, index - 1)} aria-label="Move earlier">
      <Icon name="arrowLeft" size={14} />
    </button>
    <button type="button" class="mg-btn ghost icon" disabled={index === count - 1} onclick={() => onmove?.(index, index + 1)} aria-label="Move later">
      <Icon name="arrowRight" size={14} />
    </button>
    <button type="button" class="mg-btn ghost icon" onclick={() => onduplicate?.()} aria-label="Duplicate clip" title="Duplicate">
      <Icon name="copy" size={14} />
    </button>
    <button type="button" class="mg-btn danger icon" onclick={() => onremove?.()} aria-label="Remove clip" title="Remove">
      <Icon name="trash" size={14} />
    </button>
  </div>

  <Trimmer {video} inPt={clip.src_in} outPt={clip.src_out} fps={info?.fps || project.fps || 25} compact
           onchange={(a, b) => set(() => { clip.src_in = a; clip.src_out = b; })} />

  <div class="grid">
    <label class="f">
      <span class="mg-label">Speed</span>
      <span class="mg-select">
        <select value={String(clip.speed)} onchange={(e) => set(() => (clip.speed = Number(e.currentTarget.value)))}>
          {#each SPEEDS as s (s)}<option value={String(s)}>{s}×</option>{/each}
          {#if !SPEEDS.includes(clip.speed)}<option value={String(clip.speed)}>{clip.speed}×</option>{/if}
        </select>
        <span class="ic"><Icon name="chevronDown" size={14} /></span>
      </span>
      <small class="mg-tnum">plays {clipLen(clip).toFixed(2)}s</small>
    </label>

    <label class="f">
      <span class="mg-label">Framing</span>
      <span class="mg-select">
        <select value={clip.frame?.mode || 'fill'} onchange={(e) => set(() => (clip.frame = { ...(clip.frame || {}), mode: e.currentTarget.value }))}>
          <option value="fill">Fill (crop to shape)</option>
          <option value="fit">Fit (blurred edges)</option>
        </select>
        <span class="ic"><Icon name="chevronDown" size={14} /></span>
      </span>
    </label>

    {#if (clip.frame?.mode || 'fill') === 'fill'}
      <label class="f">
        <span class="mg-label">Crop position <span class="mg-tnum">{Math.round((clip.frame?.x ?? 0.5) * 100)}%</span></span>
        <input type="range" min="0" max="1" step="0.01" value={clip.frame?.x ?? 0.5}
               oninput={(e) => set(() => (clip.frame = { ...(clip.frame || {}), x: Number(e.currentTarget.value) }))} />
      </label>
    {/if}

    <label class="f">
      <span class="mg-label">Zoom <span class="mg-tnum">{(clip.frame?.zoom ?? 1).toFixed(2)}×</span></span>
      <input type="range" min="0.5" max="2" step="0.01" value={clip.frame?.zoom ?? 1}
             oninput={(e) => set(() => (clip.frame = { ...(clip.frame || {}), zoom: Number(e.currentTarget.value) }))} />
    </label>

    <div class="f">
      <span class="mg-label">Sound {#if info && !info.has_audio}<em>(clip has none)</em>{/if}</span>
      <div class="row">
        <button type="button" class="mg-btn sm {clip.mute ? 'danger' : 'secondary'}" disabled={info && !info.has_audio}
                onclick={() => set(() => (clip.mute = !clip.mute))} aria-pressed={clip.mute}>
          <Icon name="mic" size={13} />{clip.mute ? 'Muted' : 'On'}
        </button>
        <input type="range" min="0" max="2" step="0.05" value={clip.volume} disabled={clip.mute || (info && !info.has_audio)}
               aria-label="Volume" oninput={(e) => set(() => (clip.volume = Number(e.currentTarget.value)))} />
        <span class="v mg-tnum">{Math.round(clip.volume * 100)}%</span>
      </div>
    </div>

    <label class="f">
      <span class="mg-label">Sound fade in <span class="mg-tnum">{clip.fade_in.toFixed(1)}s</span></span>
      <input type="range" min="0" max="3" step="0.1" value={clip.fade_in}
             oninput={(e) => set(() => (clip.fade_in = Number(e.currentTarget.value)))} />
    </label>
    <label class="f">
      <span class="mg-label">Sound fade out <span class="mg-tnum">{clip.fade_out.toFixed(1)}s</span></span>
      <input type="range" min="0" max="3" step="0.1" value={clip.fade_out}
             oninput={(e) => set(() => (clip.fade_out = Number(e.currentTarget.value)))} />
    </label>

    <label class="f">
      <span class="mg-label">Transition into next {#if isLast}<em>(last clip)</em>{/if}</span>
      <span class="mg-select">
        <select value={clip.trans} disabled={isLast} onchange={(e) => set(() => (clip.trans = e.currentTarget.value))}>
          {#each TRANSITIONS as t (t.value)}<option value={t.value}>{t.label}</option>{/each}
        </select>
        <span class="ic"><Icon name="chevronDown" size={14} /></span>
      </span>
    </label>
    {#if clip.trans !== 'cut' && !isLast}
      <label class="f">
        <span class="mg-label">Transition length <span class="mg-tnum">{clip.trans_dur.toFixed(1)}s</span></span>
        <input type="range" min="0.1" max="3" step="0.1" value={clip.trans_dur}
               oninput={(e) => set(() => (clip.trans_dur = Number(e.currentTarget.value)))} />
      </label>
    {/if}

    <label class="f">
      <span class="mg-label">Look (LUT)</span>
      <span class="mg-select">
        <select value={clip.grade?.lut || ''} onchange={(e) => setLut(e.currentTarget.value)}>
          <option value="">Project look{project.grade?.lut ? ` (${project.grade.lut})` : ''}</option>
          {#each luts as l (l)}<option value={l}>{l}</option>{/each}
        </select>
        <span class="ic"><Icon name="chevronDown" size={14} /></span>
      </span>
    </label>
    {#if clip.grade?.lut}
      <label class="f">
        <span class="mg-label">LUT strength <span class="mg-tnum">{Math.round((clip.grade.lut_mix ?? 1) * 100)}%</span></span>
        <input type="range" min="0" max="1" step="0.05" value={clip.grade.lut_mix ?? 1}
               oninput={(e) => set(() => (clip.grade = { ...clip.grade, lut_mix: Number(e.currentTarget.value) }))} />
      </label>
    {/if}
  </div>
</div>

<style>
  .insp { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
  .hd { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .hd b { font: 600 14px/1.2 var(--mc-font); color: var(--mc-ink); }
  .hd .fn { color: var(--mc-ink3); font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; max-width: 40ch; }
  .hd .sp { flex: 1; }
  .grid { display: grid; gap: 14px 18px; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }
  .f { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .f em { font-style: normal; color: var(--mc-ink3); }
  .f small { color: var(--mc-ink3); font-size: 11.5px; }
  .f .mg-select > select { width: 100%; }
  .row { display: flex; align-items: center; gap: 10px; }
  .row input { flex: 1; min-width: 0; }
  .v { font-size: 12px; color: var(--mc-ink2); width: 40px; text-align: right; }
  input[type='range'] { width: 100%; accent-color: var(--mc-accent); height: 28px; }
</style>
