<script>
  /* One task, one row — the /tasks page, the Team board and Home's card all
     draw this.

     Left: the 44px tick (tick to finish; on a done row, tick to reopen).
     Middle: the title (tap to open the editor), then one quiet line of
     facts — "On it", the due state, "from Daniel", the linked property (a
     real link) and a note marker. Right: "Start" / "Pause" on a live row.

     The editor opens under the row: title, notes, due, priority, property,
     and for an admin the assignee. Delete lives there too. Every verb is
     optimistic — the row changes at once via `onchange(predicted)`, then
     the server's row replaces it; a failure puts the old one back.

     `dense` (the board, Home): no Start button, no editor — tapping the title
     calls `onopen` instead (the board jumps to that person's list, Home
     goes to /tasks). The server enforces who may touch what; this component
     only draws what the viewer may do. */
  import { api } from '$lib/api.js';
  import { toast } from '$lib/state.svelte.js';
  import { VERBS, predicted, propHref } from '$lib/tasks.svelte.js';
  import { dueState, dueLabel, fromLine, doneLabel, localDay } from '$lib/tasks.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import PropertyPick from '$lib/components/PropertyPick.svelte';

  let {
    task, viewer = null, isAdmin = false, people = [], dense = false,
    onchange = () => {}, onremove = () => {}, onopen = null
  } = $props();

  let pending = $state(false);
  let editing = $state(false);
  let draft = $state(null);
  let saving = $state(false);

  const today = localDay();
  const due = $derived(dueState(task, today));
  const from = $derived(fromLine(task, viewer));
  const href = $derived(propHref(task.property));
  const done = $derived(task.status === 'done');
  const PRI = { 1: 'High', 2: 'Normal', 3: 'Low' };

  async function act(verb) {
    if (pending) return;
    pending = true;
    const before = task;
    onchange(predicted(task, verb));
    try {
      onchange(await VERBS[verb].call(task.id));
      if (verb === 'complete') toast('Done — nice one');
    } catch (e) {
      onchange(before);
      toast(e.message, 'error');
    } finally {
      pending = false;
    }
  }

  function toggleEdit() {
    if (dense) { onopen?.(task); return; }
    editing = !editing;
    if (editing) {
      draft = {
        title: task.title, notes: task.notes || '', due_date: task.due_date || '',
        priority: task.priority || 2, user_id: String(task.user_id),
        property: task.property ? { ...task.property } : null
      };
    }
  }

  async function save() {
    const title = draft.title.trim();
    if (!title) { toast('A task needs a title', 'error'); return; }
    saving = true;
    const body = {
      title, notes: draft.notes, due_date: draft.due_date || '',
      property_group_id: draft.property ? draft.property.group_id : '',
      priority: Number(draft.priority)
    };
    const moving = isAdmin && Number(draft.user_id) !== task.user_id;
    if (moving) body.user_id = Number(draft.user_id);
    try {
      const row = await api.updateTask(task.id, body);
      editing = false;
      onchange(row);
      if (moving) toast(`Moved to ${row.user_name}`);
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      saving = false;
    }
  }

  async function remove() {
    if (!confirm(`Delete “${task.title}”?`)) return;
    saving = true;
    try {
      await api.deleteTask(task.id);
      editing = false;
      onremove(task.id);
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      saving = false;
    }
  }
</script>

