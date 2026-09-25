<script>
  /* Copy this edit onto other photos — Lightroom's Sync.

     "Everything" posts to /api/photo-presets/apply (the whole look; each
     photo keeps what was painted on it). Picking groups posts to /sync with
     just those recipe keys, leaving the rest of each photo's own edit alone.
     Nothing is rendered: it only writes recipes, so it is instant across a
     whole shoot. Export them from the Export tab or the library. */
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import { pe, cleanRecipe, SYNC_GROUPS } from '$lib/media/photoedit.js';
  import { photoUrl } from '$lib/media.js';
  import { say } from '$lib/media.svelte.js';

  let { open = false, onclose, ed, photos = [], folderName = '' } = $props();

  let picked = $state(new Set());
  let everything = $state(true);
  let groups = $state(new Set(['light', 'wb', 'colour', 'detail']));
  let busy = $state(false);

  const targets = $derived(photos.filter((p) => p.id !== ed.id));

  function toggle(set, v) {
    const n = new Set(set);
    n.has(v) ? n.delete(v) : n.add(v);
    return n;
  }

  async function go() {
    const ids = [...picked];
    if (!ids.length) return;
    busy = true;
    try {
      const recipe = cleanRecipe($state.snapshot(ed.recipe));
      if (everything) {
        const r = await pe.applyTo(ids, recipe);
        say(`Settings copied to ${r.applied} photo${r.applied === 1 ? '' : 's'}`);
      } else {
        const keys = SYNC_GROUPS.filter((g) => groups.has(g.id)).flatMap((g) => g.keys);
        if (!keys.length) { say('Choose at least one group', 'error'); return; }
        const r = await pe.syncTo(ids, recipe, keys);
        say(`Synced ${r.keys.length} settings to ${r.synced} photo${r.synced === 1 ? '' : 's'}`);
      }
      picked = new Set();
      onclose?.();
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }
</script>

<Sheet {open} {onclose} title="Copy settings to other photos" size="lg">
  <div class="body">
    <div class="mode">
      <button type="button" class="mg-chip" class:on={everything} onclick={() => (everything = true)}>Everything</button>
      <button type="button" class="mg-chip" class:on={!everything} onclick={() => (everything = false)}>Only some settings</button>
    </div>
    {#if everything}
      <p class="hint">The whole look, crop and geometry included. Heal spots, removals and painted masks stay with the photo they were made on.</p>
    {:else}
      <div class="groups">
        {#each SYNC_GROUPS as g (g.id)}
          <label class="gp"><input type="checkbox" checked={groups.has(g.id)} onchange={() => (groups = toggle(groups, g.id))} /> {g.label}</label>
        {/each}
      </div>
    {/if}

    <div class="hd">
      <span class="mg-label">{folderName ? `Photos in ${folderName}` : 'Photos'} · {picked.size} of {targets.length} chosen</span>
      <button type="button" class="mg-btn ghost sm"
              onclick={() => (picked = picked.size === targets.length ? new Set() : new Set(targets.map((t) => t.id)))}>
        {picked.size === targets.length && targets.length ? 'None' : 'All'}</button>
    </div>
    {#if targets.length}
      <div class="grid">
        {#each targets as p (p.id)}
          <button type="button" class="ph" class:on={picked.has(p.id)} onclick={() => (picked = toggle(picked, p.id))}
                  aria-pressed={picked.has(p.id)} title={p.filename}>
            <img src={photoUrl(p, 400)} alt="" loading="lazy" />
            <span class="ck">{#if picked.has(p.id)}<Icon name="check" size={12} />{/if}</span>
            <span class="nm">{p.filename}</span>
          </button>
        {/each}
      </div>
    {:else}
      <p class="hint">There are no other photos in this folder.</p>
    {/if}
  </div>
  {#snippet footer()}
    <button type="button" class="mg-btn ghost" onclick={() => onclose?.()}>Cancel</button>
    <button type="button" class="mg-btn primary" onclick={go} disabled={busy || !picked.size}>
      {#if busy}<span class="mg-spin"></span>{/if}Copy to {picked.size || ''} photo{picked.size === 1 ? '' : 's'}</button>
  {/snippet}
</Sheet>

<style>
  .body { display: flex; flex-direction: column; gap: 10px; }
  .mode { display: flex; gap: 6px; flex-wrap: wrap; }
  .mode .mg-chip { min-height: 34px; }
  @media (pointer: coarse) { .mode .mg-chip, .gp { min-height: 44px; } }
  .hint { margin: 0; font-size: 12px; line-height: 1.45; color: var(--mc-ink3); }
  .groups { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 4px; }
  .gp { display: flex; align-items: center; gap: 8px; min-height: 36px; font-size: 13px; color: var(--mc-ink2); }
  .hd { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 8px; }
  .ph { position: relative; padding: 0; border: 2px solid transparent; border-radius: 12px; overflow: hidden;
        background: var(--mc-raised); cursor: pointer; display: flex; flex-direction: column;
        transition: border-color var(--mc-t-fast); }
  .ph:hover { border-color: var(--mc-line2); }
  .ph img { width: 100%; aspect-ratio: 3 / 2; object-fit: cover; opacity: 0.8; background: var(--mc-inset); display: block; }
  .ph.on { border-color: var(--mc-accent); }
  .ph.on img { opacity: 1; }
  .ck { position: absolute; top: 6px; right: 6px; width: 20px; height: 20px; border-radius: 50%;
        background: rgba(0, 0, 0, 0.55); border: 1.5px solid #fff; display: grid; place-items: center; color: var(--mc-accent-ink); }
  .ph.on .ck { background: var(--mc-accent); border-color: var(--mc-accent); }
  .nm { font-size: 10.5px; color: var(--mc-ink2); padding: 5px 7px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-align: left; }
</style>
