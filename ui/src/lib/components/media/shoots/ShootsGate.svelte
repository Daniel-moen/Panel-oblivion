<script>
  /* Shoots are for editors and admins (permissions.SHOOTS). Waits for the
     media boot and /api/me, then renders children({ me }) and calls onready(me) — or a polite no. */
  import { onMount } from 'svelte';
  import { mstate, boot } from '$lib/media.svelte.js';
  import { me as loadMe, can, CAP_SHOOTS } from '$lib/media/shoots.js';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';

  let { children, onready } = $props();

  let who = $state(null);
  let phase = $state('loading'); // loading | ok | denied | offline

  onMount(async () => {
    await boot();
    if (!mstate.ready) { phase = 'offline'; return; }
    try {
      who = await loadMe();
      phase = can(who, CAP_SHOOTS) ? 'ok' : 'denied';
      if (phase === 'ok') onready?.(who);
    } catch { phase = 'offline'; }
  });
</script>

{#if phase === 'loading'}
  <div class="sk">
    <Skeleton h="1.4rem" w="30%" />
    <Skeleton h="4rem" />
    <Skeleton h="4rem" delay={80} />
  </div>
{:else if phase === 'denied'}
  <Empty icon="lock" title="Shoots are for editors and admins"
         hint="Your account can browse the library, but bookings, captions and client deliveries need an editor or admin role. Ask an admin if you need it." />
{:else if phase === 'offline'}
  <Empty icon="alert" title="The media library isn't reachable"
         hint="Shoots live in the media backend, which didn't answer. Check Media › Settings." />
{:else}
  {@render children?.({ me: who })}
{/if}

<style>
  .sk { display: flex; flex-direction: column; gap: 12px; }
</style>
