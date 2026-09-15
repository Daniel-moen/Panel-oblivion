<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { app, toast } from '$lib/state.svelte.js';
  import { loadToday, addrOf } from '$lib/leads.svelte.js';
  import { STAGE_LABEL, MANDATE_LABEL, ago, isPast } from '$lib/panel.js';
  import { fmtM } from '$lib/format.js';

  /* Closed outcomes live in a collapsed rail so the board stays about work in flight. */
  const LIVE = ['new', 'researching', 'contact_found', 'contacted', 'meeting', 'valuation_sent', 'mandate_signed', 'listed'];
  const CLOSED = ['sold', 'lost', 'parked'];

  let rows = $state([]);
  let loaded = $state(false);
  let dragging = $state(null);
  let over = $state(null);
  let showClosed = $state(false);

  async function load() {
    try { rows = await api.tracked(); loaded = true; } catch (e) { toast(e.message, 'error'); }
  }
  onMount(load);

  const byStage = $derived.by(() => {
    const m = Object.fromEntries([...LIVE, ...CLOSED].map((s) => [s, []]));
    for (const r of rows) (m[r.stage] || m.new).push(r);
    for (const s in m) m[s].sort((a, b) => (b.priority === 'high') - (a.priority === 'high') ||
      String(a.next_task_due || '9').localeCompare(String(b.next_task_due || '9')));
    return m;
  });
  const value = (list) => list.reduce((s, r) => s + (r.price_zar || 0), 0);

  async function move(gid, stage) {
    const r = rows.find((x) => x.group_id === gid);
    if (!r || r.stage === stage) return;
    const prev = r.stage; r.stage = stage;
    try { await api.updateTracked(gid, { stage }); app.tracked[gid] = stage; loadToday(); }
    catch (e) { r.stage = prev; toast('Not moved — ' + e.message, 'error'); }
  }
  function drop(stage) { if (dragging) move(dragging, stage); dragging = null; over = null; }
  const followTone = (r) => (r.next_task_due ? (isPast(r.next_task_due) ? 'late' : 'soon') : r.last_contact_at ? '' : 'never');
</script>

<svelte:head><title>Pipeline — Leads</title></svelte:head>

<header class="hd">
  <div><h1>Pipeline</h1><p class="sub">Drag a card to move it. {rows.length} properties · {fmtM(value(rows))} in play.</p></div>
  <label class="chk"><input type="checkbox" bind:checked={showClosed} /> Show sold / lost / parked</label>
</header>

{#if loaded}
  <div class="board">
    {#each [...LIVE, ...(showClosed ? CLOSED : [])] as s (s)}
      <section class="col" class:over={over === s}
        ondragover={(e) => { e.preventDefault(); over = s; }} ondragleave={() => (over = null)}
        ondrop={() => drop(s)} role="list">
        <h2 class="s-{s}">{STAGE_LABEL[s]} <span>{byStage[s].length}</span>
          {#if byStage[s].length}<em>{fmtM(value(byStage[s]))}</em>{/if}</h2>
        {#each byStage[s] as r (r.group_id)}
          <article class="card" class:hi={r.priority === 'high'} draggable="true" role="listitem"
            ondragstart={() => (dragging = r.group_id)} ondragend={() => { dragging = null; over = null; }}>
            <a href="/leads/properties/{r.group_id}" class="addr">{addrOf(r)}</a>
            <div class="m">{r.suburb || ''}{r.price_zar ? ' · ' + fmtM(r.price_zar) : ''}</div>
            {#if r.contact_name}<a class="c" href="/leads/contacts/{r.contact_id}">👤 {r.contact_name}</a>{/if}
            <div class="foot">
              <span class="f {followTone(r)}">
                {#if r.next_task_due}⏰ {ago(r.next_task_due)}
                {:else if r.last_contact_at}{r.last_channel} {ago(r.last_contact_at)}
                {:else}no contact yet{/if}
              </span>
              {#if r.mandate_type}<span class="mand m-{r.mandate_type}">{MANDATE_LABEL[r.mandate_type]}</span>
              {:else if r.tier}<span class="tier {r.tier}">{r.tier}</span>{/if}
            </div>
          </article>
        {/each}
        {#if !byStage[s].length}<div class="ghost">—</div>{/if}
      </section>
    {/each}
  </div>
{/if}

<style>
  .hd { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 1.2rem; gap: 1rem; flex-wrap: wrap; }
  h1 { font-size: 1.7rem; font-weight: 800; letter-spacing: -0.03em; margin: 0 0 0.2rem; }
  .sub { color: var(--ink-2); font-size: 0.9rem; }
  .chk { display: flex; gap: 0.4rem; align-items: center; font-size: 0.82rem; color: var(--ink-2); }

  .board { display: flex; gap: 0.8rem; overflow-x: auto; padding-bottom: 1rem; align-items: flex-start; min-height: 60vh; }
  .col { flex: 0 0 236px; background: var(--bg-3); border-radius: var(--r-lg); padding: 0.6rem; display: flex; flex-direction: column; gap: 0.5rem;
         border: 1px dashed transparent; transition: border-color 0.12s, background 0.12s; min-height: 160px; }
  .col.over { border-color: var(--accent); background: var(--accent-soft); }
  h2 { font-size: 0.74rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-2);
       display: flex; align-items: center; gap: 0.4rem; padding: 0.2rem 0.3rem 0.3rem; }
  h2 span { background: var(--bg-2); border-radius: 999px; padding: 0.02rem 0.45rem; font-size: 0.68rem; }
  h2 em { margin-left: auto; font-style: normal; font-weight: 500; color: var(--ink-3); text-transform: none; letter-spacing: 0; }
  h2.s-mandate_signed, h2.s-listed { color: var(--good); }
  h2.s-lost { color: var(--bad); }

  .card { background: var(--bg-2); border: 1px solid var(--line); border-radius: var(--r-sm); padding: 0.65rem 0.75rem;
          display: flex; flex-direction: column; gap: 0.25rem; cursor: grab; box-shadow: var(--shadow-1); transition: transform 0.12s, box-shadow 0.12s; }
  .card:hover { transform: translateY(-1px); box-shadow: var(--shadow-2); }
  .card:active { cursor: grabbing; }
  .card.hi { border-left: 3px solid var(--hot); }
  .addr { font-size: 0.86rem; font-weight: 650; color: var(--ink); line-height: 1.25; }
  .addr:hover { color: var(--accent); }
  .m { font-size: 0.74rem; color: var(--ink-3); }
  .c { font-size: 0.76rem; color: var(--ink-2); }
  a.c:hover { color: var(--accent); }
  .foot { display: flex; justify-content: space-between; align-items: center; margin-top: 0.2rem; gap: 0.4rem; }
  .f { font-size: 0.7rem; color: var(--ink-3); }
  .f.late { color: var(--bad); font-weight: 600; }
  .f.soon { color: var(--accent-2); font-weight: 600; }
  .f.never { color: var(--warm); }
  .mand { font-size: 0.64rem; font-weight: 700; padding: 0.08rem 0.4rem; border-radius: 4px; background: var(--open-soft); color: var(--open); }
  .m-none_lost { background: var(--red-soft); color: var(--sole); }
  .ghost { text-align: center; color: var(--ink-3); font-size: 0.8rem; padding: 1.2rem 0; }
</style>
