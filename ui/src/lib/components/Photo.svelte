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
  <div class="noph"><span>No photo</span></div>
{/if}

<style>
  img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .noph {
    width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
    background:
      repeating-linear-gradient(45deg, #101014, #101014 8px, #131318 8px, #131318 16px);
  }
  .noph span { font-size: 0.58rem; letter-spacing: 0.22em; text-transform: uppercase;
               color: var(--ink-3); }
</style>
