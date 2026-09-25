<script>
  /* What has arrived through this link and not been filed yet.

     Nothing a phone sends reaches the library proper until someone does this:
     tick what to move (or leave it all), choose a folder or name a new one,
     and file. Moving files needs media.organise; without it the list is
     read-only and says why. */
  import { onMount } from 'svelte';
  import { thumbUrl, fmtBytes } from '$lib/media.js';
  import { say } from '$lib/media.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import { portals, when } from '$lib/media/portals.js';

  let { share, folders = [], canOrganise = false, onfiled } = $props();

  let data = $state(null);
  let err = $state('');
  let picked = $state(new Set());
  let target = $state('');           // folder id, or '__new'
  let newName = $state('');
  let busy = $state(false);

  async function load() {
    try { data = await portals.intake(share.id); picked = new Set(); }
    catch (e) { err = e.message; }
  }
  onMount(load);

  function flip(id) {
    const n = new Set(picked);
    n.has(id) ? n.delete(id) : n.add(id);
    picked = n;
  }

  async function file() {
    if (busy) return;
    const body = {};
    if (picked.size) body.video_ids = [...picked];
    if (target === '__new') {
      if (!newName.trim()) { say('Name the new folder', 'error'); return; }
      body.new_folder = newName.trim();
    } else if (target) body.folder_id = Number(target);
    else { say('Choose where to file them', 'error'); return; }
    busy = true;
    try {
      const r = await portals.fileIntake(share.id, body);
      say(`Filed ${r.moved} into ${r.folder}` + (r.failed?.length ? ` — ${r.failed.length} failed` : ''),
          r.failed?.length ? 'error' : 'ok');
      newName = '';
      await load();
      onfiled?.();
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }
</script>

{#if err}
  <p class="none">{err}</p>
{:else if !data}
  <p class="none">Loading…</p>
{:else if !data.items.length}
  <p class="none">The inbox is empty{data.folder ? ` (${data.folder})` : ''} — anything the client sends lands here first.</p>
{:else}
  <p class="lead">{data.count} file{data.count === 1 ? '' : 's'} waiting in <b>{data.folder}</b></p>
  <ul class="items">
    {#each data.items as it (it.id)}
      <li>
        {#if canOrganise}
          <label class="ck"><input type="checkbox" checked={picked.has(it.id)} onchange={() => flip(it.id)}
                                   aria-label="Select {it.filename}" /></label>
        {/if}
        <span class="th">
          {#if it.thumbnail_path}<img src={thumbUrl(it)} alt="" loading="lazy" />
          {:else}<Icon name={it.media_type === 'video' ? 'film' : it.media_type === 'photo' ? 'image' : 'box'} size={16} />{/if}
        </span>
        <span class="nm">
          <b title={it.filename}>{it.filename}</b>
          <small class="mg-tnum">{[fmtBytes(it.file_size), it.uploaded_by, when(it.uploaded_at)].filter(Boolean).join(' · ')}</small>
        </span>
      </li>
    {/each}
  </ul>

  {#if canOrganise}
    <div class="fileto">
      <div class="mg-select grow">
        <select bind:value={target} aria-label="File into">
          <option value="">File {picked.size ? `${picked.size} selected` : 'all'} into…</option>
          <option value="__new">A new folder…</option>
          {#each folders as f (f.id)}<option value={f.id}>{f.name}</option>{/each}
        </select>
        <span class="ic"><Icon name="chevronDown" size={15} /></span>
      </div>
      {#if target === '__new'}
        <input class="mg-input grow" type="text" bind:value={newName} placeholder="Folder name" aria-label="New folder name" />
      {/if}
      <button class="mg-btn primary sm" onclick={file} disabled={busy || !target}>
        <Icon name="folder" size={13} />{busy ? 'Filing…' : `File ${picked.size || 'all'}`}
      </button>
    </div>
  {:else}
    <p class="none">Your account can't move files, so someone with organise rights needs to file these.</p>
  {/if}
{/if}

<style>
  .none { margin: 0; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink3); }
  .lead { margin: 0 0 8px; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink2); }
  .lead b { color: var(--mc-ink); font-weight: 500; }
  .items { list-style: none; margin: 0 0 10px; padding: 0; display: flex; flex-direction: column; gap: 4px;
           max-height: 320px; overflow-y: auto; }
  li { display: flex; align-items: center; gap: 10px; min-height: 44px; padding: 4px 6px;
       border-radius: 10px; background: var(--mc-raised); }
  .ck { display: grid; place-items: center; width: 32px; height: 36px; flex: none; cursor: pointer; }
  .ck input { width: 17px; height: 17px; accent-color: var(--mc-accent); }
  .th { flex: none; width: 54px; height: 34px; border-radius: 6px; overflow: hidden; background: var(--mc-inset);
        display: grid; place-items: center; color: var(--mc-ink3); }
  .th img { width: 100%; height: 100%; object-fit: cover; }
  .nm { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .nm b { font: 500 12.5px/1.3 var(--mc-font); color: var(--mc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .nm small { font: 400 11px/1.4 var(--mc-font); color: var(--mc-ink3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .fileto { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .grow { flex: 1 1 180px; min-width: 0; }
  .mg-select.grow { display: block; }
  .fileto .mg-btn { min-height: 40px; }
</style>
