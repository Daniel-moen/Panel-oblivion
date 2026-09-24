<script>
  /* Browse: the folder rail on the left, an aspect-aware grid on the right,
     and the clip lightbox over the top.

     The grid keeps its own reveal stagger but caps the delay at ~420ms — with
     a thousand clips a per-card delay would take half a minute to finish, and
     the point of the stagger is the first screenful.

     On a phone the rail is not a rail: 220px of folder names would eat the
     grid, so below 860px the same buttons become one sideways-scrolling row of
     chips. Same state, same handlers, a different shape.

     Zerko 1.2–1.4 additions: colour labels (a filter here, client-side —
     /api/videos has no label parameter), the trash as the last entry of the
     rail, and a selection bar that labels, files into a project, copies for
     paste-into-folder, zips for download and trashes. Every control checks
     the role's capabilities from /api/me. */
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { flip } from 'svelte/animate';
  import { fly } from 'svelte/transition';
  import { mstate, boot, loadClips, loadFolders, openClip, closeClip, stepClip,
           toggleSelect, clearSelect, selectAll, say, can, CAP, setLabel, dropClips,
           LABELS } from '$lib/media.svelte.js';
  import { media, fmtBytes } from '$lib/media.js';
  import ClipCard from '$lib/components/ClipCard.svelte';
  import ClipDrawer from '$lib/components/ClipDrawer.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import LabelDots from '$lib/components/media/library/LabelDots.svelte';
  import ActivityBell from '$lib/components/media/library/ActivityBell.svelte';
  import TrashView from '$lib/components/media/library/TrashView.svelte';
  import ProjectSheet from '$lib/components/media/library/ProjectSheet.svelte';

  let opening = $state(false);
  let q = $state(mstate.filters.search || '');
  let debounce;

  let mode = $state('library');        // library | trash
  let trashCount = $state(null);
  let labelOpen = $state(false);
  let projectOpen = $state(false);
  let working = $state(false);

  onMount(async () => {
    await boot();
    if (!mstate.ready) return;
    loadFolders();
    refreshTrashCount();
    const sp = page.url.searchParams;
    if (sp.get('trash')) mode = 'trash';
    /* Arriving from the Tags page (/media/browse?tag=drone) filters to it;
       from a project stage (/media/browse?folder=12) opens that folder;
       otherwise keep whatever the grid was last showing. */
    const tag = sp.get('tag');
    const folder = sp.get('folder');
    if (tag && tag !== mstate.filters.tags) {
      mstate.filters.tags = tag;
      mstate.filters.search = '';
      q = '';
      await loadClips();
    } else if (folder && Number(folder) !== mstate.filters.folder_id) {
      setFolder(Number(folder));
    } else if (!mstate.loaded) {
      await loadClips();
    }
  });

  /* ?open= may change while we are already here (the bell links to it), so
     it is an effect, not a mount-time read. */
  let lastOpen = null;
  $effect(() => {
    const pre = page.url.searchParams.get('open');
    if (!pre || pre === lastOpen || !mstate.ready) return;
    lastOpen = pre;
    mode = 'library';
    open({ id: Number(pre) });
  });

  async function refreshTrashCount() {
    try { trashCount = (await media.trash())?.count ?? null; } catch { trashCount = null; }
  }

  async function open(clip) {
    opening = true;
    await openClip(clip.id);
    opening = false;
  }

  function setFolder(id) {
    mode = 'library';
    mstate.filters.folder_id = id;
    mstate.filters.include_subfolders = id != null;
    clearSelect();
    loadClips();
  }

  function setType(t) { mstate.filters.media_type = t; loadClips(); }
  function setSort(v) {
    const [sort_by, sort_order] = v.split(':');
    mstate.filters.sort_by = sort_by;
    mstate.filters.sort_order = sort_order;
    loadClips();
  }

  $effect(() => {
    const term = q;
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      if (term !== mstate.filters.search) {
        mstate.filters.search = term;
        loadClips();
      }
    }, 280);
  });

  const sel = $derived(mstate.selection);
  /* Label filter is client-side: the list endpoint takes no label param. */
  const clips = $derived(mstate.labelFilter
    ? mstate.clips.filter((c) => c.label === mstate.labelFilter)
    : mstate.clips);
  const totalSize = $derived(clips.reduce((a, c) => a + (c.file_size || 0), 0));

  /* The folder tree arrives nested; flatten it once for a simple list with
     indentation rather than a recursive component. */
  const flatFolders = $derived.by(() => {
    const out = [];
    const walk = (nodes, depth) => {
      for (const n of nodes || []) {
        out.push({ ...n, depth });
        if (n.children?.length) walk(n.children, depth + 1);
      }
    };
    walk(mstate.folders, 0);
    return out;
  });

  async function bulk(action) {
    const ids = [...sel];
    if (!ids.length) return;
    try {
      await media.bulk({ action, video_ids: ids });
      say(`${ids.length} clip${ids.length === 1 ? '' : 's'} queued`);
      clearSelect();
      loadClips();
    } catch (e) { say(e.message, 'error'); }
  }

  async function labelSel(label) {
    const ids = [...sel];
    labelOpen = false;
    if (ids.length && await setLabel(ids, label))
      say(label ? `Labelled ${ids.length} ${label}` : `Cleared the label on ${ids.length}`);
  }

  async function trashSel() {
    const ids = [...sel];
    if (!ids.length) return;
    working = true;
    try {
      const r = await media.trashMany(ids);
      say(`Moved ${r.affected} to the trash`);
      dropClips(ids);
      refreshTrashCount();
    } catch (e) { say(e.message, 'error'); }
    finally { working = false; }
  }

  function copySel() {
    mstate.clipboard = [...sel];
    say(`Copied ${sel.size} — open a folder and paste`);
    clearSelect();
  }

  const here = $derived(flatFolders.find((f) => f.id === mstate.filters.folder_id));

  async function paste() {
    const ids = mstate.clipboard;
    if (!ids.length || !here) return;
    working = true;
    try {
      const r = await media.copyTo(ids, here.id);
      say(`Pasted ${r.copied} into ${here.name}` + (r.failed?.length ? ` · ${r.failed.length} failed` : ''),
          r.failed?.length ? 'error' : 'ok');
      mstate.clipboard = [];
      loadClips();
      loadFolders();
    } catch (e) { say(e.message, 'error'); }
    finally { working = false; }
  }

  const zipHref = $derived(sel.size ? media.zipUrl([...sel]) : null);

  function projectDone() {
    projectOpen = false;
    clearSelect();
    loadClips();
    loadFolders();
  }

  const TYPES = [
    { value: 'all', label: 'All' },
    { value: 'video', label: 'Video' },
    { value: 'photo', label: 'Photos' }
  ];
  const VIEWS = [
    { value: 'grid', label: 'Grid', icon: 'grid' },
    { value: 'list', label: 'List', icon: 'list' }
  ];
