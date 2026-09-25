<script>
  /* Export: develop at full resolution on the server and write a new file
     next to the original (its "Edited" folder, or the project's edited
     stage), indexed straight into the library. The original is never
     touched. With "include virtual copies" it runs as a background batch
     (/api/photo-edit-batch) so each copy comes out as its own file.

     The watermark lives in the recipe (wm_*), so it shows in the preview
     and travels with presets; the logos are PNGs in MEDIA_ROOT/_watermarks. */
  import { onMount, untrack } from 'svelte';
  import Section from './Section.svelte';
  import Slider from './Slider.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import { pe, cleanRecipe, watermarkBlobUrl } from '$lib/media/photoedit.js';
  import { fmtBytes } from '$lib/media.js';
  import { say } from '$lib/media.svelte.js';

  let { api, ed, copies = [], copyName = null, caps = {}, disabled = false } = $props();

  let width = $state(0);
  let customW = $state(2400);
  let quality = $state(92);
  let fmt = $state('jpg');
  let sharpen = $state('screen');
  let maxKb = $state(0);
  let name = $state('');
  let withCopies = $state(false);
  let busy = $state(false);
  let result = $state(null);      // single export response (+ libId)
  let job = $state(null);         // batch status

  let marks = $state([]);
  let thumbs = $state({});
  let wmFolder = $state('');

  const r = $derived(ed.recipe);
  const canExport = $derived(!!caps.upload);

  async function loadMarks() {
    try {
      const w = await pe.watermarks();
      marks = w.watermarks || [];
      wmFolder = w.folder || '';
      for (const m of marks) if (!thumbs[m.name]) watermarkBlobUrl(m.name).then((u) => { if (u) thumbs = { ...thumbs, [m.name]: u }; });
    } catch { marks = []; }
  }
  $effect(() => { ed.id; ed.copy; untrack(() => { result = null; job = null; withCopies = false; }); });
  onMount(() => {
    loadMarks();
    return () => { for (const u of Object.values(thumbs)) URL.revokeObjectURL(u); };
  });

  function body() {
    return {
      width: width === -1 ? Math.max(0, Math.min(20000, Number(customW) || 0)) : width,
      quality, fmt, out_sharpen: sharpen, max_kb: fmt === 'jpg' ? Number(maxKb) || 0 : 0,
      name: name.trim() || (copyName ? `{name} - ${copyName.replace(/[{}]/g, '')}` : '')
    };
  }

  async function run() {
    busy = true;
    result = null;
    job = null;
    try {
      await api.settle();
      if (withCopies && copies.length) {
        const b = body();
        const start = await pe.batch({ video_ids: [ed.id], copies: true, width: b.width, quality: b.quality,
          fmt: b.fmt, out_sharpen: b.out_sharpen, max_kb: b.max_kb, name: name.trim() });
        job = { id: start.job_id, running: true, done: 0, total: start.total, results: [], errors: [] };
        while (job.running) {
          await new Promise((res) => setTimeout(res, 1000));
          job = await pe.batchStatus(start.job_id);
        }
        if (job.errors?.length) say(job.errors[0], 'error');
        else say(`Exported ${job.results.length} file${job.results.length === 1 ? '' : 's'}`);
      } else {
        const res = await pe.export(ed.id, { ...body(), recipe: cleanRecipe($state.snapshot(ed.recipe)) });
        result = res;
        say(`Exported ${res.filename}`);
        // find it in the library, for the "open" link
        try {
          const hits = await pe.photos({ search: res.filename.replace(/\.[^.]+$/, '') });
          const hit = (hits || []).find((v) => v.filepath === res.path) || (hits || []).find((v) => v.filename === res.filename);
          if (hit) result = { ...res, libId: hit.id };
        } catch { /* the link is a nicety */ }
      }
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }

  let fileIn = $state(null);
  let uploading = $state(false);
  async function uploadMark(e) {
    const f = e.currentTarget.files?.[0];
    e.currentTarget.value = '';
    if (!f) return;
    uploading = true;
    try {
      const res = await pe.uploadWatermark(f).promise;
      await loadMarks();
      api.set('wm_index', res.index ?? 0);
      if (!r.wm_opacity) api.set('wm_opacity', 0.8);
      api.commit();
      say(`Added ${res.name}`);
    } catch (err) { say(err.message, 'error'); }
    finally { uploading = false; }
  }
  async function dropMark(m) {
    if (!confirm(`Delete the watermark ${m.name}?`)) return;
    try { await pe.deleteWatermark(m.name); await loadMarks(); } catch (e) { say(e.message, 'error'); }
  }
  function pickMark(i) {
    ed.recipe.wm_index = i;
    if (!ed.recipe.wm_opacity) ed.recipe.wm_opacity = 0.8;
    api.touch();
  }
  const POS = ['↖', '↑', '↗', '←', '•', '→', '↙', '↓', '↘'];
</script>

<Section title="Export" icon="download">
  {#if !canExport}
    <div class="mg-strip warn"><span class="ic"><Icon name="lock" size={14} /></span>
      <span>Your account can't write files to the library, so exporting is off.</span></div>
  {/if}
  <span class="mg-label">Size</span>
  <div class="chips">
    {#each [[0, 'Full size'], [3000, '3000 px'], [2048, '2048 px'], [1600, '1600 px'], [-1, 'Custom']] as [v, l] (v)}
      <button type="button" class="mg-chip" class:on={width === v} onclick={() => (width = v)}>{l}</button>
    {/each}
  </div>
  {#if width === -1}
    <label class="inl"><span>Width</span><input class="mg-input" type="number" min="200" max="20000" bind:value={customW} /> px</label>
  {/if}
  <span class="mg-label">Format</span>
  <div class="chips">
    <button type="button" class="mg-chip" class:on={fmt === 'jpg'} onclick={() => (fmt = 'jpg')}>JPEG</button>
    <button type="button" class="mg-chip" class:on={fmt === 'tif'} onclick={() => (fmt = 'tif')}>TIFF</button>
  </div>
  {#if fmt === 'jpg'}
    <Slider label="Quality" value={quality} min={60} max={100} step={1} def={92} fmt={(v) => v}
            oninput={(v) => (quality = v)} />
    <span class="mg-label">Size limit (portals often cap uploads)</span>
    <div class="chips">
      {#each [[0, 'None'], [500, '500 KB'], [1000, '1 MB'], [2000, '2 MB'], [5000, '5 MB']] as [v, l] (v)}
        <button type="button" class="mg-chip" class:on={Number(maxKb) === v} onclick={() => (maxKb = v)}>{l}</button>
      {/each}
    </div>
  {/if}
  <span class="mg-label">Output sharpening</span>
  <div class="chips">
    {#each [['none', 'None'], ['screen', 'Screen'], ['print', 'Print']] as [v, l] (v)}
      <button type="button" class="mg-chip" class:on={sharpen === v} onclick={() => (sharpen = v)}>{l}</button>
    {/each}
  </div>
  <label class="fld">
    <span class="mg-label">File name</span>
    <input class="mg-input" bind:value={name} placeholder={copyName ? `{name} - ${copyName}` : '{name}_edit'} />
    <small>Tokens: {'{name}'} {'{n}'} {'{date}'} {'{folder}'} {'{property}'}</small>
  </label>
  {#if copies.length}
    <label class="tg"><input type="checkbox" bind:checked={withCopies} /> Also export the {copies.length} virtual cop{copies.length === 1 ? 'y' : 'ies'} (uses each one's saved edit)</label>
  {/if}

  <button type="button" class="mg-btn primary go" onclick={run} disabled={disabled || busy || !canExport}>
    {#if busy}<span class="mg-spin"></span> Exporting…{:else}<Icon name="download" size={15} /> Export{/if}
  </button>

  {#if job}
    <div class="res mg-tile">
      <div class="mg-bar"><i style:width="{job.total ? (100 * job.done) / job.total : 0}%"></i></div>
      <span class="mg-tnum">{job.running ? `Exporting ${job.current || ''}` : 'Done'} · {job.results?.length || 0} file(s)</span>
      {#each job.results || [] as f (f)}<code>{f}</code>{/each}
      {#each job.errors || [] as er (er)}<span class="err">{er}</span>{/each}
    </div>
  {/if}
  {#if result}
    <div class="res mg-tile">
      <b>{result.filename}</b>
      <span class="mg-tnum">{result.width} × {result.height} · {fmtBytes(result.size)}{result.filename.endsWith('.jpg') ? ` · quality ${result.quality}` : ''}</span>
      <code>{result.path}</code>
      {#if result.libId}<a class="mg-btn secondary sm" href="/media/browse?open={result.libId}"><Icon name="image" size={13} /> Open in library</a>{/if}
    </div>
  {/if}
</Section>

<Section title="Watermark" icon="image" open={!!r.wm_opacity} badge={r.wm_opacity ? 'On' : null}>
  {#if marks.length}
    <div class="marks">
      {#each marks as m (m.name)}
        <div class="mk" class:on={r.wm_opacity > 0 && r.wm_index === m.index}>
          <button type="button" class="pick" onclick={() => pickMark(m.index)} {disabled} title={m.name}>
            {#if thumbs[m.name]}<img src={thumbs[m.name]} alt={m.name} />{:else}<span>{m.name}</span>{/if}
          </button>
          {#if caps.admin}
            <button type="button" class="x" aria-label="Delete {m.name}" onclick={() => dropMark(m)}><Icon name="close" size={11} /></button>
          {/if}
        </div>
      {/each}
    </div>
    <Slider label="Opacity" value={r.wm_opacity} min={0} max={1} def={0} fmt={(v) => (v ? Math.round(v * 100) + '%' : 'Off')}
            {disabled} oninput={(v) => api.set('wm_opacity', v)} oncommit={(v) => api.set('wm_opacity', v, true)} />
    <Slider label="Size" value={r.wm_scale} min={0.03} max={1} def={0.22} fmt={(v) => Math.round(v * 100) + '%'}
            {disabled} oninput={(v) => api.set('wm_scale', v)} oncommit={(v) => api.set('wm_scale', v, true)} />
    <Slider label="Margin" value={r.wm_margin} min={0} max={0.25} step={0.005} def={0.03} fmt={(v) => Math.round(v * 100) + '%'}
            {disabled} oninput={(v) => api.set('wm_margin', v)} oncommit={(v) => api.set('wm_margin', v, true)} />
    <span class="mg-label">Position</span>
    <div class="pos">
      {#each POS as p, i (i)}
        <button type="button" class:on={r.wm_position === i} {disabled} aria-label="Position {i + 1}"
                onclick={() => api.set('wm_position', i, true)}>{p}</button>
      {/each}
    </div>
  {:else}
    <p class="hint">No watermarks yet. Add a transparent PNG logo.</p>
  {/if}
  {#if caps.upload}
    <input type="file" accept="image/png" bind:this={fileIn} onchange={uploadMark} hidden />
    <button type="button" class="mg-btn ghost sm start" onclick={() => fileIn?.click()} disabled={uploading}>
      {#if uploading}<span class="mg-spin"></span>{:else}<Icon name="upload" size={13} />{/if} Add a PNG logo</button>
  {/if}
</Section>

<style>
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 8px; }
  .chips .mg-chip { min-height: 32px; }
  .inl { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--mc-ink2); margin-bottom: 8px; }
  .inl .mg-input { width: 110px; height: 36px; }
  .fld { display: flex; flex-direction: column; gap: 4px; margin: 4px 0 8px; }
  .fld .mg-input { height: 36px; }
  .fld small { font-size: 11px; color: var(--mc-ink3); }
  .tg { display: flex; align-items: flex-start; gap: 8px; font-size: 12.5px; color: var(--mc-ink2); padding: 6px 0; line-height: 1.4; }
  .go { align-self: stretch; margin-top: 6px; }
  .res { margin-top: 10px; padding: 12px; border-radius: var(--mc-r-md); display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; color: var(--mc-ink2); }
  .res b { color: var(--mc-ink); font-weight: 600; overflow-wrap: anywhere; }
  .res code { font: 11px/1.4 var(--mc-mono); color: var(--mc-ink3); overflow-wrap: anywhere; }
  .res .mg-btn { align-self: flex-start; }
  .err { color: var(--mc-crit); }
  .hint { margin: 0 0 6px; font-size: 11.5px; line-height: 1.45; color: var(--mc-ink3); }
  .marks { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 6px; }
  .mk { position: relative; }
  .pick {
    width: 72px; height: 48px; border-radius: var(--mc-r-sm); border: 1px solid var(--mc-line);
    background: repeating-conic-gradient(#2a2a2e 0 25%, #1c1c20 0 50%) 0 0 / 12px 12px;
    display: grid; place-items: center; padding: 4px; cursor: pointer; overflow: hidden; color: var(--mc-ink3); font-size: 10px;
  }
  .pick img { max-width: 100%; max-height: 100%; object-fit: contain; }
  .mk.on .pick { border-color: var(--mc-accent); box-shadow: 0 0 0 1px var(--mc-accent); }
  .x { position: absolute; top: -6px; right: -6px; width: 20px; height: 20px; border-radius: 50%; border: 0;
       background: var(--mc-raised); border: 1px solid var(--mc-line2); color: var(--mc-ink); box-shadow: var(--mc-sh-1);
       display: grid; place-items: center; cursor: pointer; padding: 0; }
  .pos { display: grid; grid-template-columns: repeat(3, 44px); gap: 4px; margin: 4px 0 8px; }
  .pos button { height: 44px; border-radius: var(--mc-r-sm); border: 1px solid var(--mc-line); background: var(--mc-raised);
                color: var(--mc-ink2); cursor: pointer; font-size: 14px; }
  .pos button.on { border-color: var(--mc-ok-line); color: var(--mc-accent); background: var(--mc-ok-soft); }
  .start { align-self: flex-start; }
</style>
