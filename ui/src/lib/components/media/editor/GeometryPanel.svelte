<script>
  /* Crop, straighten, Upright and the lens.

     Upright asks the server (/upright) for the straighten and keystone that
     make the lines true, using the renderer's own mapping; Lens asks /lens
     for the maker's DNG profile or, failing that, the distortion and colour
     fringing measured from the photo's edges. Both land as ordinary slider
     values you can then nudge. */
  import Slider from './Slider.svelte';
  import Section from './Section.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import { pe, DEFAULTS } from '$lib/media/photoedit.js';
  import { say } from '$lib/media.svelte.js';

  let { api, ed, disabled = false, cropAspect = $bindable(0), srcAspect = 1.5 } = $props();
  const r = $derived(ed.recipe);

  const ASPECTS = [
    { v: 0, label: 'Free' }, { v: -1, label: 'Original' }, { v: 1, label: '1:1' },
    { v: 4 / 3, label: '4:3' }, { v: 3 / 2, label: '3:2' }, { v: 16 / 9, label: '16:9' }, { v: 4 / 5, label: '4:5' }
  ];
  let aspectPick = $state(0);
  let busy = $state(null);

  const set = (k) => (v) => api.set(k, v);
  const done = (k) => (v) => api.set(k, v, true);

  /* the frame the crop is drawn on: the renderer keeps the source's own
     shape even when rotated (apply_geometry sizes the output from it) */
  const frameAspect = $derived(srcAspect);

  function coverScale(st, pv) {
    let s = 1;
    if (st) { const t = (Math.abs(st) * Math.PI) / 180; s = Math.max(s, Math.cos(t) + Math.sin(t)); }
    if (pv) s = Math.max(s, 1 + Math.abs(pv) * 0.45);
    return Math.round(Math.min(1.6, s) * 10000) / 10000;
  }

  function pickAspect(v) {
    aspectPick = v;
    const want = v === -1 ? srcAspect : v;
    cropAspect = want;
    if (!want) return;
    // the biggest box of that shape, centred on the current one
    const k = want / frameAspect;            // w_frac / h_frac
    let w = 1, h = w / k;
    if (h > 1) { h = 1; w = k; }
    const [x0, y0, cw, ch] = r.crop;
    const cx = x0 + cw / 2, cy = y0 + ch / 2;
    const x = Math.min(1 - w, Math.max(0, cx - w / 2));
    const y = Math.min(1 - h, Math.max(0, cy - h / 2));
    ed.recipe.crop = [x, y, w, h].map((n) => Math.round(n * 10000) / 10000);
  }

  function startCrop() { api.setCropping(true); }
  function doneCrop() { api.commit(); api.setCropping(false); }
  function resetCrop() { ed.recipe.crop = [0, 0, 1, 1]; aspectPick = 0; cropAspect = 0; api.touch(); }

  function rotate(by) {
    const next = (((r.rotate || 0) + by) % 360 + 360) % 360;
    ed.recipe.rotate = next;
    ed.recipe.crop = [0, 0, 1, 1];
    api.touch();
  }

  async function upright(mode) {
    busy = mode;
    try {
      const u = await pe.upright(ed.id, mode, r);
      ed.recipe.straighten = u.straighten;
      ed.recipe.persp_v = u.persp_v;
      ed.recipe.persp_h = u.persp_h;
      ed.recipe.geo_scale = coverScale(u.straighten, u.persp_v);
      api.touch();
      say(`Upright (${u.mode}) from ${u.lines} lines`);
    } catch (e) { say(e.message, 'error'); }
    finally { busy = null; }
  }

  async function lens() {
    busy = 'lens';
    try {
      const l = await pe.lens(ed.id);
      if (l.source === 'none') { say('Nothing to correct was found in this photo'); return; }
      const clamp = (v, a) => Math.max(-a, Math.min(a, Number(v) || 0));
      if (l.distortion != null) ed.recipe.distortion = clamp(l.distortion, 0.5);
      ed.recipe.distortion2 = clamp(l.distortion2, 0.5);
      // /lens can measure fringing up to ±2 units; the recipe takes ±1
      if (l.ca_r != null) ed.recipe.ca_r = clamp(l.ca_r, 1);
      if (l.ca_b != null) ed.recipe.ca_b = clamp(l.ca_b, 1);
      if (Array.isArray(l.vig_k) && l.vig_k.length === 5) ed.recipe.lens_vig_k = l.vig_k;
      api.touch();
      say(l.source === 'profile' ? `Lens profile applied${l.camera ? ' · ' + l.camera : ''}` : 'Lens correction measured from the photo');
    } catch (e) { say(e.message, 'error'); }
    finally { busy = null; }
  }

  const geoChanged = $derived(['straighten', 'persp_v', 'persp_h', 'geo_scale', 'rotate', 'flip_h', 'flip_v', 'crop']
    .filter((k) => JSON.stringify(r[k]) !== JSON.stringify(DEFAULTS[k])).length || null);
