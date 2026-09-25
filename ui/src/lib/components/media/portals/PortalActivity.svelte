<script>
  /* What the person on the other end actually did: opened, downloaded, sent
     files, said they were done. Answers "did they ever download it?" */
  import { onMount } from 'svelte';
  import { portals, when } from '$lib/media/portals.js';

  let { share } = $props();
  let data = $state(null);
  let err = $state('');

  onMount(async () => {
    try { data = await portals.activity(share.id); }
    catch (e) { err = e.message; }
  });

  const LABELS = { viewed: 'opens', downloaded: 'downloads', downloaded_zip: 'zips',
                   uploaded: 'files sent in', confirmed: 'done' };
</script>

{#if err}
  <p class="none">{err}</p>
{:else if !data}
  <p class="none">Loading…</p>
{:else if !data.events.length}
  <p class="none">Nobody has opened this link yet.</p>
{:else}
  <div class="sum">
    {#each Object.entries(data.summary) as [k, n] (k)}
      <span class="mg-chip" class:ok={k === 'confirmed'}><b class="mg-tnum">{n}</b> {LABELS[k] || k}</span>
    {/each}
  </div>
  {#if data.downloaded_files.length}
    <p class="dl">Downloaded: {data.downloaded_files.join(', ')}</p>
  {/if}
  <ol class="ev">
    {#each data.events.slice(0, 60) as e, i (i)}
      <li>
        <span class="t mg-tnum">{when(e.at)}</span>
        <span class="w">
          {e.label}{#if e.filename} · <b>{e.filename}</b>{:else if e.detail} · <b>{e.detail}</b>{/if}
          {#if e.viewer_name || e.device}
            <small>{[e.viewer_name, e.device].filter(Boolean).join(' · ')}</small>
          {/if}
        </span>
      </li>
    {/each}
  </ol>
{/if}

<style>
  .none { margin: 0; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink3); }
  .sum { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
  .sum b { color: var(--mc-ink); font-weight: 600; }
  .dl { margin: 0 0 10px; font: 400 12px/1.5 var(--mc-font); color: var(--mc-ink2); overflow-wrap: anywhere; }
  .ev { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px;
        max-height: 320px; overflow-y: auto; }
  .ev li { display: grid; grid-template-columns: 112px minmax(0, 1fr); gap: 10px; padding: 6px 2px;
           border-bottom: 1px solid var(--mc-line); font: 400 12.5px/1.45 var(--mc-font); color: var(--mc-ink2); }
  .ev li:last-child { border-bottom: 0; }
  .t { color: var(--mc-ink3); font-size: 12px; }
  .w { min-width: 0; overflow-wrap: anywhere; }
  .w b { color: var(--mc-ink); font-weight: 500; }
  .w small { display: block; color: var(--mc-ink3); font-size: 11.5px; }
  @media (max-width: 420px) { .ev li { grid-template-columns: minmax(0, 1fr); gap: 0; } }
</style>
