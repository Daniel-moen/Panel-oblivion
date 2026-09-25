<script>
  /* The video editor (Zerko 1.4), one route, three views by query:
       /media/video               every edit — create, rename, delete
       /media/video?project=<id>  one edit open on the timeline
       /media/video?clip=<id>     sub-clips on a library clip, with
                                  "New edit with this clip" to seed a project
     Everything lives in $lib/components/media/video/ and $lib/media/video.js. */
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { mstate, boot } from '$lib/media.svelte.js';
  import { loadCaps } from '$lib/media/video.js';
  import ProjectList from '$lib/components/media/video/ProjectList.svelte';
  import Editor from '$lib/components/media/video/Editor.svelte';
  import SubclipMarker from '$lib/components/media/video/SubclipMarker.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';

  let caps = $state(null);
  let capsError = $state(null);

  onMount(async () => {
    await boot();
    if (mstate.ready) {
      try { caps = await loadCaps(); } catch (e) { capsError = e?.message || 'Could not load your permissions.'; }
    }
  });

  const projectId = $derived(Number(page.url.searchParams.get('project')) || null);
  const clipId = $derived(Number(page.url.searchParams.get('clip')) || null);
  const ffmpeg = $derived(mstate.status?.features?.ffmpeg !== false);
</script>

<svelte:head><title>Video editor · Media</title></svelte:head>

{#if mstate.ready && !ffmpeg}
  <div class="mg-strip warn">
    <span class="ic"><Icon name="alert" size={15} /></span>
    <span><b>ffmpeg isn't installed on this server</b> — edits and sub-clip ranges still save, and the DaVinci Resolve
      timeline still exports, but rendering video is off.</span>
  </div>
{/if}

{#if !mstate.ready || !caps}
  {#if mstate.error}
    <Empty icon="film" title="The video editor needs the media library"
           hint="It is unavailable on this deployment, so there are no clips to cut." />
  {:else if capsError}
    <div class="mg-strip crit"><span class="ic"><Icon name="alert" size={15} /></span><span>{capsError}</span></div>
  {:else}
    <div class="ld" aria-busy="true" aria-label="Loading edits">
      <div class="lr"><Skeleton h="22px" w="160px" /><Skeleton h="40px" w="130px" r="12px" /></div>
      <div class="lg">
        {#each [0, 1, 2] as i (i)}
          <div class="mg-panel lc"><Skeleton h="120px" r="10px" delay={i * 90} /><Skeleton lines={2} delay={i * 90} /></div>
        {/each}
      </div>
    </div>
  {/if}
{:else if !caps.has('media.read')}
  <Empty icon="lock" title="No access to the media library" hint="Your account can't see the media library. Ask an owner for access." />
{:else if projectId}
  {#key projectId}<Editor id={projectId} {caps} />{/key}
{:else if clipId}
  {#key clipId}<SubclipMarker videoId={clipId} {caps} />{/key}
{:else}
  <ProjectList canEdit={caps.has('media.upload')} />
{/if}

<style>
  .ld { display: flex; flex-direction: column; gap: 16px; }
  .lr { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .lg { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); }
  .lc { padding: 10px; display: flex; flex-direction: column; gap: 10px; }
  .mg-strip { margin-bottom: 14px; }
</style>
