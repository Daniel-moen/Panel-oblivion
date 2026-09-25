<script>
  /* The HDR tab: brackets in, one photo per set out.

     1. Source — a library folder, or the photos handed over in ?ids=.
     2. Find sets — /api/hdr/scan groups the frames by capture time and
        exposure restarts (or a fixed count). Flambient also guesses which
        frames are the flash pops; a click on a frame flips it.
     3. Settings — the mode (HDR fusion / flambient / panorama) and the
        MergeBody options. HDR uses the 1.4 merge engine with the panel's
        sliders, previewed live per set, or the classic Mertens fusion.
     4. Merge — a background job, polled; each result links to the editor.

     Nothing is overwritten: results land in a subfolder beside the frames. */
  import { onDestroy, untrack } from 'svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import { thumbUrl, photoUrl } from '$lib/media.js';
  import { say } from '$lib/media.svelte.js';
  import { hdr, HDR_LOOK, MERGE_DEFAULTS, poll } from '$lib/media/hdr.js';
  import FolderSelect from './FolderSelect.svelte';
  import Range from './Range.svelte';

  let { ids = [], features = {}, allowed = true, onlook } = $props();

  /* ---------------------------------------------------------- source */
  let source = $state(untrack(() => (ids.length ? 'ids' : 'folder')));
  let folder = $state(null);
  let mode = $state('hdr');
  let gap = $state(4);
  let fixed = $state(0);

  let scanning = $state(false);
  let scanned = $state(null);          // {message, ungrouped}
  let groups = $state([]);             // [{key, on, items:[{id, filename, thumbnail_path, flash, bias, taken_at}]}]

  /* -------------------------------------------------------- settings */
  let engine = $state('panel');        // panel (hdr_merge + sliders) | classic (Mertens)
  let look = $state({ ...HDR_LOOK });
  let opts = $state({ ...MERGE_DEFAULTS });
  let more = $state(false);

  /* --------------------------------------------------------- preview */
  let pvKey = $state(null);
  let pvUrl = $state(null);
  let pvBusy = $state(false);
  let pvErr = $state('');
  let pvTimer;

  /* ------------------------------------------------------------- job */
  let job = $state(null);
  let stopPoll = null;

  const MODES = [
    { value: 'hdr', label: 'HDR', icon: 'sun' },
    { value: 'flambient', label: 'Flambient', icon: 'bolt' },
    { value: 'panorama', label: 'Panorama', icon: 'panorama' }
  ];
  const SOURCES = $derived([
    { value: 'folder', label: 'Folder', icon: 'folder' },
    ...(ids.length ? [{ value: 'ids', label: `Selection · ${ids.length}`, icon: 'check' }] : [])
  ]);

  const chosen = $derived(groups.filter((g) => g.on && g.items.length >= 2));
  const frames = $derived(chosen.reduce((a, g) => a + g.items.length, 0));
  const canScan = $derived(allowed && !scanning && (source === 'ids' ? ids.length >= 2 : folder != null));
  const running = $derived(!!job?.running);

  function reset() {
    groups = []; scanned = null; closePreview();
  }

  async function scan() {
    if (!canScan) return;
    scanning = true; reset();
    try {
      const body = { mode, gap_seconds: Number(gap) || 4, fixed_size: Number(fixed) || 0 };
      if (source === 'ids') body.video_ids = ids; else body.folder_id = folder;
      const r = await hdr.scan(body);
      groups = (r.groups || []).map((g) => ({ ...g, on: true }));
      scanned = { message: r.message, ungrouped: r.ungrouped || 0 };
    } catch (e) { say(e.message, 'error'); }
    finally { scanning = false; }
  }

  function setMode(m) {
    if (m === mode) return;
    mode = m;
    // the sets differ per mode (panoramas run longer; flambient marks flash)
    if (groups.length) scan();
  }

  function dropFrame(g, id) {
    g.items = g.items.filter((i) => i.id !== id);
    if (pvKey === g.key) refreshPreview();
  }
  function toggleFlash(item) { item.flash = !item.flash; }

  /* ---------------------------------------------------------- preview */
  function closePreview() {
    clearTimeout(pvTimer);
    if (pvUrl) URL.revokeObjectURL(pvUrl);
    pvUrl = null; pvKey = null; pvErr = '';
  }

  async function refreshPreview() {
    const g = groups.find((x) => x.key === pvKey);
    if (!g || g.items.length < 2) { pvErr = 'A set needs at least two frames.'; return; }
    pvBusy = true; pvErr = '';
    try {
      const url = await hdr.preview(g.items.map((i) => i.id), $state.snapshot(look), opts.align, 1000);
      if (pvUrl) URL.revokeObjectURL(pvUrl);
      pvUrl = url;
    } catch (e) { pvErr = e.message; }
    finally { pvBusy = false; }
  }

  function openPreview(g) {
    if (pvKey === g.key) { closePreview(); return; }
    closePreview();
    pvKey = g.key;
    refreshPreview();
  }

  // slider moves re-render the open preview, debounced
  $effect(() => {
    JSON.stringify(look); opts.align;
    if (!untrack(() => pvKey)) return;
    clearTimeout(pvTimer);
    pvTimer = setTimeout(refreshPreview, 450);
  });

  /* ------------------------------------------------------------ merge */
  async function merge() {
    if (!chosen.length || running) return;
    const body = {
      ...$state.snapshot(opts),
      mode,
      groups: chosen.map((g) => g.items.map((i) => i.id)),
      look: mode === 'hdr' && engine === 'panel' ? $state.snapshot(look) : null,
      flash: mode === 'flambient' ? chosen.map((g) => g.items.filter((i) => i.flash).map((i) => i.id)) : []
    };
    if (mode === 'flambient') {
      const bad = chosen.findIndex((g) => !g.items.some((i) => i.flash) || g.items.every((i) => i.flash));
      if (bad >= 0) { say(`Set ${bad + 1} needs at least one flash and one ambient frame — tap a frame to switch it`, 'error', 5000); return; }
    }
    try {
      const r = await hdr.merge(body);
      job = { id: r.job_id, running: true, done: 0, total: r.total, current: 'Starting…', results: [], errors: [] };
      stopPoll?.();
      stopPoll = poll(() => hdr.job(r.job_id), (j) => !j.running, (j) => {
        job = j;
        if (!j.running) {
          const n = j.results?.length || 0;
          say(j.cancelled ? 'Merge cancelled' : `${n} photo${n === 1 ? '' : 's'} made${j.errors?.length ? ` · ${j.errors.length} failed` : ''}`,
              j.errors?.length && !n ? 'error' : 'ok');
        }
      }, (e) => { say(e.message, 'error'); job = { ...job, running: false }; });
    } catch (e) { say(e.message, 'error'); }
  }

  async function cancel() {
    if (!job?.id) return;
    try { await hdr.cancel(job.id); say('Cancelling after the current set…'); } catch (e) { say(e.message, 'error'); }
  }

  onDestroy(() => { stopPoll?.(); closePreview(); });

  const pct = (v) => `${Math.round(v * 100)}`;
  const ev = (v) => `${v > 0 ? '+' : ''}${(Math.round(v * 10) / 10).toFixed(1)} EV`;
  const sgn = (v) => `${v > 0 ? '+' : ''}${Math.round(v * 100)}`;
