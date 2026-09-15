<script>
  import '../app.css';
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { app, startPolling, stopPolling } from '$lib/state.svelte.js';
  import TopBar from '$lib/components/TopBar.svelte';
  import JobStrip from '$lib/components/JobStrip.svelte';
  import RunPanel from '$lib/components/RunPanel.svelte';
  import Toast from '$lib/components/Toast.svelte';

  let { children } = $props();

  const path = $derived(page.url.pathname);
  // The landing screen, the map and the lead-management area draw their own
  // chrome; only the prospect engine pages use the top bar.
  const bare = $derived(path === '/' || path.startsWith('/map') || path.startsWith('/leads'));

  onMount(() => {
    startPolling();
    return stopPolling;
  });

  function onKey(e) {
    if (e.key === 'Escape') {
      if (app.selectedKey) app.selectedKey = null;
      else if (app.runOpen) app.runOpen = false;
    }
  }
</script>

<svelte:window onkeydown={onKey} />

{#if !bare}
  <div class="shell">
    <TopBar />
    <JobStrip />
    <main>{@render children()}</main>
  </div>
{:else}
  {@render children()}
{/if}

<RunPanel />
<Toast />

<style>
  .shell { min-height: 100vh; display: flex; flex-direction: column; }
  main { flex: 1; width: 100%; max-width: 1480px; margin: 0 auto;
         padding: 0 clamp(1rem, 3vw, 2rem) 4rem; }
</style>
