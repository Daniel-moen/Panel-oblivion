<script>
  /* The pipeline board.

     From 768px up the stages are columns you drag cards between. A phone
     gets the same stages as a stacked list, empty stages folded to a line.
     Dragging is a mouse gesture — every card also carries a "Move to…" control
     (a native select, so a phone gets its own picker) so a stage can be
     changed with a thumb. */
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { app, toast } from '$lib/state.svelte.js';
  import { loadToday, addrOf } from '$lib/leads.svelte.js';
  import { STAGE_LABEL, MANDATE_LABEL, ago, isPast } from '$lib/panel.js';
  import { fmtM } from '$lib/format.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';

  /* Closed outcomes live behind a toggle so the board stays about work in flight. */
  const LIVE = ['new', 'researching', 'contact_found', 'contacted', 'meeting', 'valuation_sent', 'mandate_signed', 'listed'];
  const CLOSED = ['sold', 'lost', 'parked'];
  const ALL = [...LIVE, ...CLOSED];
  const TONE = { mandate_signed: 'ok', listed: 'ok', sold: 'ok', lost: 'crit', meeting: 'warn', valuation_sent: 'warn' };

  let rows = $state([]);
  let loaded = $state(false);
  let err = $state(null);
  let dragging = $state(null);
  let over = $state(null);
  let showClosed = $state(false);

  async function load() {
    try { rows = await api.tracked(); loaded = true; err = null; }
    catch (e) { err = e.message; toast(e.message, 'error'); }
  }
  onMount(load);

  const byStage = $derived.by(() => {
    const m = Object.fromEntries(ALL.map((s) => [s, []]));
    for (const r of rows) (m[r.stage] || m.new).push(r);
    for (const s in m) m[s].sort((a, b) => (b.priority === 'high') - (a.priority === 'high') ||
      String(a.next_task_due || '9').localeCompare(String(b.next_task_due || '9')));
    return m;
  });
  const stages = $derived([...LIVE, ...(showClosed ? CLOSED : [])]);
  const closedCount = $derived(CLOSED.reduce((n, s) => n + byStage[s].length, 0));
  const value = (list) => list.reduce((s, r) => s + (r.price_zar || 0), 0);

  async function move(gid, stage) {
    const r = rows.find((x) => x.group_id === gid);
    if (!r || r.stage === stage) return;
    const prev = r.stage; r.stage = stage;
    try {
      await api.updateTracked(gid, { stage }); app.tracked[gid] = stage; loadToday();
      toast('Moved to ' + STAGE_LABEL[stage], 'ok');
    } catch (e) { r.stage = prev; toast('Not moved — ' + e.message, 'error'); }
  }
  function drop(stage) { if (dragging) move(dragging, stage); dragging = null; over = null; }
  const followTone = (r) => (r.next_task_due ? (isPast(r.next_task_due) ? 'late' : 'soon') : r.last_contact_at ? '' : 'never');
</script>

<svelte:head><title>Pipeline — Leads</title></svelte:head>

