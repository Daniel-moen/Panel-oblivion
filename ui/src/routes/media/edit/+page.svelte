<script>
  /* The photo editor (Zerko 1.2 editor, 1.3 Remove tool, window pull and
     virtual copies).

     /media/edit?id=<photo>[&copy=<virtual copy>]; with no id, a picker.

     Rendering is the server's: each change is saved (debounced) to
     /api/photo-edit/{id} and the preview reloads /developed for the saved
     recipe — see components/media/editor/editor.svelte.js. The page wires
     the preview's pointer tools (crop box, remove brush, click-to-select,
     the 100% loupe) to the panels, mapping where you pointed on the
     developed frame back into the source photo with photoedit.sourceUV(). */
  import { onMount, untrack } from 'svelte';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { mstate, boot, say } from '$lib/media.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import { pop, fade } from '$lib/motion.js';
  import { photoUrl } from '$lib/media.js';
  import {
    pe, developedUrl, baseUrl, tileUrl, sourceUV, displayToSourceScale, fullRecipe, MASK_DEFAULTS, isDefault
  } from '$lib/media/photoedit.js';
  import { createEditor } from '$lib/components/media/editor/editor.svelte.js';
  import Preview from '$lib/components/media/editor/Preview.svelte';
  import AdjustPanel from '$lib/components/media/editor/AdjustPanel.svelte';
  import GeometryPanel from '$lib/components/media/editor/GeometryPanel.svelte';
  import RemovePanel from '$lib/components/media/editor/RemovePanel.svelte';
  import WindowsPanel from '$lib/components/media/editor/WindowsPanel.svelte';
  import MasksPanel from '$lib/components/media/editor/MasksPanel.svelte';
  import VersionsPanel from '$lib/components/media/editor/VersionsPanel.svelte';
  import ExportPanel from '$lib/components/media/editor/ExportPanel.svelte';
  import CopySettings from '$lib/components/media/editor/CopySettings.svelte';
  import PhotoPicker from '$lib/components/media/editor/PhotoPicker.svelte';

  const api = createEditor();
  const ed = api.ed;

  /* ------------------------------------------------------------ the photo */
  const qid = $derived(Number(page.url.searchParams.get('id')) || null);
  const qcopy = $derived(Number(page.url.searchParams.get('copy')) || null);

  let clip = $state(null);
  let clipError = $state(null);
  let srcSize = $state(null);
  let copies = $state([]);
  let siblings = $state([]);
  let siblingsFolder = null;
  let pick = $state(0);
  let caps = $state({ annotate: true, upload: true, admin: false });
  let ready = $state(false);

  const features = $derived(mstate.status?.features || {});
  const copyName = $derived(copies.find((c) => c.id === ed.copy)?.name || null);
  const srcAspect = $derived(srcSize ? srcSize.w / srcSize.h : 1.5);

  onMount(async () => {
    await boot();
    if (!mstate.ready) return;
    try {
      const me = await pe.me();
      const c = new Set(me.capabilities || []);
      caps = { annotate: c.has('media.annotate'), upload: c.has('media.upload'), admin: c.has('admin') };
    } catch { /* keep the optimistic defaults; the server still checks */ }
    ed.canEdit = caps.annotate;
    ready = true;

    const onKey = (e) => {
      const t = e.target;
      if (t && (t.tagName === 'INPUT' && t.type !== 'range' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        e.shiftKey ? api.redoStep() : api.undo();
      } else if (!e.metaKey && !e.ctrlKey && (e.key === '\\' || e.key === 'b')) {
        showBefore = !showBefore;
      }
    };
    const onHide = () => { api.settle(); };
    window.addEventListener('keydown', onKey);
    window.addEventListener('pagehide', onHide);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('pagehide', onHide);
      api.settle();
    };
  });

  /* open whatever the URL names (and follow it when a copy or photo changes) */
  $effect(() => {
    const id = qid, copy = qcopy;
    if (!ready || !id) return;
    untrack(() => openPhoto(id, copy));
  });

  async function openPhoto(id, copy) {
    await api.settle();
    const samePhoto = clip && clip.id === id;
    if (!samePhoto) {
      clip = null;
      clipError = null;
      srcSize = null;
      copies = [];
      try {
        clip = await pe.video(id);
        if (clip.media_type !== 'photo') { clipError = 'That item is a video, not a photo.'; return; }
      } catch (e) { clipError = e.status === 404 ? 'That photo is no longer in the library.' : e.message; return; }
      pe.size(id).then((s) => { if (clip?.id === id) srcSize = s; }).catch(() => {});
      pe.edited([id]).then((r) => { pick = r.picks?.[id] || 0; }).catch(() => {});
      loadCopies(id);
      if (clip.folder_id !== siblingsFolder) {
        siblingsFolder = clip.folder_id;
        pe.photos({ folder_id: clip.folder_id, sort_by: 'name', sort_order: 'asc' })
          .then((l) => (siblings = l || [])).catch(() => (siblings = []));
      }
    }
    await api.load(id, copy);
    if (ed.error && copy) {
      say('That virtual copy is gone — showing the original', 'error');
      goto(`/media/edit?id=${id}`, { replaceState: true });
    }
  }

  async function loadCopies(id = ed.id) {
    try { copies = (await pe.copies(id)).copies || []; } catch { copies = []; }
  }

  function switchCopy(cid) {
    goto(`/media/edit?id=${ed.id}${cid ? `&copy=${cid}` : ''}`, { replaceState: true, noScroll: true, keepFocus: true });
  }
  function openSibling(v) {
    goto(`/media/edit?id=${v.id}`, { noScroll: true, keepFocus: true });
  }

  /* ---------------------------------------------------------- the preview */
  let showBefore = $state(false);
  const renderW = typeof window === 'undefined' ? 1600
    : Math.max(800, Math.min(2400, Math.ceil((window.innerWidth * (window.devicePixelRatio || 1) * 0.72) / 400) * 400));
  const src = $derived(ed.loaded ? developedUrl(ed.id, { w: renderW, copy: ed.copy, v: ed.renderKey }) : null);
  const before = $derived(ed.id ? baseUrl(ed.id, renderW) : null);

  /* ------------------------------------------------------------ the tools */
  let tool = $state('adjust');
  const TOOLS = [
    { value: 'adjust', label: 'Adjust', icon: 'sliders' },
    { value: 'geometry', label: 'Crop', icon: 'crop' },
    { value: 'remove', label: 'Remove', icon: 'eraser' },
    { value: 'windows', label: 'Windows', icon: 'window' },
    { value: 'masks', label: 'Masks', icon: 'wand' },
    { value: 'versions', label: 'Versions', icon: 'layers' },
    { value: 'export', label: 'Export', icon: 'download' }
  ];

  let cropAspect = $state(0);
  let brush = $state(0.03);
  let clickArmed = $state(false);
  let loupe = $state(false);
  let loupeAt = $state(null);
  let windowOverlay = $state(null);

  /* leaving the crop tool keeps the crop */
  $effect(() => {
    const t = tool;
    untrack(() => {
      if (t !== 'geometry' && ed.cropping) { api.commit(); api.setCropping(false); }
      if (t !== 'masks') clickArmed = false;
      if (t !== 'windows') windowOverlay = null;
    });
  });

  const mode = $derived(
    loupe ? 'point'
    : tool === 'geometry' && ed.cropping ? 'crop'
    : tool === 'remove' && ed.canEdit ? 'brush'
    : tool === 'masks' && clickArmed ? 'point'
    : 'view'
  );

  const geometryFree = $derived(['crop', 'rotate', 'straighten', 'persp_v', 'persp_h', 'geo_scale', 'flip_h', 'flip_v', 'distortion', 'distortion2']
    .every((k) => isDefault(ed.recipe, k)));

  const toSource = (u, v) => {
    const [x, y] = sourceUV(u, v, ed.recipe, srcAspect);
    return [Math.min(1, Math.max(0, x)), Math.min(1, Math.max(0, y))];
  };

  /* ---- remove tool */
  let removeBusy = $state(false);
  let removeModel = $state(null);
  let removeTimer;

  async function pollRemove(start = false) {
    clearTimeout(removeTimer);
    try { removeModel = start && features.onnx ? await pe.removePrepare() : await pe.removeStatus(); } catch { /* fine */ }
    if (tool === 'remove' && removeModel?.status === 'downloading') removeTimer = setTimeout(() => pollRemove(false), 2000);
  }
  $effect(() => { if (tool === 'remove') untrack(() => pollRemove(true)); return () => clearTimeout(removeTimer); });

  async function onStroke(points, radius) {
    if (removeBusy) return;
    const pts = points.map(([u, v]) => toSource(u, v));
    const r = Math.min(0.3, Math.max(0.001, radius * displayToSourceScale(ed.recipe)));
    removeBusy = true;
    try {
      const res = await pe.remove(ed.id, pts, r, $state.snapshot(ed.recipe.removes) || []);
      ed.recipe.removes = [...(ed.recipe.removes || []), { ref: res.ref, box: res.box, kind: 'remove' }];
      api.touch();
      if (res.model) removeModel = res.model;
      if (res.engine === 'quick' && features.onnx && res.model?.status === 'downloading') pollRemove(false);
    } catch (e) { say(e.message, 'error'); }
    finally { removeBusy = false; }
  }

  /* ---- AI selections */
  let ai = $state(null);
  let selecting = $state(null);
  let aiTimer;
  async function pollAi() {
    clearTimeout(aiTimer);
    try { ai = await pe.aiStatus(); } catch { /* fine */ }
    if (tool === 'masks' && ai?.status === 'downloading') aiTimer = setTimeout(pollAi, 2000);
  }
  $effect(() => { if (tool === 'masks') untrack(pollAi); return () => clearTimeout(aiTimer); });

  const NAMES = { sky: 'Sky', subject: 'Subject', click: 'Object' };
  async function aiSelect(kind, points = null) {
    if (selecting) return;
    selecting = kind;
    try {
      const s = srcSize || { w: 1600, h: 1067 };
      const k = Math.min(1, 2000 / Math.max(s.w, s.h));
      const body = { kind, w: Math.max(16, Math.round(s.w * k)), h: Math.max(16, Math.round(s.h * k)) };
      if (points) { body.points = points; body.labels = points.map(() => 1); }
      let res;
      for (let tries = 0; tries < 400; tries++) {
        res = await pe.select(ed.id, body);
        if (!res.pending) break;
        ai = { ...res };
        await new Promise((r) => setTimeout(r, 2000));
      }
      if (!res || res.pending) { say('The selection models are still downloading — try again shortly', 'error'); return; }
      if (res.empty) { say('Nothing was selected there', 'error'); return; }
      ed.recipe.masks = [...(ed.recipe.masks || []), { ...MASK_DEFAULTS, kind: 'brush', ref: res.ref, name: NAMES[kind] }];
      api.touch();
      say(`${NAMES[kind]} selected · ${Math.round(res.coverage * 100)}% of the frame — now adjust it`);
      pollAi();
    } catch (e) { say(e.message, 'error'); }
    finally { selecting = null; clickArmed = false; }
  }

  function onPoint(u, v) {
    if (loupe) { loupeAt = toSource(u, v); return; }
    if (tool === 'masks' && clickArmed) aiSelect('click', [toSource(u, v)]);
  }
  const loupeSrc = $derived(loupe && loupeAt && srcSize
    ? tileUrl(ed.id, { x: loupeAt[0], y: loupeAt[1], zoom: Math.max(1, srcSize.w / 600), w: 600 }) : null);

  /* ---- auto, reset */
  let autoBusy = $state(false);
  async function runAuto() {
    autoBusy = true;
    try {
      const a = await pe.auto(ed.id);
      const cur = $state.snapshot(ed.recipe);
      // Auto sets tone, colour and geometry; what was painted stays
      api.replace({ ...a.recipe, masks: cur.masks, removes: cur.removes, spots: cur.spots, slices: cur.slices,
                    crop: cur.crop, wm_index: cur.wm_index, wm_opacity: cur.wm_opacity, wm_scale: cur.wm_scale,
                    wm_position: cur.wm_position, wm_margin: cur.wm_margin,
                    gen_ref: cur.gen_ref, gen_amount: cur.gen_amount, gen_look: cur.gen_look, gen_geo: cur.gen_geo });
      say('Auto applied');
    } catch (e) { say(e.message, 'error'); }
    finally { autoBusy = false; }
  }
  function resetAll() {
    if (!confirm('Reset every setting on this version to as shot? (Undo brings it back.)')) return;
    api.replace(fullRecipe({}));
  }

  /* ---- pick & stars */
  async function setPick(v) {
    const prev = pick;
    pick = pick === v ? 0 : v;
    try { await pe.pick(ed.id, pick); } catch (e) { pick = prev; say(e.message, 'error'); }
  }
  async function setStars(n) {
    const prev = clip.rating || 0;
    clip.rating = prev === n ? 0 : n;
    try { await pe.stars(ed.id, clip.rating); } catch (e) { clip.rating = prev; say(e.message, 'error'); }
  }

  let copyOpen = $state(false);
  const disabled = $derived(!ed.canEdit || !ed.loaded);
