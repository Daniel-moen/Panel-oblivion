<script>
  /* The general file store — contracts, stills, decks, anything that is not
     footage. Same backend module as Zerko's Files tab (files_api.py), which
     keeps the filesystem as the source of truth and puts every client path
     through one containment gate.

     Drag anything onto the page and it uploads into the folder you are
     standing in, each file carrying its own progress bar. */
  import { onMount } from 'svelte';
  import { fly, fade } from 'svelte/transition';
  import { flip } from 'svelte/animate';
  import { mstate, boot, say, can, CAP } from '$lib/media.svelte.js';
  import { media, uploadFile, fmtBytes } from '$lib/media.js';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';

  let path = $state('');
  let listing = $state(null);
  let loading = $state(true);
  let sel = $state(new Set());
  let dragging = $state(false);
  let queue = $state([]);          // { id, name, pct, error }
  let input;
  let depth = 0;
  let seq = 0;

  onMount(async () => {
    await boot();
    if (mstate.status?.backend) load('');
    else loading = false;
  });

  async function load(p) {
    loading = true;
    sel = new Set();
    try { listing = await media.files.list(p); path = listing.path ?? p; }
    catch (e) { say(e.message, 'error'); listing = { entries: [], breadcrumbs: [] }; }
    finally { loading = false; }
  }

  const refresh = () => load(path);

  function toggle(entry) {
    const next = new Set(sel);
    next.has(entry.path) ? next.delete(entry.path) : next.add(entry.path);
    sel = next;
  }

  async function mkdir() {
    const name = prompt('Name the new folder');
    if (!name) return;
    try { await media.files.mkdir(path, name); refresh(); }
    catch (e) { say(e.message, 'error'); }
  }

  async function rename(entry) {
    const name = prompt('Rename to', entry.name);
    if (!name || name === entry.name) return;
    try { await media.files.rename(entry.path, name); refresh(); }
    catch (e) { say(e.message, 'error'); }
  }

  async function trash() {
    const paths = [...sel];
    if (!paths.length) return;
    try {
      await media.files.remove(paths);
      say(`${paths.length} item${paths.length === 1 ? '' : 's'} moved to trash`);
      refresh();
    } catch (e) { say(e.message, 'error'); }
  }

  /* The same call as the bulk one, for the row you are pointing at. */
  async function trashOne(entry) {
    if (!confirm(`Move "${entry.name}" to trash?`)) return;
    try {
      await media.files.remove([entry.path]);
      say(`${entry.name} moved to trash`);
      refresh();
    } catch (e) { say(e.message, 'error'); }
  }

  async function star(entry) {
    try {
      await media.files.star(entry.path, !entry.starred);
      entry.starred = !entry.starred;
    } catch (e) { say(e.message, 'error'); }
  }

  async function share(entry) {
    try {
      const s = await media.files.share(entry.path, null);
      const url = `${location.origin}/media/s/${s.token}`;
      await navigator.clipboard.writeText(url).catch(() => {});
      say('Share link copied');
    } catch (e) { say(e.message, 'error'); }
  }

  function zip() {
    const paths = [...sel];
    if (!paths.length) return;
    location.href = media.files.zipUrl(paths);
  }

  /* ---- uploading ---- */
  function accept(files) {
    for (const file of Array.from(files)) {
      const id = ++seq;
      queue = [...queue, { id, name: file.name, pct: 0, error: null }];
      const { promise } = uploadFile(file, path, (p) => {
        queue = queue.map((q) => (q.id === id ? { ...q, pct: p } : q));
      });
      promise
        .then(() => {
          queue = queue.map((q) => (q.id === id ? { ...q, pct: 1 } : q));
          setTimeout(() => { queue = queue.filter((q) => q.id !== id); refresh(); }, 700);
        })
        .catch((e) => {
          queue = queue.map((q) => (q.id === id ? { ...q, error: e.message } : q));
          say(`${file.name}: ${e.message}`, 'error');
        });
    }
  }

  function onDrop(e) {
    e.preventDefault();
    depth = 0; dragging = false;
    if (e.dataTransfer?.files?.length) accept(e.dataTransfer.files);
  }

  const crumbs = $derived(listing?.breadcrumbs || []);
  const entries = $derived(listing?.entries || []);
  /* A kind is a meaning, not a drawing: the icon set answers for the glyph. */
  const ICON = { folder: 'folder', image: 'image', video: 'film', audio: 'mic',
                 pdf: 'list', document: 'list', sheet: 'grid', archive: 'copy' };
  const bytes = $derived(entries.reduce((n, e) => n + (e.is_dir ? 0 : e.size || 0), 0));
