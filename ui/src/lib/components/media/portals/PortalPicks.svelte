<script>
  /* The client's hearts and notes, and the exports that turn them into a bin
     in the edit. A row with a note but no heart is kept on purpose — "the
     lighting is off here" is feedback worth having. */
  import { onMount } from 'svelte';
  import { thumbUrl } from '$lib/media.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import { portals } from '$lib/media/portals.js';

  let { share } = $props();
  let rows = $state(null);
  let err = $state('');

  onMount(async () => {
    try { rows = (await portals.selects(share.id))?.selects || []; }
    catch (e) { err = e.message; }
  });

  const hearts = $derived((rows || []).filter((p) => p.picked).length);
  const notes = $derived((rows || []).filter((p) => p.comment).length);
</script>

{#if err}
  <p class="none">{err}</p>
{:else if !rows}
  <p class="none">Loading…</p>
{:else if !rows.length}
  <p class="none">The client has not picked anything yet.</p>
{:else}
  <div class="sum">
    <span class="mg-chip ok"><b class="mg-tnum">{hearts}</b> picked</span>
    <span class="mg-chip"><b class="mg-tnum">{notes}</b> note{notes === 1 ? '' : 's'}</span>
    {#if hearts}
      <a class="mg-btn secondary sm" href={portals.fcpxmlUrl(share.id)}><Icon name="download" size={13} />FCPXML</a>
      <a class="mg-btn secondary sm" href={portals.csvUrl(share.id)}><Icon name="download" size={13} />CSV</a>
    {/if}
  </div>
  <div class="strip mg-noscroll">
    {#each rows as p (p.video_id)}
      <figure class="pick mg-glass-soft">
        <span class="shot">
          {#if p.thumbnail_path}<img src={thumbUrl(p)} alt="" loading="lazy" />
          {:else}<span class="noimg">no thumbnail</span>{/if}
          {#if p.picked}<span class="heart" aria-label="picked">♥</span>{/if}
        </span>
        <figcaption>
          <b title={p.filename}>{p.filename || 'File ' + p.video_id}</b>
          {#if p.viewer_name}<span class="by">by {p.viewer_name}</span>{/if}
          {#if p.comment}<p title={p.comment}>{p.comment}</p>{/if}
        </figcaption>
      </figure>
    {/each}
  </div>
{/if}

<style>
  .none { margin: 0; font: 400 12.5px/1.5 var(--mg-font); color: var(--mg-i3); }
  .sum { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 10px; }
  .sum b { color: var(--mg-i); font-weight: 600; }
  .strip { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 4px; }
  .pick { flex: none; width: 168px; margin: 0; padding: 6px; border-radius: var(--mg-r-in); }
  .shot { position: relative; display: block; aspect-ratio: 16 / 9; overflow: hidden;
          border-radius: 10px; background: var(--mg-term); }
  .shot img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .noimg { position: absolute; inset: 0; display: grid; place-items: center;
           font: 400 10.5px/1 var(--mg-font); color: var(--mg-i3); }
  .heart { position: absolute; right: 5px; bottom: 5px; width: 22px; height: 22px; border-radius: 50%;
           display: grid; place-items: center; font-size: 11px; color: var(--mg-ok);
           background: rgba(8, 8, 10, 0.72); border: 1px solid rgba(62, 207, 142, 0.35); }
  figcaption { display: flex; flex-direction: column; gap: 2px; padding: 8px 4px 3px; min-width: 0; }
  figcaption b { font: 500 12px/1.3 var(--mg-font); color: var(--mg-i);
                 overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .by { font: 400 11px/1.3 var(--mg-font); color: var(--mg-i3); }
  figcaption p { margin: 3px 0 0; font: 400 11.5px/1.45 var(--mg-font); color: var(--mg-i2);
                 display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3;
                 -webkit-box-orient: vertical; overflow: hidden; }
</style>
