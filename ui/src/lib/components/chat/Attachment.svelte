<script>
  /* One attachment on a message (or a waiting one in the pending bubble):
     a property card, a media thumbnail card, or a link card. Soft glass —
     no blur of its own; the sheet is the one blurred surface.

     Property tap: the prospect drawer when that property is in the loaded
     book (its listing_key found through gidOf), else its lead page.
     Media tap: the library with that item open (/media/browse?open=<id>). */
  import { goto } from '$app/navigation';
  import Icon from '$lib/components/glass/Icon.svelte';
  import { page } from '$app/state';
  import { app, gidOf, ensureProspects, loadTracked, toast } from '$lib/state.svelte.js';
  import { closeChat } from '$lib/chat.svelte.js';
  import { fmtR } from '$lib/format.js';
  import { murl, ensureToken } from '$lib/media.js';
  import { domainOf } from './text.js';

  let { a } = $props();

  let tokenOk = $state(false);
  let broken = $state(false);

  $effect(() => {
    if (a?.type !== 'media' || !a.thumb) return;
    ensureToken().then(() => (tokenOk = true)).catch(() => (tokenOk = false));
  });

  const thumb = $derived(a?.type === 'media' && a.thumb && tokenOk ? murl(a.thumb) : null);
  const narrow = () => typeof matchMedia !== 'undefined' && !matchMedia('(min-width: 720px)').matches;

  /* The drawer lives on /prospects: there, open it in place (the chat steps
     aside while it is up and comes back after); elsewhere deep-link to it
     (/prospects?open=<listing_key>). The gid → listing_key map is the loaded
     book, fetched on demand. Only a TRACKED property that is not in the book
     goes to its lead page (that page 404s for anything untracked). */
  async function openProperty() {
    const gid = String(a.gid);
    const find = () => app.prospects.find((r) => gidOf(r) === gid);
    let row = find();
    if (!row) {
      try { await ensureProspects(); } catch { /* handled below */ }
      row = find();
    }
    if (row) {
      if (page.url.pathname.startsWith('/prospects')) {
        app.selectedKey = row.listing_key;
        return;
      }
      if (narrow()) closeChat();
      goto('/prospects?open=' + encodeURIComponent(row.listing_key));
      return;
    }
    if (!(gid in (app.tracked || {}))) {
      try { await loadTracked(); } catch { /* treated as untracked */ }
    }
    if (app.tracked?.[gid]) {
      if (narrow()) closeChat();
      goto('/leads/properties/' + encodeURIComponent(gid));
    } else {
      toast('That property is no longer in the book', 'info');
    }
  }

  function openMedia() {
    if (narrow()) closeChat();
    goto('/media/browse?open=' + encodeURIComponent(a.id));
  }

</script>

{#if a?.type === 'property'}
  <button type="button" class="att prop" data-testid="chat-att-property" onclick={openProperty}
          aria-label={'Open property ' + (a.label || '')}>
    <span class="ph">
      {#if a.photo_url && !broken}
        <img src={a.photo_url} alt="" loading="lazy" onerror={() => (broken = true)} />
      {:else}
        <Icon name="property" size={18} />
      {/if}
    </span>
    <span class="tx">
      <b>{a.label || 'Property'}</b>
      <span class="sub">
        <span class="mg-tnum">{fmtR(a.price_zar)}</span>
        {#if a.suburb}<span class="dim"> · {a.suburb}</span>{/if}
      </span>
      {#if a.tier}<span class="tier {a.tier}">{a.tier}</span>{/if}
    </span>
  </button>
{:else if a?.type === 'media'}
  <button type="button" class="att media" data-testid="chat-att-media" onclick={openMedia}
          aria-label={'Open ' + (a.name || 'media')}>
    <span class="ph">
      {#if thumb && !broken}
        <img src={thumb} alt="" loading="lazy" onerror={() => (broken = true)} />
      {:else}
        <Icon name={a.kind === 'video' ? 'film' : 'image'} size={18} />
      {/if}
      {#if a.kind === 'video'}<i class="play" aria-hidden="true"><Icon name="play" size={12} /></i>{/if}
    </span>
    <span class="tx">
      <b>{a.name || 'Media'}</b>
      {#if a.caption}<span class="sub cap">{a.caption}</span>{:else}<span class="sub dim">{a.kind || 'media'}</span>{/if}
    </span>
  </button>
{:else if a?.type === 'link'}
  <a class="att link" data-testid="chat-att-link" href={a.url} target="_blank" rel="noopener noreferrer">
    <span class="ph ic"><Icon name="link" size={16} /></span>
    <span class="tx">
      <b>{a.title || a.domain || domainOf(a.url) || a.url}</b>
      <span class="sub dim">{a.domain || domainOf(a.url)} <Icon name="external" size={11} /></span>
    </span>
  </a>
{/if}

<style>
  .att {
    display: flex; align-items: center; gap: 10px; width: 100%; max-width: 320px; min-width: 0;
    padding: 6px 10px 6px 6px; margin: 0;
    background: var(--mc-glass-soft); border: 1px solid var(--mc-glass-line); border-radius: var(--mc-r-md);
    color: var(--mc-ink); font: inherit; text-align: left; text-decoration: none; cursor: pointer;
    transition: background var(--mc-t-fast), border-color var(--mc-t-fast);
  }
  .att:hover { background: var(--mc-glass-hover); border-color: var(--mc-glass-line2); }
  .ph {
    position: relative; flex: none; width: 52px; height: 52px; border-radius: 10px; overflow: hidden;
    display: grid; place-items: center; background: var(--mc-inset); color: var(--mc-ink3);
  }
  .ph.ic { width: 36px; height: 36px; border-radius: 9px; }
  .ph img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .play {
    position: absolute; right: 4px; bottom: 4px; width: 20px; height: 20px; border-radius: 50%;
    display: grid; place-items: center; background: rgba(0, 0, 0, 0.6); color: #fff;
  }
  .tx { min-width: 0; flex: 1; display: flex; flex-direction: column; align-items: flex-start; gap: 2px; }
  .tx b {
    max-width: 100%; font: 600 13px/1.3 var(--mc-font); color: var(--mc-ink);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .sub {
    max-width: 100%; font: 400 12px/1.35 var(--mc-font); color: var(--mc-ink2);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .sub.cap { white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; }
  .dim { color: var(--mc-ink3); }
  .tier {
    display: inline-flex; align-items: center; height: 18px; padding: 0 7px; margin-top: 2px;
    border-radius: 9999px; border: 1px solid var(--mc-glass-line);
    font: 600 10px/1 var(--mc-font); text-transform: uppercase; letter-spacing: 0.04em;
  }
  @media (pointer: coarse) { .att { min-height: 52px; } }
</style>
