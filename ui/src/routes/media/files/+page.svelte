<script>
  /* The general file store — contracts, stills, decks, anything that is not
     footage. Same backend module as Zerko's Files tab (files_api.py), which
     keeps the filesystem as the source of truth and puts every client path
     through one containment gate.

     Drag anything onto the page and it uploads into the folder you are
     standing in, each file carrying its own progress bar. */
  import { onMount } from 'svelte';
  import { rise, slide, fade } from '$lib/motion.js';
  import { flip } from 'svelte/animate';
  import { mstate, boot, say, can, CAP } from '$lib/media.svelte.js';
  import { media, uploadFile, fmtBytes } from '$lib/media.js';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';

  let path = $state('');
  let listing = $state(null);
  let loading = $state(true);
  let err = $state(null);          // the listing failed
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
    loading = true; err = null;
    sel = new Set();
    try { listing = await media.files.list(p); path = listing.path ?? p; }
    catch (e) { err = e.message; say(e.message, 'error'); listing = { entries: [], breadcrumbs: [] }; }
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
  {#if mstate.status?.backend}
  <nav class="crumbs mg-noscroll" aria-label="Folder path">
    <button class="crumb" class:on={!path} onclick={() => load('')}>All files</button>
    {#each crumbs as c (c.path)}
      <span class="sep" aria-hidden="true"><Icon name="chevronRight" size={13} /></span>
      <button class="crumb" onclick={() => load(c.path)}>{c.name}</button>
    {/each}
  </nav>

  {#if sel.size}
    <div class="selbar mg-panel" transition:slide={{ y: -8, duration: 200 }}>
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
  <button class="dz" class:over={dragging}
          onclick={() => input?.click()} disabled={!mstate.status?.backend || (mstate.me && !can(CAP.UPLOAD))}>
    <span class="dzi"><Icon name="upload" size={16} /></span>
    {#if dragging}
      <b transition:fade={{ duration: 140 }}>Drop to upload</b>
    {:else}
      <b>Drop files here, or choose some</b>
    {/if}
    <span class="into">into {path || 'All files'}</span>
  </button>
  {/if}

  {#if queue.length}
    <div class="queue">
      {#each queue as u (u.id)}
        <div class="up mg-panel" animate:flip={{ duration: 200 }} in:rise>
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
    <div class="rows mg-panel sk">
      {#each Array(7) as _, i (i)}<Skeleton h="44px" r="8px" delay={i * 55} />{/each}
    </div>
  {:else if err}
    <div class="mg-strip crit">
      <span class="ic"><Icon name="alert" size={15} /></span>
      <span><b>Couldn't open this folder</b> — {err}</span>
      <button class="mg-btn secondary sm retry" onclick={refresh}><Icon name="refresh" size={13} />Retry</button>
    </div>
  {:else if !entries.length}
    <Empty icon="folder" title="This folder is empty"
           hint="Drag files anywhere on this page to put them here." />
  {:else}
    <div class="rows mg-panel">
      {#each entries as e, i (e.path)}
        <div class="row" class:sel={sel.has(e.path)} animate:flip={{ duration: 220 }}
             in:rise={{ i }}>
          <input type="checkbox" checked={sel.has(e.path)} onchange={() => toggle(e)}
                 aria-label="Select {e.name}" />

          <button class="nm" onclick={() => (e.is_dir ? load(e.path) : location.assign(media.files.downloadUrl(e.path)))}>
            <span class="ic"><Icon name={ICON[e.kind] || (e.is_dir ? 'folder' : 'list')} size={17} /></span>
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
    border-radius: var(--mc-r-sm); color: var(--mc-ink3);
    font: 500 12.5px/1 var(--mc-font); white-space: nowrap; cursor: pointer;
    transition: background var(--mc-t-fast), color var(--mc-t-fast);
  }
  .crumb:hover { background: var(--mc-raised); color: var(--mc-ink); }
  .crumb.on, .crumb:last-child { color: var(--mc-ink); }
  .sep { flex: none; display: flex; color: var(--mc-ink3); opacity: 0.6; }

  /* ———————————————————————————————————————————————————— selection ——— */
  .selbar {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    border-radius: var(--mc-r-md); padding: 8px 10px 8px 14px; margin-bottom: 12px;
  }
  .selbar b { margin-right: auto; font: 600 12.5px/1 var(--mc-font); color: var(--mc-ink); }

  /* ——————————————————————————————————————————————————— drop target ——— */
  .dz {
    width: 100%; display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    padding: 12px 14px; margin-bottom: 12px; cursor: pointer; text-align: left;
    border: 1px dashed var(--mc-line2); border-radius: var(--mc-r-md);
    background: var(--mc-surface); color: var(--mc-ink2); font: inherit;
    transition: background var(--mc-t-fast), border-color var(--mc-t-fast), color var(--mc-t-fast);
  }
  .dz:hover:not(:disabled) { background: var(--mc-raised); }
  .dz:disabled { opacity: 0.4; cursor: default; }
  .dz b { font: 600 13px/1 var(--mc-font); color: var(--mc-ink); }
  .dz .into { font: 400 11.5px/1 var(--mc-font); color: var(--mc-ink3); margin-left: auto; }
  .dzi {
    width: 30px; height: 30px; flex: none; border-radius: var(--mc-r-sm); display: grid;
    place-items: center; background: var(--mc-raised);
    border: 1px solid var(--mc-line); color: inherit;
  }
  .dz.over {
    border-color: var(--mc-accent); background: var(--mc-ok-soft);
    color: var(--mc-accent);
  }
  .dz.over b { color: var(--mc-accent); }

  /* ———————————————————————————————————————————————————— the queue ——— */
  .queue { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
  .up { border-radius: var(--mc-r-md); padding: 9px 12px; }
  .uh { display: flex; align-items: baseline; gap: 10px; margin-bottom: 7px; }
  .un { flex: 1; min-width: 0; font: 500 12.5px/1.3 var(--mc-font); color: var(--mc-ink);
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .up-pct { font: 500 11.5px/1 var(--mc-font); color: var(--mc-ink3); flex: none; }
  .up-pct.failed { color: var(--mc-crit); }
  .mg-bar.failed > i { background: var(--mc-crit); }

  /* —————————————————————————————————————————————————————— the list ——— */
  /* one panel, rows split by hairlines */
  .rows { display: flex; flex-direction: column; overflow: hidden; }
  .rows.sk { gap: 8px; padding: 12px; }
  .row {
    display: flex; align-items: center; gap: 10px; min-height: 60px; padding: 10px 12px 10px 16px;
    border-bottom: 1px solid var(--mc-line); transition: background var(--mc-t-fast);
  }
  .row:last-child { border-bottom: 0; }
  .row:hover { background: rgba(255, 255, 255, 0.03); }
  .row.sel { background: var(--mc-ok-soft); }
  .retry { margin-left: auto; align-self: center; }

  .row input[type='checkbox'] {
    flex: none; width: 17px; height: 17px; margin: 0; accent-color: var(--mc-accent); cursor: pointer;
  }

  .nm {
    flex: 1; min-width: 0; display: flex; align-items: center; gap: 10px;
    border: 0; background: none; padding: 0; color: inherit; text-align: left; cursor: pointer;
  }
  .ic {
    width: 36px; height: 36px; flex: none; border-radius: var(--mc-r-md); display: grid;
    place-items: center; color: var(--mc-ink2);
    background: var(--mc-raised); border: 1px solid var(--mc-line);
    transition: color var(--mc-t-fast), border-color var(--mc-t-fast);
  }
  .nm:hover .ic { color: var(--mc-ink); border-color: var(--mc-line2); }
  .txt { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .t { font: 500 13.5px/1.25 var(--mc-font); letter-spacing: -0.01em; color: var(--mc-ink);
       overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sub { font: 400 11.5px/1.25 var(--mc-font); color: var(--mc-ink3);
         overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
         text-transform: lowercase; }

  .acts { flex: none; display: flex; align-items: center; gap: 4px; }
  .st { color: var(--mc-ink3); }
  .st:hover { color: var(--mc-ink); background: var(--mc-raised); }
  .st.on { color: var(--mc-warn); }

  /* A thumb is not a mouse pointer: on touch the row's buttons grow to 44px. */
  @media (pointer: coarse) {
    .acts .mg-btn.icon { width: 44px; height: 44px; }
    .crumb { height: 44px; }
    .row input[type='checkbox'] { width: 22px; height: 22px; margin: 0 2px; }
    .selbar .mg-btn { height: 44px; }
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
