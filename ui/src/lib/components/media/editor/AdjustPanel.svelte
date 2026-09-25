<script>
  /* The develop sliders, grouped the way a photographer works down them:
     light, colour, the colour mixer, grading, detail, effects. Every slider
     writes one recipe field (zerko/photo_edit.py › Recipe) with its real
     bounds; the server renders it. */
  import Slider from './Slider.svelte';
  import Section from './Section.svelte';
  import { DEFAULTS, fmtSigned } from '$lib/media/photoedit.js';

  let { api, ed, disabled = false, onauto, autoBusy = false } = $props();
  const r = $derived(ed.recipe);

  const LIGHT = [
    { k: 'exposure', label: 'Exposure', min: -4, max: 4, step: 0.05, fmt: (v) => fmtSigned(v) + ' EV' },
    { k: 'contrast', label: 'Contrast' },
    { k: 'highlights', label: 'Highlights' },
    { k: 'shadows', label: 'Shadows' },
    { k: 'whites', label: 'Whites', min: -0.5, max: 0.5 },
    { k: 'blacks', label: 'Blacks', min: -0.5, max: 0.5 }
  ];
  const COLOUR = [
    { k: 'tint', label: 'Tint', track: 'linear-gradient(90deg,#3c9a4a,#777,#b04aa8)' },
    { k: 'vibrance', label: 'Vibrance' },
    { k: 'saturation', label: 'Saturation' }
  ];
  const DETAIL = [
    { k: 'sharpen', label: 'Sharpening', min: 0, max: 2 },
    { k: 'clarity', label: 'Clarity' },
    { k: 'dehaze', label: 'Dehaze', min: -0.5, max: 1 },
    { k: 'defringe', label: 'Defringe', min: 0, max: 1 },
    { k: 'dn_luma', label: 'Noise reduction', min: 0, max: 1 },
    { k: 'dn_colour', label: 'Colour noise', min: 0, max: 1 },
    { k: 'dn_shadows', label: 'Only in shadows up to', min: 0, max: 1, fmt: (v) => (v ? Math.round(v * 100) + '%' : 'Off') }
  ];
  const EFFECTS = [
    { k: 'vignette', label: 'Vignette' },
    { k: 'vig_mid', label: 'Midpoint', min: 0, max: 1 },
    { k: 'vig_feather', label: 'Feather', min: 0, max: 1 },
    { k: 'vig_round', label: 'Roundness', min: 0, max: 1 },
    { k: 'grain', label: 'Grain', min: 0, max: 1 },
    { k: 'grain_size', label: 'Grain size', min: 0, max: 1 }
  ];

  const BANDS = [
    { b: 'red', c: '#e5484d' }, { b: 'orange', c: '#f18f3b' }, { b: 'yellow', c: '#e8cf45' },
    { b: 'green', c: '#46a758' }, { b: 'aqua', c: '#3fbcc4' }, { b: 'blue', c: '#3e7fe0' },
    { b: 'purple', c: '#8e4ec6' }, { b: 'magenta', c: '#d6409f' }
  ];
  let band = $state('blue');
  const bandColour = $derived(BANDS.find((x) => x.b === band)?.c);

  const CURVES = [
    { id: 'linear', label: 'Linear', pts: [[0, 0], [1, 1]] },
    { id: 'soft', label: 'Gentle S', pts: [[0, 0.012], [0.28, 0.255], [0.72, 0.755], [1, 0.978]] },
    { id: 'strong', label: 'Strong S', pts: [[0, 0], [0.25, 0.19], [0.75, 0.82], [1, 1]] },
    { id: 'fade', label: 'Faded', pts: [[0, 0.07], [0.5, 0.52], [1, 0.95]] }
  ];
  const curveId = $derived(CURVES.find((c) => JSON.stringify(c.pts) === JSON.stringify(r.curve))?.id || 'custom');

  const set = (k) => (v) => api.set(k, v);
  const done = (k) => (v) => api.set(k, v, true);
  const changedIn = (keys) => keys.filter((k) => JSON.stringify(r[k]) !== JSON.stringify(DEFAULTS[k])).length || null;

  const hueTrack = 'linear-gradient(90deg,#f33,#ff3,#3f3,#3ff,#33f,#f3f,#f33)';
</script>

