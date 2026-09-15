<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { toast, app } from '$lib/state.svelte.js';
  import { fmtM } from '$lib/format.js';
  import { STAGE_LABEL, STAGE_ORDER, MANDATE_LABEL, ago, isPast, shortDate } from '$lib/panel.js';

  let rows = $state([]);
  let stats = $state(null);
  let loaded = $state(false);
  let q = $state('');
  let stage = $state('');
  let sort = $state('tracked_at');
  let showArchived = $state(false);

  async function load() {
    try {
      [rows, stats] = await Promise.all([
        api.tracked(showArchived ? '?archived=1' : ''),
        api.panelStats()
      ]);
      loaded = true;
    } catch (e) {
      toast('Could not load tracked properties — ' + e.message, 'error');
    }
  }
  onMount(load);

  const filtered = $derived.by(() => {
    const needle = q.trim().toLowerCase();
    const out = rows.filter((r) =>
      (!stage || r.stage === stage) &&
      (!needle || [r.title, r.suburb, r.street_address_raw, r.contact_name, r.contact_phone,
                   r.agency, r.group_id].some((v) => v && String(v).toLowerCase().includes(needle))));
    const key = {
      tracked_at: (r) => r.tracked_at || '',
      price: (r) => -(r.price_zar || 0),
      last_contact: (r) => r.last_contact_at || '',
      follow_up: (r) => r.next_task_due || r.next_follow_up_at || '9999',
      stage: (r) => STAGE_ORDER.indexOf(r.stage)
    }[sort];
    const dir = sort === 'tracked_at' || sort === 'last_contact' ? -1 : 1;
    return out.sort((a, b) => (key(a) > key(b) ? dir : key(a) < key(b) ? -dir : 0));
  });

  const funnel = $derived.by(() => {
    const s = stats?.by_stage || {};
    return [
      ['Tracked', stats?.tracked, 'accent'],
      ['In conversation', (s.contacted || 0) + (s.meeting || 0) + (s.valuation_sent || 0), ''],
      ['Mandates won', (s.mandate_signed || 0) + (s.listed || 0) + (s.sold || 0), s.mandate_signed ? 'good' : ''],
      ['Lost', s.lost, s.lost ? 'bad' : 'dim'],
      ['Follow-ups due', (stats?.due_today || 0) + (stats?.overdue_tasks || 0),
        stats?.overdue_tasks ? 'bad' : ''],
      ['Mandates expiring ≤30d', stats?.expiring_mandates_30d, 'dim']
    ];
  });

  async function setStage(r, v) {
    const prev = r.stage;
    r.stage = v;
    try {
      await api.updateTracked(r.group_id, { stage: v });
      app.tracked[r.group_id] = v;
      stats = await api.panelStats();
    } catch (e) {
      r.stage = prev;
      toast('Stage not saved — ' + e.message, 'error');
    }
  }

  async function archive(r) {
    try {
      await api.updateTracked(r.group_id, { archived: !showArchived });
      if (showArchived) app.tracked[r.group_id] = r.stage; else delete app.tracked[r.group_id];
      await load();
      toast(showArchived ? 'Restored' : 'Archived', 'ok');
    } catch (e) { toast(e.message, 'error'); }
  }

  const addr = (r) => r.street_address_raw || r.official_address || r.title || r.group_id;
</script>

<svelte:head><title>Properties — Leads</title></svelte:head>

<h1 class="pt">Properties</h1>