<li class="row" class:dense class:done class:onit={task.status === 'in_progress'} class:late={due === 'overdue'}
    class:pending data-task={task.id}>
  <button type="button" class="tick" class:on={done} onclick={() => act(done ? 'reopen' : 'complete')}
          aria-label={done ? `Reopen “${task.title}”` : `Mark “${task.title}” done`} disabled={pending}>
    <span class="ring"><Icon name="check" size={13} stroke={2.5} /></span>
  </button>

  <div class="body">
    <button type="button" class="t" onclick={toggleEdit} aria-expanded={dense ? undefined : editing}
            title={dense ? 'Open' : 'Edit'}>
      {#if task.new}<span class="new" title="New — assigned to you">New</span>{/if}
      {#if task.priority === 1 && !done}<span class="pri" title="High priority">!</span>{/if}
      {task.title}
    </button>
    <span class="meta">
      {#if done}
        <span class="k">{task.created_at && task.created_at === task.done_at ? 'Logged' : 'Done'} {doneLabel(task.done_at)}</span>
      {:else if task.status === 'in_progress'}
        <span class="k on"><i class="dot"></i>On it</span>
      {/if}
      {#if due}<span class="k" class:warn={due === 'overdue'} class:today={due === 'today'}>{dueLabel(task, today)}</span>{/if}
      {#if from}<span class="k from">{from}</span>{/if}
      {#if task.property}
        {#if href}
          <a class="k prop" {href} title={task.property.suburb || ''}><Icon name="property" size={11} />{task.property.label}</a>
        {:else}
          <span class="k prop"><Icon name="property" size={11} />{task.property.label}</span>
        {/if}
      {/if}
      {#if task.notes && (dense || editing)}<span class="k" title={task.notes}><Icon name="text" size={11} /></span>{/if}
    </span>
    {#if task.notes && !dense && !editing}<span class="notes">{task.notes}</span>{/if}
  </div>

  {#if !dense && !done}
    {#if task.status === 'open'}
      <button type="button" class="mg-btn sm ghost act" onclick={() => act('start')} disabled={pending}
              title="I'm on it — shows on the Online page">Start</button>
    {:else}
      <button type="button" class="mg-btn sm act busy" onclick={() => act('reopen')} disabled={pending}
              title="Put it back to open"><Icon name="bolt" size={13} />On it</button>
    {/if}
  {/if}
</li>

{#if editing && draft}
  <li class="editor">
    <label class="f wide"><span class="mg-label">Title</span>
      <input class="mg-input" type="text" bind:value={draft.title} maxlength="200" /></label>
    <label class="f wide"><span class="mg-label">Notes</span>
      <textarea class="mg-input ta" bind:value={draft.notes} rows="2" placeholder="Anything the next person should know"></textarea></label>
    <label class="f"><span class="mg-label">Due</span>
      <input class="mg-input" type="date" bind:value={draft.due_date} /></label>
    <label class="f"><span class="mg-label">Priority</span>
      <span class="mg-select"><select bind:value={draft.priority}>
        {#each [1, 2, 3] as p (p)}<option value={p}>{PRI[p]}</option>{/each}
      </select><span class="ic"><Icon name="chevronDown" size={14} /></span></span></label>
    <div class="f wide"><span class="mg-label">Property</span><PropertyPick bind:value={draft.property} /></div>
    {#if isAdmin && people.length}
      <label class="f"><span class="mg-label">Assigned to</span>
        <span class="mg-select"><select bind:value={draft.user_id}>
          {#each people as u (u.id)}<option value={String(u.id)}>{u.display_name}</option>{/each}
        </select><span class="ic"><Icon name="chevronDown" size={14} /></span></span></label>
    {/if}
    {#if task.created_by_name}
      <p class="f who mg-hint">Added by {task.created_by === viewer ? 'you' : task.created_by_name}</p>
    {/if}
    <div class="acts">
      <button type="button" class="mg-btn sm danger" onclick={remove} disabled={saving}><Icon name="trash" size={13} />Delete</button>
      <span class="sp"></span>
      <button type="button" class="mg-btn sm ghost" onclick={() => (editing = false)} disabled={saving}>Cancel</button>
      <button type="button" class="mg-btn sm primary" onclick={save} disabled={saving}>Save</button>
    </div>
  </li>
{/if}

<style>
  .row {
    display: flex; align-items: flex-start; gap: 2px; min-height: 52px;
    padding: 4px 10px 4px 4px; list-style: none;
    border-top: 1px solid var(--mc-line-soft);
    transition: background var(--mc-t-fast), opacity var(--mc-t-fast);
  }
  .row:first-child { border-top: 0; }
  .row:hover { background: rgba(255, 255, 255, 0.03); }
  .row.pending { opacity: 0.55; }
  .row.onit { background: rgba(62, 207, 142, 0.05); }

  .tick {
    flex: none; width: 44px; height: 44px; border: 0; padding: 0; background: none;
    display: grid; place-items: center; cursor: pointer; color: transparent;
  }
  .ring {
    width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center;
    border: 1.5px solid var(--mc-line3);
    transition: border-color var(--mc-t-fast), background var(--mc-t-fast), color var(--mc-t-fast);
  }
  .row.onit .ring { border-color: var(--mc-accent); }
  .row.late .ring { border-color: var(--mc-warn); }
  .tick:hover .ring { border-color: var(--mc-accent); color: var(--mc-accent); }
  .tick.on .ring { background: var(--mc-accent); border-color: var(--mc-accent); color: var(--mc-accent-ink); }
  .tick.on:hover .ring { background: none; color: var(--mc-accent); }
  .tick:disabled { cursor: default; }

  .body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; padding: 11px 4px 9px; }
  .t {
    display: block; width: 100%; padding: 0; border: 0; background: none; text-align: left; cursor: pointer;
    font: 500 13.5px/1.35 var(--mc-font); letter-spacing: -0.005em; color: var(--mc-ink); overflow-wrap: anywhere;
  }
  .t:hover { color: var(--mc-accent); }
  .row.done .t { color: var(--mc-ink3); text-decoration: line-through; text-decoration-color: rgba(255, 255, 255, 0.25); }
  .row.done .t:hover { color: var(--mc-ink2); }
  .pri { margin-right: 4px; color: var(--mc-crit); font-weight: 700; }
  .new {
    display: inline-block; margin-right: 6px; padding: 2px 6px; border-radius: 9999px; vertical-align: 1px;
    background: var(--mc-warn-soft); border: 1px solid var(--mc-warn-line); color: var(--mc-warn);
    font: 600 10px/1.2 var(--mc-font); letter-spacing: 0.02em; text-transform: uppercase;
  }

  .meta { display: flex; flex-wrap: wrap; gap: 3px 10px; font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); min-width: 0; }
  .k { display: inline-flex; align-items: center; gap: 4px; min-width: 0; }
  .k.warn { color: var(--mc-warn); font-weight: 500; }
  .k.today { color: var(--mc-ink); font-weight: 500; }
  .k.on { color: var(--mc-accent); font-weight: 500; }
  .k.on .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
  .k.from { color: var(--mc-mgr); }
  a.k.prop { color: var(--mc-ink2); max-width: 100%; }
  a.k.prop:hover { color: var(--mc-accent); }
  .notes {
    font: 400 12.5px/1.45 var(--mc-font); color: var(--mc-ink2); white-space: pre-line;
    display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  }

  .act { height: 32px; margin-top: 10px; }
  .act.busy { background: var(--mc-ok-soft); border-color: var(--mc-ok-line); color: var(--mc-accent); }

  .dense { min-height: 44px; padding-right: 8px; }
  .dense .tick { width: 40px; height: 40px; }
  .dense .body { padding: 9px 2px 7px; }
  .dense .t { font-size: 13px; }

  .editor {
    list-style: none; display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
    padding: 12px; margin: 2px 10px 10px; border-radius: var(--mc-r-md);
    background: var(--mc-raised); border: 1px solid var(--mc-line);
  }
  .f { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
  .f.wide { grid-column: 1 / -1; }
  .f .mg-select { width: 100%; }
  .who { margin: 0; align-self: end; padding-bottom: 10px; }
  .mg-input.ta { min-height: 64px; resize: vertical; }
  input[type='date'].mg-input { color-scheme: dark; }
  .acts { grid-column: 1 / -1; display: flex; gap: 8px; align-items: center; }
  .sp { flex: 1; }
  @media (max-width: 480px) { .editor { grid-template-columns: 1fr; } }
</style>
