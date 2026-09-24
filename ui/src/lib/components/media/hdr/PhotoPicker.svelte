<script>
  /* Pick one photo from the library: a folder select and a grid of that
     folder's photos. Used by the Looks tab when no ?id= came with the URL. */
  import { untrack } from 'svelte';
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import { media, thumbUrl } from '$lib/media.js';
  import FolderSelect from './FolderSelect.svelte';

  let { open = false, onpick, onclose, title = 'Choose a photo' } = $props();

  let folder = $state(null);
  let photos = $state([]);
  let loading = $state(false);
  let err = $state('');
  let q = $state('');

  async function load() {
    loading = true; err = '';
    try {
      photos = (await media.videos({ media_type: 'photo', folder_id: folder, search: q || null,
                                     sort_by: 'date', sort_order: 'desc' })) || [];
    } catch (e) { err = e.message; photos = []; }
    finally { loading = false; }
  }

  $effect(() => {
    if (!open) return;
    folder;
    untrack(load);
  });
</script>

<Sheet {open} {title} size="lg" {onclose}>
  <div class="bar">
    <FolderSelect value={folder} onchange={(v) => { folder = v; }} allowAll />
    <label class="mg-search s">
      <span class="ic"><Icon name="search" size={15} /></span>
      <input class="mg-input" type="search" bind:value={q} placeholder="Filter by name"
             onkeydown={(e) => e.key === 'Enter' && load()} aria-label="Filter photos" />
    </label>
  </div>
  {#if err}
    <p class="err">{err}</p>
  {:else if loading}
    <div class="mg-bar indeterminate"><i></i></div>
  {:else if !photos.length}
    <Empty icon="image" title="No photos here" hint="Pick another folder, or add photos in Browse." />
  {:else}
    <div class="grid">
      {#each photos as p (p.id)}
        <button type="button" class="tile" onclick={() => onpick?.(p)} title={p.filename}>
          {#if thumbUrl(p)}<img src={thumbUrl(p)} alt="" loading="lazy" />{:else}<span class="ph"><Icon name="image" size={18} /></span>{/if}
          <span class="nm">{p.filename}</span>
        </button>
      {/each}
    </div>
  {/if}
</Sheet>

<style>
  .bar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
  .s { flex: 1 1 180px; }
  .err { color: var(--mg-crit); font: 400 13px/1.5 var(--mg-font); }
  .grid { display: grid; gap: 8px; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); }
  .tile {
    display: flex; flex-direction: column; gap: 4px; padding: 4px; border: 1px solid var(--mg-line);
    border-radius: 12px; background: var(--mg-glass-soft); color: var(--mg-i2); cursor: pointer; text-align: left; min-width: 0;
  }
  .tile:hover { border-color: var(--mg-line2); background: var(--mg-glass-hover); }
  .tile img, .ph { width: 100%; aspect-ratio: 3 / 2; object-fit: cover; border-radius: 9px; display: grid; place-items: center; background: var(--mg-term); }
  .nm { font: 400 11.5px/1.3 var(--mg-font); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
