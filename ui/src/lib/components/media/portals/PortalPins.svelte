<script>
  /* Proofing pins: spots the client marked on a photo ("remove the hose").
     Each one is a to-do; ticking it here is the same tick the photo editor
     shows. Read through the public route with a staff preview token, so a
     client password is no obstacle and nothing counts as a view. */
  import { onMount } from 'svelte';
  import { thumbUrl } from '$lib/media.js';
  import { say } from '$lib/media.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import { portals, when } from '$lib/media/portals.js';

  let { share } = $props();
  let pins = $state(null);
  let files = $state({});           // video id -> { filename, thumbnail_path }
  let err = $state('');

  onMount(async () => {
    try {
      const r = await portals.pins(share.token);
      pins = r?.pins || [];
      if (pins.length) {
        // The portal's own file list, for names and thumbnails.
        const d = await portals.preview(share.token).catch(() => null);
        const map = {};
        for (const v of d?.videos || []) map[v.id] = v;
        files = map;
      }
    } catch (e) { err = e.message; }
  });

  const groups = $derived.by(() => {
    const g = new Map();
    for (const p of pins || []) {
      if (!g.has(p.video_id)) g.set(p.video_id, []);
      g.get(p.video_id).push(p);
    }
    return [...g.entries()];
  });

  async function tick(p) {
    const next = !p.resolved;
    p.resolved = next;
    try { await portals.resolvePin(p.id, next); }
    catch (e) { p.resolved = !next; say(e.message, 'error'); }
  }

  const editHref = (id) => `/media/edit?id=${id}`;
</script>

{#if err}
  <p class="none">{err}</p>
{:else if !pins}
  <p class="none">Loading…</p>
{:else if !pins.length}
  <p class="none">No marked spots yet. On a photo the client can tap “Mark a spot” and say what should change there.</p>
{:else}
  <div class="grid">
    {#each groups as [vid, list] (vid)}
      {@const f = files[vid]}
      <div class="ph mg-glass-soft">
        <div class="img">
          {#if f?.thumbnail_path}<img src={thumbUrl(f)} alt="" loading="lazy" />{:else}<span class="noimg">photo {vid}</span>{/if}
          {#each list as p, i (p.id)}
            <span class="dot" class:done={p.resolved} style:left="{p.x * 100}%" style:top="{p.y * 100}%">{i + 1}</span>
          {/each}
        </div>
        <div class="nm">
          <b>{f?.filename || 'Photo ' + vid}</b>
          <a class="mg-btn ghost sm" href={editHref(vid)}><Icon name="edit" size={13} />Open in editor</a>
        </div>
        <ol>
          {#each list as p, i (p.id)}
            <li class:done={p.resolved}>
              <span class="n">{i + 1}</span>
              <span class="t">{p.text}<small>{[p.viewer_name, when(p.created_at), p.resolved ? `done${p.resolved_by ? ' by ' + p.resolved_by : ''}` : ''].filter(Boolean).join(' · ')}</small></span>
              <button class="mg-btn sm {p.resolved ? 'ghost' : 'secondary'}" onclick={() => tick(p)}
                      aria-pressed={p.resolved}>
                <Icon name={p.resolved ? 'undo' : 'check'} size={13} />{p.resolved ? 'Reopen' : 'Done'}
              </button>
            </li>
          {/each}
        </ol>
      </div>
    {/each}
  </div>
{/if}

<style>
  .none { margin: 0; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink3); }
  .grid { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr)); }
  .ph { border-radius: var(--mc-r-md); padding: 8px; min-width: 0; }
  .img { position: relative; border-radius: 10px; overflow: hidden; background: var(--mc-inset); min-height: 60px; }
  .img img { display: block; width: 100%; height: auto; }
  .noimg { display: grid; place-items: center; height: 120px; font: 400 11px/1 var(--mc-font); color: var(--mc-ink3); }
  .dot { position: absolute; width: 22px; height: 22px; margin: -11px 0 0 -11px; border-radius: 50%;
         display: grid; place-items: center; background: var(--mc-warn); color: #231a02;
         font: 700 11px/1 var(--mc-font); border: 2px solid rgba(0, 0, 0, 0.45); }
  .dot.done { background: var(--mc-ink3); color: #111; }
  .nm { display: flex; align-items: center; gap: 8px; margin: 8px 2px 6px; }
  .nm b { flex: 1; min-width: 0; font: 500 12.5px/1.3 var(--mc-font); color: var(--mc-ink);
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  ol { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
  li { display: flex; gap: 9px; align-items: center; font: 400 12.5px/1.45 var(--mc-font); color: var(--mc-ink); }
  li.done .t { color: var(--mc-ink3); text-decoration: line-through; }
  .n { flex: none; width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center;
       background: var(--mc-warn); color: #231a02; font: 700 10.5px/1 var(--mc-font); }
  li.done .n { background: var(--mc-ink3); color: #111; }
  .t { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .t small { display: block; color: var(--mc-ink3); font-size: 11px; text-decoration: none; }
  li .mg-btn { flex: none; min-height: 36px; }
</style>
