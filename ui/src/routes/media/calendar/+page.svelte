<script>
  /* Calendar — a view over shoots by when they're booked (shoot_date +
     shoot_time on shoots.py). Month grid on a wide screen; on a phone the
     grid shrinks to dots and the month reads as an agenda underneath.
     Tap a shoot to open it; tap a day to book one on it. */
  import { goto } from '$app/navigation';
  import { say } from '$lib/media.svelte.js';
  import { shoots, isoDay, parseDay, fmtDay, centreOf } from '$lib/media/shoots.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import ShootsGate from '$lib/components/media/shoots/ShootsGate.svelte';
  import StatusChip from '$lib/components/media/shoots/StatusChip.svelte';
  import NewShootSheet from '$lib/components/media/shoots/NewShootSheet.svelte';

  const today = isoDay();
  let cursor = $state(new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  let all = $state([]);
  let loading = $state(true);
  let err = $state(null);        // the list failed to load
  let picked = $state(null);     // a YYYY-MM-DD the agenda narrows to
  let bookOn = $state(null);     // the day the sheet opens with; null = closed
  let showSheet = $state(false);

  async function load() {
    loading = true; err = null;
    try { all = (await shoots.list())?.shoots || []; }
    catch (e) { err = e.message; say(e.message, 'error'); }
    finally { loading = false; }
  }

  const byDay = $derived.by(() => {
    const m = new Map();
    for (const s of all) {
      if (!s.shoot_date) continue;
      if (!m.has(s.shoot_date)) m.set(s.shoot_date, []);
      m.get(s.shoot_date).push(s);
    }
    for (const list of m.values()) list.sort((a, b) => (a.shoot_time || '99').localeCompare(b.shoot_time || '99'));
    return m;
  });

  /* Six rows of seven, Monday first. */
  const cells = $derived.by(() => {
    const y = cursor.getFullYear(), mo = cursor.getMonth();
    const lead = (new Date(y, mo, 1).getDay() + 6) % 7;
    const start = new Date(y, mo, 1 - lead);
    const rows = Math.ceil((lead + new Date(y, mo + 1, 0).getDate()) / 7);
    return Array.from({ length: rows * 7 }, (_, i) => {
      const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
      const key = isoDay(d);
      return { key, day: d.getDate(), inMonth: d.getMonth() === mo, list: byDay.get(key) || [] };
    });
  });

  const monthKey = $derived(isoDay(cursor).slice(0, 7));
  const monthLabel = $derived(cursor.toLocaleDateString('en-ZA', { month: 'long', year: 'numeric' }));
  const inMonth = $derived(all.filter((s) => s.shoot_date?.startsWith(monthKey)).length);
  const unbooked = $derived(all.filter((s) => !s.shoot_date).length);

  /* The agenda: the picked day, or the whole month, day by day. */
  const agenda = $derived.by(() => {
    const days = picked ? [picked] : [...byDay.keys()].filter((k) => k.startsWith(monthKey)).sort();
    return days.map((k) => ({ key: k, list: byDay.get(k) || [] }));
  });

  function move(n) {
    cursor = new Date(cursor.getFullYear(), cursor.getMonth() + n, 1);
    picked = null;
  }
  function goToday() { cursor = new Date(new Date().getFullYear(), new Date().getMonth(), 1); picked = null; }

  function tapDay(c) {
    if (!c.inMonth) cursor = new Date(parseDay(c.key).getFullYear(), parseDay(c.key).getMonth(), 1);
    picked = picked === c.key ? null : c.key;
  }

  function book(day) { bookOn = day || ''; showSheet = true; }

  function created(s) {
    showSheet = false;
    say(`Booked ${s.address}`);
    goto(`/media/shoot?id=${s.id}`);
  }

  const WD = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
</script>

<svelte:head><title>Calendar · Media</title></svelte:head>

<ShootsGate onready={load}>
  {#snippet children()}
    <div class="mg-row">
      <h2 class="mg-h2">Calendar</h2>
      {#if !loading}<span class="mg-count">{inMonth} shoot{inMonth === 1 ? '' : 's'} this month</span>{/if}
      <div class="mg-actions">
        <a class="mg-btn secondary sm" href="/media/shoots"><Icon name="list" size={14} />All shoots</a>
        <button class="mg-btn primary sm" onclick={() => book(picked || '')}><Icon name="plus" size={14} />Book</button>
      </div>
    </div>

    <div class="nav">
      <button class="mg-btn secondary icon" onclick={() => move(-1)} aria-label="Previous month"><Icon name="chevronLeft" size={16} /></button>
      <h3 class="mon">{monthLabel}</h3>
      <button class="mg-btn secondary icon" onclick={() => move(1)} aria-label="Next month"><Icon name="chevronRight" size={16} /></button>
      <button class="mg-btn ghost sm" onclick={goToday}>Today</button>
      {#if unbooked}<a class="mg-chip warn" href="/media/shoots">{unbooked} not booked</a>{/if}
    </div>

    {#if err}
      <div class="mg-strip crit">
        <span class="ic"><Icon name="alert" size={15} /></span>
        <span><b>Couldn't load the bookings</b> — {err}</span>
        <button class="mg-btn secondary sm retry" onclick={load}><Icon name="refresh" size={13} />Retry</button>
      </div>
    {/if}
    {#if loading}
      <Skeleton h="22rem" r="16px" />
    {:else}
      <div class="cal mg-card" role="grid" aria-label={monthLabel}>
        <div class="wd" role="row">{#each WD as w (w)}<span role="columnheader">{w}</span>{/each}</div>
        <div class="days">
          {#each cells as c (c.key)}
            <div class="day" class:out={!c.inMonth} class:today={c.key === today} class:sel={picked === c.key} role="gridcell">
              <div class="dh">
                <button class="num mg-tnum" onclick={() => tapDay(c)} aria-label="{fmtDay(c.key, { weekday: 'long', day: 'numeric', month: 'long' })}, {c.list.length} shoot{c.list.length === 1 ? '' : 's'}">{c.day}</button>
                <button class="add" onclick={() => book(c.key)} aria-label="Book a shoot on {fmtDay(c.key)}" title="Book a shoot"><Icon name="plus" size={12} /></button>
              </div>
              <div class="evs">
                {#each c.list.slice(0, 3) as s (s.id)}
                  <a class="ev {s.status}" href="/media/shoot?id={s.id}" title="{s.shoot_time || ''} {s.address}">
                    {#if s.shoot_time}<b class="mg-tnum">{s.shoot_time}</b>{/if}<span>{s.address}</span>
                  </a>
                {/each}
                {#if c.list.length > 3}<button class="more" onclick={() => (picked = c.key)}>+{c.list.length - 3} more</button>{/if}
              </div>
              {#if c.list.length}
                <button class="dots" onclick={() => tapDay(c)} aria-hidden="true" tabindex="-1">
                  {#each c.list.slice(0, 4) as s (s.id)}<i class={s.status}></i>{/each}
                </button>
              {/if}
            </div>
          {/each}
        </div>
      </div>

      <section class="agenda" class:month={!picked}>
        <div class="ah">
          <h3>{picked ? fmtDay(picked, { weekday: 'long', day: 'numeric', month: 'long' }) : monthLabel}</h3>
          {#if picked}
            <button class="mg-btn secondary sm" onclick={() => book(picked)}><Icon name="plus" size={13} />Book on this day</button>
            <button class="mg-btn ghost sm" onclick={() => (picked = null)}>Whole month</button>
          {/if}
        </div>
        {#if !agenda.length || agenda.every((d) => !d.list.length)}
          <p class="none">{picked ? 'Nothing booked on this day.' : 'Nothing booked this month.'}</p>
        {:else}
          {#each agenda as d (d.key)}
            {#if !picked}<h4 class="mg-label">{fmtDay(d.key, { weekday: 'long', day: 'numeric', month: 'short' })}</h4>{/if}
            {#each d.list as s (s.id)}
              <a class="mg-card item" href="/media/shoot?id={s.id}">
                <span class="tm mg-tnum">{s.shoot_time || '—'}</span>
                <span class="main"><b>{s.address}</b><span>{[s.suburb, s.agent].filter(Boolean).join(' · ')}</span></span>
                <StatusChip status={s.status} />
              </a>
            {/each}
          {/each}
        {/if}
      </section>
    {/if}

    <NewShootSheet open={showSheet} date={bookOn || ''} near={centreOf(all)} onclose={() => (showSheet = false)} oncreated={created} />
  {/snippet}
</ShootsGate>

<style>
  .nav { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
  .mon { margin: 0; min-width: 9.5em; text-align: center; font: 600 16px/1.2 var(--mc-font); color: var(--mc-ink); }

  .cal { padding: 8px; }
  .wd, .days { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); }
  .wd span { padding: 4px 6px 8px; font: 500 11px/1 var(--mc-font); color: var(--mc-ink3); text-align: left; }
  .days { gap: 4px; }
  .day { position: relative; min-height: 104px; min-width: 0; padding: 4px; border-radius: var(--mc-r-sm);
         background: var(--mc-raised); border: 1px solid transparent; display: flex; flex-direction: column; gap: 3px; }
  .day.out { opacity: 0.45; }
  .day.today { border-color: var(--mc-ok-line); }
  .day.sel { background: var(--mc-line); border-color: var(--mc-line2); }
  .retry { margin-left: auto; align-self: center; }
  .dh { display: flex; align-items: center; justify-content: space-between; }
  .num { min-width: 28px; height: 28px; border: 0; border-radius: var(--mc-r-sm); background: none; color: var(--mc-ink2);
         font: 500 12.5px/1 var(--mc-font); cursor: pointer; padding: 0 6px; }
  .num:hover { background: var(--mc-line); color: var(--mc-ink); }
  .today .num { background: var(--mc-accent); color: var(--mc-accent-ink); font-weight: 600; }
  .add { width: 28px; height: 28px; border: 0; border-radius: var(--mc-r-sm); background: none; color: var(--mc-ink3); cursor: pointer;
         display: grid; place-items: center; opacity: 0; transition: opacity var(--mc-t-fast), background var(--mc-t-fast); }
  .day:hover .add, .add:focus-visible { opacity: 1; }
  /* no hover on a touch screen: the book button is simply there */
  @media (hover: none) { .add { opacity: 1; } }
  .add:hover { background: var(--mc-line); color: var(--mc-ink); }

  .evs { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  .ev { display: flex; gap: 5px; align-items: baseline; min-width: 0; padding: 4px 6px; border-radius: 7px;
        font: 500 11.5px/1.25 var(--mc-font); color: var(--mc-ink); background: var(--mc-warn-soft);
        border-left: 2px solid var(--mc-warn); }
  .ev.editing { background: var(--mc-mgr-soft); border-left-color: var(--mc-mgr); }
  .ev.posted { background: var(--mc-ok-soft); border-left-color: var(--mc-accent); }
  .ev { transition: background var(--mc-t-fast); }
  .ev:hover { background: var(--mc-line2); }
  .ev b { flex: none; font-weight: 600; color: var(--mc-ink2); }
  .ev span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .more { border: 0; background: none; padding: 2px 6px; text-align: left; font: 500 11px/1.2 var(--mc-font); color: var(--mc-ink3); cursor: pointer; }
  .dots { display: none; }
  @media (pointer: coarse) {
    .nav .mg-btn { height: 44px; }
    .nav .mg-btn.icon { width: 44px; }
    .add { width: 36px; height: 36px; }
    .more { min-height: 32px; }
  }

  .agenda { margin-top: 16px; }
  .ah { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
  .ah h3 { margin: 0; flex: 1; font: 600 15px/1.3 var(--mc-font); color: var(--mc-ink); }
  h4.mg-label { margin: 14px 0 6px; }
  .item { display: flex; align-items: center; gap: 12px; padding: 10px 12px; margin-bottom: 8px; min-height: 52px; }
  .tm { flex: none; width: 44px; font: 600 13px/1 var(--mc-font); color: var(--mc-ink2); }
  .main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .main b { font: 600 13.5px/1.3 var(--mc-font); color: var(--mc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .main span { font: 400 12px/1.3 var(--mc-font); color: var(--mc-ink3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .none { margin: 0; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink3); }

  /* Desktop: the grid says it all; the agenda only appears for a picked day. */
  @media (min-width: 721px) {
    .agenda.month { display: none; }
  }

  /* Phone: dots in the grid, the agenda carries the detail. */
  @media (max-width: 720px) {
    .cal { padding: 6px; }
    .wd span { padding: 2px 0 6px; text-align: center; font-size: 10.5px; }
    .days { gap: 2px; }
    .day { min-height: 48px; padding: 2px; align-items: center; cursor: pointer; }
    .dh { justify-content: center; }
    .num { min-width: 40px; height: 36px; }
    .add, .evs { display: none; }
    .dots { display: flex; gap: 3px; justify-content: center; border: 0; background: none; padding: 2px; cursor: pointer; }
    .dots i { width: 6px; height: 6px; border-radius: 50%; background: var(--mc-warn); }
    .dots i.editing { background: var(--mc-mgr); }
    .dots i.posted { background: var(--mc-accent); }
  }
</style>
