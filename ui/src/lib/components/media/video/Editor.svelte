<script>
  /* One edit open: preview on the left, the selected clip (or the project's
     own settings) on the right, the timeline underneath.

     The project document is held here as one $state object and every panel
     mutates it in place; any change schedules a save (PUT with the whole
     document ~0.8s after the last touch), so there is no Save button to
     forget. Music pieces and titles the backend model carries are kept
     untouched — this editor doesn't draw them, but it never drops them. */
  import { onMount, onDestroy } from 'svelte';
  import { say } from '$lib/media.svelte.js';
  import { vapi, newClip, layout, tc } from '$lib/media/video.js';
  import PreviewPlayer from './PreviewPlayer.svelte';
  import Timeline from './Timeline.svelte';
  import ClipInspector from './ClipInspector.svelte';
  import ProjectPanel from './ProjectPanel.svelte';
  import ClipPicker from './ClipPicker.svelte';
  import ExportSheet from './ExportSheet.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';

  let { id, caps = new Set() } = $props();

  const canEdit = $derived(caps.has('media.upload'));
  const canDownload = $derived(caps.has('media.download'));

  let row = $state(null);
  let data = $state(null);
  let err = $state(null);
  let info = $state({});           // video_id -> probe
  let luts = $state([]);
  let selected = $state(null);
  let tab = $state('clip');
  let time = $state(0);
  let picking = $state(false);
  let exporting = $state(false);
  let saveState = $state('saved'); // saved | dirty | saving | error
  let name = $state('');
  let timer = null;

  onMount(async () => {
    try {
      row = await vapi.project(id);
      data = row.data;
      name = row.name;
      selected = data.clips[0]?.id ?? null;
      if (!data.clips.length) tab = 'project';
      probeAll();
    } catch (e) { err = e.message; }
    loadLuts();
  });
  onDestroy(() => { if (saveState === 'dirty') flush(); });

  async function loadLuts() {
    try { luts = (await vapi.luts()).luts || []; } catch { luts = []; }
  }

  function probeAll() {
    const ids = new Set([...data.clips.map((c) => c.video_id), ...(data.music || []).map((m) => m.video_id)]);
    for (const vid of ids) if (!info[vid]) probe(vid);
  }
  async function probe(vid) {
    try { const p = await vapi.probe(vid); info = { ...info, [vid]: p }; return p; }
    catch { return null; }
  }

  const names = $derived(Object.fromEntries(Object.entries(info).map(([k, v]) => [k, v?.filename])));
  const selIdx = $derived(data ? data.clips.findIndex((c) => c.id === selected) : -1);
  const selClip = $derived(selIdx >= 0 ? data.clips[selIdx] : null);
  const total = $derived(data ? layout(data).total : 0);

  /* ——— saving ——— */
  function changed() {
    if (!canEdit) return;
    saveState = 'dirty';
    clearTimeout(timer);
    timer = setTimeout(flush, 800);
  }
  async function flush() {
    clearTimeout(timer);
    if (!canEdit || !data) return;
    saveState = 'saving';
    try {
      await vapi.save(id, { data: $state.snapshot(data) });
      saveState = saveState === 'saving' ? 'saved' : saveState;
    } catch (e) { saveState = 'error'; say(e.message, 'error'); }
  }
  async function rename() {
    const n = name.trim();
    if (!n || n === row.name || !canEdit) { name = row.name; return; }
    try { await vapi.save(id, { name: n }); row.name = n; }
    catch (e) { say(e.message, 'error'); name = row.name; }
  }

  /* ——— timeline edits ——— */
  async function addClips(vs) {
    picking = false;
    const at = selIdx >= 0 ? selIdx + 1 : data.clips.length;
    const fresh = [];
    for (const v of vs) {
      const p = info[v.id] || (await probe(v.id));
      const dur = p?.duration || v.duration || 5;
      if (!data.clips.length && !fresh.length && p?.fps) data.fps = p.fps;
      fresh.push(newClip(v.id, dur));
    }
    data.clips.splice(at, 0, ...fresh);
    if (fresh.length) { selected = fresh[0].id; tab = 'clip'; }
    changed();
  }

  function move(from, to) {
    if (to < 0 || to >= data.clips.length || from === to) return;
    const [c] = data.clips.splice(from, 1);
    data.clips.splice(to, 0, c);
    changed();
  }

  function removeSel() {
    if (selIdx < 0) return;
    data.clips.splice(selIdx, 1);
    selected = data.clips[Math.min(selIdx, data.clips.length - 1)]?.id ?? null;
    changed();
  }

  function duplicateSel() {
    if (!selClip) return;
    const c = { ...$state.snapshot(selClip), id: newClip(0, 1).id };
    data.clips.splice(selIdx + 1, 0, c);
    selected = c.id;
    changed();
  }

  async function uploadLut(file) {
    try {
      const r = await vapi.uploadLut(file).promise;
      say(`Added ${r.name}`);
      await loadLuts();
    } catch (e) { say(e.message, 'error'); }
  }

  const SAVE_LABEL = { saved: 'Saved', dirty: 'Unsaved…', saving: 'Saving…', error: 'Not saved' };
  const TABS = $derived([
    { value: 'clip', label: 'Clip', icon: 'scissors' },
    { value: 'project', label: 'Edit settings', icon: 'sliders' }
  ]);
