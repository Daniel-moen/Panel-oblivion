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

  let caps = $state(null);

  onMount(async () => {
    await boot();
    if (mstate.ready) caps = await loadCaps();
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
    <p class="msg">The media library is unavailable.</p>
  {:else}
    <p class="msg">Loading…</p>
  {/if}
{:else if !caps.has('media.read')}
  <p class="msg">Your account can't see the media library.</p>
{:else if projectId}
  {#key projectId}<Editor id={projectId} {caps} />{/key}
{:else if clipId}
  {#key clipId}<SubclipMarker videoId={clipId} {caps} />{/key}
{:else}
  <ProjectList canEdit={caps.has('media.upload')} />
{/if}

<style>
  .msg { color: var(--mg-i3); font-size: 13px; }
  .mg-strip { margin-bottom: 14px; }
</style>
