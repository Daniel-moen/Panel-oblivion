<script>
  /* Pick clips from the library to put on the timeline. Tap to select (the
     order you tap is the order they land in), then "Add". Only video — the
     timeline's main track is pictures. */
  import { thumbUrl, fmtDuration } from '$lib/media.js';
  import { vapi } from '$lib/media/video.js';
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';

  let { open = false, onclose, onpick, title = 'Add clips', single = false } = $props();

  let q = $state('');
  let items = $state([]);
  let loading = $state(false);
  let picked = $state([]);          // ordered ids
  let timer;

  async function load(search) {
    loading = true;
    try {
      items = ((await vapi.videos({ media_type: 'video', search, sort_by: 'date', sort_order: 'desc' })) || [])
        .filter((v) => (v.media_type || 'video') === 'video');
    } catch { items = []; }
    finally { loading = false; }
  }

  $effect(() => {
    if (!open) return;
    const s = q;
    clearTimeout(timer);
    timer = setTimeout(() => load(s), s ? 260 : 0);
    return () => clearTimeout(timer);
  });

  $effect(() => { if (open) picked = []; });

  function toggle(v) {
    if (single) { onpick?.([v]); return; }
    picked = picked.includes(v.id) ? picked.filter((x) => x !== v.id) : [...picked, v.id];
  }

  function add() {
    const byId = new Map(items.map((v) => [v.id, v]));
    onpick?.(picked.map((id) => byId.get(id)).filter(Boolean));
  }
</script>

<Sheet {open} {title} size="lg" {onclose}>
  <label class="mg-search srch">
    <span class="ic"><Icon name="search" size={15} /></span>
    <input class="mg-input" type="search" bind:value={q} placeholder="Find a clip…" aria-label="Find a clip" />
  </label>

  {#if loading && !items.length}
    <p class="hint">Loading the library…</p>
  {:else if !items.length}
    <Empty icon="film" title="No video clips" hint={q ? 'Nothing matches that name.' : 'Index some footage first.'} />
  {:else}
    <div class="grid">
      {#each items as v (v.id)}
        {@const n = picked.indexOf(v.id)}
        <button type="button" class="it" class:on={n >= 0} onclick={() => toggle(v)}>
          <span class="th">
            {#if thumbUrl(v)}<img src={thumbUrl(v)} alt="" loading="lazy" />{/if}
            {#if n >= 0}<b class="n">{n + 1}</b>{/if}
            <i class="d mg-tnum">{fmtDuration(v.duration)}</i>
          </span>
          <span class="nm">{v.filename}</span>
        </button>
      {/each}
    </div>
  {/if}

  {#snippet footer()}
    {#if !single}
    <span class="mg-count">{picked.length} selected</span>
    <div class="right">
      <button type="button" class="mg-btn ghost" onclick={() => onclose?.()}>Cancel</button>
      <button type="button" class="mg-btn accent" disabled={!picked.length} onclick={add}>
        <Icon name="plus" size={15} />Add {picked.length || ''}
      </button>
    </div>
    {/if}
  {/snippet}
</Sheet>

<style>
  .srch { margin-bottom: 12px; }
  .hint { color: var(--mc-ink3); font-size: 13px; }
  .grid { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }
  .it {
    display: flex; flex-direction: column; gap: 6px; padding: 6px; text-align: left;
    border: 1px solid var(--mc-line); border-radius: 14px; background: var(--mc-raised);
    color: var(--mc-ink2); cursor: pointer; min-width: 0; font: 500 12px/1.3 var(--mc-font);
  }
  .it.on { border-color: var(--mc-accent); background: rgba(62, 207, 142, 0.1); color: var(--mc-ink); }
  .th { position: relative; aspect-ratio: 16 / 9; border-radius: 9px; overflow: hidden; background: var(--mc-inset); }
  .th img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .n {
    position: absolute; top: 6px; left: 6px; width: 24px; height: 24px; border-radius: 50%;
    display: grid; place-items: center; background: var(--mc-accent); color: var(--mc-accent-ink); font-size: 12px;
  }
  .d { position: absolute; right: 6px; bottom: 6px; font-style: normal; font-size: 11px; padding: 2px 6px; border-radius: 6px; background: rgba(0, 0, 0, 0.6); color: #fff; }
  .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  @media (max-width: 560px) { .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
