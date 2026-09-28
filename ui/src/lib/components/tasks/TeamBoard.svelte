<script>
  /* The Team board (admins): a column per person — what they are on, what
     is open, and what they finished this week — so "who is doing what" is
     one glance. Tick from here to finish anyone's task; tap a title or a
     name to open that person's full list.

     Columns wrap into rows on a wide screen; on a phone they sit side by
     side and scroll sideways (snapping). A disabled account with nothing on
     it is left out. The presence dot is /online's roster (the page subscribes). */
  import { boardColumns } from '$lib/tasks.js';
  import { roster } from '$lib/presence.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import TaskRow from './TaskRow.svelte';

  let { users = [], viewer = null, people = [], onopen = () => {}, onchange = () => {}, onremove = () => {} } = $props();

  const DONE_MAX = 5;
  let openDone = $state(new Set());

  const cols = $derived(users
    .filter((u) => !u.disabled || (u.tasks || []).length)
    .map((u) => ({ u, c: boardColumns(u.tasks || []) })));
  const status = (id) => roster.users.find((r) => r.id === id)?.status || 'offline';
  const initials = (n) => (n || '?').split(/[\s._-]+/).filter(Boolean).map((p) => p[0]).slice(0, 2).join('').toUpperCase();

  function toggleDone(id) {
    const s = new Set(openDone);
    s.has(id) ? s.delete(id) : s.add(id);
    openDone = s;
  }
</script>

<div class="board" data-testid="team-board">
  {#each cols as { u, c } (u.id)}
    {@const late = c.open.filter((t) => t.overdue).length + c.in_progress.filter((t) => t.overdue).length}
    <section class="mg-section col" aria-label="{u.display_name}'s tasks">
      <div class="head">
        <button type="button" class="who" onclick={() => onopen(u.id)} title="Open {u.display_name}'s list">
          <span class="av">{initials(u.display_name)}<i class="pd {status(u.id)}" title={status(u.id)}></i></span>
          <span class="nm">{u.id === viewer ? `${u.display_name} (me)` : u.display_name}</span>
        </button>
        <span class="mg-actions">
          {#if late}<span class="mg-chip warn n">{late} late</span>{/if}
          <span class="mg-count">{c.open.length + c.in_progress.length} open</span>
        </span>
      </div>

      <div class="grp">
        <h3>On it <span class="mg-count">{c.in_progress.length || ''}</span></h3>
        {#if c.in_progress.length}
          <ul class="lst">
            {#each c.in_progress as t (t.id)}
              <TaskRow task={t} {viewer} isAdmin {people} dense onopen={() => onopen(u.id)} {onchange} {onremove} />
            {/each}
          </ul>
        {:else}
          <p class="none">Nothing in progress</p>
        {/if}
      </div>

      <div class="grp">
        <h3>Open <span class="mg-count">{c.open.length || ''}</span></h3>
        {#if c.open.length}
          <ul class="lst">
            {#each c.open as t (t.id)}
              <TaskRow task={t} {viewer} isAdmin {people} dense onopen={() => onopen(u.id)} {onchange} {onremove} />
            {/each}
          </ul>
        {:else}
          <p class="none">All clear</p>
        {/if}
      </div>

      <div class="grp done">
        <h3>Done this week <span class="mg-count">{c.doneWeek.length || ''}</span></h3>
        {#if c.doneWeek.length}
          {@const all = openDone.has(u.id)}
          <ul class="lst">
            {#each all ? c.doneWeek : c.doneWeek.slice(0, DONE_MAX) as t (t.id)}
              <TaskRow task={t} {viewer} isAdmin {people} dense onopen={() => onopen(u.id)} {onchange} {onremove} />
            {/each}
          </ul>
          {#if c.doneWeek.length > DONE_MAX}
            <button type="button" class="more" onclick={() => toggleDone(u.id)}>
              {all ? 'Show less' : `+${c.doneWeek.length - DONE_MAX} more`}
            </button>
          {/if}
        {:else}
          <p class="none">Nothing yet this week</p>
        {/if}
      </div>

      <button type="button" class="foot" onclick={() => onopen(u.id)}>
        Open {u.id === viewer ? 'my' : `${u.display_name}'s`} list <Icon name="arrowRight" size={13} />
      </button>
    </section>
  {:else}
    <p class="mg-hint">No accounts yet.</p>
  {/each}
</div>

<style>
  /* Wide screens: the columns wrap into rows. Phones: one row of columns
     that scrolls sideways and snaps, the next person peeking in. */
  .board { display: grid; gap: 16px; align-items: start; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); }
  @media (max-width: 719.98px) {
    .board {
      grid-template-columns: none; grid-auto-flow: column; grid-auto-columns: 86%;
      overflow-x: auto; scroll-snap-type: x mandatory; overscroll-behavior-x: contain;
      scrollbar-width: none; padding-bottom: 4px;
    }
    .board::-webkit-scrollbar { display: none; }
  }
  .col { scroll-snap-align: start; min-width: 0; display: flex; flex-direction: column; }
  .col > .head { align-items: center; padding: 8px 12px 8px 8px; }
  .who {
    display: flex; align-items: center; gap: 10px; min-width: 0; min-height: 40px; padding: 0 6px;
    border: 0; border-radius: 10px; background: none; cursor: pointer; color: var(--mc-ink);
  }
  .who:hover { background: rgba(255, 255, 255, 0.05); }
  .av {
    position: relative; flex: none; width: 30px; height: 30px; border-radius: 50%;
    display: grid; place-items: center; background: var(--mc-glass-hover); border: 1px solid var(--mc-glass-line);
    font: 600 11px/1 var(--mc-font); color: var(--mc-ink);
  }
  .pd { position: absolute; right: -1px; bottom: -1px; width: 9px; height: 9px; border-radius: 50%; border: 2px solid #1c1c20; background: var(--mc-ink3); }
  .pd.online { background: var(--mc-ok); }
  .pd.away { background: var(--mc-warn); }
  .nm { font: 600 13.5px/1.2 var(--mc-font); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .n { height: 22px; padding: 0 8px; font-size: 11px; }

  .grp { border-top: 1px solid var(--mc-line-soft); padding-bottom: 4px; }
  .col > .head + .grp { border-top: 0; }
  h3 {
    margin: 0; padding: 10px 14px 4px; display: flex; gap: 6px; align-items: baseline;
    font: 600 11px/1.3 var(--mc-font); letter-spacing: 0.04em; text-transform: uppercase; color: var(--mc-ink3);
  }
  h3 .mg-count { font-size: 11px; }
  .lst { margin: 0; padding: 0; }
  .none { margin: 0; padding: 4px 14px 10px; font: 400 12.5px/1.4 var(--mc-font); color: var(--mc-ink3); }
  .more {
    display: block; width: 100%; height: 36px; border: 0; background: none; cursor: pointer;
    color: var(--mc-ink2); font: 500 12.5px/1 var(--mc-font);
  }
  .more:hover { color: var(--mc-ink); background: rgba(255, 255, 255, 0.03); }
  .foot {
    display: flex; align-items: center; justify-content: center; gap: 6px; height: 40px; margin-top: auto;
    border: 0; border-top: 1px solid var(--mc-line); background: none; cursor: pointer;
    color: var(--mc-ink2); font: 500 12.5px/1 var(--mc-font);
  }
  .foot:hover { color: var(--mc-accent); background: rgba(255, 255, 255, 0.03); }
</style>
