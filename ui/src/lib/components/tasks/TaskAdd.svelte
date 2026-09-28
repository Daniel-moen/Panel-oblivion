<script>
  /* The quick-add bar: one line to add a task, or — flipped to "Log done" —
     to record something already finished in one step (team.py creates it
     with status "done", so it lands straight in the Done history).

     Row one: the mode switch, the title, the add button. Row two, the
     details: due date and priority (to-dos only), a property link (the
     /api/team/properties picker), a note (logged items), and for an admin
     "For" — anyone's list. Row two is always shown from 720px; on a phone
     it folds behind the "…" button so the bar stays one line.

     `compact` (Home's card): just the title and the add button, and what
     it adds is due today — the card lists today's work, so that is where
     the new line shows up. */
  import { untrack } from 'svelte';
  import { api } from '$lib/api.js';
  import { toast } from '$lib/state.svelte.js';
  import { localDay } from '$lib/tasks.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import PropertyPick from '$lib/components/PropertyPick.svelte';

  let {
    isAdmin = false, people = [], viewer = null, forUser = null,
    compact = false, oncreated = () => {}
  } = $props();

  let mode = $state('todo');                 // 'todo' | 'done'
  let more = $state(false);
  let saving = $state(false);
  const blank = () => ({ title: '', due_date: '', priority: 2, property: null, notes: '', user_id: '' });
  let draft = $state(blank());

  /* The assignee follows whose list is on screen; a pick holds until the
     list on screen changes. */
  $effect(() => {
    const want = forUser != null ? String(forUser) : viewer != null ? String(viewer) : '';
    untrack(() => { draft.user_id = want; });
  });

  const logging = $derived(mode === 'done');
  const target = $derived(people.find((u) => String(u.id) === draft.user_id));
  const forOther = $derived(isAdmin && draft.user_id && viewer != null && Number(draft.user_id) !== viewer);
  const placeholder = $derived(
    compact ? 'Add something for today…' : logging ? (forOther ? `What did ${target?.display_name || 'they'} get done?` : 'What did you get done?')
      : forOther ? `A task for ${target?.display_name || 'them'}…` : 'Add a task…'
  );

  async function submit(e) {
    e?.preventDefault();
    const title = draft.title.trim();
    if (!title || saving) return;
    saving = true;
    const body = { title };
    if (logging) {
      body.status = 'done';
      if (draft.notes.trim()) body.notes = draft.notes.trim();
    } else {
      body.priority = Number(draft.priority);
      if (draft.due_date) body.due_date = draft.due_date;
      else if (compact) body.due_date = localDay();   // Home's card is about today
    }
    if (draft.property) body.property_group_id = draft.property.group_id;
    if (isAdmin && draft.user_id) body.user_id = Number(draft.user_id);
    try {
      const row = await api.createTask(body);
      oncreated(row);
      if (row.user_id !== viewer && row.user_name) toast(logging ? `Logged for ${row.user_name}` : `Assigned to ${row.user_name}`);
      else if (logging) toast('Logged — nice work');
      const keep = draft.user_id;
      draft = { ...blank(), user_id: keep };
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      saving = false;
    }
  }

  const setToday = () => (draft.due_date = draft.due_date === localDay() ? '' : localDay());
</script>

