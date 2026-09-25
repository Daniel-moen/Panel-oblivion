<script>
  /* Every tracked property. The funnel figures up top, one control row, and
     the book as a table (sticky head, scrolls sideways when it must). A phone
     gets the same rows as a list — eight columns do not fit a thumb — with
     the stage control kept on every row. */
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { toast, app } from '$lib/state.svelte.js';
  import { fmtM } from '$lib/format.js';
  import { STAGE_LABEL, STAGE_ORDER, MANDATE_LABEL, ago, isPast, shortDate } from '$lib/panel.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';

  let rows = $state([]);
  let stats = $state(null);
  let loaded = $state(false);
  let err = $state(null);
  let q = $state('');
  let stage = $state('');
  let sort = $state('tracked_at');
  let showArchived = $state(false);
  let busy = $state(null);

  async function load() {
    try {
      [rows, stats] = await Promise.all([
        api.tracked(showArchived ? '?archived=1' : ''),
        api.panelStats()
      ]);
      loaded = true; err = null;
    } catch (e) {
      err = e.message;
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
    const due = (stats?.due_today || 0) + (stats?.overdue_tasks || 0);
    return [
      ['Tracked', stats?.tracked, '', 'in lead management'],
      ['In conversation', (s.contacted || 0) + (s.meeting || 0) + (s.valuation_sent || 0), '', 'contacted → valuation'],
      ['Mandates won', (s.mandate_signed || 0) + (s.listed || 0) + (s.sold || 0), s.mandate_signed ? 'ok' : '', 'signed, listed, sold'],
      ['Lost', s.lost, s.lost ? 'crit' : '', 'to another agency'],
      ['Follow-ups due', due, stats?.overdue_tasks ? 'crit' : due ? 'warn' : '', stats?.overdue_tasks ? `${stats.overdue_tasks} overdue` : 'today'],
      ['Expiring ≤ 30d', stats?.expiring_mandates_30d, stats?.expiring_mandates_30d ? 'warn' : '', 'mandates to renew']
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
    busy = r.group_id;
    try {
      await api.updateTracked(r.group_id, { archived: !showArchived });
      if (showArchived) app.tracked[r.group_id] = r.stage; else delete app.tracked[r.group_id];
      await load();
      toast(showArchived ? 'Restored' : 'Archived', 'ok');
    } catch (e) { toast(e.message, 'error'); }
    finally { busy = null; }
  }
  function toggleArchived() { showArchived = !showArchived; loaded = false; load(); }

  const addr = (r) => r.street_address_raw || r.official_address || r.title || r.group_id;
  const stageTone = (s) => ({ mandate_signed: 'ok', listed: 'ok', sold: 'ok', lost: 'crit', parked: 'mute' }[s] || '');
  const mandTone = (t) => (t === 'none_lost' ? 'crit' : 'ok');
</script>

<svelte:head><title>Properties — Leads</title></svelte:head>

<div class="mg-row">
  <div class="titles">
    <h1 class="mg-h1">Properties</h1>
    <p class="mg-sub">{#if loaded}{rows.length} {showArchived ? 'archived' : 'tracked'} propert{rows.length === 1 ? 'y' : 'ies'}{:else}&nbsp;{/if}</p>
  </div>
</div>

<div class="tiles">
  {#each funnel as [l, v, tone, sub], i (l)}
    <div class="mg-stat-tile mg-rise" style:--i={i}>
      <span class="hud">{l}</span>
      <div class="v {tone}">{#if stats}{v ?? '—'}{:else if err}—{:else}<Skeleton h="26px" w="44px" />{/if}</div>
      <div class="sub" class:warn={tone === 'warn' || tone === 'crit'}>{sub}</div>
    </div>
  {/each}
</div>

<div class="mg-controls">
  <label class="mg-search">
    <span class="ic"><Icon name="search" size={16} /></span>
    <input class="mg-input" type="search" placeholder="Filter by address, contact…" bind:value={q} aria-label="Filter properties" />
    {#if q}<button type="button" class="clear" onclick={() => (q = '')} aria-label="Clear"><Icon name="close" size={14} /></button>{/if}
  </label>
  <div class="mg-select">
    <select bind:value={stage} aria-label="Stage">
      <option value="">All stages</option>
      {#each STAGE_ORDER as s (s)}<option value={s}>{STAGE_LABEL[s]} ({stats?.by_stage?.[s] ?? 0})</option>{/each}
    </select>
    <span class="ic"><Icon name="chevronDown" size={14} /></span>
  </div>
  <div class="mg-select">
    <select bind:value={sort} aria-label="Sort">
      <option value="tracked_at">Newest tracked</option>
      <option value="follow_up">Next follow-up</option>
      <option value="last_contact">Last contacted</option>
      <option value="stage">Stage</option>
      <option value="price">Price</option>
    </select>
    <span class="ic"><Icon name="chevronDown" size={14} /></span>
  </div>
  <button type="button" class="mg-chip arch" class:on={showArchived} aria-pressed={showArchived} onclick={toggleArchived}>
    <Icon name="box" size={13} /> Archived
  </button>
  {#if loaded}<span class="mg-count cnt">{filtered.length} of {rows.length}</span>{/if}
</div>

{#if err && !loaded}
  <div class="mg-strip crit"><span class="ic"><Icon name="alert" size={15} /></span><span><b>Couldn't load tracked properties</b> — {err}</span></div>
  <Empty icon="building" title="Properties unavailable" hint="The tracked book will show here once the server answers.">
    <button type="button" class="mg-btn secondary" onclick={load}><Icon name="refresh" size={15} /> Try again</button>
  </Empty>
{:else if !loaded}
  <section class="mg-section">
    <div class="mg-list">
      {#each Array(6) as _, i (i)}
        <div class="skrow"><span class="sk"><Skeleton h="14px" w="50%" delay={i * 50} /><Skeleton h="11px" w="30%" delay={i * 50 + 30} /></span><Skeleton h="32px" w="120px" r="10px" delay={i * 50} /></div>
      {/each}
    </div>
  </section>
{:else if rows.length === 0}
  <Empty icon="building" title={showArchived ? 'No archived properties' : 'Nothing tracked yet'}
         hint={showArchived ? 'Archived properties land here; restore one to put it back in the book.'
                            : 'Open a prospect and hit Track. Tracked properties gather contacts, every call you make, and the mandate you win.'}>
    {#if showArchived}<button type="button" class="mg-btn secondary" onclick={toggleArchived}>Show tracked</button>
    {:else}<a class="mg-btn primary" href="/prospects"><Icon name="building" size={15} /> Go to prospects</a>{/if}
  </Empty>
{:else if !filtered.length}
  <Empty icon="search" title="No properties match" hint="Nothing in the book matches this search and stage.">
    <button type="button" class="mg-btn secondary" onclick={() => { q = ''; stage = ''; }}>Clear filters</button>
  </Empty>
{:else}
  <!-- iPad / desktop: the table -->
  <section class="mg-section wide mg-rise">
    <div class="mg-tablewrap">
      <table class="mg-table">
        <thead>
          <tr>
            <th>Property</th><th class="r">Price</th><th>Stage</th><th>Contact</th>
            <th>Last contact</th><th>Follow-up</th><th>Mandate</th><th class="r"><span class="sr">Actions</span></th>
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
                  {#if r.listing_count > 1}<span class="mg-chip xs">{r.agency_count} agencies</span>{/if}
                </span>
              </td>
              <td class="r b mg-tnum">{r.price_zar ? fmtM(r.price_zar) : '—'}</td>
              <td>
                <div class="mg-select stg {stageTone(r.stage)}">
                  <select value={r.stage} onchange={(e) => setStage(r, e.target.value)} aria-label="Stage of {addr(r)}">
                    {#each STAGE_ORDER as s (s)}<option value={s}>{STAGE_LABEL[s]}</option>{/each}
                  </select>
                  <span class="ic"><Icon name="chevronDown" size={13} /></span>
                </div>
              </td>
              <td>
                {#if r.contact_name || r.contact_phone}
                  <a class="c" href="/leads/contacts/{r.contact_id}">{r.contact_name || '—'}</a>
                  <span class="sub mg-tnum">{r.contact_phone || r.contact_email || ''}{r.contact_count > 1 ? ` +${r.contact_count - 1}` : ''}</span>
                {:else}<span class="dim">none</span>{/if}
              </td>
              <td>
                {#if r.last_contact_at}
                  <span class="one">{ago(r.last_contact_at)}</span>
                  <span class="sub">{r.last_channel} · {(r.last_outcome || '').replace(/_/g, ' ')} · {r.attempts}×</span>
                {:else}<span class="dim">never</span>{/if}
              </td>
              <td>
                {#if r.next_task_due || r.next_follow_up_at}
                  {@const d = r.next_task_due || r.next_follow_up_at}
                  <span class="one" class:late={isPast(d)}>{ago(d)}</span>
                  <span class="sub mg-tnum">{shortDate(d)}{r.open_tasks ? ` · ${r.open_tasks} open` : ''}</span>
                {:else}<span class="dim">—</span>{/if}
              </td>
              <td>
                {#if r.mandate_type}
                  <span class="mg-chip xs {mandTone(r.mandate_type)}">{MANDATE_LABEL[r.mandate_type] || r.mandate_type}</span>
                  <span class="sub">
                    {#if r.mandate_type === 'none_lost'}{r.mandate_lost_to ? 'to ' + r.mandate_lost_to : ''}
                    {:else}{r.mandate_expires_at ? 'exp ' + shortDate(r.mandate_expires_at) : ''}{r.mandate_price ? ' · ' + fmtM(r.mandate_price) : ''}{/if}
                  </span>
                {:else}<span class="dim">—</span>{/if}
              </td>
              <td class="r act">
                <a class="mg-btn secondary sm" href="/leads/properties/{r.group_id}">Open</a>
                <button type="button" class="mg-btn ghost icon sm" onclick={() => archive(r)} disabled={busy === r.group_id}
                        title={showArchived ? 'Restore' : 'Archive'} aria-label={showArchived ? 'Restore' : 'Archive'}>
                  <Icon name={showArchived ? 'undo' : 'box'} size={15} />
                </button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>

  <!-- phone: the same rows as a list -->
  <section class="mg-section narrow">
    <div class="mg-list">
      {#each filtered as r, i (r.group_id)}
        {@const d = r.next_task_due || r.next_follow_up_at}
        <div class="prow mg-rise" style:--i={Math.min(i, 12)}>
          <a class="pmain" href="/leads/properties/{r.group_id}">
            <span class="t">
              <b>{addr(r)}</b>
              <span>{[r.suburb, r.price_zar ? fmtM(r.price_zar) : null, r.contact_name].filter(Boolean).join(' · ')}</span>
              <span class="meta">
                {#if d}<span class:late={isPast(d)}><Icon name="clock" size={11} /> {ago(d)}</span>
                {:else if r.last_contact_at}<span>last {r.last_channel} {ago(r.last_contact_at)}</span>
                {:else}<span class="dim">never contacted</span>{/if}
                {#if r.mandate_type}<span class="mg-chip xs {mandTone(r.mandate_type)}">{MANDATE_LABEL[r.mandate_type]}</span>{/if}
                {#if r.tier}<span class="tier {r.tier}">{r.tier}</span>{/if}
              </span>
            </span>
            <Icon name="chevronRight" size={15} class="chev" />
          </a>
          <div class="pacts">
            <div class="mg-select stg {stageTone(r.stage)}">
              <select value={r.stage} onchange={(e) => setStage(r, e.target.value)} aria-label="Stage of {addr(r)}">
                {#each STAGE_ORDER as s (s)}<option value={s}>{STAGE_LABEL[s]}</option>{/each}
              </select>
              <span class="ic"><Icon name="chevronDown" size={13} /></span>
            </div>
            <button type="button" class="mg-btn secondary icon" onclick={() => archive(r)} disabled={busy === r.group_id}
                    title={showArchived ? 'Restore' : 'Archive'} aria-label={showArchived ? 'Restore' : 'Archive'}>
              <Icon name={showArchived ? 'undo' : 'box'} size={16} />
            </button>
          </div>
        </div>
      {/each}
    </div>
  </section>
{/if}

<style>
  .mg-search input::-webkit-search-cancel-button { -webkit-appearance: none; appearance: none; }
  .titles { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .tiles { display: grid; gap: 10px; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-bottom: 16px; }
  @media (min-width: 700px) { .tiles { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
  @media (min-width: 1280px) { .tiles { grid-template-columns: repeat(6, minmax(0, 1fr)); } }

  .cnt { margin-left: auto; }
  @media (max-width: 639px) {
    .mg-controls > .mg-search { flex-basis: 100%; max-width: none; }
    .mg-controls > .mg-select { flex: 1 1 calc(50% - 4px); }
    .mg-controls > .mg-select select { width: 100%; }
  }

  .wide { display: none; }
  .narrow { display: block; }
  @media (min-width: 640px) { .wide { display: block; } .narrow { display: none; } }

  .wide .mg-tablewrap { max-height: calc(100dvh - 180px); }
  .mg-table td { vertical-align: top; }
  .mg-table td > .one, .mg-table td > a { display: block; }
  .prop { min-width: 240px; }
  .addr { font-weight: 600; color: var(--mc-ink); }
  .addr:hover, .c:hover { color: var(--mc-accent); }
  .c { font-weight: 500; color: var(--mc-ink); }
  .sub { margin-top: 3px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); }
  .dim { color: var(--mc-ink3); }
  .late { color: var(--mc-crit); font-weight: 600; }
  .act { white-space: nowrap; }
  .act > * { vertical-align: middle; }
  .act > .mg-btn + .mg-btn { margin-left: 4px; }
  .mg-chip.xs { height: 22px; padding: 0 8px; font-size: 11px; }
  .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }

  /* the stage control carries the stage's state colour */
  .stg { min-width: 150px; }
  .stg select { height: 32px; font-size: 12.5px; font-weight: 600; border-radius: 10px; }
  .stg.ok select { color: var(--mc-accent); border-color: var(--mc-ok-line); background: var(--mc-ok-soft); }
  .stg.crit select { color: var(--mc-crit); border-color: var(--mc-crit-line); background: var(--mc-crit-soft); }
  .stg.mute select { color: var(--mc-ink3); }

  /* the phone list */
  .prow { display: flex; flex-direction: column; gap: 8px; padding: 12px 16px; }
  .pmain { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .pmain .t { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .pmain b { font: 600 14px/1.35 var(--mc-font); color: var(--mc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pmain .t > span { font: 400 12.5px/1.4 var(--mc-font); color: var(--mc-ink3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pmain .t > .meta { display: flex; gap: 8px; align-items: center; margin-top: 4px; color: var(--mc-ink2); }
  .meta > span { display: inline-flex; align-items: center; gap: 4px; }
  .narrow :global(.chev) { color: var(--mc-ink3); flex: none; }
  .pacts { display: flex; gap: 8px; }
  .pacts .stg { flex: 1; }
  .pacts .stg select { height: 40px; }
  @media (pointer: coarse) {
    .pacts .stg select { height: 44px; }
    .pacts .mg-btn { width: 44px; height: 44px; }
  }

  .skrow { display: flex; gap: 12px; align-items: center; padding: 14px 16px; }
  .sk { flex: 1; display: flex; flex-direction: column; gap: 8px; }
</style>