<div class="mg-row">
  <div class="titles">
    <h1 class="mg-h1">Pipeline</h1>
    <p class="mg-sub">
      {#if loaded}{rows.length} propert{rows.length === 1 ? 'y' : 'ies'} · <span class="mg-tnum">{fmtM(value(rows))}</span> in play<span class="dragtip">&nbsp;· drag a card to another stage, or use the arrow on it</span>{:else}&nbsp;{/if}
    </p>
  </div>
  <div class="mg-actions">
    <button type="button" class="mg-chip" class:on={showClosed} aria-pressed={showClosed} onclick={() => (showClosed = !showClosed)}>
      <Icon name={showClosed ? 'eye' : 'eyeOff'} size={13} /> Sold / lost / parked{#if loaded} <span class="mg-tnum">{closedCount}</span>{/if}
    </button>
  </div>
</div>

{#if err && !loaded}
  <div class="mg-strip crit"><span class="ic"><Icon name="alert" size={15} /></span><span><b>Couldn't load the pipeline</b> — {err}</span></div>
  <Empty icon="layers" title="Pipeline unavailable" hint="Your tracked properties will show here once the server answers.">
    <button type="button" class="mg-btn secondary" onclick={load}><Icon name="refresh" size={15} /> Try again</button>
  </Empty>
{:else if !loaded}
  <div class="board">
    {#each Array(4) as _, c (c)}
      <section class="col">
        <div class="ch"><Skeleton h="12px" w="90px" /></div>
        <div class="cards">{#each Array(3 - (c % 2)) as _, i (i)}<Skeleton h="92px" r="12px" delay={c * 60 + i * 60} />{/each}</div>
      </section>
    {/each}
  </div>
{:else if !rows.length}
  <Empty icon="layers" title="Nothing in the pipeline" hint="Track a prospect from the engine and it lands here in New, ready to work through the stages.">
    <a class="mg-btn primary" href="/prospects"><Icon name="building" size={15} /> Go to prospects</a>
  </Empty>
{:else}
  <div class="board">
    {#each stages as s, ci (s)}
      <section class="col mg-rise" style:--i={ci} class:over={over === s} class:empty={!byStage[s].length}
        ondragover={(e) => { e.preventDefault(); over = s; }} ondragleave={() => (over = null)}
        ondrop={() => drop(s)} aria-label={STAGE_LABEL[s]}>
        <div class="ch">
          <span class="mg-dot {TONE[s] || ''}"></span>
          <h2>{STAGE_LABEL[s]}</h2>
          <span class="mg-count">{byStage[s].length}</span>
          {#if byStage[s].length}<span class="val mg-tnum">{fmtM(value(byStage[s]))}</span>{/if}
        </div>
        <div class="cards" role="list">
          {#each byStage[s] as r (r.group_id)}
            <article class="card" class:hi={r.priority === 'high'} class:drag={dragging === r.group_id} draggable="true" role="listitem"
              ondragstart={() => (dragging = r.group_id)} ondragend={() => { dragging = null; over = null; }}>
              <div class="c1">
                <a href="/leads/properties/{r.group_id}" class="addr">{addrOf(r)}</a>
                <label class="mover mg-btn ghost icon sm" title="Move to another stage">
                  <Icon name="arrowRight" size={14} />
                  <select value={r.stage} onchange={(e) => move(r.group_id, e.target.value)} aria-label="Move {addrOf(r)} to stage">
                    {#each ALL as o (o)}<option value={o}>{o === r.stage ? '• ' : ''}{STAGE_LABEL[o]}</option>{/each}
                  </select>
                </label>
              </div>
              <div class="m">{r.suburb || ''}{#if r.price_zar}<span class="mg-tnum">{r.suburb ? ' · ' : ''}{fmtM(r.price_zar)}</span>{/if}</div>
              {#if r.contact_name}<a class="c" href="/leads/contacts/{r.contact_id}"><Icon name="user" size={12} />{r.contact_name}</a>{/if}
              <div class="foot">
                <span class="f {followTone(r)}">
                  {#if r.next_task_due}<Icon name="clock" size={12} /> {ago(r.next_task_due)}
                  {:else if r.last_contact_at}{r.last_channel} {ago(r.last_contact_at)}
                  {:else}no contact yet{/if}
                </span>
                {#if r.mandate_type}<span class="mg-chip {r.mandate_type === 'none_lost' ? 'crit' : 'ok'} xs">{MANDATE_LABEL[r.mandate_type]}</span>
                {:else if r.tier}<span class="tier {r.tier}">{r.tier}</span>{/if}
              </div>
            </article>
          {/each}
          {#if !byStage[s].length}<div class="emptycol">{over === s ? 'Drop here' : 'Empty'}</div>{/if}
        </div>
      </section>
    {/each}
  </div>
{/if}

<style>
  .titles { min-width: 0; display: flex; flex-direction: column; gap: 4px; }

  /* phone: a stacked list of stages */
  .board { display: flex; flex-direction: column; gap: 12px; }
  .col {
    background: var(--mc-surface); border: 1px solid var(--mc-line); border-radius: var(--mc-r);
    box-shadow: var(--mc-sh-1); display: flex; flex-direction: column; min-width: 0;
    transition: border-color var(--mc-t-fast), background var(--mc-t-fast);
  }
  .col.over { border-color: var(--mc-ok-line); background: var(--mc-ok-soft); }
  .ch { display: flex; align-items: center; gap: 8px; padding: 12px 14px; min-height: 44px; }
  .ch h2 { margin: 0; font: 600 13px/1.3 var(--mc-font); color: var(--mc-ink2); white-space: nowrap; }
  .val { margin-left: auto; font: 500 12px/1 var(--mc-font); color: var(--mc-ink3); }
  .cards { display: flex; flex-direction: column; gap: 8px; padding: 0 10px 10px; }
  .dragtip { display: none; }

  /* an empty stage on a phone is one quiet line, not a box */
  .col.empty .cards { display: none; }
  .col.empty .ch { opacity: 0.7; }

  /* iPad and up: the stages are columns */
  @media (min-width: 768px) {
    .board {
      flex-direction: row; align-items: flex-start; gap: 10px;
      overflow-x: auto; padding-bottom: 12px; min-height: 60vh;
      scroll-snap-type: x proximity; -webkit-overflow-scrolling: touch;
    }
    .col { flex: 0 0 248px; scroll-snap-align: start; min-height: 180px; }
    .ch { border-bottom: 1px solid var(--mc-line); margin-bottom: 10px; }
    .col.empty .cards { display: flex; }
    .col.empty .ch { opacity: 1; }
    .dragtip { display: inline; }
  }

  .card {
    position: relative; display: flex; flex-direction: column; gap: 4px;
    padding: 10px 10px 10px 12px; border-radius: var(--mc-r-md);
    background: var(--mc-raised); border: 1px solid var(--mc-line);
    cursor: grab; transition: border-color var(--mc-t-fast), transform var(--mc-t) var(--mc-ease), opacity var(--mc-t-fast);
  }
  .card:hover { border-color: var(--mc-line2); }
  .card:active { cursor: grabbing; }
  .card.drag { opacity: 0.45; }
  .card.hi::before { content: ''; position: absolute; left: -1px; top: 10px; bottom: 10px; width: 3px; border-radius: 0 3px 3px 0; background: var(--mc-crit); }
  .c1 { display: flex; align-items: flex-start; gap: 6px; }
  .addr { flex: 1; min-width: 0; font: 600 13.5px/1.3 var(--mc-font); color: var(--mc-ink); padding-top: 5px; overflow-wrap: anywhere; }
  .addr:hover { color: var(--mc-accent); }
  .m { font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); }
  .c { display: inline-flex; align-items: center; gap: 5px; font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink2); min-width: 0; }
  .c:hover { color: var(--mc-accent); }
  .foot { display: flex; justify-content: space-between; align-items: center; gap: 6px; margin-top: 4px; }
  .f { display: inline-flex; align-items: center; gap: 4px; font: 500 11.5px/1.3 var(--mc-font); color: var(--mc-ink3); }
  .f.late { color: var(--mc-crit); font-weight: 600; }
  .f.soon { color: var(--mc-accent); font-weight: 600; }
  .f.never { color: var(--mc-warn); }
  .mg-chip.xs { height: 22px; padding: 0 8px; font-size: 11px; }

  /* the move control: an icon button with a transparent native select on top */
  .mover { position: relative; overflow: hidden; margin: -2px -4px 0 0; }
  .mover select { position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; font-size: 16px; }
  .mover:focus-within { outline: 2px solid rgba(62, 207, 142, 0.7); outline-offset: 1px; }

  .emptycol { text-align: center; color: var(--mc-ink3); font: 400 12px/1 var(--mc-font); padding: 22px 0; border: 1px dashed var(--mc-line); border-radius: var(--mc-r-md); }
  .col.over .emptycol { border-color: var(--mc-ok-line); color: var(--mc-accent); }

  @media (pointer: coarse) {
    .mover { width: 44px; height: 44px; }
    .ch { min-height: 48px; }
  }
</style>