<form class="add" class:compact class:logging onsubmit={submit}>
  <div class="line">
    {#if !compact}
      <div class="mode" role="group" aria-label="Add a to-do or log something done">
        <button type="button" class:on={!logging} aria-pressed={!logging} onclick={() => (mode = 'todo')}>To do</button>
        <button type="button" class:on={logging} aria-pressed={logging} onclick={() => (mode = 'done')}>Log done</button>
      </div>
    {/if}
    <input class="mg-input title" type="text" {placeholder} bind:value={draft.title} maxlength="200"
           aria-label={logging ? 'What you did' : 'New task'} enterkeyhint="done" />
    {#if !compact}
      <button type="button" class="mg-btn secondary icon moreb" class:on={more} onclick={() => (more = !more)}
              aria-label="Details" aria-expanded={more} title="Due date, property, assignee">
        <Icon name="sliders" size={16} />
      </button>
    {/if}
    <button type="submit" class="mg-btn accent go" class:icon={compact} disabled={!draft.title.trim() || saving}
            aria-label={logging ? 'Log it' : 'Add task'}>
      <Icon name={logging ? 'check' : 'plus'} size={16} stroke={2.25} />
      {#if !compact}<span class="gol">{logging ? 'Log it' : 'Add'}</span>{/if}
    </button>
  </div>

  {#if !compact}
    <div class="details" class:open={more}>
      {#if !logging}
        <div class="f due">
          <span class="mg-label">Due</span>
          <span class="dueline">
            <input class="mg-input" type="date" bind:value={draft.due_date} aria-label="Due date" />
            <button type="button" class="mg-chip" class:on={draft.due_date === localDay()} onclick={setToday}>Today</button>
          </span>
        </div>
        <label class="f pri"><span class="mg-label">Priority</span>
          <span class="mg-select"><select bind:value={draft.priority} aria-label="Priority">
            <option value={1}>High</option><option value={2}>Normal</option><option value={3}>Low</option>
          </select><span class="ic"><Icon name="chevronDown" size={14} /></span></span></label>
      {:else}
        <label class="f note"><span class="mg-label">Note <i>optional</i></span>
          <input class="mg-input" type="text" bind:value={draft.notes} maxlength="2000" placeholder="How it went, what's next" /></label>
      {/if}
      <div class="f prop"><span class="mg-label">Property <i>optional</i></span><PropertyPick bind:value={draft.property} /></div>
      {#if isAdmin && people.length}
        <label class="f who"><span class="mg-label">For</span>
          <span class="mg-select"><select bind:value={draft.user_id} aria-label="Assign to">
            {#each people as u (u.id)}
              {#if !u.disabled || String(u.id) === draft.user_id}
                <option value={String(u.id)}>{u.id === viewer ? `Me (${u.display_name})` : u.display_name}</option>
              {/if}
            {/each}
          </select><span class="ic"><Icon name="chevronDown" size={14} /></span></span></label>
      {/if}
    </div>
  {/if}
</form>

<style>
  .add { display: flex; flex-direction: column; gap: 10px; padding: 12px; }
  .line { display: flex; gap: 8px; align-items: center; min-width: 0; }
  .title { flex: 1; min-width: 0; }
  .go { padding: 0 16px; }
  .go.icon { padding: 0; }
  .add.logging .title { border-color: var(--mc-ok-line); }

  /* The mode switch: a two-way segmented pill, the Seg look without the glide. */
  .mode {
    flex: none; display: inline-flex; padding: 3px; gap: 2px; border-radius: 9999px;
    background: var(--mc-glass-soft); border: 1px solid var(--mc-glass-line);
  }
  .mode button {
    height: 32px; padding: 0 12px; border: 0; border-radius: 9999px; background: none; cursor: pointer;
    color: var(--mc-ink2); font: 500 12.5px/1 var(--mc-font); white-space: nowrap;
    transition: background var(--mc-t-fast), color var(--mc-t-fast);
  }
  .mode button:hover { color: var(--mc-ink); }
  .mode button.on { background: var(--mc-glass-on); color: var(--mc-ink); }

  .details { display: none; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .details.open { display: grid; }
  .f { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
  .f .mg-select { width: 100%; }
  .mg-label i { font-style: normal; color: var(--mc-ink3); font-weight: 400; text-transform: none; letter-spacing: 0; }
  .prop, .note { grid-column: 1 / -1; }
  .dueline { display: flex; gap: 6px; align-items: center; }
  .dueline .mg-input { flex: 1; min-width: 0; }
  .dueline .mg-chip { height: 40px; }
  input[type='date'].mg-input { color-scheme: dark; }

  /* Phones: the mode switch gets its own line above the title. */
  @media (max-width: 559.98px) {
    .line { flex-wrap: wrap; }
    .mode { order: -1; width: 100%; }
    .mode button { flex: 1; }
    .gol { display: none; }
    .go:not(.icon) { width: 40px; padding: 0; }
  }
  /* From 720px the details are always there, one row. */
  @media (min-width: 720px) {
    .moreb { display: none; }
    .details, .details.open { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.8fr) minmax(0, 1.6fr) minmax(0, 1fr); }
    .prop, .note { grid-column: auto; }
    .logging .details { grid-template-columns: minmax(0, 1.6fr) minmax(0, 1.6fr) minmax(0, 1fr); }
  }
  .compact { padding: 10px 12px; }
</style>