</script>

<svelte:head><title>{clip ? clip.filename + ' · ' : ''}Photo editor · Media</title></svelte:head>

{#if mstate.error}
  <Empty icon="sliders" title="The photo editor needs the media library"
         hint="It is unavailable on this deployment, so there are no photos to edit." />
{:else if !qid}
  {#if ready}
    <PhotoPicker />
  {:else}
    <div class="boot" aria-busy="true" aria-label="Loading photos">
      <Skeleton h="22px" w="160px" />
      <Skeleton h="40px" w="min(22rem, 100%)" r="12px" delay={60} />
      <div class="bootg">{#each Array(8) as _, i (i)}<Skeleton h="auto" r="12px" delay={i * 40} />{/each}</div>
    </div>
  {/if}
{:else if clipError}
  <Empty icon="alert" title="Can't open this photo" hint={clipError}>
    <a class="mg-btn secondary" href="/media/edit">Choose another photo</a>
  </Empty>
{:else}
  <!-- ——————————————————————————————————————————————————— header row ——— -->
  <div class="mg-row head">
    <a class="mg-btn secondary icon sm" href="/media/edit" aria-label="All photos" title="All photos"><Icon name="grid" size={15} /></a>
    <div class="ttl">
      <h2 class="mg-h2">{clip?.filename || 'Loading…'}</h2>
      <span class="sub">
        {#if ed.copy}<span class="mg-chip mgr">{copyName || 'Virtual copy'}</span>{/if}
        {#if srcSize}<span class="mg-tnum">{srcSize.w} × {srcSize.h}</span>{/if}
        {#if ed.saving}<span class="st">Saving…</span>{:else if ed.saveError}<span class="st crit">Not saved</span>{:else if ed.loaded && ed.canEdit}<span class="st">Saved</span>{/if}
      </span>
    </div>
    <div class="mg-actions">
      <div class="rate" role="group" aria-label="Pick and rating">
        <button type="button" class="flag" class:rej={pick === -1} onclick={() => setPick(-1)} disabled={!caps.annotate}
                aria-pressed={pick === -1} title="Reject"><Icon name="close" size={14} /></button>
        <button type="button" class="flag" class:pk={pick === 1} onclick={() => setPick(1)} disabled={!caps.annotate}
                aria-pressed={pick === 1} title="Pick"><Icon name="check" size={14} /></button>
        {#each [1, 2, 3, 4, 5] as n (n)}
          <button type="button" class="star" class:on={(clip?.rating || 0) >= n} onclick={() => setStars(n)}
                  disabled={!caps.annotate || !clip} aria-label="{n} star{n > 1 ? 's' : ''}">★</button>
        {/each}
      </div>
      <button type="button" class="mg-btn secondary icon sm" onclick={() => api.undo()} disabled={disabled || ed.undo.length < 2}
              aria-label="Undo" title="Undo (⌘Z)"><Icon name="undo" size={14} /></button>
      <button type="button" class="mg-btn secondary icon sm" onclick={() => api.redoStep()} disabled={disabled || !ed.redo.length}
              aria-label="Redo" title="Redo (⇧⌘Z)"><Icon name="redo" size={14} /></button>
      <button type="button" class="mg-btn sm" class:accent={showBefore} class:secondary={!showBefore}
              onclick={() => (showBefore = !showBefore)} aria-pressed={showBefore} title="Before / after (B)">
        <Icon name="eye" size={14} /> {showBefore ? 'Before' : 'After'}</button>
      <button type="button" class="mg-btn sm" class:accent={loupe} class:secondary={!loupe}
              onclick={() => { loupe = !loupe; loupeAt = null; }} aria-pressed={loupe} disabled={!srcSize}
              title="Inspect the original at 100%"><Icon name="search" size={14} /> 100%</button>
      <button type="button" class="mg-btn secondary sm" onclick={() => (copyOpen = true)} disabled={disabled}
              title="Copy these settings to other photos"><Icon name="copy" size={14} /> Copy to…</button>
      <a class="mg-btn secondary sm" href="/media/hdr?id={qid}" title="Twilight, Looks and HDR"><Icon name="sun" size={14} /> HDR & Looks</a>
      <button type="button" class="mg-btn ghost sm" onclick={resetAll} disabled={disabled}>Reset</button>
    </div>
  </div>

  {#if ed.loaded && !ed.canEdit}
    <div class="mg-strip warn"><span class="ic"><Icon name="lock" size={14} /></span>
      <span>Your account has view-only access — you can look at this edit but not change it.</span></div>
  {/if}
  {#if ed.error}
    <div class="mg-strip crit"><span class="ic"><Icon name="alert" size={14} /></span><span>{ed.error}</span></div>
  {/if}

  <div class="ed">
    <!-- ———————————————————————————————————————————————— the picture ——— -->
    <div class="view mg-panel">
      <div class="pv">
        <Preview {src} {before} {showBefore} busy={ed.saving || removeBusy || !!selecting} {mode}
                 bind:crop={ed.recipe.crop} {cropAspect} {brush} overlay={windowOverlay}
                 onstroke={onStroke} onpoint={onPoint} />
        {#if loupe}
          <div class="loupe mg-raised" transition:pop={{ duration: 220, y: 8 }}>
            <div class="lh"><span>Original · 100%</span>
              <button type="button" class="mg-btn ghost icon sm" onclick={() => { loupe = false; loupeAt = null; }} aria-label="Close"><Icon name="close" size={13} /></button></div>
            {#if loupeSrc}<img src={loupeSrc} alt="100% crop of the original" />{:else}<p>Tap the photo to look closer.</p>{/if}
          </div>
        {/if}
        {#if mode === 'point' && !loupe}<span class="tip mg-chip" transition:fade={{ duration: 150 }}>Tap the object to select</span>{/if}
        {#if mode === 'brush'}<span class="tip mg-chip" transition:fade={{ duration: 150 }}>Paint over what should go</span>{/if}
      </div>

      {#if siblings.length > 1}
        <div class="strip mg-noscroll" aria-label="Photos in this folder">
          {#each siblings as v (v.id)}
            <button type="button" class="th" class:on={v.id === ed.id} onclick={() => openSibling(v)} title={v.filename}>
              <img src={photoUrl(v, 240)} alt={v.filename} loading="lazy" />
            </button>
          {/each}
        </div>
      {/if}
    </div>

    <!-- ———————————————————————————————————————————————— the panels ——— -->
    <aside class="side mg-panel">
      <div class="tools mg-noscroll"><Seg options={TOOLS} value={tool} onchange={(v) => (tool = v)} label="Editor tools" /></div>
      <div class="panel">
        {#if !ed.loaded}
          <div class="ld" aria-busy="true" aria-label="Loading the edit">
            <Skeleton h="32px" r="10px" />
            <Skeleton lines={6} />
            <Skeleton h="32px" r="10px" delay={120} />
            <Skeleton lines={4} delay={120} />
          </div>
        {:else if tool === 'adjust'}
          <AdjustPanel {api} {ed} {disabled} onauto={runAuto} {autoBusy} />
        {:else if tool === 'geometry'}
          <GeometryPanel {api} {ed} {disabled} bind:cropAspect {srcAspect} />
        {:else if tool === 'remove'}
          <RemovePanel {api} {ed} bind:brush busy={removeBusy} model={removeModel} onnx={!!features.onnx} {disabled} />
        {:else if tool === 'windows'}
          <WindowsPanel {api} {ed} {srcSize} {siblings} bind:overlay={windowOverlay} {geometryFree} {disabled} />
        {:else if tool === 'masks'}
          <MasksPanel {api} {ed} {disabled} onnx={!!features.onnx} {ai} {selecting} bind:clickArmed onselect={(k) => aiSelect(k)} />
        {:else if tool === 'versions'}
          <VersionsPanel {api} {ed} {copies} onswitch={switchCopy} onreloadcopies={() => loadCopies()} {disabled} />
        {:else if tool === 'export'}
          <ExportPanel {api} {ed} {copies} {copyName} {caps} disabled={!ed.loaded} />
        {/if}
      </div>
    </aside>
  </div>

  <CopySettings open={copyOpen} onclose={() => (copyOpen = false)} {ed} photos={siblings} folderName={clip?.folder_name || ''} />
{/if}

<style>
  .head { align-items: center; }
  .boot { display: flex; flex-direction: column; gap: 14px; }
  .bootg { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); }
  .bootg > :global(.mg-skel) { aspect-ratio: 4 / 3; }
  @media (max-width: 480px) { .bootg { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  .ttl { min-width: 0; flex: 1 1 200px; display: flex; flex-direction: column; gap: 4px; }
  .ttl .mg-h2 { font-size: 17px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sub { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--mc-ink3); flex-wrap: wrap; }
  .sub .mg-chip { padding: 3px 9px; font-size: 11px; }
  .st.crit { color: var(--mc-crit); }
  .rate { display: flex; align-items: center; gap: 0; padding: 0 4px; border-radius: var(--mc-r-md);
          background: var(--mc-raised); border: 1px solid var(--mc-line); height: 40px; }
  .flag, .star { width: 32px; height: 38px; border: 0; background: none; cursor: pointer; color: var(--mc-ink3);
                 display: grid; place-items: center; padding: 0; font-size: 15px; }
  .flag:disabled, .star:disabled { cursor: default; opacity: 0.5; }
  .flag.pk { color: var(--mc-accent); }
  .flag.rej { color: var(--mc-crit); }
  .star.on { color: var(--mc-warn); }
  @media (pointer: coarse) { .flag, .star { width: 40px; height: 44px; } .rate { height: 46px; } }

  .ed {
    display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px;
    height: calc(100vh - 250px); height: calc(100svh - 250px); min-height: 480px;
  }
  .view { display: flex; flex-direction: column; min-height: 0; padding: 10px; gap: 10px; overflow: hidden; }
  .pv { position: relative; flex: 1; min-height: 0; }
  .side { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
  .tools { flex: none; padding: 10px 10px 6px; overflow-x: auto; border-bottom: 1px solid var(--mc-line); }
  .tools :global(.seg) { max-width: none; }
  .panel { flex: 1; min-height: 0; overflow-y: auto; padding: 8px 16px 20px; display: flex; flex-direction: column; }
  .ld { display: flex; flex-direction: column; gap: 14px; padding: 12px 0; }

  .strip { flex: none; display: flex; gap: 6px; overflow-x: auto; }
  .th { flex: none; width: 76px; height: 52px; padding: 0; border: 2px solid transparent; border-radius: 9px;
        overflow: hidden; background: var(--mc-inset); cursor: pointer; opacity: 0.65; transition: opacity 0.15s, border-color 0.15s; }
  .th:hover { opacity: 1; }
  .th.on { border-color: var(--mc-accent); opacity: 1; }
  .th img { width: 100%; height: 100%; object-fit: cover; display: block; }

  .loupe { position: absolute; right: 10px; bottom: 10px; width: min(320px, calc(100% - 20px));
           padding: 8px; border-radius: var(--mc-r); display: flex; flex-direction: column; gap: 6px; }
  .lh { display: flex; align-items: center; justify-content: space-between; font-size: 11.5px; color: var(--mc-ink2); padding-left: 4px; }
  .loupe img { width: 100%; border-radius: var(--mc-r-sm); display: block; image-rendering: pixelated; }
  .loupe p { margin: 0; padding: 20px 8px; text-align: center; font-size: 12px; color: var(--mc-ink3); }
  .tip { position: absolute; left: 50%; bottom: 12px; transform: translateX(-50%); pointer-events: none;
         background: var(--mc-raised); border-color: var(--mc-line2); color: var(--mc-ink); box-shadow: var(--mc-sh-2); }

  /* A finger on a dense tool: every small control grows to 44px on touch. */
  @media (pointer: coarse) {
    .head :global(.mg-btn.sm), .ed :global(.mg-btn.sm), .ed :global(button.mg-chip) { min-height: 44px; }
    .head :global(.mg-btn.icon.sm), .ed :global(.mg-btn.icon.sm) { min-width: 44px; }
    .ed :global(.mg-input) { min-height: 44px; }
  }

  @media (max-width: 1100px) {
    .ed { grid-template-columns: minmax(0, 1fr) 320px; }
  }
  @media (max-width: 900px) {
    .ed { grid-template-columns: minmax(0, 1fr); height: auto; min-height: 0; }
    .view { height: 58vh; height: 58svh; min-height: 300px; padding: 6px; }
    .side { overflow: visible; }
    .panel { overflow: visible; padding: 6px 14px 20px; }
    /* sticks under the status strip, on the panel's own fill so the controls
       scrolling beneath it never show through */
    .tools { position: sticky; top: calc(var(--mc-strip-h) + var(--sat)); z-index: 3; background: var(--mc-surface);
             border-radius: var(--mc-r) var(--mc-r) 0 0; }
    .head .mg-actions { margin-left: 0; width: 100%; overflow-x: auto; flex-wrap: nowrap; scrollbar-width: none; padding-bottom: 2px; }
    .head .mg-actions::-webkit-scrollbar { display: none; }
  }
</style>
