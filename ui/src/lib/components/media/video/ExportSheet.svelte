<script>
  /* Getting the edit out, three ways:
       Render      — an MP4 made by ffmpeg on the server (/render, polled via
                     /api/video-render/{job}); downloaded, optionally kept in
                     a library folder too.
       DaVinci     — the timeline as FCPXML (/fcpxml), which Resolve imports
                     with File › Import › Timeline. Instant, no ffmpeg.
       Pack        — that timeline plus the footage it uses, one ZIP (/pack),
                     for finishing on another machine.
     All three are downloads, so the whole sheet needs media.download. */
  import { onDestroy, untrack } from 'svelte';
  import { mstate, loadFolders } from '$lib/media.svelte.js';
  import { vapi, poll, download } from '$lib/media/video.js';
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';

  let { open = false, onclose, row, data, onsave, canDownload = true, canUpload = false, say } = $props();

  const ffmpeg = $derived(mstate.status?.features?.ffmpeg !== false);

  let size = $state(1080);
  let quality = $state('high');
  let filename = $state('');
  let keep = $state(false);
  let folderId = $state(null);
  let proxies = $state(false);

  let job = $state(null);        // { id, kind: 'render'|'pack', status, progress, error, filename, saved_id }
  let stop = null;

  $effect(() => { if (open) untrack(() => { filename = row?.name || ''; if (!mstate.folders.length) loadFolders(); }); });
  onDestroy(() => stop?.());

  const flatFolders = $derived.by(() => {
    const out = [];
    const walk = (nodes, d) => { for (const n of nodes || []) { out.push({ id: n.id, name: n.name, d }); walk(n.children, d + 1); } };
    walk(mstate.folders, 0);
    return out;
  });

  function watch(id, kind) {
    stop?.();
    job = { id, kind, status: 'running', progress: 0 };
    stop = poll(() => vapi.job(id), (r, err) => {
      if (err) { job = { ...job, status: 'failed', error: err.message }; return; }
      job = { ...job, ...r };
      if (r.status === 'done') {
        say?.(kind === 'pack' ? 'Resolve pack ready' : 'Render finished');
        fetchFile();
      } else if (r.status === 'failed') say?.(kind === 'pack' ? 'The pack failed' : 'The render failed', 'error');
    }, (r) => r.status !== 'running');
  }

  async function render() {
    try {
      const body = { size, quality, filename: filename.trim() || null, data };
      if (keep && folderId) body.save_folder_id = folderId;
      const r = await vapi.render(row.id, body);
      watch(r.id, 'render');
    } catch (e) { say?.(e.message, 'error'); }
  }

  async function pack() {
    try {
      await onsave?.();
      const r = await vapi.pack(row.id, proxies);
      watch(r.id, 'pack');
    } catch (e) { say?.(e.message, 'error'); }
  }

  async function cancel() {
    if (!job) return;
    try { await vapi.cancel(job.id); } catch (e) { say?.(e.message, 'error'); }
  }

  async function fetchFile() {
    if (!job) return;
    download(await vapi.jobFileUrl(job.id), job.filename || '');
  }

  async function resolve() {
    try {
      await onsave?.();
      download(await vapi.fcpxmlUrl(row.id));
      say?.('Timeline downloaded — in Resolve: File › Import › Timeline');
    } catch (e) { say?.(e.message, 'error'); }
  }

  const SIZES = [{ value: 720, label: '720p' }, { value: 1080, label: '1080p' }, { value: 2160, label: '4K' }];
  const QUALS = [{ value: 'high', label: 'High quality' }, { value: 'small', label: 'Smaller file' }];
  const busy = $derived(job?.status === 'running');
</script>

