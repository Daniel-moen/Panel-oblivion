<script>
  /* Local adjustments, and the AI selections that make them.

     Sky / Subject / Click ask /select for a mask: Segment Anything on this
     server when its models are here (108 MB, fetched on first use — the call
     answers 202 with progress until then), the classical colour-and-texture
     selectors otherwise. The mask comes back as a brush bitmap in source
     space; a radial or linear is just numbers. Each mask carries its own
     small set of sliders (photo_edit.py › Mask). */
  import Slider from './Slider.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import { pct, fmtMB, MASK_DEFAULTS } from '$lib/media/photoedit.js';

  let {
    api, ed, disabled = false, onnx = true, ai = null, selecting = null,
    clickArmed = $bindable(false), onselect
  } = $props();


  const masks = $derived(ed.recipe.masks || []);
  let sel = $state(0);
  const m = $derived(masks[sel] ? { ...MASK_DEFAULTS, ...masks[sel] } : null);

  /* the page adds AI masks; select the newest when the list grows */
  let seen = 0;
  $effect(() => {
    const n = masks.length;
    if (n > seen) sel = n - 1;
    seen = n;
  });

  function add(kind) {
    const base = { ...MASK_DEFAULTS, kind, name: kind === 'radial' ? 'Radial' : 'Gradient' };
    if (kind === 'linear') Object.assign(base, { cy: 0.35, angle: 0, feather: 0.6 });
    ed.recipe.masks = [...masks, base];
    api.touch();
  }
  function setM(k, v, done = false) {
    const list = [...masks];
    list[sel] = { ...MASK_DEFAULTS, ...list[sel], [k]: v };
    ed.recipe.masks = list;
    api.touch(done);
  }
  function drop(i) {
    ed.recipe.masks = masks.filter((_, j) => j !== i);
    sel = Math.max(0, Math.min(sel, masks.length - 2));
    api.touch();
  }

  const LOCAL = [
    { k: 'exposure', label: 'Exposure', min: -4, max: 4, step: 0.05 },
    { k: 'contrast', label: 'Contrast' },
    { k: 'highlights', label: 'Highlights' },
    { k: 'shadows', label: 'Shadows' },
    { k: 'saturation', label: 'Saturation' },
    { k: 'temp_shift', label: 'Warmth', min: -4000, max: 4000, step: 50, fmt: (v) => (v > 0 ? '+' : '') + Math.round(v) + ' K' },
    { k: 'tint_shift', label: 'Tint' },
    { k: 'clarity', label: 'Clarity' }
  ];
  const SHAPE = {
    radial: [
      { k: 'cx', label: 'Centre ↔', min: 0, max: 1 }, { k: 'cy', label: 'Centre ↕', min: 0, max: 1 },
      { k: 'rx', label: 'Width', min: 0.02, max: 1.5 }, { k: 'ry', label: 'Height', min: 0.02, max: 1.5 },
      { k: 'angle', label: 'Angle', min: -180, max: 180, step: 1 }, { k: 'feather', label: 'Feather', min: 0, max: 1 }
    ],
    linear: [
      { k: 'cy', label: 'Position', min: 0, max: 1 }, { k: 'cx', label: 'Along', min: 0, max: 1 },
      { k: 'angle', label: 'Angle', min: -180, max: 180, step: 1 }, { k: 'feather', label: 'Softness', min: 0, max: 1 }
    ]
  };
  const NAMES = { brush: 'Selection', radial: 'Radial', linear: 'Gradient', colour: 'Colour range' };
</script>

