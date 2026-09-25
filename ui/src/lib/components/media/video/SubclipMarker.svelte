<script>
  /* Sub-clips on one library clip (/media/video?clip=<id>).

     Mark an in and an out, keep the range (/api/subclips — the range is the
     record, nothing is rendered yet). Then, for any set of ranges:
       Download   — /api/cuts/download: rendered to temp and handed over, one
                    file or a ZIP; nothing written to the drive.
       Keep       — /api/subclips/{id}/export: rendered into a "Clips" folder
                    beside the source and indexed as an ordinary clip.
       Edit       — a new video-editor project seeded with the ranges.
     Fast = stream copy (seconds; starts on the keyframe before IN).
     Exact = re-encode (frame-accurate, slower). */
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { mstate, say } from '$lib/media.svelte.js';
  import { fmtDuration } from '$lib/media.js';
  import { vapi, poll, download, tc } from '$lib/media/video.js';
  import Trimmer from './Trimmer.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';

  let { videoId, caps = new Set() } = $props();

  const canMark = $derived(caps.has('media.annotate'));
  const canKeep = $derived(caps.has('media.upload'));
  const canDownload = $derived(caps.has('media.download'));
  const canEdit = $derived(caps.has('media.upload'));
  const ffmpeg = $derived(mstate.status?.features?.ffmpeg !== false);

  let video = $state(null);
  let fps = $state(25);
  let err = $state(null);
  let subs = $state([]);
  let inPt = $state(0);
  let outPt = $state(null);
  let name = $state('');
  let editing = $state(null);      // sub-clip id being re-marked
  let picked = $state(new Set());
  let mode = $state('fast');
  let cut = $state(null);          // cuts job status
  let stopCut = null;
  let listTimer = null;

  onMount(async () => {
    try {
      video = await vapi.video(videoId);
      if ((video.media_type || 'video') !== 'video' && video.media_type !== 'audio') err = 'Only video and audio have a timeline.';
      outPt = video.duration || null;
      vapi.probe(videoId).then((p) => { if (p?.fps) fps = p.fps; if (!video.duration && p?.duration) { video.duration = p.duration; outPt = p.duration; } }).catch(() => {});
      await loadSubs();
    } catch (e) { err = e.message; }
  });
  onDestroy(() => { stopCut?.(); clearTimeout(listTimer); });

  async function loadSubs() {
    clearTimeout(listTimer);
    try { subs = (await vapi.subclips(videoId)).subclips || []; }
    catch (e) { say(e.message, 'error'); }
    if (subs.some((s) => s.status === 'queued' || s.status === 'processing')) listTimer = setTimeout(loadSubs, 1500);
  }

  const ranges = $derived(subs.filter((s) => s.id !== editing).map((s) => ({ id: s.id, start: s.start, end: s.end })));
  const outV = $derived(outPt ?? video?.duration ?? 0);

  async function saveRange() {
    try {
      if (editing) {
        await vapi.editSub(editing, { start: inPt, end: outV, name: name.trim() || '' });
        say('Range updated');
      } else {
        await vapi.addSub({ video_id: videoId, start: inPt, end: outV, name: name.trim() || null });
        say('Range kept');
      }
      editing = null;
      name = '';
      loadSubs();
    } catch (e) { say(e.message, 'error'); }
  }

  function load(s) {
    editing = s.id;
    inPt = s.start;
    outPt = s.end;
    name = s.name || '';
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function cancelEdit() { editing = null; name = ''; }

  async function remove(s) {
    try { await vapi.delSub(s.id); if (editing === s.id) cancelEdit(); loadSubs(); }
    catch (e) { say(e.message, 'error'); }
  }

  async function keep(s) {
    try { await vapi.exportSub(s.id, mode); say('Rendering into the library…'); loadSubs(); }
    catch (e) { say(e.message, 'error'); }
  }

  async function fileOf(s) { download(await vapi.subFileUrl(s.id), s.output_filename || ''); }

  function togglePick(id) {
    const n = new Set(picked);
    n.has(id) ? n.delete(id) : n.add(id);
    picked = n;
  }

  async function startCuts(body) {
    stopCut?.();
    try {
      const r = await vapi.cuts({ mode, zip_name: ((video?.filename || 'Clip').replace(/\.[^.]+$/, '').slice(0, 100) + ' cuts'), ...body });
      cut = { id: r.id, status: 'running', done: 0, total: r.total };
      stopCut = poll(() => vapi.cutsStatus(r.id), async (j, e) => {
        if (e) { cut = { ...cut, status: 'failed', errors: [e.message] }; return; }
        cut = j;
        if (j.status === 'done') { download(await vapi.cutsFileUrl(j.id), j.filename || ''); say('Cuts ready'); }
        else if (j.status === 'failed') say('The export failed', 'error');
      }, (j) => j.status !== 'running');
    } catch (e) { say(e.message, 'error'); }
  }

  const downloadRange = () => startCuts({ items: [{ video_id: videoId, start: inPt, end: outV, name: name.trim() || null }] });
  const downloadPicked = () => startCuts({ subclip_ids: subs.filter((s) => picked.has(s.id)).map((s) => s.id) });

  async function newEdit(fromPicked) {
    try {
      const body = fromPicked
        ? { name: `${video.filename} — selects`, subclip_ids: subs.filter((s) => picked.has(s.id)).map((s) => s.id) }
        : { name: video.filename, video_ids: [videoId] };
      const p = await vapi.create(body);
      goto(`/media/video?project=${p.id}`);
    } catch (e) { say(e.message, 'error'); }
  }

  const MODES = [{ value: 'fast', label: 'Fast' }, { value: 'exact', label: 'Exact' }];
  const chip = (s) => ({ done: 'ok', failed: 'crit', queued: 'warn', processing: 'warn' })[s] || '';
  const noFf = "Rendering needs ffmpeg on the server, and this deployment doesn't have it.";
</script>

{#if err}
  <Empty icon="alert" title="Can't mark this clip" hint={err}>
    {#snippet children()}<a class="mg-btn secondary sm" href="/media/video"><Icon name="arrowLeft" size={14} />Video editor</a>{/snippet}
  </Empty>
{:else if !video}
  <p class="loading">Opening the clip…</p>
{:else}
  <div class="mg-row">
    <a class="mg-btn ghost icon" href="/media/video" aria-label="Video editor" title="Video editor"><Icon name="arrowLeft" size={16} /></a>
    <h2 class="mg-h2 ttl">Sub-clips · {video.filename}</h2>
    <span class="mg-count mg-tnum">{fmtDuration(video.duration)}</span>
    {#if canEdit}
      <div class="mg-actions">
        <button type="button" class="mg-btn secondary" onclick={() => newEdit(false)}>
          <Icon name="film" size={15} />New edit with this clip
        </button>
      </div>
    {/if}
  </div>

  <div class="lay">
    <div class="mark mg-glass-soft">
      <Trimmer {video} {inPt} {outPt} {fps} {ranges} onchange={(a, b) => { inPt = a; outPt = b; }} />
      <div class="save">
        <input class="mg-input" bind:value={name} maxlength="200" placeholder="Name this range (optional)" aria-label="Range name" />
        {#if canMark}
          <button type="button" class="mg-btn accent" onclick={saveRange} disabled={outV - inPt < 0.1}>
            <Icon name={editing ? 'check' : 'plus'} size={15} />{editing ? 'Update range' : 'Keep range'}
          </button>
        {/if}
        {#if editing}<button type="button" class="mg-btn ghost" onclick={cancelEdit}>Cancel</button>{/if}
        {#if canDownload}
          <button type="button" class="mg-btn secondary" onclick={downloadRange} disabled={!ffmpeg || cut?.status === 'running'}
                  title={ffmpeg ? 'Download just this range' : noFf}>
            <Icon name="download" size={15} />Download range
          </button>
        {/if}
      </div>
      <p class="hint">Drag the green handles or press <kbd>I</kbd> / <kbd>O</kbd> at the playhead. Purple bands are ranges you've kept.</p>
    </div>

    <div class="list mg-glass-soft">
      <div class="lh">
        <span class="mg-label">Kept ranges · {subs.length}</span>
        <span class="sp"></span>
        <Seg options={MODES} value={mode} onchange={(v) => (mode = v)} label="Render mode" />
      </div>
      <p class="hint">{mode === 'fast' ? 'Fast copies the stream — seconds, but a cut can start up to a keyframe early.' : 'Exact re-encodes — frame-accurate, slower.'}</p>
      {#if !ffmpeg}<p class="hint warn">{noFf}</p>{/if}

      {#if !subs.length}
        <Empty icon="scissors" title="No ranges yet" hint="Mark an in and an out above and keep it." />
      {:else}
        <div class="rows">
          {#each subs as s (s.id)}
            <div class="r" class:on={editing === s.id}>
              <label class="pk"><input type="checkbox" checked={picked.has(s.id)} onchange={() => togglePick(s.id)}
                                       aria-label="Select {s.name || 'range'}" /></label>
              <button type="button" class="info" onclick={() => load(s)} title="Load into the scrubber">
                <img src={vapi.frameUrl(videoId, s.start, 120)} alt="" loading="lazy" />
                <span class="tx">
                  <b>{s.name || 'Untitled range'}</b>
                  <span class="mg-tnum">{tc(s.start)} → {tc(s.end)} · {s.duration.toFixed(1)}s</span>
                </span>
              </button>
              {#if s.status !== 'marked'}<span class="mg-chip {chip(s.status)}">{s.status === 'done' ? 'in library' : s.status}</span>{/if}
              <div class="acts">
                {#if s.status === 'done' && s.output_video_id && canDownload}
                  <button type="button" class="mg-btn ghost icon" title="Download {s.output_filename}" aria-label="Download file"
                          onclick={() => fileOf(s)}><Icon name="download" size={15} /></button>
                {/if}
                {#if canKeep}
                  <button type="button" class="mg-btn ghost icon" aria-label="Save to library"
                          title={ffmpeg ? `Save to library (${mode})` : noFf}
                          disabled={!ffmpeg || s.status === 'queued' || s.status === 'processing'}
                          onclick={() => keep(s)}><Icon name="inbox" size={15} /></button>
                {/if}
                {#if canMark}
                  <button type="button" class="mg-btn ghost icon" aria-label="Delete range" title="Forget this range"
                          disabled={s.status === 'queued' || s.status === 'processing'}
                          onclick={() => remove(s)}><Icon name="trash" size={15} /></button>
                {/if}
              </div>
              {#if s.status === 'failed' && s.error}<pre class="err">{s.error}</pre>{/if}
            </div>
          {/each}
        </div>

        <div class="bulk">
          <button type="button" class="mg-btn ghost sm" onclick={() => (picked = picked.size === subs.length ? new Set() : new Set(subs.map((s) => s.id)))}>
            {picked.size === subs.length ? 'Select none' : 'Select all'}
          </button>
          <span class="sp"></span>
          {#if canEdit}
            <button type="button" class="mg-btn secondary sm" disabled={!picked.size} onclick={() => newEdit(true)}>
              <Icon name="film" size={14} />New edit from {picked.size || ''} selected
            </button>
          {/if}
          {#if canDownload}
            <button type="button" class="mg-btn accent sm" disabled={!picked.size || !ffmpeg || cut?.status === 'running'} onclick={downloadPicked}>
              <Icon name="download" size={14} />Download {picked.size > 1 ? `${picked.size} cuts (ZIP)` : 'cut'}
            </button>
          {/if}
        </div>
      {/if}

      {#if cut}
        <div class="job">
          <div class="jh">
            <b>Cuts</b>
            <span class="mg-chip {cut.status === 'done' ? 'ok' : cut.status === 'running' ? 'warn' : 'crit'}">{cut.status}</span>
            <span class="mg-tnum pc">{cut.done}/{cut.total}</span>
          </div>
          <div class="mg-bar"><i style:width="{cut.total ? (cut.done / cut.total) * 100 : 0}%"></i></div>
          {#if cut.current}<p class="hint">{cut.current}</p>{/if}
          {#each cut.errors || [] as e (e)}<pre class="err">{e}</pre>{/each}
          {#if cut.status === 'done'}
            <button type="button" class="mg-btn secondary sm" onclick={async () => download(await vapi.cutsFileUrl(cut.id), cut.filename || '')}>
              <Icon name="download" size={13} />Download {cut.filename} again
            </button>
          {/if}
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .loading { color: var(--mc-ink3); font-size: 13px; }
  .ttl { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }
  .lay { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr); gap: 14px; align-items: start; }
  .mark, .list { border-radius: var(--mc-r-md); padding: 12px 14px 14px; min-width: 0; display: flex; flex-direction: column; gap: 12px; }
  .save { display: flex; gap: 8px; flex-wrap: wrap; }
  .save .mg-input { flex: 1 1 200px; min-width: 0; }
  .hint { margin: 0; font-size: 12px; line-height: 1.5; color: var(--mc-ink3); }
  .hint.warn { color: var(--mc-warn); }
  kbd { font: 600 11px/1 var(--mc-mono); padding: 2px 5px; border-radius: 4px; background: rgba(255, 255, 255, 0.1); color: var(--mc-ink2); }
  .lh { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .lh .sp, .bulk .sp { flex: 1; }
  .rows { display: flex; flex-direction: column; gap: 6px; }
  .r {
    display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding: 6px; border-radius: 12px;
    border: 1px solid var(--mc-line); background: rgba(255, 255, 255, 0.03);
  }
  .r.on { border-color: var(--mc-accent); }
  .pk { display: grid; place-items: center; width: 36px; height: 40px; cursor: pointer; }
  .pk input { width: 18px; height: 18px; accent-color: var(--mc-accent); }
  .info { flex: 1 1 160px; min-width: 0; display: flex; align-items: center; gap: 10px; background: none; border: 0; padding: 0; text-align: left; cursor: pointer; color: var(--mc-ink2); }
  .info img { width: 64px; height: 36px; object-fit: cover; border-radius: 6px; background: var(--mc-inset); flex: none; }
  .tx { display: flex; flex-direction: column; gap: 2px; min-width: 0; font-size: 12px; }
  .tx b { color: var(--mc-ink); font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .acts { display: flex; gap: 2px; margin-left: auto; }
  .bulk { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .job { display: flex; flex-direction: column; gap: 8px; padding-top: 10px; border-top: 1px solid var(--mc-line); }
  .jh { display: flex; align-items: center; gap: 8px; }
  .jh b { font-size: 13px; color: var(--mc-ink); }
  .pc { margin-left: auto; font-size: 12.5px; color: var(--mc-ink2); }
  .err { margin: 0; width: 100%; max-height: 100px; overflow: auto; white-space: pre-wrap; font: 11px/1.45 var(--mc-mono); color: var(--mc-crit); }
  @media (max-width: 900px) { .lay { grid-template-columns: minmax(0, 1fr); } }
</style>