<Sheet {open} title="Export" size="md" {onclose}>
  {#if !canDownload}
    <div class="mg-strip warn"><span class="ic"><Icon name="lock" size={15} /></span>
      <span>Your account cannot download files, so renders and timelines are off.</span></div>
  {/if}

  <section>
    <h3><Icon name="film" size={15} />Render a video</h3>
    {#if !ffmpeg}
      <p class="why">Rendering needs ffmpeg on the server, and this deployment doesn't have it.</p>
    {/if}
    <div class="row"><Seg options={SIZES} value={size} onchange={(v) => (size = v)} label="Size" /></div>
    <div class="row"><Seg options={QUALS} value={quality} onchange={(v) => (quality = v)} label="Quality" /></div>
    <label class="f"><span class="mg-label">File name</span>
      <input class="mg-input" bind:value={filename} maxlength="150" placeholder={row?.name} /></label>
    {#if canUpload}
      <label class="tg"><input type="checkbox" bind:checked={keep} />Also keep it in the library</label>
      {#if keep}
        <span class="mg-select full">
          <select bind:value={folderId} aria-label="Library folder">
            <option value={null}>Choose a folder…</option>
            {#each flatFolders as f (f.id)}<option value={f.id}>{'  '.repeat(f.d)}{f.name}</option>{/each}
          </select>
          <span class="ic"><Icon name="chevronDown" size={14} /></span>
        </span>
      {/if}
    {/if}
    {#if data?.titles?.length}
      <p class="why">This edit has {data.titles.length} title{data.titles.length === 1 ? '' : 's'}; titles are drawn by the full editor and are left out of renders made here (they still go to Resolve).</p>
    {/if}
    <button type="button" class="mg-btn accent" disabled={!ffmpeg || !canDownload || busy || !data?.clips?.length || (keep && !folderId)}
            onclick={render}>
      <Icon name="play" size={15} />Render {size === 2160 ? '4K' : size + 'p'}
    </button>
  </section>

  <section>
    <h3><Icon name="layers" size={15} />DaVinci Resolve</h3>
    <p class="why">The timeline as FCPXML — every clip, trim, speed, transition, music piece, volume and title where you put it.
      In Resolve: <b>File › Import › Timeline</b>. The clips link to the originals on this drive; colour is left for Resolve.</p>
    <div class="btns">
      <button type="button" class="mg-btn secondary" disabled={!canDownload || !data?.clips?.length} onclick={resolve}>
        <Icon name="download" size={15} />Export for DaVinci Resolve
      </button>
    </div>
    <p class="why">Finishing on another machine? A pack zips the timeline with the footage it uses.</p>
    <label class="tg"><input type="checkbox" bind:checked={proxies} />Pack the smaller proxy copies instead of originals</label>
    <div class="btns">
      <button type="button" class="mg-btn secondary" disabled={!canDownload || busy || !data?.clips?.length} onclick={pack}>
        <Icon name="box" size={15} />Make a Resolve pack (ZIP)
      </button>
    </div>
  </section>

  {#if job}
    <section class="job mg-glass-soft">
      <div class="jh">
        <b>{job.kind === 'pack' ? 'Resolve pack' : 'Render'}</b>
        <span class="mg-chip {job.status === 'done' ? 'ok' : job.status === 'running' ? 'warn' : 'crit'}">{job.status}</span>
        <span class="mg-tnum pc">{Math.round((job.progress || 0) * 100)}%</span>
      </div>
      <div class="mg-bar"><i style:width="{(job.progress || 0) * 100}%"></i></div>
      {#if job.error && job.status !== 'running'}<pre class="err">{job.error}</pre>{/if}
      {#if job.saved_id}<p class="why">Kept in the library (clip #{job.saved_id}).</p>{/if}
      {#if job.save_error}<p class="why">Couldn't keep it in the library: {job.save_error}</p>{/if}
      <div class="btns">
        {#if busy}
          <button type="button" class="mg-btn danger sm" onclick={cancel}><Icon name="stop" size={13} />Cancel</button>
        {:else if job.status === 'done'}
          <button type="button" class="mg-btn accent sm" onclick={fetchFile}><Icon name="download" size={13} />Download {job.filename}</button>
        {/if}
      </div>
    </section>
  {/if}
</Sheet>

<style>
  section { display: flex; flex-direction: column; gap: 10px; padding: 4px 0 18px; }
  section + section { border-top: 1px solid var(--mg-line); padding-top: 16px; }
  h3 { margin: 0; display: flex; align-items: center; gap: 8px; font: 600 14px/1.3 var(--mg-font); color: var(--mg-i); }
  .row { overflow-x: auto; }
  .f { display: flex; flex-direction: column; gap: 5px; }
  .full, .full > select { width: 100%; }
  .why { margin: 0; font-size: 12.5px; line-height: 1.55; color: var(--mg-i3); }
  .why b { color: var(--mg-i2); font-weight: 600; }
  .tg { display: inline-flex; align-items: center; gap: 8px; min-height: 40px; font-size: 13px; color: var(--mg-i2); cursor: pointer; }
  .tg input { width: 18px; height: 18px; accent-color: var(--mg-ok); }
  .btns { display: flex; gap: 8px; flex-wrap: wrap; }
  .job { border-radius: var(--mg-r-in); padding: 12px 14px; border-top: 0 !important; margin-top: 4px; }
  .jh { display: flex; align-items: center; gap: 8px; }
  .jh b { font-size: 13px; color: var(--mg-i); }
  .pc { margin-left: auto; font-size: 12.5px; color: var(--mg-i2); }
  .err { margin: 0; max-height: 120px; overflow: auto; white-space: pre-wrap; font: 11px/1.45 var(--mg-mono); color: var(--mg-crit); }
</style>
