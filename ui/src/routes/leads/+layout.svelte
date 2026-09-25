<script>
  /* Lead management — the header row of the pane, and nothing else.

     What is Leads' own: the jump-to search (properties and people, one box)
     and the four sub-sections as a segmented row. The dock / rail is the
     app's navigation; this row is only the section's insides.

     The search results are a real popover: a solid raised plane under the
     field, keyboard-driven (↑ ↓ Enter Esc), grouped People / Properties, and
     it says so when nothing matches rather than silently showing nothing. */
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { fade } from 'svelte/transition';
  import { slide } from '$lib/motion.js';
  import { api } from '$lib/api.js';
  import { leads, loadToday } from '$lib/leads.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';

  let { children } = $props();
  const path = $derived(page.url.pathname);
  let q = $state('');
  let all = $state([]);
  let people = $state([]);
  let focused = $state(false);
  let cursor = $state(0);
  let box = $state(null);
  let got = $state(0); // how many of the two lists have landed

  onMount(() => {
    loadToday();
    api.tracked().then((r) => (all = r)).catch(() => {}).finally(() => got++);
    api.contacts().then((r) => (people = r)).catch(() => {}).finally(() => got++);
  });

  const needle = $derived(q.trim().toLowerCase());
  const has = (vals) => vals.some((v) => v && String(v).toLowerCase().includes(needle));

  const hitsPeople = $derived(
    !needle ? [] : people.filter((c) => has([c.name, c.phone, c.email, c.company])).slice(0, 5)
      .map((c) => ({
        key: 'c' + c.id, href: '/leads/contacts/' + c.id, b: c.name || c.phone || '—', ico: 'user',
        s: [c.phone, c.properties.length + ' propert' + (c.properties.length === 1 ? 'y' : 'ies')].filter(Boolean).join(' · ')
      }))
  );
  const hitsProps = $derived(
    !needle ? [] : all.filter((r) => has([r.street_address_raw, r.title, r.suburb, r.contact_name, r.contact_phone])).slice(0, 6)
      .map((r) => ({
        key: 'p' + r.group_id, href: '/leads/properties/' + r.group_id, b: r.street_address_raw || r.title || r.group_id, ico: 'building',
        s: [r.suburb, r.contact_name].filter(Boolean).join(' · ')
      }))
  );
  const results = $derived([...hitsPeople, ...hitsProps]);
  const open = $derived(focused && !!needle);

  // a new query puts the cursor back on the first hit
  $effect(() => { needle; cursor = 0; });

  function go(r) {
    q = '';
    focused = false;
    goto(r.href);
  }
  function onkey(e) {
    if (e.key === 'Escape') { if (q) q = ''; else e.currentTarget.blur(); return; }
    if (!results.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); cursor = (cursor + 1) % results.length; }
    else if (e.key === 'ArrowUp') { e.preventDefault(); cursor = (cursor - 1 + results.length) % results.length; }
    else if (e.key === 'Enter') { e.preventDefault(); go(results[cursor]); }
  }
  // close when focus leaves the field AND its popover
  function onout(e) {
    if (!box?.contains(e.relatedTarget)) focused = false;
  }

  const due = $derived(leads.today ? leads.today.overdue.length + leads.today.due_today.length : 0);
  const nav = $derived([
    { value: '/leads', label: 'Today', icon: 'clock', count: due || null },
    { value: '/leads/pipeline', label: 'Pipeline', icon: 'layers' },
    { value: '/leads/properties', label: 'Properties', icon: 'building' },
    { value: '/leads/contacts', label: 'Contacts', icon: 'users' }
  ]);
  const here = $derived(
    nav.reduce(
      (best, n) => ((n.value === '/leads' ? path === '/leads' : path.startsWith(n.value)) ? n.value : best),
      '/leads'
    )
  );
</script>

