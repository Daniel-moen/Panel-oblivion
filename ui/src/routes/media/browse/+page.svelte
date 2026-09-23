<script>
  /* Browse: the folder rail on the left, an aspect-aware grid on the right,
     and the clip lightbox over the top.

     The grid keeps its own reveal stagger but caps the delay at ~420ms — with
     a thousand clips a per-card delay would take half a minute to finish, and
     the point of the stagger is the first screenful.

     On a phone the rail is not a rail: 220px of folder names would eat the
     grid, so below 860px the same buttons become one sideways-scrolling row of
     chips. Same state, same handlers, a different shape. */
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { flip } from 'svelte/animate';
  import { fly } from 'svelte/transition';
  import { mstate, boot, loadClips, loadFolders, openClip, closeClip, stepClip,
           toggleSelect, clearSelect, selectAll, say } from '$lib/media.svelte.js';
  import { media, fmtBytes } from '$lib/media.js';
  import ClipCard from '$lib/components/ClipCard.svelte';
  import ClipDrawer from '$lib/components/ClipDrawer.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';

  let opening = $state(false);
  let q = $state('');
  let debounce;

  onMount(async () => {
    await boot();
    if (!mstate.ready) return;
    loadFolders();
    /* Arriving from the Tags page (/media/browse?tag=drone) filters to it;
       otherwise keep whatever the grid was last showing. */
    const tag = page.url.searchParams.get('tag');
    if (tag && tag !== mstate.filters.tags) {
      mstate.filters.tags = tag;
      mstate.filters.search = '';
      q = '';
      await loadClips();
    } else if (!mstate.loaded) {
      await loadClips();
    }
    const pre = page.url.searchParams.get('open');
    if (pre) open({ id: Number(pre) });
  });

  async function open(clip) {
    opening = true;
    await openClip(clip.id);
    opening = false;
  }

  function setFolder(id) {
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
  const clips = $derived(mstate.clips);
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
  {#if clips.length}
    <span class="mg-count">
      {clips.length} clip{clips.length === 1 ? '' : 's'} · {fmtBytes(totalSize)}
    </span>
  {/if}
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
  </nav>

  <section class="main">
    {#if sel.size}
      <div class="selbar mg-glass-soft" in:fly={{ y: 8, duration: 220 }}>
        <b>{sel.size} selected</b>
        <button class="mg-btn secondary sm" onclick={() => bulk('proxy')}>
          <Icon name="film" size={14} />Build proxies
        </button>
        <button class="mg-btn secondary sm" onclick={() => bulk('transcribe')}>
          <Icon name="mic" size={14} />Transcribe
        </button>
        <button class="mg-btn ghost sm" onclick={selectAll}>Select all</button>
        <button class="mg-btn ghost sm" onclick={clearSelect}>Clear</button>
      </div>
    {/if}

    {#if mstate.loading}
      <div class="grid">
        {#each Array(12) as _, i (i)}
          <div class="ghost"><Skeleton h="100%" r="18px" delay={i * 55} /></div>
        {/each}
      </div>
    {:else if !clips.length}
      {#if mstate.filters.search}
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
  </section>
</div>

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

  /* —————————————————————————————————————————————————————— selection ——— */
  .main { min-width: 0; }
  .selbar {
    display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
    padding: 6px 8px 6px 16px; margin-bottom: 12px; border-radius: 9999px;
  }
  .selbar b { margin-right: 4px; font: 600 12.5px/1 var(--mg-font); color: var(--mg-i); }

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
  @media (max-width: 560px) {
    .selbar { border-radius: var(--mg-r-card); padding: 8px 10px; }
    .sort > select { width: 132px; }
  }
</style>
