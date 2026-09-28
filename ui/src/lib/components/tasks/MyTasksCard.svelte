<script>
  /* Home's "My tasks" card: what needs doing now — overdue, due today, on
     it, and anything new from somebody else — with a one-line quick-add and
     a tick to finish. Everything else is one tap away on /tasks.

     Its own small fetch of /api/team/tasks (Home's /api/home stays one
     round trip for everything else), refreshed when the tab comes back. */
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api.js';
  import { focusTasks, localDay } from '$lib/tasks.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import TaskRow from './TaskRow.svelte';
  import TaskAdd from './TaskAdd.svelte';

  const MAX = 5;
  let data = $state(null);
  let failed = $state(false);

  const tasks = $derived(data?.tasks || []);
  const focus = $derived(focusTasks(tasks, localDay()));
  const liveN = $derived(tasks.filter((t) => t.status !== 'done').length);
  const rest = $derived(liveN - Math.min(focus.length, MAX));
  const lateN = $derived(focus.filter((t) => t.overdue).length);

  async function load() {
    try { data = await api.myTasks(null, 1); failed = false; } catch { failed = true; }
  }

  onMount(() => {
    load();
    const onVis = () => { if (!document.hidden) load(); };
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  });

  function onchange(row) {
    if (!data) return;
    const i = data.tasks.findIndex((t) => t.id === row.id);
    if (row.user_id !== data.me) { if (i >= 0) data.tasks.splice(i, 1); return; }
    if (i >= 0) data.tasks[i] = row; else data.tasks.unshift(row);
  }
  function onremove(id) { if (data) data.tasks = data.tasks.filter((t) => t.id !== id); }
</script>

<section class="mg-section mytasks" aria-label="My tasks" data-testid="home-tasks">
  <div class="head">
    <h2>My tasks</h2>
    <span class="mg-count">{liveN || ''}</span>
    {#if lateN}<span class="mg-chip warn n">{lateN} late</span>{/if}
    <div class="mg-actions">
      <a class="mg-btn sm ghost" href="/tasks">All tasks <Icon name="arrowRight" size={13} /></a>
    </div>
  </div>

  <TaskAdd compact viewer={data?.me ?? null} oncreated={onchange} />

  {#if !data && !failed}
    <div class="skel">{#each Array(2) as _, i (i)}<Skeleton h="14px" w="{60 - i * 15}%" delay={i * 60} />{/each}</div>
  {:else if failed && !data}
    <p class="none">Tasks are not answering right now.</p>
  {:else if !focus.length}
    <p class="none">
      <Icon name="check" size={14} />
      {liveN ? `Nothing due today — ${liveN} open on your list.` : 'Nothing on your list. Add the next thing above.'}
    </p>
  {:else}
    <ul class="lst">
      {#each focus.slice(0, MAX) as t (t.id)}
        <TaskRow task={t} viewer={data.me} dense onopen={() => goto('/tasks')} {onchange} {onremove} />
      {/each}
    </ul>
  {/if}
  {#if data && rest > 0 && focus.length}
    <a class="more" href="/tasks">+{rest} more on your list</a>
  {/if}
</section>

<style>
  .mytasks > .head { align-items: center; }
  .n { height: 22px; padding: 0 8px; font-size: 11px; }
  .mytasks :global(.add) { border-bottom: 1px solid var(--mc-line-soft); }
  .lst { margin: 0; padding: 0; }
  .skel { display: flex; flex-direction: column; gap: 12px; padding: 16px 20px; }
  .none {
    margin: 0; padding: 14px 16px; display: flex; gap: 8px; align-items: center;
    font: 400 13px/1.45 var(--mc-font); color: var(--mc-ink3);
  }
  .none :global(svg) { color: var(--mc-accent); flex: none; }
  .more {
    display: flex; align-items: center; justify-content: center; height: 40px;
    border-top: 1px solid var(--mc-line); color: var(--mc-ink2); font: 500 12.5px/1 var(--mc-font);
  }
  .more:hover { color: var(--mc-ink); background: rgba(255, 255, 255, 0.03); }
</style>