<div class="bar">
  <div class="find" bind:this={box} onfocusin={() => (focused = true)} onfocusout={onout}>
    <div class="mg-search">
      <span class="ic"><Icon name="search" size={16} /></span>
      <input class="mg-input" type="search" placeholder="Find a property or person…" bind:value={q}
             onkeydown={onkey} aria-label="Find a property or person" autocomplete="off"
             role="combobox" aria-expanded={open} aria-controls="lead-hits" />
      {#if q}
        <button type="button" class="clear" onclick={() => (q = '')} aria-label="Clear the search">
          <Icon name="close" size={14} />
        </button>
      {/if}
    </div>

    {#if open}
      <div class="hits mg-popover" id="lead-hits" role="listbox" transition:slide={{ y: -6, duration: 180 }}>
        {#if !results.length && got < 2}
          <p class="none"><span class="mg-spin"></span> Searching…</p>
        {:else if !results.length}
          <p class="none">No property or person matches “{q.trim()}”.</p>
        {:else}
          {#each results as r, i (r.key)}
            {#if i === 0 && hitsPeople.length}<span class="hud grp">People</span>{/if}
            {#if i === hitsPeople.length && hitsProps.length}<span class="hud grp">Properties</span>{/if}
            <button type="button" role="option" aria-selected={i === cursor} class:cur={i === cursor}
                    onmouseenter={() => (cursor = i)} onclick={() => go(r)}>
              <span class="hic"><Icon name={r.ico} size={15} /></span>
              <span class="t"><b>{r.b}</b>{#if r.s}<span>{r.s}</span>{/if}</span>
              <Icon name="chevronRight" size={14} class="chev" />
            </button>
          {/each}
        {/if}
      </div>
    {/if}
  </div>

  <div class="sections mg-noscroll">
    <Seg options={nav} value={here} onchange={(v) => goto(v)} label="Lead sections" />
  </div>
</div>

{#key path}
  <div in:fade={{ duration: 180, delay: 60 }}>{@render children()}</div>
{/key}

<style>
  .bar {
    position: relative; z-index: 30;
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 16px;
  }
  .find { position: relative; flex: 1 1 260px; max-width: 26rem; min-width: 0; }
  .sections { display: flex; overflow-x: auto; min-width: 0; max-width: 100%; padding: 1px 0; }
  @media (max-width: 639px) {
    .find { flex-basis: 100%; max-width: none; }
    .sections { flex-basis: 100%; }
  }
  /* a phone: the four labels fit on one line once the icons step aside */
  @media (max-width: 439px) {
    .sections :global(button svg) { display: none; }
    .sections :global(button) { padding: 0 10px; }
  }

  .find input::-webkit-search-cancel-button { -webkit-appearance: none; appearance: none; }
  .hits {
    position: absolute; top: calc(100% + 6px); left: 0; right: 0; z-index: 40;
    display: flex; flex-direction: column; gap: 1px;
    max-height: min(60vh, 440px); overflow-y: auto; overscroll-behavior: contain;
  }
  @media (min-width: 640px) { .hits { min-width: 360px; } }
  .grp { padding: 8px 10px 4px; }
  .hits > button.cur { background: rgba(255, 255, 255, 0.06); color: var(--mc-ink); }
  .hic {
    flex: none; width: 30px; height: 30px; border-radius: 8px; display: grid; place-items: center;
    background: var(--mc-glass-soft); border: 1px solid var(--mc-line); color: var(--mc-ink3);
  }
  .t { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
  .t b { font: 500 13px/1.35 var(--mc-font); color: var(--mc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .t span { font: 400 12px/1.35 var(--mc-font); color: var(--mc-ink3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .hits :global(.chev) { flex: none; color: var(--mc-ink3); }
  .none { display: flex; align-items: center; gap: 8px; margin: 0; padding: 12px 10px; font: 400 13px/1.45 var(--mc-font); color: var(--mc-ink3); }
  @media (pointer: coarse) { .hits > button { min-height: 48px; } }
</style>
