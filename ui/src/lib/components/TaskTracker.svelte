<script>
  /* My tasks — one person's to-do list, on the home page.

     Everyone sees their own list; an admin (the owner, or anyone holding
     `admin`) also gets a switcher to look at anybody's and an "Assign to…"
     when adding. All of that is a courtesy: team.py refuses a member who
     forges a user id, so nothing here is a control.

     The verbs are deliberately few. Tick the circle to finish. "I'm on it"
     marks a task in progress — which is what the /online page shows as
     "busy with". Tap the title to edit everything else (notes, due date,
     property link, priority, assignee). Done tasks fold away under one line.

     Every status change is optimistic: the row moves at once, the server's
     answer replaces it, a failure puts it back and says why. Touch targets
     are 44px on every control, which is why the tick is a button of its own
     and not a checkbox. */
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { toast } from '$lib/state.svelte.js';
  import { me } from '$lib/me.svelte.js';
  import { ago } from '$lib/panel.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import PropertyPick from '$lib/components/PropertyPick.svelte';

  let { compact = false } = $props();

  let data = $state(null);          // the /api/team/tasks payload
  let board = $state([]);           // admins: every account, for the switcher
  let viewUser = $state('me');      // 'me' or a user id (admins)
  let loading = $state(true);
  let more = $state(false);         // the add row's extra fields
  let showDone = $state(false);
  let editing = $state(null);       // task id open in the inline editor
  let editDraft = $state(null);
  let saving = $state(false);
  let busy = $state(new Set());     // task ids with a request in flight

  const blank = () => ({ title: '', due_date: '', property: null, user_id: 'me', priority: 2 });
  let draft = $state(blank());

  const isAdmin = $derived(!!data?.is_admin || (data == null && me.loaded && me.privileges.includes('admin')));
  const tasks = $derived(data?.tasks || []);
  const live = $derived(tasks.filter((t) => t.status !== 'done'));
  const done = $derived(tasks.filter((t) => t.status === 'done'));
  const counts = $derived(data?.counts || { open: 0, in_progress: 0, overdue: 0, done: 0 });
  const mine = $derived(!data || data.user?.id === data.me);
  const whose = $derived(mine ? 'My tasks' : `${data.user.display_name}'s tasks`);

  async function load(user = viewUser) {
    try {
      data = await api.myTasks(user === 'me' ? null : user);
      if (data.is_admin && !board.length) loadBoard();
    } catch (e) {
      if (e.status === 403 && user !== 'me') { viewUser = 'me'; return load('me'); }
      toast(e.message, 'error');
    } finally {
      loading = false;
    }
  }

  async function loadBoard() {
    try { board = (await api.taskBoard()).users; } catch { /* not an admin after all */ }
  }

  onMount(() => { load(); });

  function switchUser(e) {
    viewUser = e.target.value;
    draft.user_id = viewUser;
    editing = null;
    load(viewUser);
  }

  /* ——— optimistic status changes ——— */
  function patchLocal(id, fields) {
    if (!data) return null;
    const i = data.tasks.findIndex((t) => t.id === id);
    if (i < 0) return null;
    const before = { ...data.tasks[i] };
    data.tasks[i] = { ...data.tasks[i], ...fields };
    recount();
    return before;
  }

  function recount() {
    if (!data) return;
    const lv = data.tasks.filter((t) => t.status !== 'done');
    data.counts = {
      open: lv.length,
      in_progress: lv.filter((t) => t.status === 'in_progress').length,
      overdue: lv.filter((t) => t.overdue).length,
      done: data.tasks.length - lv.length
    };
  }

  function replace(row) {
    if (!data) return;
    const i = data.tasks.findIndex((t) => t.id === row.id);
    if (i >= 0) data.tasks[i] = row; else data.tasks.unshift(row);
    recount();
    refreshBoard();
  }

  function refreshBoard() { if (isAdmin && board.length) loadBoard(); }

  async function transition(t, verb) {
    if (busy.has(t.id)) return;
    busy.add(t.id); busy = new Set(busy);
    const want = { start: 'in_progress', complete: 'done', reopen: 'open' }[verb];
    const before = patchLocal(t.id, {
      status: want, done_at: want === 'done' ? new Date().toISOString() : null,
      overdue: want !== 'done' && t.due_date && t.due_date < today()
    });
    try {
      const fn = { start: api.startTask, complete: api.completeTask, reopen: api.reopenTask }[verb];
      replace(await fn(t.id));
      if (verb === 'complete') toast('Done — nice one');
    } catch (e) {
      if (before) patchLocal(t.id, before);
      toast(e.message, 'error');
    } finally {
      busy.delete(t.id); busy = new Set(busy);
    }
  }

  const today = () => new Date().toISOString().slice(0, 10);

  /* ——— add ——— */
  async function add(e) {
    e?.preventDefault();
    const title = draft.title.trim();
    if (!title || saving) return;
    saving = true;
    const body = { title, priority: draft.priority };
    if (draft.due_date) body.due_date = draft.due_date;
    if (draft.property) body.property_group_id = draft.property.group_id;
    const target = isAdmin && draft.user_id !== 'me' ? Number(draft.user_id) : null;
    if (target) body.user_id = target;
    try {
      const row = await api.createTask(body);
      const shownUser = viewUser === 'me' ? data?.me : Number(viewUser);
      if (row.user_id === shownUser) replace(row);
      else toast(`Assigned to ${row.user_name}`);
      draft = { ...blank(), user_id: draft.user_id };
      more = false;
      refreshBoard();
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      saving = false;
    }
  }

  /* ——— edit ——— */
  function openEdit(t) {
    if (editing === t.id) { editing = null; return; }
    editing = t.id;
    editDraft = {
      title: t.title, notes: t.notes || '', due_date: t.due_date || '',
      property: t.property ? { group_id: t.property.group_id, label: t.property.label, suburb: t.property.suburb } : null,
      priority: t.priority, user_id: String(t.user_id)
    };
  }

  async function saveEdit(t) {
    if (saving) return;
    const title = editDraft.title.trim();
    if (!title) { toast('A task needs a title', 'error'); return; }
    saving = true;
    const body = {
      title, notes: editDraft.notes, due_date: editDraft.due_date || '',
      property_group_id: editDraft.property ? editDraft.property.group_id : '',
      priority: Number(editDraft.priority)
    };
    if (isAdmin && Number(editDraft.user_id) !== t.user_id) body.user_id = Number(editDraft.user_id);
    try {
      const row = await api.updateTask(t.id, body);
      if (body.user_id && row.user_id !== t.user_id) {
        data.tasks = data.tasks.filter((x) => x.id !== t.id);
        recount();
        refreshBoard();
        toast(`Moved to ${row.user_name}`);
      } else {
        replace(row);
      }
      editing = null;
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      saving = false;
    }
  }

  async function remove(t) {
    if (saving) return;
    saving = true;
    const keep = data.tasks;
    data.tasks = data.tasks.filter((x) => x.id !== t.id);
    recount();
    editing = null;
    try {
      await api.deleteTask(t.id);
      refreshBoard();
    } catch (e) {
      data.tasks = keep; recount();
      toast(e.message, 'error');
    } finally {
      saving = false;
    }
  }

  const dueWord = (t) => (t.due_date ? `due ${ago(t.due_date)}` : '');
  const where = (p) => (p?.group_id ? '/leads/properties/' + p.group_id : null);
  const PRI = { 1: 'High', 2: 'Normal', 3: 'Low' };