<div class="stats">
  {#each funnel as [l, v, cls] (l)}
    <div class="stat panel {cls}"><span class="slabel">{l}</span><b>{v ?? '—'}</b></div>
  {/each}
</div>

<div class="bar">
  <input type="search" placeholder="Search address, suburb, contact, phone…" bind:value={q} />
  <select bind:value={stage}>
    <option value="">All stages</option>
    {#each STAGE_ORDER as s (s)}<option value={s}>{STAGE_LABEL[s]} ({stats?.by_stage?.[s] ?? 0})</option>{/each}
  </select>
  <select bind:value={sort}>
    <option value="tracked_at">Newest tracked</option>
    <option value="follow_up">Next follow-up</option>
    <option value="last_contact">Last contacted</option>
    <option value="stage">Stage</option>
    <option value="price">Price</option>
  </select>
  <label class="chk"><input type="checkbox" bind:checked={showArchived} onchange={load} /> Archived</label>
  <span class="count">{filtered.length} of {rows.length}</span>
</div>

{#if loaded && rows.length === 0}
  <div class="empty panel">
    <h3>{showArchived ? 'No archived properties' : 'Nothing tracked yet'}</h3>
    <p>Hover a prospect card and hit <b>+ Track</b>, or use the button in the detail drawer.
       Tracked properties gather contacts, every call you make, and the mandate you win.</p>
    <a class="btn primary" href="/prospects">Go to prospects</a>
  </div>
{:else if loaded}
  <div class="wrap panel">
    <table>
      <thead>
        <tr>
          <th>Property</th><th>Price</th><th>Stage</th><th>Contact</th>
          <th>Last contact</th><th>Follow-up</th><th>Mandate</th><th></th>
        </tr>
      </thead>
      <tbody>
        {#each filtered as r (r.group_id)}
          <tr>
            <td class="prop">
              <a href="/leads/properties/{r.group_id}" class="addr">{addr(r)}</a>
              <span class="sub">
                {[r.suburb, r.property_type, r.bedrooms ? r.bedrooms + ' bed' : null].filter(Boolean).join(' · ')}
                {#if r.tier}<span class="tier {r.tier}">{r.tier}</span>{/if}
                {#if r.listing_count > 1}<span class="pill">{r.agency_count} agencies</span>{/if}
              </span>
            </td>
            <td class="price">{r.price_zar ? fmtM(r.price_zar) : '—'}</td>
            <td>
              <select class="stg s-{r.stage}" value={r.stage} onchange={(e) => setStage(r, e.target.value)}>
                {#each STAGE_ORDER as s (s)}<option value={s}>{STAGE_LABEL[s]}</option>{/each}
              </select>
            </td>
            <td>
              {#if r.contact_name || r.contact_phone}
                <a class="c" href="/leads/contacts/{r.contact_id}">{r.contact_name || '—'}</a>
                <span class="sub">{r.contact_phone || r.contact_email || ''}{r.contact_count > 1 ? ` +${r.contact_count - 1}` : ''}</span>
              {:else}<span class="dim">none</span>{/if}
            </td>
            <td>
              {#if r.last_contact_at}
                <span>{ago(r.last_contact_at)}</span>
                <span class="sub">{r.last_channel} · {(r.last_outcome || '').replace(/_/g, ' ')} · {r.attempts}×</span>
              {:else}<span class="dim">never</span>{/if}
            </td>
            <td>
              {#if r.next_task_due || r.next_follow_up_at}
                {@const d = r.next_task_due || r.next_follow_up_at}
                <span class:late={isPast(d)}>{ago(d)}</span>
                <span class="sub">{shortDate(d)}{r.open_tasks ? ` · ${r.open_tasks} open` : ''}</span>
              {:else}<span class="dim">—</span>{/if}
            </td>
            <td>
              {#if r.mandate_type}
                <span class="mand m-{r.mandate_type}">{MANDATE_LABEL[r.mandate_type] || r.mandate_type}</span>
                <span class="sub">
                  {#if r.mandate_type === 'none_lost'}{r.mandate_lost_to ? 'to ' + r.mandate_lost_to : ''}
                  {:else}{r.mandate_expires_at ? 'exp ' + shortDate(r.mandate_expires_at) : ''}{r.mandate_price ? ' · ' + fmtM(r.mandate_price) : ''}{/if}
                </span>
              {:else}<span class="dim">—</span>{/if}
            </td>
            <td class="act">
              <a class="btn sm" href="/leads/properties/{r.group_id}">Open</a>
              <button class="btn sm" onclick={() => archive(r)} title={showArchived ? 'Restore' : 'Archive'}>
                {showArchived ? '↶' : '⌫'}</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<style>
  .pt { font-size: 1.7rem; font-weight: 800; letter-spacing: -0.03em; margin: 0; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
           gap: 0.75rem; margin: 1rem 0; }
  .stat { padding: 0.9rem 1rem; display: flex; flex-direction: column; gap: 0.3rem; }
  .slabel { font-size: 0.74rem; color: var(--ink-3); font-weight: 500; }
  .stat b { font-size: 1.5rem; font-weight: 800; letter-spacing: -0.02em; }
  .stat.accent b { color: var(--accent); }
  .stat.good b { color: var(--good); }
  .stat.bad b { color: var(--bad); }
  .stat.dim b { color: var(--ink-2); }

  .bar { display: flex; gap: 0.6rem; align-items: center; margin-bottom: 0.9rem; flex-wrap: wrap; }
  .bar input[type='search'] { flex: 1; min-width: 220px; }
  .chk { display: flex; gap: 0.4rem; align-items: center; font-size: 0.82rem; color: var(--ink-2); }
  .count { font-size: 0.78rem; color: var(--ink-3); margin-left: auto; }

  .empty { padding: 3rem 2rem; text-align: center; max-width: 560px; margin: 2rem auto; }
  .empty h3 { margin-bottom: 0.5rem; }
  .empty p { color: var(--ink-2); margin-bottom: 1.2rem; line-height: 1.5; }

  .wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.86rem; }
  th { text-align: left; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em;
       color: var(--ink-3); font-weight: 600; padding: 0.7rem 0.9rem; border-bottom: 1px solid var(--line); }
  td { padding: 0.65rem 0.9rem; border-bottom: 1px solid var(--line); vertical-align: top; }
  tr:hover td { background: var(--hover); }
  td:not(.act) > span, td:not(.act) > a { display: block; }
  .sub { font-size: 0.75rem; color: var(--ink-3); margin-top: 0.15rem; display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; }
  .prop { min-width: 240px; }
  .addr { font-weight: 600; color: var(--ink); }
  .addr:hover { color: var(--accent); }
  .pill { font-size: 0.68rem; padding: 0.1rem 0.45rem; border-radius: 999px; background: var(--bg-3); color: var(--ink-2); }
  .dim { color: var(--ink-3); }
  .late { color: var(--bad); font-weight: 600; }
  .c { font-weight: 500; color: var(--ink); }
  a.c:hover { color: var(--accent); }
  .act { white-space: nowrap; text-align: right; }
  .act .btn { display: inline-flex; margin-left: 0.3rem; }

  .stg { font-size: 0.78rem; padding: 0.3rem 1.7rem 0.3rem 0.6rem; font-weight: 600; min-width: 140px; }
  .s-mandate_signed, .s-listed, .s-sold { color: var(--good); }
  .s-lost { color: var(--bad); }
  .s-parked { color: var(--ink-3); }
  .s-contacted, .s-meeting, .s-valuation_sent { color: var(--accent-2); }

  .mand { display: inline-block; font-size: 0.72rem; font-weight: 700; padding: 0.15rem 0.5rem;
          border-radius: 4px; background: var(--open-soft); color: var(--open); }
  .m-open { background: var(--popen-soft); color: var(--popen); }
  .m-none_lost { background: var(--red-soft); color: var(--sole); }
</style>
