<script>
  /* Everyone you could phone, merged across properties. A card per person;
     the whole card opens the person, and call / WhatsApp are real links of
     their own beside it (not buttons nested inside a link). */
  import { staggerIn, pressable } from '$lib/motion.js';
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { toast } from '$lib/state.svelte.js';
  import { waNumber } from '$lib/leads.svelte.js';
  import { STAGE_LABEL, ago } from '$lib/panel.js';
  import { fmtM } from '$lib/format.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';

  let people = $state([]);
  let loaded = $state(false);
  let err = $state(null);
  let q = $state('');
  let filter = $state('all');   // all | uncontacted | active | mandate

  async function load() {
    try { people = await api.contacts(); loaded = true; err = null; }
    catch (e) { err = e.message; toast(e.message, 'error'); }
  }
  onMount(load);

  const TESTS = {
    all: () => true,
    uncontacted: (p) => !p.attempts,
    active: (p) => p.properties.some((x) => ['contacted', 'meeting', 'valuation_sent'].includes(x.stage)),
    mandate: (p) => !!p.mandates
  };
  const shown = $derived.by(() => {
    const n = q.trim().toLowerCase();
    return people.filter((p) => {
      if (!TESTS[filter](p)) return false;
      if (!n) return true;
      return [p.name, p.phone, p.email, p.company, ...p.properties.map((x) => x.address), ...p.properties.map((x) => x.suburb)]
        .some((v) => v && String(v).toLowerCase().includes(n));
    });
  });
  const count = (k) => (loaded ? people.filter(TESTS[k]).length : null);
  const FILTERS = $derived([
    { value: 'all', label: 'All', count: count('all') },
    { value: 'uncontacted', label: 'Never contacted', count: count('uncontacted') },
    { value: 'active', label: 'In conversation', count: count('active') },
    { value: 'mandate', label: 'Mandate holders', count: count('mandate') }
  ]);
  const propCount = $derived(new Set(people.flatMap((p) => p.properties.map((x) => x.group_id))).size);
  const initials = (n) => (n || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
</script>

<svelte:head><title>Contacts — Leads</title></svelte:head>

<div class="mg-row">
  <div class="titles">
    <h1 class="mg-h1">Contacts</h1>
    <p class="mg-sub">{#if loaded}{people.length} {people.length === 1 ? 'person' : 'people'} across {propCount} propert{propCount === 1 ? 'y' : 'ies'}{:else}&nbsp;{/if}</p>
  </div>
</div>

<div class="mg-controls">
  <label class="mg-search">
    <span class="ic"><Icon name="search" size={16} /></span>
    <input class="mg-input" type="search" placeholder="Name, number, email, address…" bind:value={q} aria-label="Filter contacts" />
    {#if q}<button type="button" class="clear" onclick={() => (q = '')} aria-label="Clear"><Icon name="close" size={14} /></button>{/if}
  </label>
  <div class="segrow mg-noscroll"><Seg options={FILTERS} value={filter} onchange={(v) => (filter = v)} label="Show" /></div>
</div>

{#if err && !loaded}
  <div class="mg-strip crit"><span class="ic"><Icon name="alert" size={15} /></span><span><b>Couldn't load contacts</b> — {err}</span></div>
  <Empty icon="users" title="Contacts unavailable" hint="Owners and agents you've found will show here once the server answers.">
    <button type="button" class="mg-btn secondary" onclick={load}><Icon name="refresh" size={15} /> Try again</button>
  </Empty>
{:else if !loaded}
  <div class="grid">
    {#each Array(6) as _, i (i)}
      <div class="card sk"><Skeleton h="44px" w="44px" r="50%" delay={i * 50} />
        <span class="skb"><Skeleton h="15px" w="60%" delay={i * 50} /><Skeleton h="12px" w="40%" delay={i * 50 + 30} /><Skeleton h="12px" w="80%" delay={i * 50 + 60} /></span></div>
    {/each}
  </div>
{:else if !people.length}
  <Empty icon="users" title="No contacts yet" hint="Contacts appear when you find an owner on a tracked property — from the deeds lookup, the engine, or by adding one by hand.">
    <a class="mg-btn primary" href="/leads/properties"><Icon name="building" size={15} /> Tracked properties</a>
  </Empty>
{:else if !shown.length}
  <Empty icon="search" title="No contacts match" hint="Nobody matches this search and filter.">
    <button type="button" class="mg-btn secondary" onclick={() => { q = ''; filter = 'all'; }}>Clear filters</button>
  </Empty>
{:else}
  <div class="grid">
    {#each shown as p, i (p.key)}
      <div class="card" in:staggerIn|global={{ i }} use:pressable={'lift'}>
        <span class="av" aria-hidden="true">{initials(p.name)}</span>
        <div class="cb">
          <div class="nm">
            <a class="cover" href="/leads/contacts/{p.id}">{p.name || p.phone || '—'}</a>
            {#if p.mandates}<span class="mg-chip ok xs">{p.mandates} mandate{p.mandates > 1 ? 's' : ''}</span>{/if}
          </div>
          <div class="ln mg-tnum">{[p.phone, p.email].filter(Boolean).join(' · ') || 'no number yet'}</div>
          {#if p.company}<div class="ln dim">{p.company}</div>{/if}
          <div class="props">
            {#each p.properties.slice(0, 3) as x (x.group_id)}
              <div class="pr"><Icon name="building" size={12} /><span><b>{x.address || x.group_id}</b><i>{[x.suburb, x.price_zar ? fmtM(x.price_zar) : null, x.stage ? STAGE_LABEL[x.stage] : null].filter(Boolean).join(' · ')}</i></span></div>
            {/each}
            {#if p.properties.length > 3}<span class="dim more">+{p.properties.length - 3} more</span>{/if}
          </div>
          <div class="foot">
            {#if p.attempts}<span>{p.attempts} attempt{p.attempts > 1 ? 's' : ''} · {p.spoke} spoke · last {ago(p.last_contact_at)}</span>
            {:else}<span class="warn"><span class="mg-dot warn sm"></span> never contacted</span>{/if}
            <span class="dim">via {p.providers.join(', ')}</span>
          </div>
        </div>
        {#if p.phone}
          <div class="acts">
            <a class="mg-btn secondary icon sm" href="tel:{p.phone}" title="Call" aria-label="Call {p.name || ''}"><Icon name="phone" size={15} /></a>
            {#if waNumber(p.phone)}<a class="mg-btn secondary icon sm" href="https://wa.me/{waNumber(p.phone)}" target="_blank" rel="noopener" title="WhatsApp" aria-label="WhatsApp {p.name || ''}"><Icon name="message" size={15} /></a>{/if}
          </div>
        {/if}
      </div>
    {/each}
  </div>
{/if}

<style>
  .mg-search input::-webkit-search-cancel-button { -webkit-appearance: none; appearance: none; }
  .titles { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .segrow { display: flex; overflow-x: auto; min-width: 0; max-width: 100%; }
  @media (max-width: 639px) {
    .mg-controls > .mg-search { flex-basis: 100%; max-width: none; }
    .segrow { flex-basis: 100%; }
  }

  .grid { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 330px), 1fr)); }
  .card {
    position: relative; display: flex; gap: 12px; align-items: flex-start; padding: 14px 14px 14px 16px;
    background: var(--mc-surface); border: 1px solid var(--mc-line); border-radius: var(--mc-r);
    box-shadow: var(--mc-sh-1); transition: border-color var(--mc-t-fast), transform var(--mg-spring-snappy);
  }
  .card:hover { border-color: var(--mc-line2); }
  .card:has(.cover:focus-visible) { outline: 2px solid rgba(62, 207, 142, 0.7); outline-offset: 2px; }
  .card.sk { align-items: center; }
  .skb { flex: 1; display: flex; flex-direction: column; gap: 8px; }

  .av {
    width: 44px; height: 44px; flex: none; border-radius: 50%; display: grid; place-items: center;
    background: var(--mc-raised); border: 1px solid var(--mc-line2); color: var(--mc-ink2); font: 600 14px/1 var(--mc-font);
  }
  .cb { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .nm { display: flex; gap: 8px; align-items: center; min-width: 0; }
  /* the name link stretches over the whole card */
  .cover { min-width: 0; font: 600 14.5px/1.35 var(--mc-font); color: var(--mc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; outline: none; }
  .cover::after { content: ''; position: absolute; inset: 0; border-radius: inherit; }
  .card:hover .cover { color: var(--mc-accent); }
  .mg-chip.xs { height: 22px; padding: 0 8px; font-size: 11px; }
  .ln { font: 400 12.5px/1.45 var(--mc-font); color: var(--mc-ink2); overflow-wrap: anywhere; }
  .dim { color: var(--mc-ink3); }
  .props { display: flex; flex-direction: column; gap: 6px; margin-top: 6px; }
  .pr { display: flex; gap: 8px; align-items: flex-start; color: var(--mc-ink3); }
  .pr :global(svg) { margin-top: 3px; flex: none; }
  .pr > span { display: flex; flex-direction: column; min-width: 0; }
  .pr b { font: 500 12.5px/1.4 var(--mc-font); color: var(--mc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pr i { font: 400 11.5px/1.4 var(--mc-font); font-style: normal; color: var(--mc-ink3); }
  .more { font-size: 12px; padding-left: 20px; }
  .foot { display: flex; justify-content: space-between; gap: 4px 10px; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--mc-line); font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink2); flex-wrap: wrap; }
  .warn { display: inline-flex; align-items: center; gap: 6px; color: var(--mc-warn); font-weight: 500; }

  .acts { position: relative; z-index: 1; display: flex; flex-direction: column; gap: 6px; }
  @media (pointer: coarse) { .acts .mg-btn { width: 44px; height: 44px; } }
</style>
