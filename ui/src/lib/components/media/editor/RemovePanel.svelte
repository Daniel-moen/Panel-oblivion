<script>
  /* The Remove tool (Zerko 1.3): paint over a bin, a car, a cable — the
     server fills it from its surroundings and hands back a patch that goes
     into recipe.removes. LaMa (onnxruntime, a 92 MB model fetched on first
     use) does the filling; until it is here OpenCV's quick fill stands in,
     which is fine for small things and soft on big ones. */
  import Slider from './Slider.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import { pct, fmtMB } from '$lib/media/photoedit.js';

  let { api, ed, brush = $bindable(0.03), busy = false, model = null, onnx = true, disabled = false } = $props();

  const removes = $derived(ed.recipe.removes || []);
  const KIND = { remove: 'Removed', pull: 'Window view', sky: 'Sky', glow: 'Window glow' };

  function drop(i) {
    ed.recipe.removes = removes.filter((_, j) => j !== i);
    api.touch();
  }
  function clearAll() {
    ed.recipe.removes = removes.filter((x) => x.kind !== 'remove');
    api.touch();
  }
</script>

<div class="wrap">
  {#if !onnx}
    <div class="mg-strip warn">
      <span class="ic"><Icon name="alert" size={14} /></span>
      <span>onnxruntime isn't installed on this server, so the LaMa model can't run — Remove uses OpenCV's
        quick fill instead (good for small things, soft on large ones).</span>
    </div>
  {:else if model && model.status === 'downloading'}
    <div class="dl">
      <span class="mg-label">Fetching the remove model · {fmtMB(model.done)} of {fmtMB(model.total)}</span>
      <div class="mg-bar"><i style:width="{pct(model.done, model.total)}%"></i></div>
      <span class="hint">Quick fill works in the meantime.</span>
    </div>
  {:else if model && model.status === 'error'}
    <div class="mg-strip warn">
      <span class="ic"><Icon name="alert" size={14} /></span>
      <span>The remove model could not be fetched ({model.error || 'unknown error'}) — using the quick fill.</span>
    </div>
  {:else if model && model.status === 'ready'}
    <span class="mg-chip ok"><span class="dot"></span>LaMa model ready</span>
  {/if}

  <p class="hint">Paint over what should go. Each stroke is filled on the server and can be taken back below.</p>

  <Slider label="Brush size" value={brush} min={0.005} max={0.15} step={0.001} def={0.03}
          fmt={(v) => Math.round(v * 100) + '%'} {disabled} oninput={(v) => (brush = v)} />

  {#if busy}<p class="work"><span class="mg-spin"></span> Filling…</p>{/if}

  {#if removes.length}
    <div class="list">
      {#each removes as x, i (x.ref)}
        <div class="it">
          <span>{KIND[x.kind] || x.kind} {i + 1}</span>
          <button type="button" class="mg-btn ghost icon sm" onclick={() => drop(i)} {disabled}
                  aria-label="Take back" title="Take back"><Icon name="trash" size={13} /></button>
        </div>
      {/each}
    </div>
    {#if removes.some((x) => x.kind === 'remove')}
      <button type="button" class="mg-btn ghost sm" onclick={clearAll} {disabled}>Clear all removals</button>
    {/if}
  {/if}
</div>

<style>
  .wrap { display: flex; flex-direction: column; gap: 10px; padding-top: 4px; }
  .wrap > .mg-chip { align-self: flex-start; }
  .mg-strip { margin: 0; }
  .dl { display: flex; flex-direction: column; gap: 6px; }
  .hint { margin: 0; font-size: 11.5px; line-height: 1.45; color: var(--mg-i3); }
  .work { margin: 0; display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--mg-i2); }
  .list { display: flex; flex-direction: column; }
  .it { display: flex; align-items: center; justify-content: space-between; min-height: 40px;
        border-bottom: 1px solid var(--mg-line); font-size: 13px; color: var(--mg-i2); }
  .it:last-child { border-bottom: 0; }
</style>
