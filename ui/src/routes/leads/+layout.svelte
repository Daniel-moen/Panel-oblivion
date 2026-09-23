<script>
  /* Lead management — the header row of the pane, and nothing else.

     The sidebar is gone: the dock is the navigation now, and the app's one
     pane holds the page. What survives is what was actually Leads' own —
     the jump-to search (properties and people, one box) and the four
     sub-sections as a segmented row.

     TODO(leads agent): this is the foundation pass — the search results
     dropdown, the badge on Today and the page headers underneath still want
     the full glass treatment. */
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { fade } from 'svelte/transition';
  import { api } from '$lib/api.js';
  import { leads, loadToday } from '$lib/leads.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';

  let { children } = $props();
  const path = $derived(page.url.pathname);
  let q = $state('');
  let results = $state([]);
  let all = $state([]);
  let people = $state([]);

  onMount(() => { loadToday(); api.tracked().then((r) => (all = r)).catch(() => {});
                api.contacts().then((r) => (people = r)).catch(() => {}); });

  $effect(() => {
    const n = q.trim().toLowerCase();
    if (!n) { results = []; return; }
    const props = all.filter((r) => [r.street_address_raw, r.title, r.suburb, r.contact_name, r.contact_phone]
      .some((v) => v && String(v).toLowerCase().includes(n))).slice(0, 6)
      .map((r) => ({ key: 'p' + r.group_id, href: '/leads/properties/' + r.group_id, b: r.street_address_raw || r.title,
                     s: [r.suburb, r.contact_name].filter(Boolean).join(' · '), ico: 'building' }));
    const ppl = people.filter((c) => [c.name, c.phone, c.email, c.company].some((v) => v && String(v).toLowerCase().includes(n))).slice(0, 5)
      .map((c) => ({ key: 'c' + c.id, href: '/leads/contacts/' + c.id, b: c.name || c.phone,
                     s: [c.phone, c.properties.length + ' propert' + (c.properties.length === 1 ? 'y' : 'ies')].filter(Boolean).join(' · '), ico: 'user' }));
    results = [...ppl, ...props];
  });

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

<div class="mg-controls">
  <label class="mg-search">
    <span class="ic"><Icon name="search" size={16} /></span>
    <input class="mg-input" type="search" placeholder="Find a property or person…" bind:value={q} />
    {#if q}
      <button class="clear" onclick={() => (q = '')} aria-label="Clear the search">
        <Icon name="close" size={14} />
      </button>
    {/if}
    {#if results.length}
      <ul class="hits mg-glass-strong">
        {#each results as r (r.key)}
          <li><button onclick={() => { q = ''; goto(r.href); }}>
            <Icon name={r.ico} size={15} />
            <span class="t"><b>{r.b}</b><span>{r.s}</span></span>
          </button></li>
        {/each}
      </ul>
    {/if}
  </label>

  <Seg options={nav} value={here} onchange={(v) => goto(v)} label="Lead sections" />
</div>

{#key path}
  <div in:fade={{ duration: 180, delay: 60 }}>{@render children()}</div>
{/key}

<style>
  .mg-controls { position: relative; z-index: 20; }

  .hits {
    position: absolute; top: calc(100% + 6px); left: 0; right: 0; z-index: 30;
    list-style: none; margin: 0; padding: 6px;
    max-height: 60vh; overflow-y: auto;
  }
  .hits button {
    width: 100%; display: flex; align-items: center; gap: 10px;
    background: none; border: 0; border-radius: 12px; padding: 8px 10px;
    text-align: left; color: var(--mg-i2); cursor: pointer;
    transition: background 0.15s;
  }
  .hits button:hover { background: var(--mg-glass-soft); color: var(--mg-i); }
  .t { min-width: 0; display: flex; flex-direction: column; }
  .t b { font: 500 13px/1.4 var(--mg-font); color: var(--mg-i);
         overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .t span { font: 400 11.5px/1.4 var(--mg-font); color: var(--mg-i3); }
</style>