</script>

<svelte:head><title>Files · Media</title></svelte:head>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="page"
     ondragenter={(e) => { if (e.dataTransfer?.types?.includes('Files')) { depth++; dragging = true; } }}
     ondragleave={() => { depth = Math.max(0, depth - 1); if (!depth) dragging = false; }}
     ondragover={(e) => { if (e.dataTransfer?.types?.includes('Files')) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; } }}
     ondrop={onDrop}>

  <!-- —————————————————————————————————————————————————— header row ——— -->
  <div class="mg-row">
    <h2 class="mg-h2">Files</h2>
    {#if !loading && entries.length}
      <span class="mg-count">
        {entries.length} item{entries.length === 1 ? '' : 's'}{bytes ? ` · ${fmtBytes(bytes)}` : ''}
      </span>
    {/if}
    <div class="mg-actions">
      {#if can(CAP.UPLOAD)}
        <button class="mg-btn secondary sm" onclick={mkdir} disabled={!mstate.status?.backend}>
          <Icon name="plus" size={14} />Folder
        </button>
        <button class="mg-btn primary sm" onclick={() => input?.click()} disabled={!mstate.status?.backend}>
          <Icon name="upload" size={14} />Upload
        </button>
      {/if}
      <input type="file" multiple bind:this={input} hidden
             onchange={(e) => { accept(e.currentTarget.files); e.currentTarget.value = ''; }} />
    </div>
  </div>

  <!-- ————————————————————————————————————————————————— where you are ——— -->
  <nav class="crumbs mg-noscroll" aria-label="Folder path">
    <button class="crumb" class:on={!path} onclick={() => load('')}>All files</button>
    {#each crumbs as c (c.path)}
      <span class="sep" aria-hidden="true"><Icon name="chevronRight" size={13} /></span>
      <button class="crumb" onclick={() => load(c.path)}>{c.name}</button>
    {/each}
  </nav>

  {#if sel.size}
    <div class="selbar mg-glass-soft" in:fly={{ y: -8, duration: 180 }}>
      <b class="mg-tnum">{sel.size} selected</b>
      {#if can(CAP.DOWNLOAD)}
        <button class="mg-btn secondary sm" onclick={zip}><Icon name="download" size={14} />Zip</button>
      {/if}
      {#if can(CAP.UPLOAD)}
        <button class="mg-btn danger sm" onclick={trash}><Icon name="trash" size={14} />Trash</button>
      {/if}
      <button class="mg-btn ghost sm" onclick={() => (sel = new Set())}>Clear</button>
    </div>
  {/if}

  <!-- ——————————————————————————————————————————————— the drop target ——— -->
  <button class="dz mg-glass-soft" class:over={dragging}
          onclick={() => input?.click()} disabled={!mstate.status?.backend || (mstate.me && !can(CAP.UPLOAD))}>
    <span class="dzi"><Icon name="upload" size={16} /></span>
    {#if dragging}
      <b transition:fade={{ duration: 140 }}>Drop to upload</b>
    {:else}
      <b>Drop files here, or choose some</b>
    {/if}
    <span class="into">into {path || 'All files'}</span>
  </button>

  {#if queue.length}
    <div class="queue">
      {#each queue as u (u.id)}
        <div class="up mg-glass-soft" animate:flip={{ duration: 200 }} in:fly={{ y: 8, duration: 200 }}>
          <div class="uh">
            <span class="un">{u.name}</span>
            <span class="up-pct mg-tnum" class:failed={u.error}>
              {u.error ? 'failed' : Math.round(u.pct * 100) + '%'}
            </span>
          </div>
          <div class="mg-bar" class:failed={!!u.error}>
            <i style:width="{Math.round(u.pct * 100)}%"></i>
          </div>
        </div>
      {/each}
    </div>
  {/if}

  {#if !mstate.status?.backend}
    <Empty icon="alert" title="File store unavailable"
           hint={mstate.status?.backend_error || 'The media backend is not installed here.'} />
  {:else if loading}
    <div class="rows">
      {#each Array(7) as _, i (i)}<Skeleton h="60px" r="18px" delay={i * 55} />{/each}
    </div>
  {:else if !entries.length}
    <Empty icon="folder" title="This folder is empty"
           hint="Drag files anywhere on this page to put them here." />
  {:else}
    <div class="rows">
      {#each entries as e, i (e.path)}
        <div class="row mg-card" class:sel={sel.has(e.path)} animate:flip={{ duration: 220 }}
             in:fly={{ y: 8, duration: 260, delay: Math.min(i * 22, 260) }}>
          <input type="checkbox" checked={sel.has(e.path)} onchange={() => toggle(e)}
                 aria-label="Select {e.name}" />

          <button class="nm" onclick={() => (e.is_dir ? load(e.path) : location.assign(media.files.downloadUrl(e.path)))}>
            <span class="ic"><Icon name={ICON[e.kind] || 'list'} size={17} /></span>
            <span class="txt">
              <span class="t">{e.name}</span>
              <span class="sub mg-tnum">{e.is_dir ? 'Folder' : `${e.kind || 'file'} · ${fmtBytes(e.size)}`}</span>
            </span>
          </button>

          <div class="acts">
            <button class="mg-btn icon sm st" class:on={e.starred} onclick={() => star(e)}
                    aria-label={e.starred ? 'Unstar' : 'Star'} title={e.starred ? 'Unstar' : 'Star'}>
              <Icon name="star" size={14} />
            </button>
            {#if !e.is_dir}
              <a class="mg-btn icon sm secondary dl" href={media.files.downloadUrl(e.path)}
                 aria-label="Download {e.name}" title="Download">
                <Icon name="download" size={14} />
              </a>
            {/if}
            {#if can(CAP.SHARES)}
              <button class="mg-btn icon sm secondary" onclick={() => share(e)}
                      aria-label="Copy a share link for {e.name}" title="Share">
                <Icon name="share" size={14} />
              </button>
            {/if}
            {#if can(CAP.UPLOAD)}
              <button class="mg-btn ghost sm rn" onclick={() => rename(e)}>Rename</button>
              <button class="mg-btn icon sm danger" onclick={() => trashOne(e)}
                      aria-label="Move {e.name} to trash" title="Move to trash">
                <Icon name="trash" size={14} />
              </button>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .page { position: relative; min-height: 60vh; }

  /* ———————————————————————————————————————————————————— breadcrumbs ——— */
  .crumbs {
    display: flex; align-items: center; gap: 2px; margin-bottom: 12px;
    overflow-x: auto; padding-bottom: 2px;
  }
  .crumb {
    flex: none; border: 0; background: none; padding: 0 10px; height: 32px;
    border-radius: 9999px; color: var(--mg-i3);
    font: 500 12.5px/1 var(--mg-font); white-space: nowrap; cursor: pointer;
    transition: background 0.18s, color 0.18s;
  }
  .crumb:hover { background: rgba(255, 255, 255, 0.08); color: var(--mg-i); }
  .crumb.on, .crumb:last-child { color: var(--mg-i); }
  .sep { flex: none; display: flex; color: var(--mg-i3); opacity: 0.6; }

  /* ———————————————————————————————————————————————————— selection ——— */
  .selbar {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    border-radius: var(--mg-r-in); padding: 8px 10px 8px 14px; margin-bottom: 12px;
  }
  .selbar b { margin-right: auto; font: 600 12.5px/1 var(--mg-font); color: var(--mg-i); }

  /* ——————————————————————————————————————————————————— drop target ——— */
  .dz {
    width: 100%; display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    padding: 12px 14px; margin-bottom: 12px; cursor: pointer; text-align: left;
    border: 1px dashed var(--mg-line2); border-radius: var(--mg-r-card);
    color: var(--mg-i2);
    transition: background 0.18s, border-color 0.18s, color 0.18s;
  }
  .dz:hover:not(:disabled) { background: var(--mg-glass-hover); }
  .dz:disabled { opacity: 0.4; cursor: default; }
  .dz b { font: 600 13px/1 var(--mg-font); color: var(--mg-i); }
  .dz .into { font: 400 11.5px/1 var(--mg-font); color: var(--mg-i3); margin-left: auto; }
  .dzi {
    width: 30px; height: 30px; flex: none; border-radius: 10px; display: grid;
    place-items: center; background: rgba(255, 255, 255, 0.07);
    border: 1px solid var(--mg-line); color: inherit;
  }
  .dz.over {
    border-color: rgba(62, 207, 142, 0.7); background: rgba(62, 207, 142, 0.1);
    color: var(--mg-ok);
  }
  .dz.over b { color: var(--mg-ok); }

  /* ———————————————————————————————————————————————————— the queue ——— */
  .queue { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
  .up { border-radius: var(--mg-r-in); padding: 9px 12px; }
  .uh { display: flex; align-items: baseline; gap: 10px; margin-bottom: 7px; }
  .un { flex: 1; min-width: 0; font: 500 12.5px/1.3 var(--mg-font); color: var(--mg-i);
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .up-pct { font: 500 11.5px/1 var(--mg-font); color: var(--mg-i3); flex: none; }
  .up-pct.failed { color: var(--mg-crit); }
  .mg-bar.failed > i { background: var(--mg-crit); }

  /* —————————————————————————————————————————————————————— the list ——— */
  .rows { display: flex; flex-direction: column; gap: 6px; }
  .row {
    display: flex; align-items: center; gap: 10px; padding: 12px;
  }
  .row.sel { background: rgba(62, 207, 142, 0.1); border-color: rgba(62, 207, 142, 0.4); }

  .row input[type='checkbox'] {
    flex: none; width: 17px; height: 17px; margin: 0; accent-color: var(--mg-ok); cursor: pointer;
  }

  .nm {
    flex: 1; min-width: 0; display: flex; align-items: center; gap: 10px;
    border: 0; background: none; padding: 0; color: inherit; text-align: left; cursor: pointer;
  }
  .ic {
    width: 36px; height: 36px; flex: none; border-radius: 50%; display: grid;
    place-items: center; color: var(--mg-i2);
    background: rgba(255, 255, 255, 0.07); border: 1px solid var(--mg-line);
    transition: color 0.18s, border-color 0.18s;
  }
  .nm:hover .ic { color: var(--mg-i); border-color: var(--mg-line2); }
  .txt { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .t { font: 500 13.5px/1.25 var(--mg-font); letter-spacing: -0.01em; color: var(--mg-i);
       overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sub { font: 400 11.5px/1.25 var(--mg-font); color: var(--mg-i3);
         overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
         text-transform: lowercase; }

  .acts { flex: none; display: flex; align-items: center; gap: 4px; }
  .st { color: var(--mg-i3); }
  .st:hover { color: var(--mg-i); background: rgba(255, 255, 255, 0.08); }
  .st.on { color: var(--mg-warn); }

  /* A thumb is not a mouse pointer: on touch the row's round buttons grow to
     the 40px the rest of the section keeps for a tap target. */
  @media (pointer: coarse) {
    .acts .mg-btn.icon { width: 40px; height: 40px; }
    .crumb { height: 40px; }
    .row input[type='checkbox'] { width: 22px; height: 22px; margin: 0 2px; }
    .selbar .mg-btn { height: 40px; }
  }

  /* A phone keeps the two actions you reach for; the rest live on the row you
     can actually see the width of. */
  @media (max-width: 560px) {
    .rn, .dl { display: none; }
    .dz .into { margin-left: 0; width: 100%; }
    .row { padding: 10px; gap: 8px; }
    .acts { gap: 2px; }
    .ic { width: 32px; height: 32px; }
  }
</style>
