<script>
  /* Attach one item from the media library — photos and clips, newest first,
     filtered by name. A Sheet (it portals above the chat sheet), built on
     media.js's list call; the editor/video pickers are single-kind and wired
     to their own pages, so this is the small general one. */
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import { media, thumbUrl, ensureToken } from '$lib/media.js';

  let { open = false, onclose, onpick } = $props();

  let q = $state('');
  let items = $state([]);
  let loading = $state(false);
  let error = $state('');
  let limit = $state(48);
  let timer;
  let seq = 0;               // only the newest request may land

  async function load(search) {
    const mine = ++seq;
    loading = true;
    error = '';
    try {
      await ensureToken();
      const got = (await media.videos({ search: search || null, sort_by: 'date', sort_order: 'desc' })) || [];
      if (mine !== seq) return;
      items = got;
      limit = 48;
    } catch (e) {
      if (mine !== seq) return;
      error = e?.status === 403 ? 'Your account cannot use the media library.' : (e?.message || 'Could not load the library');
      items = [];
    } finally {
      if (mine === seq) loading = false;
    }
  }

  $effect(() => {
    if (!open) return;
    const s = q.trim();
    clearTimeout(timer);
    timer = setTimeout(() => load(s), s ? 260 : 0);
    return () => clearTimeout(timer);
  });

  function pick(v) {
    onpick?.({
      type: 'media', id: v.id,
      name: v.filename || v.name || 'Media',
      kind: v.media_type || 'video',
      thumb: v.thumbnail_path || null,
      caption: null
    });
  }
</script>

<Sheet {open} title="Attach from the library" size="lg" {onclose}>
  <label class="mg-search srch">
    <span class="ic"><Icon name="search" size={15} /></span>
    <input class="mg-input" type="search" bind:value={q} placeholder="Find a photo or clip…" aria-label="Find media" />
  </label>

  {#if error}
    <Empty icon="alert" title="Library unavailable" hint={error} />
  {:else if loading && !items.length}
    <div class="grid" aria-busy="true" aria-label="Loading the library">
      {#each Array(8) as _, i (i)}<div class="it"><span class="th mg-skel"></span></div>{/each}
    </div>
  {:else if !items.length}
    <Empty icon="image" title="Nothing found" hint={q ? 'Nothing matches that name.' : 'The library is empty.'} />
  {:else}
    <div class="grid" role="listbox" aria-label="Media">
      {#each items.slice(0, limit) as v (v.id)}
        <button type="button" class="it" role="option" aria-selected="false" onclick={() => pick(v)}>
          <span class="th">
            {#if thumbUrl(v)}<img src={thumbUrl(v)} alt="" loading="lazy" />{:else}<Icon name={v.media_type === 'photo' ? 'image' : 'film'} size={20} />{/if}
            {#if (v.media_type || 'video') === 'video'}<i class="k"><Icon name="play" size={11} /></i>{/if}
          </span>
          <span class="nm">{v.filename}</span>
        </button>
      {/each}
    </div>
    {#if items.length > limit}
      <div class="more"><button type="button" class="mg-btn secondary sm" onclick={() => (limit += 48)}>Show more</button></div>
    {/if}
  {/if}
</Sheet>

<style>
  .srch { margin-bottom: 14px; }
  .grid { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); }
  .it {
    display: flex; flex-direction: column; gap: 6px; padding: 0; min-width: 0;
    border: 0; background: none; color: var(--mc-ink2); cursor: pointer; text-align: left; font: inherit;
  }
  .th {
    position: relative; display: grid; place-items: center; width: 100%; aspect-ratio: 4 / 3;
    border-radius: 10px; overflow: hidden; background: var(--mc-inset); border: 1px solid var(--mc-glass-line);
    color: var(--mc-ink3); transition: border-color var(--mc-t-fast);
  }
  .it:hover .th, .it:focus-visible .th { border-color: var(--mc-accent); }
  .th img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .k {
    position: absolute; right: 5px; bottom: 5px; width: 20px; height: 20px; border-radius: 50%;
    display: grid; place-items: center; background: rgba(0, 0, 0, 0.6); color: #fff;
  }
  .nm { font: 400 12px/1.3 var(--mc-font); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .more { display: flex; justify-content: center; margin-top: 14px; }
</style>
