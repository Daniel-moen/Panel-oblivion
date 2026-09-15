<script>
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { leads, loadToday } from '$lib/leads.svelte.js';

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
                     s: [r.suburb, r.contact_name].filter(Boolean).join(' · '), ico: '🏠' }));
    const ppl = people.filter((c) => [c.name, c.phone, c.email, c.company].some((v) => v && String(v).toLowerCase().includes(n))).slice(0, 5)
      .map((c) => ({ key: 'c' + c.id, href: '/leads/contacts/' + c.id, b: c.name || c.phone,
                     s: [c.phone, c.properties.length + ' propert' + (c.properties.length === 1 ? 'y' : 'ies')].filter(Boolean).join(' · '), ico: '👤' }));
    results = [...ppl, ...props];
  });

  const due = $derived(leads.today ? leads.today.overdue.length + leads.today.due_today.length : 0);
  const nav = $derived([
    ['/leads', 'Today', due || null],
    ['/leads/pipeline', 'Pipeline', null],
    ['/leads/properties', 'Properties', null],
    ['/leads/contacts', 'Contacts', null]
  ]);
  const on = (href) => (href === '/leads' ? path === '/leads' : path.startsWith(href));
</script>

<div class="app">
  <aside>
    <a class="home" href="/"><span class="mark"></span><span>Oblivion</span><small>Leads</small></a>

    <div class="search">
      <input type="search" placeholder="Find a property or person…" bind:value={q} />
      {#if results.length}
        <ul class="hits">
          {#each results as r (r.key)}
            <li><button onclick={() => { q = ''; goto(r.href); }}>
              <b>{r.ico} {r.b}</b>
              <span>{r.s}</span>
            </button></li>
          {/each}
        </ul>
      {/if}
    </div>

    <nav>
      {#each nav as [href, label, badge] (href)}
        <a {href} class:on={on(href)}>{label}{#if badge}<i>{badge}</i>{/if}</a>
      {/each}
    </nav>

    <div class="foot">
      <a href="/prospects">Prospect engine →</a>
      <a href="/map">Map</a>
    </div>
  </aside>

  <main>{@render children()}</main>
</div>

<style>
  .app { min-height: 100vh; display: grid; grid-template-columns: 232px 1fr; background: var(--bg); }
  aside { position: sticky; top: 0; height: 100vh; display: flex; flex-direction: column; gap: 1.2rem;
          padding: 1.2rem 0.9rem; border-right: 1px solid var(--line); background: var(--bg-2); }
  .home { display: flex; align-items: baseline; gap: 0.5rem; padding: 0.2rem 0.5rem; font-weight: 800; color: var(--ink); }
  .mark { width: 10px; height: 10px; border-radius: 3px; background: var(--accent); align-self: center; }
  .home small { font-weight: 500; color: var(--ink-3); font-size: 0.74rem; }

  .search { position: relative; }
  .search input { width: 100%; font-size: 0.84rem; }
  .hits { position: absolute; top: 100%; left: 0; right: 0; z-index: 20; margin-top: 0.3rem; list-style: none; padding: 0.3rem;
          background: var(--bg-2); border: 1px solid var(--line-2); border-radius: var(--r-sm); box-shadow: var(--shadow-2); }
  .hits button { width: 100%; text-align: left; background: none; border: 0; padding: 0.45rem 0.6rem; border-radius: 6px;
                 display: flex; flex-direction: column; cursor: pointer; color: var(--ink); }
  .hits button:hover { background: var(--bg-3); }
  .hits b { font-size: 0.84rem; font-weight: 600; }
  .hits span { font-size: 0.72rem; color: var(--ink-3); }

  nav { display: flex; flex-direction: column; gap: 0.15rem; }
  nav a { display: flex; align-items: center; justify-content: space-between; padding: 0.55rem 0.75rem;
          border-radius: var(--r-sm); color: var(--ink-2); font-size: 0.9rem; font-weight: 500; }
  nav a:hover { background: var(--bg-3); color: var(--ink); }
  nav a.on { background: var(--accent-soft); color: var(--accent-2); font-weight: 600; }
  nav i { font-style: normal; font-size: 0.7rem; font-weight: 700; background: var(--bad); color: #fff;
          padding: 0.1rem 0.45rem; border-radius: 999px; }

  .foot { margin-top: auto; display: flex; flex-direction: column; gap: 0.3rem; padding: 0 0.75rem; }
  .foot a { font-size: 0.8rem; color: var(--ink-3); }
  .foot a:hover { color: var(--ink); }

  main { padding: 1.6rem clamp(1rem, 3vw, 2.4rem) 4rem; max-width: 1280px; width: 100%; }

  @media (max-width: 820px) {
    .app { grid-template-columns: 1fr; }
    aside { position: static; height: auto; flex-direction: row; flex-wrap: wrap; align-items: center; }
    nav { flex-direction: row; }
    .foot { margin-top: 0; flex-direction: row; }
    .search { flex: 1; min-width: 180px; }
  }
</style>
