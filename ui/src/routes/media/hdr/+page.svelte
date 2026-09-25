<script>
  /* HDR & Looks.

     /media/hdr                    the HDR tab (brackets → merged photos)
     /media/hdr?ids=1,2,3          …with those photos as the source
     /media/hdr?tab=looks&id=12    the Looks tab on photo 12
     /media/hdr?id=12              same (an id alone means "a look for this photo")

     The tab and the photo live in the query string so a result can be linked
     and the back button behaves. */
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { mstate, boot } from '$lib/media.svelte.js';
  import { me, can } from '$lib/media/hdr.js';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import HdrPanel from '$lib/components/media/hdr/HdrPanel.svelte';
  import LooksPanel from '$lib/components/media/hdr/LooksPanel.svelte';

  let who = $state(null);

  const sp = $derived(page.url.searchParams);
  const photoId = $derived(Number(sp.get('id')) || null);
  const ids = $derived(
    (sp.get('ids') || '').split(',').map((x) => Number(x.trim())).filter((x) => Number.isInteger(x) && x > 0)
  );
  const tab = $derived(sp.get('tab') === 'looks' || (sp.get('tab') !== 'hdr' && photoId && !ids.length) ? 'looks' : 'hdr');
  const features = $derived(mstate.status?.features || {});

  onMount(async () => {
    await boot();
    if (!mstate.ready) return;
    try { who = await me(); } catch { who = null; }
  });

  function nav(params) {
    const u = new URL(page.url);
    for (const [k, v] of Object.entries(params)) {
      if (v == null || v === '') u.searchParams.delete(k); else u.searchParams.set(k, String(v));
    }
    goto(u.pathname + u.search, { replaceState: false, keepFocus: true, noScroll: true });
  }

  const TABS = [
    { value: 'hdr', label: 'HDR merge', icon: 'sun' },
    { value: 'looks', label: 'Looks', icon: 'wand' }
  ];
</script>

<svelte:head><title>HDR & Looks · Media</title></svelte:head>

<div class="mg-row">
  <h2 class="mg-h2">HDR &amp; Looks</h2>
  <div class="mg-actions">
    <Seg options={TABS} value={tab} onchange={(v) => nav({ tab: v })} label="HDR or Looks" />
  </div>
</div>

{#if mstate.error}
  <Empty icon="alert" title="Media library unavailable" hint={mstate.error} />
{:else if !mstate.ready}
  <div class="ld" aria-busy="true" aria-label="Loading">
    <div class="mg-panel"><Skeleton h="14px" w="40%" /><Skeleton lines={3} delay={80} /></div>
    <div class="mg-panel"><Skeleton h="140px" r="12px" delay={140} /></div>
  </div>
{:else if tab === 'hdr'}
  <HdrPanel {ids} {features} allowed={!who || can(who, 'media.upload')}
            onlook={(id) => nav({ tab: 'looks', id, ids: null })} />
{:else}
  <LooksPanel {photoId} {features} canEdit={!who || can(who, 'media.annotate')}
              onphoto={(id) => nav({ tab: 'looks', id })} />
{/if}

<style>
  .ld { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
  .ld .mg-panel { padding: 16px; display: flex; flex-direction: column; gap: 12px; }
</style>