</script>

{#if err}
  <Empty icon="alert" title="Couldn't open that edit" hint={err}>
    {#snippet children()}<a class="mg-btn secondary sm" href="/media/video"><Icon name="arrowLeft" size={14} />All edits</a>{/snippet}
  </Empty>
{:else if !data}
  <p class="loading">Opening the edit…</p>
{:else}
  <div class="mg-row head">
    <a class="mg-btn ghost icon" href="/media/video" aria-label="All edits" title="All edits"><Icon name="arrowLeft" size={16} /></a>
    <input class="nm" bind:value={name} onblur={rename} onkeydown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
           readonly={!canEdit} aria-label="Edit name" maxlength="160" />
    <span class="mg-chip {saveState === 'error' ? 'crit' : saveState === 'saved' ? '' : 'warn'}">
      {canEdit ? SAVE_LABEL[saveState] : 'Read only'}
    </span>
    <div class="mg-actions">
      {#if canEdit}
        <button type="button" class="mg-btn secondary" onclick={() => (picking = true)}>
          <Icon name="plus" size={15} />Add clips
        </button>
      {/if}
      <button type="button" class="mg-btn accent" onclick={async () => { if (saveState === 'dirty') await flush(); exporting = true; }}
              disabled={!data.clips.length}>
        <Icon name="download" size={15} />Export
      </button>
    </div>
  </div>

  <div class="top">
    <div class="pvw mg-glass-soft">
      <PreviewPlayer project={data} bind:time />
    </div>
    {#if data.clips.length}
      <div class="tlw">
        <Timeline project={data} {selected} {time} {names}
                  onselect={(cid) => { selected = cid; tab = 'clip'; }}
                  onmove={canEdit ? move : undefined}
                  onseek={(t) => (time = t)} />
      </div>
    {/if}
    <div class="side mg-glass-soft">
      <div class="tabs mg-noscroll"><Seg options={TABS} value={tab} onchange={(v) => (tab = v)} label="Panel" /></div>
      <fieldset disabled={!canEdit}>
        {#if tab === 'clip'}
          {#if selClip}
            {#key selClip.id}
              <ClipInspector clip={selClip} info={info[selClip.video_id]} project={data} {luts}
                             index={selIdx} count={data.clips.length} isLast={selIdx === data.clips.length - 1}
                             onchange={changed} onremove={removeSel} onmove={(a, b) => move(a, b)}
                             onduplicate={duplicateSel} />
            {/key}
          {:else}
            <Empty icon="film" title={data.clips.length ? 'Pick a clip on the timeline' : 'No clips yet'}
                   hint={data.clips.length ? 'Its trim, speed, sound, transition and look show here.' : 'Add clips from the library to start the edit.'}>
              {#snippet children()}
                {#if canEdit && !data.clips.length}
                  <button type="button" class="mg-btn accent sm" onclick={() => (picking = true)}><Icon name="plus" size={14} />Add clips</button>
                {/if}
              {/snippet}
            </Empty>
          {/if}
        {:else}
          <ProjectPanel project={data} {luts} canUpload={canEdit} onchange={changed} onuploadlut={uploadLut} />
        {/if}
      </fieldset>
    </div>
  </div>

  <p class="foot mg-tnum">{data.clips.length} clip{data.clips.length === 1 ? '' : 's'} · {tc(total)} · {data.aspect}</p>

  <ClipPicker open={picking} onclose={() => (picking = false)} onpick={addClips} />
  <ExportSheet open={exporting} onclose={() => (exporting = false)} {row} data={$state.snapshot(data)}
               onsave={flush} {canDownload} canUpload={canEdit} {say} />
{/if}

<style>
  .loading { color: var(--mg-i3); font-size: 13px; }
  .head { gap: 8px; }
  .nm {
    flex: 1 1 200px; min-width: 0; max-width: 32rem; height: 40px; padding: 0 12px; border-radius: 12px;
    background: transparent; border: 1px solid transparent; color: var(--mg-i);
    font: 600 18px/1.2 var(--mg-font); letter-spacing: -0.01em;
  }
  .nm:hover:not([readonly]) { border-color: var(--mg-line); }
  .nm:focus { outline: none; border-color: rgba(62, 207, 142, 0.6); background: var(--mg-glass-soft); }
  .top {
    display: grid; grid-template-columns: minmax(260px, 420px) minmax(0, 1fr); gap: 14px; align-items: start;
    grid-template-areas: 'pv side' 'tl tl';
  }
  .pvw { grid-area: pv; border-radius: var(--mg-r-card); padding: 12px; min-width: 0; }
  .tlw { grid-area: tl; min-width: 0; }
  .side { grid-area: side; border-radius: var(--mg-r-card); padding: 12px 14px 16px; min-width: 0; }
  .tabs { margin-bottom: 14px; overflow-x: auto; }
  fieldset { border: 0; margin: 0; padding: 0; min-width: 0; }
  .foot { margin: 10px 4px 0; font-size: 12px; color: var(--mg-i3); }
  @media (max-width: 900px) {
    .top { grid-template-columns: minmax(0, 1fr); grid-template-areas: 'pv' 'tl' 'side'; }
  }
  @media (max-width: 560px) {
    .head .mg-actions { margin-left: 0; width: 100%; }
    .head .mg-actions > * { flex: 1; }
  }
</style>