<div class="auto">
  <button type="button" class="mg-btn accent sm" onclick={onauto} disabled={disabled || autoBusy}>
    {#if autoBusy}<span class="mg-spin"></span>{:else}✦{/if} Auto
  </button>
  <span class="hint">Measures this frame: exposure, highlights, white balance, level and keystone.</span>
</div>

<Section title="Light" icon="sun" badge={changedIn(LIGHT.map((x) => x.k))}>
  {#each LIGHT as s (s.k)}
    <Slider label={s.label} value={r[s.k]} min={s.min ?? -1} max={s.max ?? 1} step={s.step ?? 0.01}
            def={DEFAULTS[s.k]} fmt={s.fmt} {disabled} oninput={set(s.k)} oncommit={done(s.k)} />
  {/each}
  <div class="curves">
    <span class="mg-label">Tone curve</span>
    <div class="chips">
      {#each CURVES as c (c.id)}
        <button type="button" class="mg-chip" class:on={curveId === c.id} {disabled}
                onclick={() => api.set('curve', c.pts.map((p) => [...p]), true)}>{c.label}</button>
      {/each}
      {#if curveId === 'custom'}<span class="mg-chip on">Custom</span>{/if}
    </div>
  </div>
</Section>

<Section title="Colour" icon="palette" badge={changedIn(['temp_k', 'tint', 'vibrance', 'saturation'])}>
  <Slider label="Temperature" value={r.temp_k} min={2000} max={15000} step={50} def={6500}
          fmt={(v) => Math.round(v) + ' K'} track="linear-gradient(90deg,#3e7fe0,#ddd,#f1a23b)"
          {disabled} oninput={set('temp_k')} oncommit={done('temp_k')} />
  {#each COLOUR as s (s.k)}
    <Slider label={s.label} value={r[s.k]} def={0} track={s.track} {disabled} oninput={set(s.k)} oncommit={done(s.k)} />
  {/each}
</Section>

<Section title="Colour mixer" icon="layers" open={false}
         badge={changedIn(BANDS.flatMap((x) => [`sat_${x.b}`, `hue_${x.b}`, `lum_${x.b}`]))}>
  <div class="bands" role="group" aria-label="Colour band">
    {#each BANDS as x (x.b)}
      <button type="button" class="band" class:on={band === x.b} style:--c={x.c} aria-label={x.b}
              aria-pressed={band === x.b} onclick={() => (band = x.b)}></button>
    {/each}
  </div>
  <Slider label="Hue" value={r[`hue_${band}`]} def={0} {disabled}
          track="linear-gradient(90deg,#888,{bandColour},#888)"
          oninput={set(`hue_${band}`)} oncommit={done(`hue_${band}`)} />
  <Slider label="Saturation" value={r[`sat_${band}`]} def={0} {disabled}
          track="linear-gradient(90deg,#777,{bandColour})"
          oninput={set(`sat_${band}`)} oncommit={done(`sat_${band}`)} />
  <Slider label="Luminance" value={r[`lum_${band}`]} def={0} {disabled}
          track="linear-gradient(90deg,#111,{bandColour},#fff)"
          oninput={set(`lum_${band}`)} oncommit={done(`lum_${band}`)} />
</Section>

<Section title="Colour grading" icon="aperture" open={false}
         badge={changedIn(['grade_sh_sat', 'grade_mid_sat', 'grade_hi_sat', 'grade_balance'])}>
  {#each [['sh', 'Shadows'], ['mid', 'Midtones'], ['hi', 'Highlights']] as [z, name] (z)}
    <div class="grade">
      <span class="mg-label">{name}</span>
      <Slider label="Hue" value={r[`grade_${z}_hue`]} min={0} max={360} step={1} def={DEFAULTS[`grade_${z}_hue`]}
              fmt={(v) => Math.round(v) + '°'} track={hueTrack} {disabled}
              oninput={set(`grade_${z}_hue`)} oncommit={done(`grade_${z}_hue`)} />
      <Slider label="Amount" value={r[`grade_${z}_sat`]} min={0} max={1} def={0} {disabled}
              oninput={set(`grade_${z}_sat`)} oncommit={done(`grade_${z}_sat`)} />
    </div>
  {/each}
  <Slider label="Balance" value={r.grade_balance} def={0} {disabled}
          oninput={set('grade_balance')} oncommit={done('grade_balance')} />
</Section>

<Section title="Detail" icon="eye" open={false} badge={changedIn(DETAIL.map((x) => x.k))}>
  {#each DETAIL as s (s.k)}
    <Slider label={s.label} value={r[s.k]} min={s.min ?? -1} max={s.max ?? 1} def={DEFAULTS[s.k]}
            fmt={s.fmt} {disabled} oninput={set(s.k)} oncommit={done(s.k)} />
  {/each}
</Section>

<Section title="Vignette & grain" icon="aperture" open={false} badge={changedIn(EFFECTS.map((x) => x.k))}>
  {#each EFFECTS as s (s.k)}
    <Slider label={s.label} value={r[s.k]} min={s.min ?? -1} max={s.max ?? 1} def={DEFAULTS[s.k]}
            {disabled} oninput={set(s.k)} oncommit={done(s.k)} />
  {/each}
</Section>

<style>
  .auto { display: flex; align-items: center; gap: 10px; padding: 4px 0 10px; border-bottom: 1px solid var(--mc-line); }
  .hint { font-size: 11.5px; line-height: 1.4; color: var(--mc-ink3); }
  .curves { padding-top: 6px; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
  .chips .mg-chip { min-height: 32px; }
  .bands { display: flex; gap: 6px; flex-wrap: wrap; padding: 4px 0 6px; }
  .band {
    width: 32px; height: 32px; border-radius: 50%; background: var(--c); cursor: pointer;
    border: 2px solid transparent; box-shadow: inset 0 0 0 2px rgba(0, 0, 0, 0.35);
  }
  .band.on { border-color: var(--mc-ink); }
  .grade { padding-top: 4px; }
</style>
