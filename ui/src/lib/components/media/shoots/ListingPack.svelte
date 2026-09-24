<script>
  /* Export by room with listing sizes — the one-click listing pack
     (listing_pack.py). POST /api/shoots/{id}/listing-pack starts a job; we
     poll /api/listing-pack/{job} and hand over the ZIP through murl (a
     download link cannot carry a bearer header).

     What the backend offers: a Portal size (width 800–6000 px, capped to a
     file size in KB, 0 = no cap), an optional 4:5 Social crop at 1080 px, a
     vertical reel (needs ffmpeg), the listing text, and — for photos not
     yet sorted into rooms — an AI room sort (needs AI). Photos already in
     the room plan are named after their rooms either way. */
  import { onDestroy } from 'svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import { say } from '$lib/media.svelte.js';
  import { shoots } from '$lib/media/shoots.js';

  let { shoot, features = {}, photoCount = 0 } = $props();

  const WIDTHS = [1600, 2048, 2560, 3000, 4000];
  const CAPS = [{ v: 500, l: '500 KB' }, { v: 1000, l: '1 MB' }, { v: 2000, l: '2 MB' }, { v: 5000, l: '5 MB' }, { v: 0, l: 'No cap' }];

  let body = $state({ portal_width: 2048, portal_kb: 1000, social: true, reel: true, text: true, rooms: true });
  let job = $state(null);
  let timer;

  const running = $derived(job?.state === 'running');
  const ffmpeg = $derived(features.ffmpeg !== false);
  const ai = $derived(!!features.ai);

  async function poll(id) {
    try {
      job = await shoots.packState(id);
      if (job.state === 'running') timer = setTimeout(() => poll(id), 1200);
      else if (job.state === 'done') say('Listing pack ready');
      else if (job.state === 'error') say(job.error || 'The pack failed', 'error');
    } catch (e) { say(e.message, 'error'); job = null; }
  }

  async function start() {
    clearTimeout(timer);
    try {
      const b = { ...body, reel: body.reel && ffmpeg, rooms: body.rooms && ai };
      job = await shoots.startPack(shoot.id, b);
      poll(job.id);
    } catch (e) { say(e.message, 'error'); }
  }

  onDestroy(() => clearTimeout(timer));

  const pct = $derived(job?.total ? Math.round((100 * (job.done || 0)) / job.total) : 0);
</script>

<section class="mg-card">
  <div class="hd">
    <h3><Icon name="box" size={15} />Export by room</h3>
    <span class="mg-count">{photoCount} photo{photoCount === 1 ? '' : 's'}</span>
  </div>
  <p class="lede">A ZIP with every photo developed and named after its room (Bedroom1, Pool1…) at portal size, plus what you tick below.</p>

  <div class="two">
    <div class="f">
      <label class="mg-label" for="lp-w">Portal width</label>
      <div class="mg-select">
        <select id="lp-w" bind:value={body.portal_width}>
          {#each WIDTHS as w (w)}<option value={w}>{w} px{w === 2048 ? ' (default)' : ''}</option>{/each}
        </select>
        <span class="ic"><Icon name="chevronDown" size={15} /></span>
      </div>
    </div>
    <div class="f">
      <label class="mg-label" for="lp-kb">Max file size</label>
      <div class="mg-select">
        <select id="lp-kb" bind:value={body.portal_kb}>
          {#each CAPS as c (c.v)}<option value={c.v}>{c.l}</option>{/each}
        </select>
        <span class="ic"><Icon name="chevronDown" size={15} /></span>
      </div>
    </div>
  </div>

  <div class="togs">
    <button type="button" class="mg-chip tog" class:on={body.social} aria-pressed={body.social} onclick={() => (body.social = !body.social)}>
      {#if body.social}<Icon name="check" size={12} />{/if}Social 4:5 · 1080 px
    </button>
    <button type="button" class="mg-chip tog" class:on={body.reel && ffmpeg} aria-pressed={body.reel && ffmpeg}
            disabled={!ffmpeg} onclick={() => (body.reel = !body.reel)}>
      {#if body.reel && ffmpeg}<Icon name="check" size={12} />{/if}Vertical reel
    </button>
    <button type="button" class="mg-chip tog" class:on={body.text} aria-pressed={body.text} onclick={() => (body.text = !body.text)}>
      {#if body.text}<Icon name="check" size={12} />{/if}Listing text
    </button>
    <button type="button" class="mg-chip tog" class:on={body.rooms && ai} aria-pressed={body.rooms && ai}
            disabled={!ai} onclick={() => (body.rooms = !body.rooms)}>
      {#if body.rooms && ai}<Icon name="check" size={12} />{/if}AI room sort
    </button>
  </div>
  {#if !ffmpeg}<p class="why">The reel needs ffmpeg, which isn't installed on this server.</p>{/if}
  {#if !ai}<p class="why">AI room sorting isn't configured — photos not in the room plan below are named Photo1, Photo2…</p>{/if}

  <button class="mg-btn primary wide" onclick={start} disabled={running || !photoCount}>
    {#if running}<span class="mg-spin"></span>{job.step || 'Working'}…{:else}<Icon name="download" size={15} />Make the listing pack{/if}
  </button>
  {#if !photoCount}<p class="why">Link a folder with photos first.</p>{/if}

  {#if job}
    <div class="job">
      {#if running}
        <div class="mg-bar" class:indeterminate={!job.total}><i style:width="{pct}%"></i></div>
        <p class="st mg-tnum">{job.step}{job.total ? ` · ${job.done || 0}/${job.total}` : ''}</p>
      {:else if job.state === 'done' && job.ready}
        <a class="mg-btn accent wide" href={shoots.packZipUrl(job.id)} download><Icon name="download" size={15} />Download the ZIP</a>
        <p class="st">{job.reel ? 'Includes the reel. ' : ''}The photos are also in the folder's “Listing pack” export.</p>
        {#if job.errors?.length}<p class="why">{job.errors.length} photo{job.errors.length === 1 ? '' : 's'} could not be developed: {job.errors.slice(0, 2).join('; ')}</p>{/if}
      {:else if job.state === 'error'}
        <p class="err">{job.error}</p>
      {/if}
    </div>
  {/if}
</section>

<style>
  .hd { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
  h3 { margin: 0; flex: 1; display: flex; align-items: center; gap: 7px; font: 600 14px/1.3 var(--mg-font); color: var(--mg-i); }
  .lede { margin: 0 0 12px; font: 400 12.5px/1.5 var(--mg-font); color: var(--mg-i3); }
  .two { display: grid; gap: 10px; grid-template-columns: 1fr 1fr; margin-bottom: 10px; }
  .f { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
  .mg-select { display: block; }
  .togs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
  .tog { min-height: 36px; padding: 0 12px; }
  .tog:disabled { opacity: 0.45; cursor: not-allowed; }
  .why { margin: 0 0 8px; font: 400 11.5px/1.45 var(--mg-font); color: var(--mg-i3); }
  .wide { width: 100%; margin-top: 4px; }
  .job { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }
  .st { margin: 0; font: 400 12px/1.4 var(--mg-font); color: var(--mg-i2); }
  .err { margin: 0; font: 400 12.5px/1.45 var(--mg-font); color: var(--mg-crit); }
</style>
