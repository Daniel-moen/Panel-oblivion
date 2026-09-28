<script>
  /* /tasks — everyone's to-do list.

     Everyone gets their own list: the quick-add bar (a to-do, or "Log done"
     for something already finished), "To do" in working order (on it,
     overdue, due today, then by date), and "Done" split into this week and
     earlier, so the team can see what got done.

     An admin (the owner, or anyone with `admin`) also gets a person switcher
     — anybody's list, with the add bar assigning to whoever is on screen —
     and the Team board: a column per person, open / on it / done this week.
     team.py enforces all of it; a member who forges ?user= gets a 403.

     Opening your OWN list clears the "new from others" badge on the dock
     ($lib/tasks.svelte.js). The view and person live in the query string
     (?view=board, ?user=<id>) so a link or a reload lands in the same place;
     it is read on mount because the page is prerendered. */
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api.js';
  import { toast } from '$lib/state.svelte.js';
  import { watchRoster, roster } from '$lib/presence.svelte.js';
  import { markTasksSeen, taskInbox } from '$lib/tasks.svelte.js';
  import { liveOrder, splitDone, localDay } from '$lib/tasks.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import TaskRow from '$lib/components/tasks/TaskRow.svelte';
  import TaskAdd from '$lib/components/tasks/TaskAdd.svelte';
  import TeamBoard from '$lib/components/tasks/TeamBoard.svelte';

  let data = $state(null);          // /api/team/tasks for `who`
  let board = $state([]);           // admins: /api/team/tasks/board?detail=1
  let view = $state('list');        // 'list' | 'board'
  let who = $state(null);           // user id on screen (null = me)
  let failed = $state('');
  let doneLimit = $state(50);
  let showEarlier = $state(false);

  const viewer = $derived(data?.me ?? null);
  const isAdmin = $derived(!!data?.is_admin);
  const mine = $derived(!data || data.user?.id === data.me);
  const person = $derived(data?.user);
  const tasks = $derived(data?.tasks || []);
  const live = $derived(liveOrder(tasks, localDay()));
  const done = $derived(splitDone(tasks));
  const lateN = $derived(live.filter((t) => t.overdue).length);
  const people = $derived(board.map((u) => ({ id: u.id, display_name: u.display_name, disabled: u.disabled })));
  const title = $derived(view === 'board' ? 'Team board' : mine ? 'My tasks' : `${person?.display_name}'s tasks`);

  async function loadList(user = who, limit = doneLimit) {
    try {
      data = await api.myTasks(user, limit);
      failed = '';
      if (data.user?.id === data.me && (data.counts?.new || taskInbox.unseen)) markTasksSeen();
    } catch (e) {
      if (e.status === 403 || e.status === 404) { who = null; syncUrl(); return loadList(null); }
      failed = e.message;
    }
  }

  async function loadBoard() {
    try { board = (await api.taskBoard(true)).users; } catch { board = []; }
  }

  function syncUrl() {
    const q = new URLSearchParams();
    if (view === 'board') q.set('view', 'board');
    else if (who != null) q.set('user', String(who));
    const s = q.toString();
    goto('/tasks' + (s ? '?' + s : ''), { replaceState: true, noScroll: true, keepFocus: true });
  }

  onMount(() => {
    const q = new URLSearchParams(location.search);
    const u = Number(q.get('user'));
    if (u) who = u;
    if (q.get('view') === 'board') view = 'board';
    loadList().then(() => { if (isAdmin) loadBoard(); else if (view === 'board') { view = 'list'; syncUrl(); } });
    const stopRoster = watchRoster(60);
    /* Keep it fresh while someone leaves it open on a desk. */
    const t = setInterval(() => {
      if (document.hidden) return;
      loadList();
      if (isAdmin) loadBoard();
    }, 60000);
    return () => { clearInterval(t); stopRoster(); };
  });

  function pickView(v) {
    view = v;
    syncUrl();
    if (v === 'board') loadBoard();
  }

  function openPerson(id) {
    who = id === viewer ? null : id;
    view = 'list';
    showEarlier = false;
    syncUrl();
    data = data && { ...data, tasks: [] };
    loadList();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function switchPerson(e) { openPerson(Number(e.target.value)); }

  /* ——— keeping the list and the board in step with what a row did ——— */
  function onchange(row) {
    const shown = data?.user?.id;
    if (data) {
      const i = data.tasks.findIndex((t) => t.id === row.id);
      const was = i >= 0 && data.tasks[i].status === 'done';
      const is = row.user_id === shown && row.status === 'done';
      if (data.counts && was !== is) data.counts.done = Math.max(0, (data.counts.done || 0) + (is ? 1 : -1));
      if (row.user_id !== shown) { if (i >= 0) data.tasks.splice(i, 1); }
      else if (i >= 0) data.tasks[i] = row;
      else data.tasks.unshift(row);
    }
    if (board.length) {
      for (const u of board) {
        const list = u.tasks || (u.tasks = []);
        const i = list.findIndex((t) => t.id === row.id);
        if (u.id === row.user_id) { if (i >= 0) list[i] = row; else list.unshift(row); }
        else if (i >= 0) list.splice(i, 1);
      }
    }
  }

  function onremove(id) {
    if (data) {
      if (data.counts && data.tasks.some((t) => t.id === id && t.status === 'done')) data.counts.done -= 1;
      data.tasks = data.tasks.filter((t) => t.id !== id);
    }
    for (const u of board) if (u.tasks) u.tasks = u.tasks.filter((t) => t.id !== id);
    toast('Deleted');
  }

  function loadEarlier() {
    showEarlier = true;
    if (doneLimit < 300 && (data?.counts?.done || 0) > doneLimit) { doneLimit = 300; loadList(); }
  }

  const VIEWS = [{ value: 'list', label: 'List', icon: 'list' }, { value: 'board', label: 'Team board', icon: 'users' }];
</script>

<svelte:head><title>Tasks — Oblivion</title></svelte:head>

<div class="mg-row top">
  <div class="titles">
    <h1 class="mg-h2">{title}
      {#if data && view === 'list'}<span class="mg-count">{live.length} open{#if lateN}{' · '}<b class="late">{lateN} late</b>{/if}</span>{/if}
    </h1>
    <p class="mg-hint">
      {#if view === 'board'}Everyone's work at a glance — tap a name for their full list.
      {:else if mine}Your list. Add a to-do, or log something you already did.
      {:else}You are looking at {person?.display_name}'s list — what you add lands on it, marked from you.{/if}
    </p>
  </div>
  <div class="mg-actions">
    {#if isAdmin}
      {#if view === 'list' && board.length}
        <label class="mg-select sw">
          <select value={String(person?.id ?? '')} onchange={switchPerson} aria-label="Whose tasks">
            {#each board as u (u.id)}
              {#if !u.disabled || u.id === person?.id}
                <option value={String(u.id)}>{u.id === viewer ? 'Me' : u.display_name}{u.counts.open ? ` · ${u.counts.open}` : ''}</option>
              {/if}
            {/each}
          </select>
          <span class="ic"><Icon name="chevronDown" size={14} /></span>
        </label>
      {/if}
      <Seg options={VIEWS} value={view} onchange={pickView} label="Tasks view" />
    {/if}
    <a class="mg-chip online" href="/online" title="Who is signed in and what they are on">
      <span class="mg-dot ok sm"></span>{roster.loaded ? `${roster.online} online` : 'Online'}
    </a>
  </div>
</div>

{#if failed && !data}
  <div class="mg-section"><p class="mg-hint pad">Could not load tasks — {failed}</p></div>
{:else}
  <section class="mg-section addwrap" aria-label="Add">
    <TaskAdd {isAdmin} {people} {viewer} forUser={view === 'list' ? person?.id ?? null : viewer} oncreated={onchange} />
  </section>

  {#if view === 'board' && isAdmin}
    {#if board.length}
      <TeamBoard users={board} {viewer} {people} onopen={openPerson} {onchange} {onremove} />
    {:else}
      <div class="mg-section"><p class="mg-hint pad">Loading the board…</p></div>
    {/if}
  {:else}
    <div class="cols">
      <section class="mg-section todo" aria-label="To do">
        <div class="head">
          <h2>To do</h2><span class="mg-count">{live.length || ''}</span>
        </div>
        {#if !data}
          <div class="skel">{#each Array(3) as _, i (i)}<Skeleton h="14px" w="{70 - i * 12}%" delay={i * 60} />{/each}</div>
        {:else if !live.length}
          <div class="mg-empty quiet">
            <span class="ic"><Icon name="check" size={20} /></span>
            <h3>Nothing to do</h3>
            <p>{done.thisWeek.length ? `${done.thisWeek.length} done this week — good going.` : 'Add the next thing above.'}</p>
          </div>
        {:else}
          <ul class="lst">
            {#each live as t (t.id)}
              <TaskRow task={t} {viewer} {isAdmin} {people} {onchange} {onremove} />
            {/each}
          </ul>
        {/if}
      </section>

      <section class="mg-section donesec" aria-label="Done">
        <div class="head">
          <h2>Done</h2><span class="mg-count">{data?.counts?.done || ''}</span>
        </div>
        <h3 class="sub">This week <span class="mg-count">{done.thisWeek.length || ''}</span></h3>
        {#if done.thisWeek.length}
          <ul class="lst">
            {#each done.thisWeek as t (t.id)}
              <TaskRow task={t} {viewer} {isAdmin} {people} {onchange} {onremove} />
            {/each}
          </ul>
        {:else}
          <p class="none">{mine ? 'Nothing ticked off yet this week. Did something? Log it above.' : 'Nothing ticked off yet this week.'}</p>
        {/if}
        {#if done.earlier.length}
          <button type="button" class="fold" onclick={() => (showEarlier ? (showEarlier = false) : loadEarlier())} aria-expanded={showEarlier}>
            <Icon name={showEarlier ? 'chevronDown' : 'chevronRight'} size={14} />
            Earlier <span class="mg-count">{(data?.counts?.done || 0) - done.thisWeek.length}</span>
          </button>
          {#if showEarlier}
            <ul class="lst">
              {#each done.earlier as t (t.id)}
                <TaskRow task={t} {viewer} {isAdmin} {people} {onchange} {onremove} />
              {/each}
            </ul>
          {/if}
        {/if}
      </section>
    </div>
  {/if}
{/if}

<style>
  .top { align-items: flex-start; }
  .titles { min-width: 0; display: flex; flex-direction: column; gap: 4px; max-width: 62ch; }
  .titles .mg-h2 { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
  .late { color: var(--mc-warn); font-weight: 500; }
  .sw select { height: 38px; width: 180px; font-size: 13px; }
  .online { height: 38px; padding: 0 14px; }
  .online .mg-dot { margin-right: 2px; }

  .addwrap { margin-bottom: 16px; overflow: visible; }
  .pad { padding: 16px; }

  .cols { display: flex; flex-direction: column; gap: 16px; }
  @media (min-width: 1100px) {
    .cols { display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr); align-items: start; }
  }
  .lst { margin: 0; padding: 0; }
  .skel { display: flex; flex-direction: column; gap: 14px; padding: 18px 20px; }
  .quiet { padding: 28px 20px; }
  .quiet .ic { color: var(--mc-accent); }

  .sub {
    margin: 0; padding: 12px 16px 4px; display: flex; gap: 6px; align-items: baseline;
    font: 600 11px/1.3 var(--mc-font); letter-spacing: 0.04em; text-transform: uppercase; color: var(--mc-ink3);
  }
  .sub .mg-count { font-size: 11px; }
  .none { margin: 0; padding: 6px 16px 14px; font: 400 12.5px/1.45 var(--mc-font); color: var(--mc-ink3); }
  .fold {
    display: flex; align-items: center; gap: 6px; width: 100%;
    min-height: 44px; padding: 0 14px; border: 0; border-top: 1px solid var(--mc-line); background: none; cursor: pointer;
    color: var(--mc-ink2); font: 500 12.5px/1 var(--mc-font); text-align: left;
  }
  .fold:hover { color: var(--mc-ink); background: rgba(255, 255, 255, 0.03); }

  @media (max-width: 559.98px) {
    .top > .mg-actions { margin-left: 0; width: 100%; }
    .sw { flex: 1; }
    .sw select { width: 100%; }
  }
</style>
