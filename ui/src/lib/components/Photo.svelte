<script>
  import { photoSrc } from '$lib/format.js';

  /** r: prospect row · fills its parent; parent sets the box size */
  let { r, alt = '', eager = false } = $props();

  let failedKey = $state(null);
  const src = $derived(photoSrc(r));
  const show = $derived(src && failedKey !== r.listing_key);
</script>

{#if show}
  <img {src} {alt} loading={eager ? 'eager' : 'lazy'}
       onerror={() => (failedKey = r.listing_key)} />
{:else}
  <div class="noph"><span class="hud">No photo</span></div>
{/if}

<style>
  img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .noph { width: 100%; height: 100%; display: grid; place-items: center; background: var(--mc-inset); }
  .noph .hud { font-size: 10px; letter-spacing: 0.08em; }
</style>
