<script>
  /* The edit as a whole: its shape, fades from and to black, the look every
     clip shares (a LUT plus the grade sliders video_edit.Grade holds) and the
     sound settings (AudioOpts). Mutates project in place; onchange autosaves. */
  import { ASPECTS, FLAT_GRADE } from '$lib/media/video.js';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';

  let { project, luts = [], canUpload = false, onchange, onuploadlut } = $props();

  const set = (fn) => { fn(); onchange?.(); };
  const g = $derived(project.grade || FLAT_GRADE);
  const setG = (k, v) => set(() => (project.grade = { ...(project.grade || FLAT_GRADE), [k]: v }));
  const setA = (k, v) => set(() => (project.audio = { ...project.audio, [k]: v }));

  const SLIDERS = [
    ['exposure', 'Exposure', -2, 2, 0.05, (v) => `${v > 0 ? '+' : ''}${v.toFixed(2)} st`],
    ['contrast', 'Contrast', -1, 1, 0.05, (v) => `${Math.round(v * 100)}`],
    ['highlights', 'Highlights', -1, 1, 0.05, (v) => `${Math.round(v * 100)}`],
    ['shadows', 'Shadows', -1, 1, 0.05, (v) => `${Math.round(v * 100)}`],
    ['temp', 'Temperature', -1, 1, 0.05, (v) => `${Math.round(v * 100)}`],
    ['tint', 'Tint', -1, 1, 0.05, (v) => `${Math.round(v * 100)}`],
    ['saturation', 'Saturation', -1, 1, 0.05, (v) => `${Math.round(v * 100)}`]
  ];

  let fileIn = $state(null);
</script>

<div class="pp">
  <section>
    <span class="mg-label">Shape</span>
    <div class="scroller mg-noscroll">
      <Seg options={ASPECTS.map((a) => ({ value: a, label: a }))} value={project.aspect}
           onchange={(v) => set(() => (project.aspect = v))} label="Aspect ratio" />
    </div>
    <div class="two">
      <label class="f">
        <span class="mg-label">Fade in from black <span class="mg-tnum">{project.fade_in.toFixed(1)}s</span></span>
        <input type="range" min="0" max="3" step="0.1" value={project.fade_in}
               oninput={(e) => set(() => (project.fade_in = Number(e.currentTarget.value)))} />
      </label>
      <label class="f">
        <span class="mg-label">Fade out to black <span class="mg-tnum">{project.fade_out.toFixed(1)}s</span></span>
        <input type="range" min="0" max="3" step="0.1" value={project.fade_out}
               oninput={(e) => set(() => (project.fade_out = Number(e.currentTarget.value)))} />
      </label>
    </div>
    <p class="note mg-tnum">{project.fps} fps · {project.clips.length} clip{project.clips.length === 1 ? '' : 's'}
      {#if project.music?.length}{" · "}{project.music.length} music piece{project.music.length === 1 ? '' : 's'}{/if}
      {#if project.titles?.length}{" · "}{project.titles.length} title{project.titles.length === 1 ? '' : 's'} (kept as they are){/if}
    </p>
  </section>

  <section>
    <div class="lh">
      <span class="mg-label">Look — every clip without its own LUT</span>
      {#if canUpload}
        <button type="button" class="mg-btn ghost sm" onclick={() => fileIn?.click()}>
          <Icon name="upload" size={13} />Add .cube LUT
        </button>
        <input bind:this={fileIn} type="file" accept=".cube" hidden
               onchange={(e) => { const f = e.currentTarget.files?.[0]; if (f) onuploadlut?.(f); e.currentTarget.value = ''; }} />
      {/if}
    </div>
    <div class="two">
      <label class="f">
        <span class="mg-label">LUT</span>
        <span class="mg-select">
          <select value={g.lut || ''} onchange={(e) => setG('lut', e.currentTarget.value)}>
            <option value="">None</option>
            {#each luts as l (l)}<option value={l}>{l}</option>{/each}
          </select>
          <span class="ic"><Icon name="chevronDown" size={14} /></span>
        </span>
      </label>
      {#if g.lut}
        <label class="f">
          <span class="mg-label">LUT strength <span class="mg-tnum">{Math.round((g.lut_mix ?? 1) * 100)}%</span></span>
          <input type="range" min="0" max="1" step="0.05" value={g.lut_mix ?? 1}
                 oninput={(e) => setG('lut_mix', Number(e.currentTarget.value))} />
        </label>
      {/if}
      {#each SLIDERS as [k, label, min, max, step, fmt] (k)}
        <label class="f">
          <span class="mg-label">{label} <span class="mg-tnum">{fmt(g[k] || 0)}</span></span>
          <input type="range" {min} {max} {step} value={g[k] || 0}
                 oninput={(e) => setG(k, Number(e.currentTarget.value))}
                 ondblclick={() => setG(k, 0)} />
        </label>
      {/each}
    </div>
    <p class="note">The grade is applied in the render; the preview here shows it only roughly. Double-click a slider to reset it.
      The DaVinci Resolve timeline leaves colour to Resolve.</p>
  </section>

  <section>
    <span class="mg-label">Sound</span>
    <div class="toggles">
      <label class="tg"><input type="checkbox" checked={project.audio.loudness}
             onchange={(e) => setA('loudness', e.currentTarget.checked)} />
        Level for social ({project.audio.target} LUFS)</label>
      <label class="tg"><input type="checkbox" checked={project.audio.voice}
             onchange={(e) => setA('voice', e.currentTarget.checked)} />Voice clarity</label>
      {#if project.music?.length}
        <label class="tg"><input type="checkbox" checked={project.audio.duck}
               onchange={(e) => setA('duck', e.currentTarget.checked)} />Duck music under speech</label>
      {/if}
    </div>
    <div class="two">
      {#if project.audio.loudness}
        <label class="f">
          <span class="mg-label">Loudness target <span class="mg-tnum">{project.audio.target} LUFS</span></span>
          <input type="range" min="-30" max="-8" step="1" value={project.audio.target}
                 oninput={(e) => setA('target', Number(e.currentTarget.value))} />
        </label>
      {/if}
      {#each [['eq_low', 'Bass'], ['eq_mid', 'Mids'], ['eq_high', 'Treble']] as [k, label] (k)}
        <label class="f">
          <span class="mg-label">{label} <span class="mg-tnum">{project.audio[k] > 0 ? '+' : ''}{project.audio[k]} dB</span></span>
          <input type="range" min="-12" max="12" step="1" value={project.audio[k]}
                 oninput={(e) => setA(k, Number(e.currentTarget.value))} ondblclick={() => setA(k, 0)} />
        </label>
      {/each}
    </div>
  </section>
</div>

<style>
  .pp { display: flex; flex-direction: column; gap: 22px; min-width: 0; }
  section { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
  .scroller { overflow-x: auto; }
  .lh { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: space-between; }
  .two { display: grid; gap: 12px 18px; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }
  .f { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .f .mg-select > select { width: 100%; }
  .note { margin: 0; font-size: 12px; line-height: 1.5; color: var(--mc-ink3); }
  .toggles { display: flex; flex-wrap: wrap; gap: 8px 18px; }
  .tg { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; font-size: 13px; color: var(--mc-ink2); cursor: pointer; }
  .tg input { width: 18px; height: 18px; accent-color: var(--mc-accent); }
  input[type='range'] { width: 100%; accent-color: var(--mc-accent); height: 28px; }
  @media (pointer: coarse) { input[type='range'] { height: 44px; } }
</style>