</script>

<svelte:head><title>Browse · Media</title></svelte:head>

<!-- ————————————————————————————————————————————————————— header row ——— -->
<div class="mg-row">
  <h2 class="mg-h2">Browse</h2>
  {#if mode === 'library' && clips.length}
    <span class="mg-count">
      {clips.length} clip{clips.length === 1 ? '' : 's'} · {fmtBytes(totalSize)}
    </span>
  {/if}
  <div class="mg-actions">
    <ActivityBell compact />
  </div>
</div>

<!-- ——————————————————————————————————————————————— the one control row ——— -->
<div class="mg-controls">
  <label class="mg-search">
    <span class="ic"><Icon name="search" size={15} /></span>
    <input class="mg-input" type="search" bind:value={q}
           placeholder="Filter this view…" aria-label="Filter this view" />
    {#if q}
      <button class="clear" type="button" onclick={() => (q = '')} aria-label="Clear filter">
        <Icon name="close" size={14} />
      </button>
    {/if}
  </label>

  {#if mstate.filters.tags}
    <button class="mg-chip on" type="button"
            onclick={() => { mstate.filters.tags = ''; loadClips(); }}>
      {mstate.filters.tags}<Icon name="x" size={12} />
    </button>
  {/if}

  <Seg options={TYPES} value={mstate.filters.media_type}
       onchange={setType} label="Media type" />

  <span class="lf mg-glass-soft" title="Filter by colour label">
    <LabelDots value={mstate.labelFilter} noneLabel="Any label" label="Filter by label"
               onchange={(v) => (mstate.labelFilter = v)} />
  </span>

  <span class="mg-select sort">
    <select aria-label="Sort"
            value={mstate.filters.sort_by + ':' + mstate.filters.sort_order}
            onchange={(e) => setSort(e.currentTarget.value)}>
      <option value="date:desc">Newest first</option>
      <option value="date:asc">Oldest first</option>
      <option value="name:asc">Name A–Z</option>
      <option value="size:desc">Largest first</option>
      <option value="duration:desc">Longest first</option>
      <option value="rating:desc">Best rated</option>
    </select>
    <span class="ic"><Icon name="chevronDown" size={15} /></span>
  </span>

  <Seg options={VIEWS} value={mstate.view}
       onchange={(v) => (mstate.view = v)} label="Layout" />
</div>

<div class="wrap">
  <!-- ——————————————————————————————————————————————————— folder rail ——— -->
  <nav class="rail mg-glass-soft mg-noscroll" aria-label="Folders">
    <span class="mg-label rl">Folders</span>

    <button class="f" class:on={mstate.filters.folder_id == null}
            onclick={() => setFolder(null)}>
      <span>All clips</span>
      <i class="mg-tnum">{mstate.stats?.total_videos ?? ''}</i>
    </button>

    {#each flatFolders as f (f.id)}
      <button class="f" class:on={mstate.filters.folder_id === f.id}
              style:padding-left="{10 + f.depth * 11}px"
              onclick={() => setFolder(f.id)}>
        <span>{f.name}</span>
        {#if f.count != null}<i class="mg-tnum">{f.count}</i>{/if}
      </button>
    {:else}
      {#if !mstate.ready}
        {#each Array(6) as _, i (i)}
          <div class="sk"><Skeleton h="14px" r="8px" delay={i * 70} /></div>
        {/each}
      {/if}
    {/each}

    <span class="sep" aria-hidden="true"></span>
    <button class="f trash" class:on={mode === 'trash'}
            onclick={() => { mode = 'trash'; clearSelect(); }}>
      <span><Icon name="trash" size={13} /> Trash</span>
      {#if trashCount}<i class="mg-tnum">{trashCount}</i>{/if}
    </button>
  </nav>

  <section class="main">
    {#if mode === 'trash'}
      <TrashView oncount={(n) => (trashCount = n)} />
    {:else}
    {#if mstate.clipboard.length && can(CAP.UPLOAD)}
      <div class="selbar paste mg-glass-soft" in:fly={{ y: 8, duration: 220 }}>
        <b>{mstate.clipboard.length} copied</b>
        {#if here}
          <button class="mg-btn primary sm" disabled={working} onclick={paste}>
            <Icon name="copy" size={14} /><span class="t">Paste into {here.name}</span>
          </button>
        {:else}
          <span class="hint">Pick a folder to paste into</span>
        {/if}
        <button class="mg-btn ghost sm" onclick={() => (mstate.clipboard = [])}>Cancel</button>
      </div>
    {/if}

    {#if sel.size}
      <div class="selbar mg-glass-soft" in:fly={{ y: 8, duration: 220 }}>
        <b>{sel.size} selected</b>
        {#if can(CAP.ANNOTATE)}
          <button class="mg-btn secondary sm" class:on={labelOpen} aria-expanded={labelOpen}
                  onclick={() => (labelOpen = !labelOpen)} title="Colour label">
            <Icon name="palette" size={14} /><span class="t">Label</span>
          </button>
        {/if}
        {#if can(CAP.ORGANISE)}
          <button class="mg-btn secondary sm" onclick={() => (projectOpen = true)} title="Add to project">
            <Icon name="folder" size={14} /><span class="t">Add to project</span>
          </button>
        {/if}
        {#if can(CAP.UPLOAD)}
          <button class="mg-btn secondary sm" onclick={copySel} title="Copy (paste into a folder)">
            <Icon name="copy" size={14} /><span class="t">Copy</span>
          </button>
        {/if}
        {#if can(CAP.DOWNLOAD) && zipHref}
          <a class="mg-btn secondary sm" href={zipHref} download title="Download as zip">
            <Icon name="download" size={14} /><span class="t">Zip</span>
          </a>
        {/if}
        {#if can(CAP.PROXY)}
          <button class="mg-btn secondary sm" onclick={() => bulk('proxy')} title="Build proxies">
            <Icon name="film" size={14} /><span class="t">Build proxies</span>
          </button>
        {/if}
        {#if can(CAP.TRANSCRIBE)}
          <button class="mg-btn secondary sm" onclick={() => bulk('transcribe')} title="Transcribe">
            <Icon name="mic" size={14} /><span class="t">Transcribe</span>
          </button>
        {/if}
        {#if can(CAP.TRASH)}
          <button class="mg-btn danger sm" disabled={working} onclick={trashSel} title="Move to trash">
            <Icon name="trash" size={14} /><span class="t">Trash</span>
          </button>
        {/if}
        <span class="gap"></span>
        <button class="mg-btn ghost sm" onclick={selectAll}>All</button>
        <button class="mg-btn ghost sm" onclick={clearSelect}>Clear</button>
        {#if labelOpen}
          <div class="labelrow" in:fly={{ y: -4, duration: 180 }}>
            <LabelDots value={null} showNone={false} toggle={false} label="Label the selection"
                       onchange={labelSel} />
            <button class="mg-btn ghost sm" onclick={() => labelSel(null)}>Clear label</button>
          </div>
        {/if}
      </div>
    {/if}

    {#if mstate.loading}
      <div class="grid">
        {#each Array(12) as _, i (i)}
          <div class="ghost"><Skeleton h="100%" r="18px" delay={i * 55} /></div>
        {/each}
      </div>
    {:else if !clips.length}
      {#if mstate.labelFilter && mstate.clips.length}
        <Empty icon="palette" title="No {mstate.labelFilter} labels here"
               hint="Nothing in this view carries that colour label.">
          {#snippet children()}
            <button class="mg-btn secondary sm" onclick={() => (mstate.labelFilter = null)}>
              Show every label
            </button>
          {/snippet}
        </Empty>
      {:else if mstate.filters.search}
        <Empty icon="search" title="Nothing matches that"
               hint="Try fewer words — or search what was said on camera instead.">
          {#snippet children()}
            <a class="mg-btn secondary sm" href="/media/search">
              <Icon name="search" size={14} />Search transcripts
            </a>
          {/snippet}
        </Empty>
      {:else if !mstate.status?.media_root?.ok}
        <Empty icon="alert" title="Nothing here yet"
               hint="There is no footage drive on this deployment, so the catalogue is empty." />
      {:else}
        <Empty icon="folder" title="Nothing here yet"
               hint="Run a re-index to pick up whatever is on the drive.">
          {#snippet children()}
            <a class="mg-btn secondary sm" href="/media">
              <Icon name="refresh" size={14} />Go to the overview
            </a>
          {/snippet}
        </Empty>
      {/if}
    {:else}
      <div class={mstate.view === 'grid' ? 'grid' : 'list'}>
        {#each clips as c, i (c.id)}
          <div animate:flip={{ duration: 260 }}
               in:fly={{ y: 16, duration: 380, delay: Math.min(i * 28, 420) }}>
            <ClipCard clip={c}
                      selected={sel.has(c.id)}
                      selecting={sel.size > 0}
                      onopen={open}
                      ontoggle={(x) => toggleSelect(x.id)} />
          </div>
        {/each}
      </div>
    {/if}
    {/if}
  </section>
</div>

<ProjectSheet open={projectOpen} ids={[...sel]} onclose={() => (projectOpen = false)}
              ondone={projectDone} />

{#if mstate.openId != null}
  <ClipDrawer clip={mstate.openClip} loading={opening}
              onclose={closeClip} onstep={stepClip} />
{/if}

<style>
  /* Chrome draws its own × inside a search field; this one has a pill button. */
  input[type='search']::-webkit-search-cancel-button { -webkit-appearance: none; appearance: none; }

  .sort > select { width: 148px; }

  .wrap { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 16px; align-items: start; }

  /* ———————————————————————————————————————————————————— folder rail ——— */
  .rail {
    position: sticky; top: 16px; align-self: start;
    max-height: calc(100vh - 190px); overflow-y: auto;
    border-radius: var(--mg-r-card); padding: 10px;
    display: flex; flex-direction: column; gap: 2px; min-width: 0;
  }
  .rl { padding: 3px 10px 5px; }
  .f {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    width: 100%; min-height: 36px; text-align: left; padding: 7px 10px;
    border: 0; border-radius: 10px; background: none; color: var(--mg-i2);
    font: 500 12.5px/1.35 var(--mg-font); cursor: pointer;
    transition: background 0.18s, color 0.18s;
  }
  .f:hover { background: rgba(255, 255, 255, 0.06); color: var(--mg-i); }
  .f.on { background: rgba(255, 255, 255, 0.1); color: var(--mg-i); }
  .f span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .f i { font-style: normal; font-size: 11px; color: var(--mg-i3); flex: none; }
  .f.on i { color: var(--mg-i2); }
  .sk { padding: 8px 10px; }
  .sep { display: block; height: 1px; margin: 6px 8px; background: var(--mg-line); flex: none; }
  .f.trash span { display: inline-flex; align-items: center; gap: 7px; }

  .lf { display: inline-flex; align-items: center; height: 40px; padding: 0 4px;
        border-radius: 9999px; border: 1px solid var(--mg-line); }

  /* —————————————————————————————————————————————————————— selection ——— */
  .main { min-width: 0; }
  .selbar {
    display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
    padding: 6px 8px 6px 16px; margin-bottom: 12px; border-radius: 9999px;
  }
  .selbar b { margin-right: 4px; font: 600 12.5px/1 var(--mg-font); color: var(--mg-i); }
  .selbar .gap { flex: 1; }
  .selbar .on { border-color: rgba(62, 207, 142, 0.5); color: var(--mg-ok); }
  .selbar .hint { font: 400 12px/1 var(--mg-font); color: var(--mg-i3); }
  .labelrow { flex: 1 1 100%; display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
              padding: 4px 0 2px; border-top: 1px solid var(--mg-line); margin-top: 2px; }

  /* ———————————————————————————————————————————————————————— the grid ——— */
  .grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(216px, 1fr)); }
  .list { display: grid; gap: 8px; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); }
  .ghost { aspect-ratio: 16 / 11; }

  /* ——————————————————————————————————— the rail becomes a chip row ——— */
  @media (max-width: 860px) {
    .wrap { grid-template-columns: minmax(0, 1fr); gap: 14px; }
    .rail {
      position: static; max-height: none; padding: 0; gap: 6px;
      background: none; border: 0; border-radius: 0;
      flex-direction: row; align-items: center;
      overflow-x: auto; overflow-y: hidden; padding-bottom: 2px;
    }
    .rl { display: none; }
    .f {
      width: auto; flex: none; min-height: 40px; border-radius: 9999px;
      padding: 0 14px !important; gap: 7px;
      background: var(--mg-glass-soft); border: 1px solid var(--mg-line);
    }
    .f.on { background: rgba(62, 207, 142, 0.12); border-color: rgba(62, 207, 142, 0.4); color: var(--mg-ok); }
    .f.on i { color: var(--mg-ok); }
    .sk { flex: none; width: 90px; padding: 0; }
    .grid { grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }
    .list { grid-template-columns: minmax(0, 1fr); }
  }
  @media (max-width: 860px) {
    .sep { width: 1px; height: 24px; margin: 0 2px; }
  }
  @media (max-width: 560px) {
    .selbar { border-radius: var(--mg-r-card); padding: 8px 10px; }
    .selbar b { flex: 1 1 100%; margin: 2px 0 4px; }
    .selbar .t { display: none; }
    .selbar .mg-btn { height: 40px; }
    .selbar .mg-btn:has(.t) { width: 40px; padding: 0; }
    .paste .mg-btn:has(.t) { width: auto; padding: 0 14px; }
    .paste .t { display: inline; }
    .sort > select { width: 132px; }
    .lf { height: 40px; }
  }
</style>
