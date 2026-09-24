<script>
  /* Window pull (Zerko 1.3): find the blown-out windows in an interior, then
     take the view through them from a darker frame of the same shot — a
     bracket, or a frame exposed for the windows. The server lines the two up
     (a hand-held bracket moves a little) and returns a soft-edged patch that
     goes into recipe.removes as kind "pull". */
  import Icon from '$lib/components/glass/Icon.svelte';
  import { untrack } from 'svelte';
  import { pe, maskUrl } from '$lib/media/photoedit.js';
  import { photoUrl } from '$lib/media.js';
  import { say } from '$lib/media.svelte.js';

  let { api, ed, srcSize = null, siblings = [], overlay = $bindable(null), geometryFree = true, disabled = false } = $props();

  let finding = $state(false);
  let found = $state(null);          // { count, ref, candidates }
  let pulling = $state(null);
  let showMask = $state(true);
  let pickOther = $state(false);

  $effect(() => { ed.id; untrack(() => { found = null; pickOther = false; }); });
  $effect(() => { overlay = found?.ref && showMask && geometryFree ? maskUrl(found.ref) : null; });

  async function find() {
    finding = true;
    try {
      const s = srcSize || { w: 1600, h: 1067 };
      const k = Math.min(1, 2000 / Math.max(s.w, s.h));
      found = await pe.windows(ed.id, Math.max(16, Math.round(s.w * k)), Math.max(16, Math.round(s.h * k)));
      if (!found.count) say('No blown-out windows found in this frame');
    } catch (e) { say(e.message, 'error'); }
    finally { finding = false; }
  }

  async function pull(fromId) {
    pulling = fromId;
    try {
      const res = await pe.windowPull(ed.id, found.ref, fromId, ed.recipe.removes || []);
      ed.recipe.removes = [...(ed.recipe.removes || []), { ref: res.ref, box: res.box, kind: res.kind || 'pull' }];
      api.touch();
      say('Window view laid in');
      showMask = false;
    } catch (e) { say(e.message, 'error'); }
    finally { pulling = null; }
  }

  const others = $derived(siblings.filter((v) => v.id !== ed.id && !(found?.candidates || []).some((c) => c.id === v.id)));
  const pulls = $derived((ed.recipe.removes || []).filter((x) => x.kind === 'pull').length);
</script>

<div class="wrap">
  <p class="hint">For interiors where the windows burn out: find them, then pick a darker frame of the same shot to take the view from.</p>
  <button type="button" class="mg-btn secondary sm" onclick={find} disabled={disabled || finding}>
    {#if finding}<span class="mg-spin"></span>{:else}<Icon name="window" size={14} />{/if}
    {found ? 'Find again' : 'Find the windows'}
  </button>

  {#if found && found.count}
    <div class="res">
      <span class="mg-chip ok"><span class="dot"></span>{found.count} window{found.count === 1 ? '' : 's'} found</span>
      {#if geometryFree}
        <label class="tg"><input type="checkbox" bind:checked={showMask} /> Show on photo</label>
      {:else}
        <span class="hint">(mask shown only without crop or geometry)</span>
      {/if}
    </div>

    <span class="mg-label">Darker frames of this shot</span>
    {#if found.candidates.length}
      <div class="cands">
        {#each found.candidates as c (c.id)}
          <button type="button" class="cand mg-glass-soft mg-hover" onclick={() => pull(c.id)} disabled={disabled || !!pulling}>
            <img src={photoUrl(c, 400)} alt="" loading="lazy" />
            <span class="nm">{c.filename}</span>
            <span class="meta mg-tnum">{c.ev} EV · match {Math.round(c.match * 100)}%</span>
            {#if pulling === c.id}<span class="mg-spin sp"></span>{/if}
          </button>
        {/each}
      </div>
    {:else}
      <p class="hint">No darker bracket of this frame was found automatically.</p>
    {/if}

    {#if others.length}
      <button type="button" class="mg-btn ghost sm" onclick={() => (pickOther = !pickOther)}>
        {pickOther ? 'Hide' : 'Choose'} another photo from this folder
      </button>
      {#if pickOther}
        <div class="cands">
          {#each others.slice(0, 40) as c (c.id)}
            <button type="button" class="cand mg-glass-soft mg-hover" onclick={() => pull(c.id)} disabled={disabled || !!pulling}>
              <img src={photoUrl(c, 400)} alt="" loading="lazy" />
              <span class="nm">{c.filename}</span>
              {#if pulling === c.id}<span class="mg-spin sp"></span>{/if}
            </button>
          {/each}
        </div>
      {/if}
    {/if}
  {/if}

  {#if pulls}
    <p class="hint">{pulls} window view{pulls === 1 ? '' : 's'} in this edit — take one back from the Remove tab.</p>
  {/if}
</div>

<style>
  .wrap { display: flex; flex-direction: column; gap: 10px; padding-top: 4px; }
  .wrap > .mg-btn { align-self: flex-start; }
  .hint { margin: 0; font-size: 11.5px; line-height: 1.45; color: var(--mg-i3); }
  .res { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .tg { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--mg-i2); min-height: 32px; }
  .cands { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; }
  .cand {
    position: relative; display: flex; flex-direction: column; gap: 4px; padding: 6px; text-align: left;
    border-radius: var(--mg-r-in); cursor: pointer; color: inherit; font: inherit;
  }
  .cand:disabled { opacity: 0.5; cursor: default; }
  .cand img { width: 100%; aspect-ratio: 3 / 2; object-fit: cover; border-radius: 8px; background: #000; }
  .nm { font-size: 11.5px; color: var(--mg-i2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .meta { font-size: 11px; color: var(--mg-i3); }
  .sp { position: absolute; top: 12px; right: 12px; }
</style>