</script>

<section class="mg-section tt" class:compact aria-label={whose}>
  <div class="head">
    <h2>{whose}</h2>
    <span class="mg-count">{counts.open || ''}</span>
    <span class="badges" aria-label="{counts.open} open, {counts.overdue} overdue">
      {#if counts.in_progress}<span class="mg-chip on badge">{counts.in_progress} on it</span>{/if}
      {#if counts.overdue}<span class="mg-chip warn badge">{counts.overdue} overdue</span>{/if}
    </span>
    {#if isAdmin && board.length}
      <div class="mg-actions">
        <label class="mg-select sw">
          <span class="sr">Whose tasks</span>
          <select value={viewUser} onchange={switchUser} aria-label="Whose tasks">
            <option value="me">Mine</option>
            {#each board as u (u.id)}
              {#if u.id !== data?.me}
                <option value={String(u.id)}>{u.display_name}{u.counts.open ? ` · ${u.counts.open}` : ''}{u.counts.overdue ? ` (${u.counts.overdue} late)` : ''}</option>
              {/if}
            {/each}
          </select>
          <span class="ic"><Icon name="chevronDown" size={14} /></span>
        </label>
      </div>
    {/if}
  </div>

  <form class="add" onsubmit={add}>
    <input class="mg-input" type="text" placeholder={mine ? 'Add a task…' : `Add a task for ${data?.user?.display_name}…`}
           bind:value={draft.title} maxlength="200" aria-label="New task" enterkeyhint="done" />
    <button type="button" class="mg-btn secondary icon" class:on={more} onclick={() => (more = !more)}
            aria-label="More options" aria-expanded={more} title="Due date, property, assignee">
      <Icon name="more" size={16} />
    </button>
    <button type="submit" class="mg-btn accent icon" disabled={!draft.title.trim() || saving} aria-label="Add task">
      <Icon name="plus" size={17} stroke={2} />
    </button>
  </form>
  {#if more}
    <div class="extra">
      <label class="f">
        <span class="mg-label">Due</span>
        <input class="mg-input" type="date" bind:value={draft.due_date} min={today()} />
      </label>
      <div class="f wide">
        <span class="mg-label">Property</span>
        <PropertyPick bind:value={draft.property} />
      </div>
      {#if isAdmin && board.length}
        <label class="f">
          <span class="mg-label">Assign to</span>
          <span class="mg-select sel">
            <select bind:value={draft.user_id} aria-label="Assign to">
              <option value="me">Me</option>
              {#each board as u (u.id)}
                {#if u.id !== data?.me && !u.disabled}<option value={String(u.id)}>{u.display_name}</option>{/if}
              {/each}
            </select>
            <span class="ic"><Icon name="chevronDown" size={14} /></span>
          </span>
        </label>
      {/if}
    </div>
  {/if}

  {#if loading}
    <p class="mg-hint pad">Loading…</p>
  {:else if !live.length}
    <p class="mg-hint pad">{done.length ? 'All done. Add the next thing above.' : 'Nothing on the list yet.'}</p>
  {:else}
    <ul class="mg-list list">
      {#each live as t (t.id)}
        <li class="row" class:onit={t.status === 'in_progress'} class:late={t.overdue} class:pending={busy.has(t.id)}>
          <button type="button" class="tick" onclick={() => transition(t, 'complete')}
                  aria-label="Mark “{t.title}” done" disabled={busy.has(t.id)}>
            <span class="ring"><Icon name="check" size={13} stroke={2.5} /></span>
          </button>
          <button type="button" class="body" onclick={() => openEdit(t)} aria-expanded={editing === t.id}>
            <span class="t">
              {#if t.priority === 1}<span class="pri" title="High priority">!</span>{/if}
              {t.title}
            </span>
            <span class="meta">
              {#if t.status === 'in_progress'}<span class="k on">On it</span>{/if}
              {#if t.due_date}<span class="k" class:warn={t.overdue}>{dueWord(t)}</span>{/if}
              {#if t.property}<span class="k prop"><Icon name="property" size={11} />{t.property.label}</span>{/if}
              {#if t.created_by && t.created_by !== t.user_id && t.created_by_name}<span class="k">from {t.created_by_name}</span>{/if}
              {#if t.notes}<span class="k"><Icon name="text" size={11} /></span>{/if}
            </span>
          </button>
          {#if t.status === 'open'}
            <button type="button" class="mg-btn sm ghost act" onclick={() => transition(t, 'start')} disabled={busy.has(t.id)}>I'm on it</button>
          {:else}
            <button type="button" class="mg-btn sm act busy" onclick={() => transition(t, 'reopen')} disabled={busy.has(t.id)}
                    title="Put it back to open">
              <Icon name="bolt" size={13} />Busy
            </button>
          {/if}
        </li>
        {#if editing === t.id && editDraft}
          <li class="editor">
            <label class="f wide"><span class="mg-label">Title</span>
              <input class="mg-input" type="text" bind:value={editDraft.title} maxlength="200" /></label>
            <label class="f wide"><span class="mg-label">Notes</span>
              <textarea class="mg-input ta" bind:value={editDraft.notes} rows="2" placeholder="Anything the next person should know"></textarea></label>
            <label class="f"><span class="mg-label">Due</span>
              <input class="mg-input" type="date" bind:value={editDraft.due_date} /></label>
            <label class="f"><span class="mg-label">Priority</span>
              <span class="mg-select sel"><select bind:value={editDraft.priority}>
                {#each [1, 2, 3] as p}<option value={p}>{PRI[p]}</option>{/each}
              </select><span class="ic"><Icon name="chevronDown" size={14} /></span></span></label>
            <div class="f wide"><span class="mg-label">Property</span><PropertyPick bind:value={editDraft.property} /></div>
            {#if isAdmin && board.length}
              <label class="f"><span class="mg-label">Assigned to</span>
                <span class="mg-select sel"><select bind:value={editDraft.user_id}>
                  {#each board as u (u.id)}<option value={String(u.id)}>{u.display_name}</option>{/each}
                </select><span class="ic"><Icon name="chevronDown" size={14} /></span></span></label>
            {/if}
            {#if t.property?.group_id}
              <a class="lnk" href={where(t.property)}><Icon name="external" size={13} />Open the lead</a>
            {/if}
            <div class="acts">
              <button type="button" class="mg-btn sm danger" onclick={() => remove(t)} disabled={saving}>Delete</button>
              <span class="sp"></span>
              <button type="button" class="mg-btn sm ghost" onclick={() => (editing = null)} disabled={saving}>Cancel</button>
              <button type="button" class="mg-btn sm primary" onclick={() => saveEdit(t)} disabled={saving}>Save</button>
            </div>
          </li>
        {/if}
      {/each}
    </ul>
  {/if}

  {#if done.length}
    <button type="button" class="fold" onclick={() => (showDone = !showDone)} aria-expanded={showDone}>
      <Icon name={showDone ? 'chevronDown' : 'chevronRight'} size={14} />
      Done <span class="mg-count">{counts.done}</span>
    </button>
    {#if showDone}
      <ul class="mg-list list donelist">
        {#each done as t (t.id)}
          <li class="row done">
            <button type="button" class="tick on" onclick={() => transition(t, 'reopen')} aria-label="Reopen “{t.title}”" disabled={busy.has(t.id)}>
              <span class="ring"><Icon name="check" size={13} stroke={2.5} /></span>
            </button>
            <span class="body static">
              <span class="t">{t.title}</span>
              <span class="meta"><span class="k">done {t.done_at ? ago(t.done_at) : ''}</span>
                {#if t.property}<span class="k prop">{t.property.label}</span>{/if}</span>
            </span>
            <button type="button" class="mg-btn sm ghost icon" onclick={() => remove(t)} aria-label="Delete “{t.title}”" disabled={saving}>
              <Icon name="close" size={14} />
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</section>

<style>
  /* An .mg-section like Home's "Needs you": the header row, a hairline
     under the add row, then 48px list rows. Everything reads the --mc-*
     tokens; nothing here has its own palette. */
  .tt { display: flex; flex-direction: column; width: 100%; min-width: 0; }
  .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }

  /* ——— header ——— */
  .tt > .head { flex-wrap: wrap; align-items: center; }
  .badges { display: inline-flex; gap: 6px; flex-wrap: wrap; }
  .badge { height: 22px; padding: 0 8px; font: 500 11px/1 var(--mc-mono); font-variant-numeric: tabular-nums; }
  .sw select { height: 32px; max-width: 200px; font-size: 12.5px; padding-right: 30px; }
  .sel { display: inline-block; width: 100%; }

  /* ——— add ——— */
  .add { display: flex; gap: 6px; align-items: center; padding: 10px 12px; border-bottom: 1px solid var(--mc-line); }
  .add .mg-input { flex: 1; }
  input[type='date'].mg-input { color-scheme: dark; }
  .mg-input.ta { min-height: 64px; }

  .extra, .editor {
    display: grid; grid-template-columns: 1fr 1fr; gap: 10px 10px;
    padding: 12px; margin: 10px 12px 0; border-radius: var(--mc-r-md);
    background: var(--mc-raised); border: 1px solid var(--mc-line);
  }
  .editor { margin: 4px 12px 8px; }
  .f { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
  .f.wide { grid-column: 1 / -1; }
  .lnk { grid-column: 1 / -1; display: inline-flex; align-items: center; gap: 6px; min-height: 32px; color: var(--mc-accent); font: 500 13px/1 var(--mc-font); }
  .acts { grid-column: 1 / -1; display: flex; gap: 8px; align-items: center; }
  .sp { flex: 1; }

  /* ——— the list ——— */
  .pad { padding: 14px 16px; }
  .list { margin: 0; padding: 0; list-style: none; }
  .row {
    display: flex; align-items: center; gap: 4px; min-height: 48px;
    padding: 4px 8px 4px 4px;
    transition: background var(--mc-t-fast), opacity var(--mc-t-fast);
  }
  .row:hover { background: rgba(255, 255, 255, 0.03); }
  .row.pending { opacity: 0.55; }
  .row.onit { background: rgba(62, 207, 142, 0.05); }
  .row.done .t { color: var(--mc-ink3); text-decoration: line-through; }
  .editor { border-bottom: 0; }

  .tick {
    flex: none; width: 44px; height: 44px; border: 0; padding: 0; background: none;
    display: grid; place-items: center; cursor: pointer; color: transparent;
  }
  .ring {
    width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center;
    border: 1.5px solid var(--mc-line3); transition: border-color var(--mc-t-fast), background var(--mc-t-fast), color var(--mc-t-fast);
  }
  .row.onit .ring { border-color: var(--mc-accent); }
  .row.late .ring { border-color: var(--mc-warn); }
  .tick:hover .ring { border-color: var(--mc-accent); color: var(--mc-accent); }
  .tick.on .ring, .tick:active .ring { background: var(--mc-accent); border-color: var(--mc-accent); color: var(--mc-accent-ink); }
  .tick:disabled { cursor: default; }

  .body {
    flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; align-items: flex-start;
    min-height: 44px; padding: 5px 4px; border: 0; border-radius: 8px; background: none; text-align: left; cursor: pointer;
    color: inherit; font: inherit; justify-content: center;
  }
  .body.static { cursor: default; }
  .t { font: 500 13.5px/1.35 var(--mc-font); letter-spacing: -0.005em; color: var(--mc-ink); overflow-wrap: anywhere; }
  .body:hover .t { color: var(--mc-accent); }
  .body.static:hover .t { color: var(--mc-ink3); }
  .pri { display: inline-block; margin-right: 5px; color: var(--mc-crit); font-weight: 700; }
  .meta { display: flex; flex-wrap: wrap; gap: 3px 10px; font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); }
  .k { display: inline-flex; align-items: center; gap: 4px; }
  .k.warn { color: var(--mc-warn); font-weight: 500; }
  .k.on { color: var(--mc-accent); font-weight: 500; }
  .k.prop { color: var(--mc-ink2); }

  .act { height: 36px; }
  .act.busy { background: var(--mc-ok-soft); border-color: var(--mc-ok-line); color: var(--mc-accent); }
  .act.busy:hover { border-color: var(--mc-accent); }

  .fold {
    display: flex; align-items: center; gap: 6px; width: 100%;
    min-height: 40px; padding: 0 14px; border: 0; border-top: 1px solid var(--mc-line); background: none; cursor: pointer;
    color: var(--mc-ink3); font: 500 12.5px/1 var(--mc-font); text-align: left;
  }
  .fold:hover { color: var(--mc-ink); background: rgba(255, 255, 255, 0.03); }
  .donelist { border-top: 1px solid var(--mc-line); }
  .donelist .row { min-height: 44px; }

  @media (max-width: 480px) {
    .extra, .editor { grid-template-columns: 1fr; }
    .sw select { max-width: 150px; }
  }
</style>