</script>

{#if !allowed}
  <div class="mg-strip warn">
    <span class="ic"><Icon name="lock" size={15} /></span>
    <span><b>View only</b> — merging writes new photos into the library, which your account can't do.</span>
  </div>
{/if}
{#if features.raw === false}
  <div class="mg-strip warn">
    <span class="ic"><Icon name="alert" size={15} /></span>
    <span><b>RAW decoding unavailable on this server</b> — JPEG and TIFF brackets merge normally; RAW frames
      only give their small embedded preview.</span>
  </div>
{/if}

<div class="lay">
  <!-- ——————————————————————————————————————————— left: the sets ——— -->
  <section class="col">
    <div class="mg-panel card">
      <span class="mg-label">1 · Frames</span>
      <div class="row">
        {#if SOURCES.length > 1}
          <Seg options={SOURCES} value={source} onchange={(v) => { source = v; reset(); }} label="Source" />
        {/if}
        {#if source === 'folder'}
          <FolderSelect value={folder} onchange={(v) => { folder = v; reset(); }} placeholder="Choose the shoot's folder…" />
        {/if}
      </div>
      <div class="row">
        <Seg options={MODES} value={mode} onchange={setMode} label="Merge mode" />
      </div>
      <p class="hint">
        {#if mode === 'hdr'}Bracketed exposures of the same view, fused into one natural photo.
        {:else if mode === 'flambient'}Ambient frames plus flash pops: true colour from the flash, mood from the room's own light.
        {:else}Overlapping frames (about a third each) stitched into one wide photo.{/if}
      </p>
      <div class="row grid2">
        <label class="fld">
          <span class="mg-label">New set after a pause of (s)</span>
          <input class="mg-input" type="number" min="0.5" max="120" step="0.5" bind:value={gap} />
        </label>
        <label class="fld">
          <span class="mg-label">Frames per set (0 = work it out)</span>
          <input class="mg-input" type="number" min="0" max="60" step="1" bind:value={fixed} />
        </label>
      </div>
      <div class="row">
        <button class="mg-btn primary" onclick={scan} disabled={!canScan}>
          {#if scanning}<span class="mg-spin"></span>{:else}<Icon name="layers" size={15} />{/if}
          Find {mode === 'panorama' ? 'panoramas' : 'sets'}
        </button>
        {#if scanned}<span class="mg-count">{scanned.message}{scanned.ungrouped ? ` · ${scanned.ungrouped} frame${scanned.ungrouped === 1 ? '' : 's'} on their own` : ''}</span>{/if}
      </div>
    </div>

    {#if scanned && !groups.length}
      <Empty icon="layers" title="No sets found"
             hint="Try a longer pause, or set the number of frames you shoot per set." />
    {/if}

    {#each groups as g, n (g.key)}
      <article class="set mg-tile" class:off={!g.on}>
        <header>
          <label class="tick">
            <input type="checkbox" bind:checked={g.on} />
            <b>Set {n + 1}</b>
          </label>
          <span class="mg-count">{g.items.length} frame{g.items.length === 1 ? '' : 's'}</span>
          {#if mode === 'hdr' && engine === 'panel'}
            <button class="mg-btn ghost sm pv" onclick={() => openPreview(g)} disabled={!allowed || g.items.length < 2}>
              <Icon name={pvKey === g.key ? 'eyeOff' : 'eye'} size={14} />{pvKey === g.key ? 'Hide' : 'Preview'}
            </button>
          {/if}
        </header>
        <div class="frames mg-noscroll">
          {#each g.items as it (it.id)}
            <div class="fr" class:flash={mode === 'flambient' && it.flash}>
              {#if mode === 'flambient'}
                <button type="button" class="thumb" onclick={() => toggleFlash(it)}
                        title={it.flash ? 'Flash frame — tap for ambient' : 'Ambient frame — tap for flash'}>
                  {#if thumbUrl(it)}<img src={thumbUrl(it)} alt={it.filename} loading="lazy" />{/if}
                  <span class="tag">{it.flash ? 'Flash' : 'Ambient'}</span>
                </button>
              {:else}
                <div class="thumb">
                  {#if thumbUrl(it)}<img src={thumbUrl(it)} alt={it.filename} loading="lazy" />{/if}
                  {#if it.bias != null}<span class="tag">{it.bias > 0 ? '+' : ''}{it.bias} EV</span>{/if}
                </div>
              {/if}
              <span class="fn" title={it.filename}>{it.filename}</span>
              <button type="button" class="x" aria-label="Leave {it.filename} out of this set"
                      onclick={() => dropFrame(g, it.id)}><Icon name="x" size={12} /></button>
            </div>
          {/each}
        </div>
        {#if pvKey === g.key}
          <div class="pvbox">
            {#if pvUrl}<img src={pvUrl} alt="Preview of set {n + 1}" class:dim={pvBusy} />{/if}
            {#if pvBusy && !pvUrl}<div class="mg-bar indeterminate"><i></i></div>{/if}
            {#if pvErr}<p class="err">{pvErr}</p>{/if}
            <p class="hint">A small preview — move the sliders and it follows. The merge itself runs at full size.</p>
          </div>
        {/if}
      </article>
    {/each}
  </section>

  <!-- ——————————————————————————————————————— right: the settings ——— -->
  <aside class="col side">
    <div class="mg-panel card">
      <span class="mg-label">2 · Settings</span>

      {#if mode === 'hdr'}
        <Seg options={[{ value: 'panel', label: 'HDR engine' }, { value: 'classic', label: 'Classic fusion' }]}
             value={engine} onchange={(v) => { engine = v; if (v !== 'panel') closePreview(); }} label="Merge engine" />
        {#if engine === 'panel'}
          <Seg options={[{ value: 'natural', label: 'Natural' }, { value: 'hdr', label: 'Bold HDR' }]}
               value={look.method} onchange={(v) => (look.method = v)} label="Tone mapping" />
          <Range label="Window pull" bind:value={look.windows} min={0} max={1} def={HDR_LOOK.windows} fmt={pct}
                 hint="The view through bright windows, taken from the darkest frame." />
          <Range label="Exposure" bind:value={look.exposure} min={-2} max={2} step={0.1} def={HDR_LOOK.exposure} fmt={ev} />
          <Range label="Shadows" bind:value={look.shadows} min={-1} max={1} def={HDR_LOOK.shadows} fmt={sgn} />
          <Range label="Contrast" bind:value={look.contrast} min={-1} max={1} def={HDR_LOOK.contrast} fmt={sgn} />
          <Range label="Saturation" bind:value={look.saturation} min={-1} max={1} def={HDR_LOOK.saturation} fmt={sgn} />
          <Range label="Detail" bind:value={look.detail} min={0} max={1} def={HDR_LOOK.detail} fmt={pct} />
          <Range label="Warmth" bind:value={look.warmth} min={-1} max={1} def={HDR_LOOK.warmth} fmt={sgn} />
          <Range label="Noise smoothing" bind:value={look.noise} min={0} max={1} def={HDR_LOOK.noise} fmt={pct} />
          <label class="sw"><input type="checkbox" bind:checked={look.deghost} />
            <span>De-ghost <i>— trees, people, water that moved come from one frame</i></span></label>
          <button class="mg-btn ghost sm" onclick={() => (look = { ...HDR_LOOK })}><Icon name="undo" size={13} />Reset sliders</button>
        {:else}
          <p class="hint">Mertens exposure fusion — the pre-1.4 merge. Quick and safe, fewer controls.</p>
        {/if}
      {:else if mode === 'flambient'}
        <Range label="Ambient mix" bind:value={opts.ambient_mix} min={0} max={1} def={MERGE_DEFAULTS.ambient_mix} fmt={pct}
               hint="0 = all flash (clean, neutral) · 100 = mostly the room's own light." />
        <p class="hint">Tap a frame to switch it between flash and ambient. Each set needs at least one of each.</p>
      {:else}
        <p class="hint">Frames are stitched, then cropped to a clean rectangle. Shoot with about a third overlap.</p>
      {/if}

      <label class="sw"><input type="checkbox" bind:checked={opts.align} /><span>Align frames <i>— hand-held</i></span></label>
      {#if mode !== 'hdr' || engine === 'classic'}
        <label class="sw"><input type="checkbox" bind:checked={opts.polish} /><span>Polish <i>— a little contrast and colour back</i></span></label>
      {/if}

      <button type="button" class="more" onclick={() => (more = !more)} aria-expanded={more}>
        <Icon name={more ? 'chevronUp' : 'chevronDown'} size={14} />Output
      </button>
      {#if more}
        <div class="grid2">
          <label class="fld">
            <span class="mg-label">Format</span>
            <span class="mg-select"><select bind:value={opts.fmt}>
              <option value="jpg">JPEG</option><option value="tif">TIFF</option>
            </select><span class="ic"><Icon name="chevronDown" size={15} /></span></span>
          </label>
          {#if opts.fmt === 'jpg'}
            <label class="fld">
              <span class="mg-label">JPEG quality</span>
              <input class="mg-input" type="number" min="60" max="100" bind:value={opts.quality} />
            </label>
          {:else}
            <label class="sw"><input type="checkbox" bind:checked={opts.bits16} /><span>16-bit</span></label>
          {/if}
          <label class="fld">
            <span class="mg-label">Longest edge (px)</span>
            <input class="mg-input" type="number" min="1000" max="20000" step="500" bind:value={opts.max_dim} />
          </label>
          <label class="fld">
            <span class="mg-label">Subfolder</span>
            <input class="mg-input" type="text" maxlength="60" bind:value={opts.subfolder} />
          </label>
        </div>
        <p class="hint">"HDR" becomes "Flambient" or "Panorama" in those modes. Inside a project the stage's own folder is used.</p>
        <label class="sw"><input type="checkbox" bind:checked={opts.add_to_library} /><span>Add results to the library</span></label>
        {#if features.raw === false}
          <label class="sw"><input type="checkbox" bind:checked={opts.allow_preview_raw} />
            <span>Fuse RAW anyway <i>— from the small embedded preview</i></span></label>
        {/if}
      {/if}
    </div>

    <div class="mg-panel card go">
      <span class="mg-label">3 · Merge</span>
      <p class="sum mg-tnum">{chosen.length} set{chosen.length === 1 ? '' : 's'} · {frames} frame{frames === 1 ? '' : 's'}</p>
      {#if running}
        <div class="mg-bar"><i style:width="{job.total ? (job.done / job.total) * 100 : 5}%"></i></div>
        <p class="hint">{job.current || 'Working…'} · {job.done}/{job.total}</p>
        <button class="mg-btn secondary" onclick={cancel}><Icon name="stop" size={14} />Cancel</button>
      {:else}
        <button class="mg-btn accent lg" onclick={merge} disabled={!allowed || !chosen.length}>
          <Icon name="sparkles" size={16} />Merge {chosen.length || ''} set{chosen.length === 1 ? '' : 's'}
        </button>
      {/if}
    </div>

    {#if job && (job.results?.length || job.errors?.length)}
      <div class="mg-panel card">
        <span class="mg-label">Results</span>
        <ul class="res">
          {#each job.results as r (r.path)}
            <li>
              {#if r.id}<img src={photoUrl({ id: r.id }, 400)} alt="" loading="lazy" />{/if}
              <div class="rt">
                <b title={r.filename}>{r.filename}</b>
                <span class="mg-count">{r.frames} frames</span>
                {#if r.id}
                  <div class="acts">
                    <a class="mg-btn secondary sm" href="/media/edit?id={r.id}"><Icon name="sliders" size={13} />Edit</a>
                    <button class="mg-btn ghost sm" onclick={() => onlook?.(r.id)}><Icon name="wand" size={13} />Looks</button>
                  </div>
                {:else}
                  <span class="hint">Saved to disk, not in the library.</span>
                {/if}
              </div>
            </li>
          {/each}
        </ul>
        {#each job.errors || [] as e, i (i)}
          <p class="err">{e}</p>
        {/each}
      </div>
    {/if}
  </aside>
</div>

<style>
  .lay { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 16px; align-items: start; }
  .col { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  .side { position: sticky; top: calc(var(--mc-strip-h) + var(--sat) + 16px); }
  .card { padding: 16px; display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; align-items: end; }
  .fld { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
  .fld .mg-input, .fld select { width: 100%; }
  .hint { margin: 0; font: 400 12px/1.5 var(--mc-font); color: var(--mc-ink3); }
  .err { margin: 0; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-crit); overflow-wrap: anywhere; }
  .sw { display: flex; gap: 9px; align-items: flex-start; min-height: 28px; font: 500 12.5px/1.45 var(--mc-font); color: var(--mc-ink2); cursor: pointer; }
  .sw input { margin-top: 2px; accent-color: var(--mc-accent); width: 16px; height: 16px; flex: none; }
  .sw i { font-style: normal; color: var(--mc-ink3); font-weight: 400; }
  .more { display: inline-flex; gap: 6px; align-items: center; border: 0; background: none; color: var(--mc-ink2);
          font: 500 12.5px/1 var(--mc-font); cursor: pointer; padding: 6px 0; min-height: 32px; }

  .set { border-radius: var(--mc-r-md); padding: 12px; display: flex; flex-direction: column; gap: 10px; }
  .set.off { opacity: 0.5; }
  .set header { display: flex; align-items: center; gap: 10px; }
  .tick { display: flex; align-items: center; gap: 8px; cursor: pointer; min-height: 40px; }
  .tick input { width: 18px; height: 18px; accent-color: var(--mc-accent); }
  .tick b { font: 600 13px/1 var(--mc-font); color: var(--mc-ink); }
  .pv { margin-left: auto; }
  .frames { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 2px; }
  .fr { position: relative; flex: none; width: 132px; display: flex; flex-direction: column; gap: 4px; }
  .thumb { position: relative; display: block; width: 100%; aspect-ratio: 3 / 2; padding: 0; border: 2px solid transparent;
           border-radius: 10px; overflow: hidden; background: var(--mc-inset); cursor: default; }
  button.thumb { cursor: pointer; }
  .fr.flash .thumb { border-color: var(--mc-warn); }
  .thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .tag { position: absolute; left: 5px; bottom: 5px; padding: 3px 7px; border-radius: 9999px; background: var(--mc-raised);
         border: 1px solid var(--mc-line2); color: var(--mc-ink); font: 500 10.5px/1 var(--mc-font); }
  .fr.flash .tag { background: var(--mc-warn); border-color: var(--mc-warn); color: #231a02; }
  .fn { font: 400 11px/1.3 var(--mc-font); color: var(--mc-ink3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .x { position: absolute; top: 4px; right: 4px; width: 28px; height: 28px; border-radius: 50%;
       border: 1px solid var(--mc-line2); background: var(--mc-raised); color: var(--mc-ink); box-shadow: var(--mc-sh-1);
       display: grid; place-items: center; cursor: pointer; transition: color var(--mc-t-fast), border-color var(--mc-t-fast); }
  .x:hover { color: var(--mc-crit); border-color: var(--mc-crit-line); }
  .pvbox { display: flex; flex-direction: column; gap: 8px; }
  .pvbox img { width: 100%; border-radius: var(--mc-r-md); display: block; transition: opacity 0.2s; }
  .pvbox img.dim { opacity: 0.6; }

  .go .sum { margin: 0; font: 600 15px/1.2 var(--mc-font); color: var(--mc-ink); }
  .go .mg-btn.lg { width: 100%; }
  .res { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
  .res li { display: flex; gap: 10px; align-items: flex-start; min-width: 0; }
  .res img { width: 96px; aspect-ratio: 3 / 2; object-fit: cover; border-radius: 9px; flex: none; background: var(--mc-inset); }
  .rt { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .rt b { font: 600 12.5px/1.3 var(--mc-font); color: var(--mc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .acts { display: flex; gap: 6px; flex-wrap: wrap; }

  @media (pointer: coarse) {
    .sw, .more, .tick { min-height: 44px; align-items: center; }
    .sw input { margin-top: 0; }
    .x { width: 36px; height: 36px; }
    .col :global(.mg-btn.sm), .side :global(.mg-btn.sm) { min-height: 44px; }
  }
  @media (max-width: 960px) {
    .lay { grid-template-columns: minmax(0, 1fr); }
    .side { position: static; }
  }
  @media (max-width: 560px) {
    .acts .mg-btn, .pv { height: 40px; }
    .fr { width: 116px; }
  }
</style>