</script>

<Section title="Crop & rotate" icon="crop" badge={geoChanged}>
  {#if ed.cropping}
    <div class="chips">
      {#each ASPECTS as a (a.label)}
        <button type="button" class="mg-chip" class:on={aspectPick === a.v} onclick={() => pickAspect(a.v)}>{a.label}</button>
      {/each}
    </div>
    <p class="hint">Drag the corners on the photo. The whole frame is shown while you crop.</p>
    <div class="row">
      <button type="button" class="mg-btn accent sm" onclick={doneCrop}><Icon name="check" size={14} /> Done</button>
      <button type="button" class="mg-btn ghost sm" onclick={resetCrop}>Reset crop</button>
    </div>
  {:else}
    <div class="row">
      <button type="button" class="mg-btn secondary sm" onclick={startCrop} {disabled}><Icon name="crop" size={14} /> Crop</button>
      <button type="button" class="mg-btn secondary icon sm" onclick={() => rotate(-90)} {disabled} aria-label="Rotate left" title="Rotate left">
        <span class="flip"><Icon name="rotate" size={14} /></span></button>
      <button type="button" class="mg-btn secondary icon sm" onclick={() => rotate(90)} {disabled} aria-label="Rotate right" title="Rotate right">
        <Icon name="rotate" size={14} /></button>
      <button type="button" class="mg-chip" class:on={r.flip_h} {disabled}
              onclick={() => api.set('flip_h', !r.flip_h, true)}>Flip ↔</button>
      <button type="button" class="mg-chip" class:on={r.flip_v} {disabled}
              onclick={() => api.set('flip_v', !r.flip_v, true)}>Flip ↕</button>
    </div>
  {/if}
  <Slider label="Straighten" value={r.straighten} min={-45} max={45} step={0.1} def={0}
          fmt={(v) => Number(v).toFixed(1) + '°'} {disabled} oninput={set('straighten')} oncommit={done('straighten')} />
  <Slider label="Scale" value={r.geo_scale} min={1} max={3} step={0.01} def={1}
          fmt={(v) => Math.round(v * 100) + '%'} {disabled} oninput={set('geo_scale')} oncommit={done('geo_scale')} />
  <button type="button" class="mg-btn ghost sm fill" {disabled}
          onclick={() => api.set('geo_scale', coverScale(r.straighten, r.persp_v), true)}>Fill the frame</button>
</Section>

<Section title="Upright" icon="building" badge={r.persp_v || r.persp_h ? '●' : null}>
  <div class="row">
    {#each [['auto', 'Auto'], ['level', 'Level'], ['vertical', 'Vertical'], ['full', 'Full']] as [m, l] (m)}
      <button type="button" class="mg-btn secondary sm" onclick={() => upright(m)} disabled={disabled || !!busy}>
        {#if busy === m}<span class="mg-spin"></span>{/if}{l}</button>
    {/each}
  </div>
  <Slider label="Vertical keystone" value={r.persp_v} def={0} {disabled} oninput={set('persp_v')} oncommit={done('persp_v')} />
  <Slider label="Horizontal keystone" value={r.persp_h} def={0} {disabled} oninput={set('persp_h')} oncommit={done('persp_h')} />
</Section>

<Section title="Lens" icon="aperture" open={false}
         badge={r.distortion || r.distortion2 || r.ca_r || r.ca_b || r.lens_vig ? '●' : null}>
  <button type="button" class="mg-btn secondary sm" onclick={lens} disabled={disabled || !!busy}>
    {#if busy === 'lens'}<span class="mg-spin"></span>{:else}<Icon name="wand" size={14} />{/if} Correct the lens
  </button>
  <Slider label="Distortion" value={r.distortion} min={-0.5} max={0.5} step={0.005} def={0} {disabled}
          oninput={set('distortion')} oncommit={done('distortion')} />
  <Slider label="Edge distortion" value={r.distortion2} min={-0.5} max={0.5} step={0.005} def={0} {disabled}
          oninput={set('distortion2')} oncommit={done('distortion2')} />
  <Slider label="Red/cyan fringe" value={r.ca_r} def={0} {disabled} oninput={set('ca_r')} oncommit={done('ca_r')} />
  <Slider label="Blue/yellow fringe" value={r.ca_b} def={0} {disabled} oninput={set('ca_b')} oncommit={done('ca_b')} />
  <Slider label="Corner shading" value={r.lens_vig} min={0} max={1.5} def={0} {disabled}
          oninput={set('lens_vig')} oncommit={done('lens_vig')} />
</Section>

<style>
  .row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 2px 0 8px; }
  .row .mg-chip { min-height: 32px; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; padding-bottom: 6px; }
  .chips .mg-chip { min-height: 32px; }
  .hint { margin: 0 0 6px; font-size: 11.5px; color: var(--mg-i3); line-height: 1.4; }
  .flip { display: inline-flex; transform: scaleX(-1); }
  .fill { align-self: flex-start; }
</style>
