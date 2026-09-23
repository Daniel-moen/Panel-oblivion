<script>
  /* Duplicates: byte-identical copies, grouped, with the space they waste.

     Deliberately read-mostly. The backend refuses to delete the last copy in
     a group, but a screen that makes bulk deletion one click away is a screen
     that eventually deletes the wrong master — so resolving is per group and
     asks first. The copy being kept is marked before you press anything. */
  import { onMount } from 'svelte';
  import { fly } from 'svelte/transition';
  import { mstate, boot, say } from '$lib/media.svelte.js';
  import { media, thumbUrl, fmtBytes } from '$lib/media.js';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';

  let data = $state(null);
  let loading = $state(true);
  let scanning = $state(false);

  onMount(async () => {
    await boot();
    if (!mstate.ready) { loading = false; return; }
    load();
  });

  async function load() {
    loading = true;
    try { data = await media.duplicates(); }
    catch (e) { say(e.message, 'error'); }
    finally { loading = false; }
  }

  async function scan() {
    scanning = true;
    try { await media.duplicateScan(); say('Hashing the library — this takes a while'); }
    catch (e) { say(e.message, 'error'); }
    finally { scanning = false; }
  }

  async function resolve(group) {
    const keep = group.videos?.[0];
    const drop = (group.videos || []).slice(1);
    if (!drop.length) return;
    if (!confirm(`Keep "${keep.filename}" and move ${drop.length} copy/copies to trash?`)) return;
    try {
      await media.duplicateResolve({ groups: [{ hash: group.hash, keep_id: keep.id,
                                                delete_ids: drop.map((v) => v.id) }],
                                     mode: 'trash' });
      say('Copies moved to trash');
      load();
    } catch (e) { say(e.message, 'error'); }
  }

  const groups = $derived(data?.groups || []);
</script>

<svelte:head><title>Duplicates · Media</title></svelte:head>

<div class="mg-row">
  <h2 class="mg-h2">Duplicates</h2>
  {#if data}
    <span class="mg-count">
      {groups.length} group{groups.length === 1 ? '' : 's'}{#if data.reclaimable} · {fmtBytes(data.reclaimable)} reclaimable{/if}
    </span>
  {:else}
    <span class="mg-count">Byte-identical copies</span>
  {/if}
  <div class="mg-actions">
    <button class="mg-btn secondary sm" onclick={scan} disabled={scanning || !mstate.ready}>
      {#if scanning}<span class="mg-spin"></span>Scanning…{:else}<Icon name="refresh" size={14} />Re-scan{/if}
    </button>
  </div>
</div>

{#if loading}
  <div class="list">
    {#each Array(4) as _, i (i)}
      <Skeleton h="180px" r="var(--mg-r-card)" delay={i * 70} />
    {/each}
  </div>
{:else if !groups.length}
  <Empty icon="copy" title="No duplicates found"
         hint="Either the library is clean or it has not been hashed yet — a re-scan compares every file byte for byte.">
    {#snippet children()}
      <button class="mg-btn primary sm" onclick={scan} disabled={scanning || !mstate.ready}>
        <Icon name="refresh" size={14} />Re-scan the library
      </button>
    {/snippet}
  </Empty>
{:else}
  <div class="list">
    {#each groups as g, i (g.hash)}
      <article class="mg-card grp" in:fly={{ y: 12, duration: 320, delay: Math.min(i * 45, 320) }}>
        <div class="gh">
          <b>{g.videos?.length || 0} copies</b>
          <span class="dim mg-tnum">{fmtBytes(g.size || g.videos?.[0]?.file_size || 0)} each</span>
          {#if g.wasted}<span class="mg-chip warn"><span class="mg-tnum">{fmtBytes(g.wasted)}</span> wasted</span>{/if}
          <div class="ga">
            <button class="mg-btn sm danger" onclick={() => resolve(g)}>
              <Icon name="trash" size={14} />Keep first, trash rest
            </button>
          </div>
        </div>

        <div class="copies mg-noscroll">
          {#each g.videos || [] as v, vi (v.id)}
            <figure class="copy mg-glass-soft" class:keep={vi === 0}>
              <span class="shot">
                {#if thumbUrl(v)}
                  <img src={thumbUrl(v)} alt="" loading="lazy" />
                {:else}
                  <span class="noimg">no thumbnail</span>
                {/if}
                {#if vi === 0}<span class="mg-chip ok mark">keeping</span>{/if}
              </span>
              <figcaption>
                <b title={v.filename}>{v.filename}</b>
                <span class="path" title={v.filepath || v.folder_name}>{v.folder_name || v.filepath}</span>
                {#if v.file_size}<span class="dim mg-tnum">{fmtBytes(v.file_size)}</span>{/if}
              </figcaption>
            </figure>
          {/each}
        </div>
      </article>
    {/each}
  </div>
{/if}

<style>
  .list { display: flex; flex-direction: column; gap: 12px; }
  .grp { padding: 14px; }

  .gh { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
  .gh b { font: 600 13.5px/1 var(--mg-font); letter-spacing: -0.01em; color: var(--mg-i); }
  .dim { font: 400 12px/1 var(--mg-font); color: var(--mg-i3); }
  .ga { margin-left: auto; display: flex; gap: 8px; flex-wrap: wrap; }

  /* One row of copies that scrolls sideways: three copies of the same file are
     the same picture, so stacking them down the page would only cost height. */
  .copies { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 4px; }

  .copy { flex: none; width: 160px; margin: 0; padding: 6px; border-radius: var(--mg-r-in); }
  .copy.keep { border-color: rgba(62, 207, 142, 0.4); background: rgba(62, 207, 142, 0.08); }

  .shot {
    position: relative; display: block; aspect-ratio: 16 / 9; overflow: hidden;
    border-radius: 10px; background: var(--mg-term);
  }
  .shot img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .noimg { position: absolute; inset: 0; display: grid; place-items: center;
           font: 400 10.5px/1 var(--mg-font); color: var(--mg-i3); }
  .mark { position: absolute; left: 5px; bottom: 5px; padding: 3px 8px; font-size: 10.5px;
          background: rgba(6, 40, 26, 0.75); border-color: rgba(62, 207, 142, 0.5); }

  figcaption { display: flex; flex-direction: column; gap: 2px; padding: 8px 4px 3px; min-width: 0; }
  figcaption b { font: 500 12px/1.3 var(--mg-font); color: var(--mg-i);
                 overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .path { font: 11px/1.35 var(--mg-mono); color: var(--mg-i3);
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
