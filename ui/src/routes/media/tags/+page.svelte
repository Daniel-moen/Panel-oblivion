<script>
  /* Tags: what exists, how much each holds, and where it came from.

     Rendered as a wall rather than a grid of cards. A tag is a word with a
     weight — the weight IS the type size — so the shape of the library reads
     at a glance: the three tags that hold half the footage are simply bigger
     than the forty that hold one clip each.

     Provenance stays on the chip. Most of this library is tagged by machine —
     camera make from EXIF, stage from the filename, subjects from the
     transcript — and knowing which rule put a tag there is what tells you
     whether to trust it or fix the rule. */
  import { onMount } from 'svelte';
  import { rise } from '$lib/motion.js';
  import { flip } from 'svelte/animate';
  import { mstate, boot, runAutoTag, say, can, CAP } from '$lib/media.svelte.js';
  import { media } from '$lib/media.js';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';

  let overview = $state(null);
  let loading = $state(true);
  let q = $state('');

  onMount(async () => {
    await boot();
    if (!mstate.ready) { loading = false; return; }
    try { overview = await media.tagOverview(); }
    catch (e) { say(e.message, 'error'); }
    finally { loading = false; }
  });

  const tags = $derived.by(() => {
    const list = overview?.tags || [];
    const n = q.trim().toLowerCase();
    const filtered = n ? list.filter((t) => t.name?.toLowerCase().includes(n)) : list;
    return [...filtered].sort((a, b) => (b.count || 0) - (a.count || 0));
  });
  const max = $derived(Math.max(1, ...tags.map((t) => t.count || 0)));

  /* 12.5 → 17px, on a square root so one enormous tag does not flatten the
     rest of the wall into the same small size. */
  const sizeOf = (n) => 12.5 + Math.sqrt(Math.min(1, (n || 0) / max)) * 4.5;

  const SOURCE = { transcript: 'spoken', camera: 'camera', stage: 'stage', manual: 'by hand' };
</script>

<svelte:head><title>Tags · Media</title></svelte:head>

<div class="mg-row">
  <h2 class="mg-h2">Tags</h2>
  {#if overview}
    <span class="mg-count">{tags.length} tag{tags.length === 1 ? '' : 's'}</span>
  {/if}
  {#if can(CAP.ADMIN)}
    <div class="mg-actions">
      <button class="mg-btn secondary sm" onclick={runAutoTag} disabled={!mstate.ready}>
        <Icon name="sparkles" size={14} />Auto-tag
      </button>
    </div>
  {/if}
</div>

<div class="mg-controls">
  <div class="mg-search">
    <span class="ic"><Icon name="search" size={15} /></span>
    <input class="mg-input" type="search" placeholder="Find a tag…"
           aria-label="Find a tag" bind:value={q} />
    {#if q}
      <button type="button" class="clear" aria-label="Clear the filter" onclick={() => (q = '')}>
        <Icon name="x" size={15} />
      </button>
    {/if}
  </div>
</div>

{#if loading}
  <div class="wall">
    {#each Array(14) as _, i (i)}
      <Skeleton h="40px" w="{70 + ((i * 37) % 90)}px" r="9999px" delay={i * 45} />
    {/each}
  </div>
{:else if mstate.error}
  <Empty icon="alert" title="The media library is offline"
         hint="The media backend could not be reached. The notice above has the detail." />
{:else if !tags.length}
  <Empty icon="tag"
         title={q ? 'No tag matches that' : 'Nothing tagged yet'}
         hint={q
           ? 'Try a shorter word — tag names match anywhere, not just at the start.'
           : 'Run the auto-tag pass to label clips by camera, workflow stage and what was said on camera.'}>
    {#snippet children()}
      {#if q}
        <button class="mg-btn secondary sm" onclick={() => (q = '')}>Clear the filter</button>
      {:else if can(CAP.ADMIN)}
        <button class="mg-btn primary sm" onclick={runAutoTag} disabled={!mstate.ready}>
          <Icon name="sparkles" size={14} />Run auto-tag
        </button>
      {/if}
    {/snippet}
  </Empty>
{:else}
  <div class="wall">
    {#each tags as t, i (t.id ?? t.name)}
      <a class="mg-chip tag" href="/media/browse?tag={encodeURIComponent(t.name)}"
         style:font-size="{sizeOf(t.count)}px"
         title="{t.name} — {t.count ?? 0} clip{(t.count ?? 0) === 1 ? '' : 's'}{t.source ? ' · ' + (SOURCE[t.source] || t.source) : ''}"
         animate:flip={{ duration: 240 }}
         in:rise={{ i }}>
        <span class="nm">{t.name}</span>
        {#if t.source}<span class="src">{SOURCE[t.source] || t.source}</span>{/if}
        <span class="n mg-tnum">{t.count ?? 0}</span>
      </a>
    {/each}
  </div>
{/if}

<style>
  /* The wall: chips flow, they do not line up. Nothing scrolls sideways. */
  .wall { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }

  .tag {
    min-height: 40px; max-width: 100%; padding: 0 14px; height: auto;
    font-weight: 500; letter-spacing: -0.01em; color: var(--mc-ink);
  }
  .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .src { font-size: 10.5px; font-weight: 500; color: var(--mc-ink3); flex: none; }
  .n { font-size: 11px; color: var(--mc-ink3); flex: none; }
  .tag:hover .n, .tag:hover .src { color: var(--mc-ink2); }

  @media (pointer: coarse) { .tag { min-height: 44px; } }
  @media (max-width: 560px) {
    .wall { gap: 6px; }
    .tag { padding: 0 12px; }
    .src { display: none; }
  }

  /* The browser's own clear affordance would sit beside ours. */
  .mg-search input::-webkit-search-cancel-button { -webkit-appearance: none; appearance: none; }
</style>
