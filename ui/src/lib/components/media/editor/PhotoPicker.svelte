<script>
  /* /media/edit with no photo: the most recent stills, to pick one to edit. */
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import { pe } from '$lib/media/photoedit.js';
  import { photoUrl } from '$lib/media.js';

  let photos = $state([]);
  let loading = $state(true);
  let error = $state(null);
  let search = $state('');
  let edited = $state({ edited: [], picks: {}, stars: {}, copies: {} });
  let limit = $state(60);
  let timer;

  async function load() {
    loading = true;
    try {
      photos = (await pe.photos({ search: search.trim() || null })) || [];
      error = null;
      const ids = photos.slice(0, 400).map((p) => p.id);
      if (ids.length) pe.edited(ids).then((e) => (edited = e)).catch(() => {});
    } catch (e) { error = e.message; photos = []; }
    finally { loading = false; }
  }
  onMount(load);

  function onSearch() {
    clearTimeout(timer);
    timer = setTimeout(() => { limit = 60; load(); }, 300);
  }
  const isEdited = (id) => edited.edited?.includes(id);
</script>

<div class="mg-row">
  <h2 class="mg-h2">Photo editor</h2>
  <span class="mg-count">{photos.length ? `${photos.length} photos` : ''}</span>
</div>
<div class="mg-controls">
  <label class="mg-search">
    <span class="ic"><Icon name="search" size={15} /></span>
    <input class="mg-input" type="search" placeholder="Find a photo" bind:value={search} oninput={onSearch} />
  </label>
</div>

{#if error}
  <Empty icon="alert" title="Couldn't load photos" hint={error} />
{:else if loading && !photos.length}
  <div class="grid" aria-busy="true">{#each Array(12) as _, i (i)}<div class="mg-panel sk"><Skeleton h="auto" r="0" delay={i * 40} /><div class="skm"><Skeleton h="12px" w="70%" delay={i * 40} /></div></div>{/each}</div>
{:else if !photos.length}
  <Empty icon="image" title="No photos yet" hint="Photos appear here once they're in the media library.">
    <a class="mg-btn secondary" href="/media/browse">Open the library</a>
  </Empty>
{:else}
  <div class="grid">
    {#each photos.slice(0, limit) as p (p.id)}
      <button type="button" class="card mg-panel mg-hover" onclick={() => goto(`/media/edit?id=${p.id}`)}>
        <img src={photoUrl(p, 600)} alt="" loading="lazy" />
        <span class="meta">
          <span class="nm">{p.filename}</span>
          <span class="bd">
            {#if isEdited(p.id)}<span class="mg-chip ok">Edited</span>{/if}
            {#if edited.copies?.[p.id]}<span class="mg-chip">{edited.copies[p.id]} cop{edited.copies[p.id] === 1 ? 'y' : 'ies'}</span>{/if}
            {#if edited.stars?.[p.id]}<span class="st">{'★'.repeat(edited.stars[p.id])}</span>{/if}
          </span>
        </span>
      </button>
    {/each}
  </div>
  {#if photos.length > limit}
    <div class="more"><button type="button" class="mg-btn secondary" onclick={() => (limit += 60)}>Show more</button></div>
  {/if}
{/if}

<style>
  .grid { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); }
  .card { display: flex; flex-direction: column; padding: 0; overflow: hidden; border-radius: var(--mc-r-md);
          cursor: pointer; color: inherit; font: inherit; text-align: left; }
  .card img { width: 100%; aspect-ratio: 3 / 2; object-fit: cover; background: var(--mc-inset); display: block; }
  .meta { display: flex; flex-direction: column; gap: 6px; padding: 8px 10px 10px; min-width: 0; }
  .nm { font-size: 12.5px; color: var(--mc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bd { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; min-height: 18px; }
  .bd .mg-chip { padding: 3px 8px; font-size: 10.5px; }
  .st { color: var(--mc-warn); font-size: 11px; letter-spacing: 1px; }
  .sk { overflow: hidden; border-radius: var(--mc-r-md); }
  .sk > :global(.mg-skel:first-child) { aspect-ratio: 3 / 2; height: auto; }
  .skm { padding: 10px; }
  .more { display: flex; justify-content: center; margin-top: 16px; }
  @media (max-width: 480px) { .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
