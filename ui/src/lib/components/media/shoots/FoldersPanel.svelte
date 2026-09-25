<script>
  /* The library folders a shoot owns. Linking and unlinking never touches a
     file — it only records which folders belong to this address
     (POST/DELETE /api/shoots/{id}/folders). A folder can belong to one shoot. */
  import Icon from '$lib/components/glass/Icon.svelte';
  import { goto } from '$app/navigation';
  import { mstate, say } from '$lib/media.svelte.js';
  import { media } from '$lib/media.js';
  import { shoots, folderName } from '$lib/media/shoots.js';

  let { shoot, onchange } = $props();

  let suggestions = $state([]);
  let allFolders = $state([]);
  let pick = $state('');
  let busy = $state(false);

  async function loadOptions() {
    const [s, f] = await Promise.all([
      shoots.suggestFolders().catch(() => null),
      media.folders().catch(() => null)
    ]);
    suggestions = s?.suggestions || [];
    allFolders = Array.isArray(f) ? f : [];
  }
  $effect(() => { shoot; loadOptions(); });

  const linked = $derived(new Set(shoot.folders || []));
  const suggestedPaths = $derived(new Set(suggestions.map((s) => s.path)));
  /* Everything else in the library, for a sub-folder or a folder the
     suggestions skip (they only offer top-level folders not on a shoot). */
  const others = $derived(
    allFolders
      .map((f) => String(f.path || '').replace(/\\/g, '/').replace(/\/$/, ''))
      .filter((p) => p && !linked.has(p) && !suggestedPaths.has(p))
  );
  const rel = (p) => {
    const f = allFolders.find((x) => String(x.path).replace(/\\/g, '/').replace(/\/$/, '') === p);
    return f?.relative_path || folderName(p);
  };

  /* Browse has no ?folder= param; it keeps its filters in mstate, so set
     them and make it reload on arrival. */
  function openInBrowse(id) {
    mstate.filters.folder_id = id;
    mstate.filters.include_subfolders = true;
    mstate.loaded = false;
    goto('/media/browse');
  }

  async function link() {
    if (!pick) return;
    busy = true;
    try {
      const s = await shoots.addFolder(shoot.id, pick);
      pick = '';
      say('Folder linked');
      onchange?.(s);           // the new shoot re-runs loadOptions via the effect
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }

  async function unlink(path) {
    if (!confirm(`Unlink "${folderName(path)}"? The files stay exactly where they are.`)) return;
    try {
      const s = await shoots.removeFolder(shoot.id, path);
      say('Folder unlinked');
      onchange?.(s);           // the new shoot re-runs loadOptions via the effect
    } catch (e) { say(e.message, 'error'); }
  }
</script>

<section class="mg-card">
  <div class="hd">
    <h3><Icon name="folder" size={15} />Library folders</h3>
    {#if shoot.counts}
      <span class="mg-count">{shoot.counts.photos} photos · {shoot.counts.videos} videos</span>
    {/if}
  </div>

  {#if shoot.folders?.length}
    <ul class="fl">
      {#each shoot.folders as p, i (p)}
        <li>
          <Icon name="folder" size={14} />
          <span class="nm" title={p}>{rel(p)}</span>
          {#if shoot.folder_ids?.[i] != null}
            <button class="mg-btn ghost sm" onclick={() => openInBrowse(shoot.folder_ids[i])}>Open</button>
          {:else}
            <span class="mg-chip warn">not indexed</span>
          {/if}
          <button class="mg-btn ghost icon sm" onclick={() => unlink(p)} aria-label="Unlink {folderName(p)}" title="Unlink">
            <Icon name="x" size={14} />
          </button>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="none">No folders yet. Link the folder the photos and video landed in.</p>
  {/if}

  <div class="add">
    <div class="mg-select">
      <select bind:value={pick} aria-label="Folder to link">
        <option value="">Link a folder…</option>
        {#if suggestions.length}
          <optgroup label="Suggested (not on a shoot yet)">
            {#each suggestions as s (s.path)}<option value={s.path}>{folderName(s.path)}</option>{/each}
          </optgroup>
        {/if}
        {#if others.length}
          <optgroup label="All folders">
            {#each others as p (p)}<option value={p}>{rel(p)}</option>{/each}
          </optgroup>
        {/if}
      </select>
      <span class="ic"><Icon name="chevronDown" size={15} /></span>
    </div>
    <button class="mg-btn secondary" onclick={link} disabled={!pick || busy}><Icon name="link" size={14} />Link</button>
  </div>
</section>

<style>
  .hd { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
  h3 { margin: 0; flex: 1; display: flex; align-items: center; gap: 7px; font: 600 14px/1.3 var(--mc-font); color: var(--mc-ink); }
  .fl { list-style: none; margin: 0 0 12px; padding: 0; display: flex; flex-direction: column; gap: 4px; }
  .fl li { display: flex; align-items: center; gap: 8px; min-height: 40px; padding: 0 4px 0 10px;
           border-radius: var(--mc-r-md); background: var(--mc-raised); border: 1px solid var(--mc-line); color: var(--mc-ink3); }
  .nm { flex: 1; min-width: 0; font: 500 13px/1.3 var(--mc-font); color: var(--mc-ink);
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .none { margin: 0 0 12px; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink3); }
  .add { display: flex; gap: 8px; }
  .add .mg-select { flex: 1; min-width: 0; }
</style>
