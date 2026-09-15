<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { toast } from '$lib/state.svelte.js';
  import { waNumber } from '$lib/leads.svelte.js';
  import { STAGE_LABEL, ago } from '$lib/panel.js';
  import { fmtM } from '$lib/format.js';

  let people = $state([]);
  let loaded = $state(false);
  let q = $state('');
  let filter = $state('all');   // all | uncontacted | active | mandate

  onMount(async () => {
    try { people = await api.contacts(); loaded = true; } catch (e) { toast(e.message, 'error'); }
  });

  const shown = $derived.by(() => {
    const n = q.trim().toLowerCase();
    return people.filter((p) => {
      if (filter === 'uncontacted' && p.attempts) return false;
      if (filter === 'active' && !p.properties.some((x) => ['contacted', 'meeting', 'valuation_sent'].includes(x.stage))) return false;
      if (filter === 'mandate' && !p.mandates) return false;
      if (!n) return true;
      return [p.name, p.phone, p.email, p.company, ...p.properties.map((x) => x.address), ...p.properties.map((x) => x.suburb)]
        .some((v) => v && String(v).toLowerCase().includes(n));
    });
  });
  const initials = (n) => (n || '?').split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
  const hue = (s) => [...String(s || '')].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 0);
</script>

<svelte:head><title>Contacts — Leads</title></svelte:head>

<header class="hd">
  <div><h1>Contacts</h1><p class="sub">{people.length} people across {new Set(people.flatMap((p) => p.properties.map((x) => x.group_id))).size} properties.</p></div>
</header>

<div class="bar">
  <input type="search" placeholder="Name, number, email, address…" bind:value={q} />
  <div class="seg">
    {#each [['all', 'All'], ['uncontacted', 'Never contacted'], ['active', 'In conversation'], ['mandate', 'Mandate holders']] as [k, l] (k)}
      <button class:on={filter === k} onclick={() => (filter = k)}>{l}</button>
    {/each}
  </div>
</div>

{#if loaded && !shown.length}
  <div class="empty panel"><p>No contacts match.</p></div>
{:else if loaded}
  <div class="grid">
    {#each shown as p (p.key)}
      <a class="card panel" href="/leads/contacts/{p.id}">
        <div class="av" style:background="hsl({hue(p.name)} 45% 45%)">{initials(p.name)}</div>
        <div class="body">
          <div class="nm"><b>{p.name || p.phone || '—'}</b>
            {#if p.mandates}<span class="mand">{p.mandates} mandate{p.mandates > 1 ? 's' : ''}</span>{/if}</div>
          <div class="ln">{[p.phone, p.email].filter(Boolean).join(' · ') || 'no number yet'}</div>
          {#if p.company}<div class="ln dim">{p.company}</div>{/if}
          <div class="props">
            {#each p.properties.slice(0, 3) as x (x.group_id)}
              <span class="pr">🏠 {x.address || x.group_id}<i>{x.suburb}{x.price_zar ? ' · ' + fmtM(x.price_zar) : ''}{x.stage ? ' · ' + STAGE_LABEL[x.stage] : ''}</i></span>
            {/each}
            {#if p.properties.length > 3}<span class="dim">+{p.properties.length - 3} more</span>{/if}
          </div>
          <div class="foot">
            {#if p.attempts}<span>{p.attempts} attempt{p.attempts > 1 ? 's' : ''} · {p.spoke} spoke · last {ago(p.last_contact_at)}</span>
            {:else}<span class="warn">never contacted</span>{/if}
            <span class="dim">via {p.providers.join(', ')}</span>
          </div>
        </div>
        <div class="acts">
          {#if p.phone}<span class="ib" role="button" tabindex="0" onclick={(e) => { e.preventDefault(); location.href = 'tel:' + p.phone; }} onkeydown={(e) => e.key === 'Enter' && (location.href = 'tel:' + p.phone)} title="Call">📞</span>{/if}
          {#if waNumber(p.phone)}<span class="ib" role="button" tabindex="0" onclick={(e) => { e.preventDefault(); window.open('https://wa.me/' + waNumber(p.phone)); }} onkeydown={(e) => e.key === 'Enter' && window.open('https://wa.me/' + waNumber(p.phone))} title="WhatsApp">💬</span>{/if}
        </div>
      </a>
    {/each}
  </div>
{/if}

<style>
  .hd { margin-bottom: 1rem; }
  h1 { font-size: 1.7rem; font-weight: 800; letter-spacing: -0.03em; margin: 0 0 0.2rem; }
  .sub { color: var(--ink-2); font-size: 0.9rem; }
  .bar { display: flex; gap: 0.7rem; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; }
  .bar input { flex: 1; min-width: 240px; }
  .seg { display: flex; gap: 0.2rem; background: var(--bg-3); padding: 0.2rem; border-radius: 999px; }
  .seg button { background: none; border: 0; padding: 0.35rem 0.8rem; border-radius: 999px; font-size: 0.8rem; font-weight: 500; color: var(--ink-2); cursor: pointer; }
  .seg button.on { background: var(--bg-2); color: var(--ink); font-weight: 600; box-shadow: var(--shadow-1); }
  .empty { padding: 2rem; text-align: center; color: var(--ink-3); }

  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 0.8rem; }
  .card { display: flex; gap: 0.9rem; padding: 0.95rem 1rem; color: var(--ink); transition: transform 0.12s, box-shadow 0.12s; align-items: flex-start; }
  .card:hover { transform: translateY(-2px); box-shadow: var(--shadow-2); }
  .av { width: 44px; height: 44px; border-radius: 50%; flex: none; display: grid; place-items: center; color: #fff; font-weight: 700; font-size: 0.9rem; }
  .body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 0.2rem; }
  .nm { display: flex; gap: 0.5rem; align-items: center; }
  .nm b { font-size: 0.98rem; font-weight: 700; }
  .ln { font-size: 0.82rem; color: var(--ink-2); }
  .dim { color: var(--ink-3); }
  .mand { font-size: 0.66rem; font-weight: 700; padding: 0.08rem 0.45rem; border-radius: 4px; background: var(--open-soft); color: var(--open); }
  .props { display: flex; flex-direction: column; gap: 0.15rem; margin-top: 0.3rem; }
  .pr { font-size: 0.8rem; display: flex; flex-direction: column; }
  .pr i { font-style: normal; font-size: 0.72rem; color: var(--ink-3); padding-left: 1.35rem; }
  .foot { display: flex; justify-content: space-between; gap: 0.5rem; margin-top: 0.4rem; font-size: 0.74rem; color: var(--ink-2); flex-wrap: wrap; }
  .warn { color: var(--warm); font-weight: 600; }
  .acts { display: flex; flex-direction: column; gap: 0.3rem; }
  .ib { width: 32px; height: 32px; display: grid; place-items: center; border-radius: 8px; border: 1px solid var(--line); background: var(--bg-2); font-size: 0.9rem; }
  .ib:hover { background: var(--bg-3); border-color: var(--line-3); }
</style>