<div class="wrap">
  <span class="mg-label">AI selection</span>
  {#if !onnx}
    <p class="hint warn">onnxruntime isn't installed here, so Segment Anything can't run — selections use the
      built-in colour-and-texture method (good on skies, rougher on objects).</p>
  {:else if ai && ai.status === 'downloading'}
    <div class="dl">
      <span class="mg-label">Fetching the selection models · {fmtMB(ai.done)} of {fmtMB(ai.total)}</span>
      <div class="mg-bar"><i style:width="{pct(ai.done, ai.total)}%"></i></div>
    </div>
  {:else if ai && ai.status === 'error'}
    <p class="hint warn">The selection models could not be fetched ({ai.error}); the built-in method answers instead.</p>
  {:else if ai && ai.status === 'ready'}
    <span class="mg-chip ok"><span class="dot"></span>Segment Anything ready</span>
  {:else if ai}
    <p class="hint">The selection models (≈{fmtMB(ai.total || 108570406)}) download the first time you select.</p>
  {/if}
  <div class="row">
    <button type="button" class="mg-btn secondary sm" onclick={() => onselect?.('sky')} disabled={disabled || !!selecting}>
      {#if selecting === 'sky'}<span class="mg-spin"></span>{/if}Sky</button>
    <button type="button" class="mg-btn secondary sm" onclick={() => onselect?.('subject')} disabled={disabled || !!selecting}>
      {#if selecting === 'subject'}<span class="mg-spin"></span>{/if}Subject</button>
    <button type="button" class="mg-btn sm" class:accent={clickArmed} class:secondary={!clickArmed}
            onclick={() => (clickArmed = !clickArmed)} disabled={disabled || !!selecting}>
      {#if selecting === 'click'}<span class="mg-spin"></span>{/if}{clickArmed ? 'Tap the photo…' : 'Click an object'}</button>
  </div>

  <span class="mg-label">Shapes</span>
  <div class="row">
    <button type="button" class="mg-btn ghost sm" onclick={() => add('radial')} {disabled}><Icon name="plus" size={13} /> Radial</button>
    <button type="button" class="mg-btn ghost sm" onclick={() => add('linear')} {disabled}><Icon name="plus" size={13} /> Gradient</button>
  </div>

  {#if masks.length}
    <div class="list" role="listbox" aria-label="Masks">
      {#each masks as x, i (i)}
        <div class="it" class:on={i === sel}>
          <button type="button" class="nm" onclick={() => (sel = i)} role="option" aria-selected={i === sel}>
            <span class="mg-dot sm" class:ok={x.enabled !== false}></span>
            {x.name || NAMES[x.kind] || x.kind} {i + 1}
          </button>
          <button type="button" class="mg-btn ghost icon sm" aria-label="Show or hide" title="Show or hide" {disabled}
                  onclick={() => { sel = i; setM('enabled', !(x.enabled !== false), true); }}>
            <Icon name="eye" size={13} /></button>
          <button type="button" class="mg-btn ghost icon sm" aria-label="Delete mask" title="Delete" {disabled}
                  onclick={() => drop(i)}><Icon name="trash" size={13} /></button>
        </div>
      {/each}
    </div>
  {/if}

  {#if m}
    <div class="edit">
      <div class="row">
        <button type="button" class="mg-chip" class:on={m.invert} {disabled} onclick={() => setM('invert', !m.invert, true)}>Invert</button>
        {#if m.enabled === false}<span class="mg-chip warn">Hidden</span>{/if}
      </div>
      <Slider label="Amount" value={m.amount} min={0} max={1} def={1} {disabled}
              oninput={(v) => setM('amount', v)} oncommit={(v) => setM('amount', v, true)} />
      {#each LOCAL as s (s.k)}
        <Slider label={s.label} value={m[s.k]} min={s.min ?? -1} max={s.max ?? 1} step={s.step ?? 0.01} def={0}
                fmt={s.fmt} {disabled} oninput={(v) => setM(s.k, v)} oncommit={(v) => setM(s.k, v, true)} />
      {/each}
      {#if SHAPE[m.kind]}
        <span class="mg-label sp">Shape</span>
        {#each SHAPE[m.kind] as s (s.k)}
          <Slider label={s.label} value={m[s.k]} min={s.min} max={s.max} step={s.step ?? 0.01} def={MASK_DEFAULTS[s.k]}
                  {disabled} oninput={(v) => setM(s.k, v)} oncommit={(v) => setM(s.k, v, true)} />
        {/each}
      {/if}
    </div>
  {/if}
</div>

<style>
  .wrap { display: flex; flex-direction: column; gap: 8px; padding-top: 4px; }
  .wrap > .mg-chip { align-self: flex-start; }
  .row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .row .mg-chip { min-height: 32px; }
  .hint { margin: 0; font-size: 11.5px; line-height: 1.45; color: var(--mg-i3); }
  .hint.warn { color: var(--mg-warn); }
  .dl { display: flex; flex-direction: column; gap: 6px; }
  .list { display: flex; flex-direction: column; border-top: 1px solid var(--mg-line); margin-top: 4px; }
  .it { display: flex; align-items: center; gap: 2px; border-bottom: 1px solid var(--mg-line); border-radius: 10px; }
  .it.on { background: var(--mg-glass-soft); }
  .nm { flex: 1; display: flex; align-items: center; gap: 8px; min-height: 40px; padding: 0 8px; border: 0; background: none;
        color: var(--mg-i2); font: 500 12.5px/1 var(--mg-font); text-align: left; cursor: pointer; }
  .it.on .nm { color: var(--mg-i); }
  .edit { display: flex; flex-direction: column; gap: 4px; padding-top: 6px; }
  .sp { margin-top: 6px; }
</style>
