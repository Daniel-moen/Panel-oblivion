<script>
  /* Put the selection into a project (zerko/projects.py).

     A project is a folder per shoot with numbered stage folders inside it
     (01 Originals, 02 HDR, 03 Edited, 04 Selects, 05 Exports), so every tool
     downstream drops its output in the right stage. Two ways in: an existing
     project + a stage, or a new project made from these files (they land in
     01 Originals). Either way the files MOVE on disk — the project folder is
     the point; copying would leave the pipeline guessing which one is live. */
  import { media } from '$lib/media.js';
  import { say } from '$lib/media.svelte.js';
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';

  let { open = false, ids = [], onclose, ondone } = $props();

  let projects = $state([]);
  let stages = $state([]);
  let mode = $state('existing');
  let pid = $state('');
  let stage = $state('originals');
  let name = $state('');
  let busy = $state(false);

  $effect(() => {
    if (!open) return;
    media.projects().then((r) => {
      projects = r?.projects || [];
      stages = r?.stages || [];
      if (!projects.length) mode = 'new';
      if (!pid && projects.length) pid = String(projects[0].id);
    }).catch((e) => say(e.message, 'error'));
  });

  const MODES = [
    { value: 'existing', label: 'Existing project' },
    { value: 'new', label: 'New project' }
  ];

  const n = $derived(ids.length);
  const current = $derived(projects.find((p) => String(p.id) === pid));
  const liveStages = $derived(stages.filter((s) => !current?.skipped?.includes(s.key)));

  async function go() {
    if (!n) return;
    busy = true;
    try {
      if (mode === 'new') {
        if (!name.trim()) { say('Give the project a name', 'error'); return; }
        const p = await media.createProject({ name: name.trim(), video_ids: ids, move_files: true });
        say(`Made “${p.name}” with ${n} file${n === 1 ? '' : 's'} in 01 Originals`);
      } else {
        if (!pid) return;
        const r = await media.bringIn(Number(pid), ids, stage, true);
        const sk = r.skipped?.length || 0;
        say(`Moved ${r.moved} into ${r.project?.name} › ${r.project?.stages?.[stage]?.name || stage}` +
            (sk ? ` · ${sk} skipped` : ''), sk ? 'error' : 'ok');
      }
      name = '';
      ondone?.();
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }
</script>

<Sheet {open} title="Add {n} to a project" size="sm" {onclose}>
  <div class="body">
    {#if projects.length}
      <Seg options={MODES} value={mode} onchange={(v) => (mode = v)} label="Project" />
    {/if}

    {#if mode === 'existing' && projects.length}
      <label class="fld">
        <span class="mg-label">Project</span>
        <span class="mg-select">
          <select bind:value={pid}>
            {#each projects as p (p.id)}<option value={String(p.id)}>{p.name}</option>{/each}
          </select>
          <span class="ic"><Icon name="chevronDown" size={15} /></span>
        </span>
      </label>
      <div class="fld">
        <span class="mg-label">Stage</span>
        <div class="stages">
          {#each liveStages as s (s.key)}
            <button type="button" class="stage mg-glass-soft" class:on={stage === s.key}
                    onclick={() => (stage = s.key)}>
              <b>{s.name}</b><span>{s.hint}</span>
              {#if current?.stages?.[s.key]}<i class="mg-tnum">{current.stages[s.key].count}</i>{/if}
            </button>
          {/each}
        </div>
      </div>
    {:else}
      <label class="fld">
        <span class="mg-label">Project name</span>
        <input class="mg-input" type="text" bind:value={name} maxlength="120"
               placeholder="e.g. 20 Main Rd Greenpoint"
               onkeydown={(e) => { if (e.key === 'Enter') go(); }} />
      </label>
      <p class="hint">Makes the folder with 01 Originals … 05 Exports inside it and moves the
        selection into 01 Originals.</p>
    {/if}
    <p class="hint">Files are moved on disk into the project folder.</p>
  </div>

  {#snippet footer()}
    <div class="right">
      <button class="mg-btn ghost sm" onclick={onclose}>Cancel</button>
      <button class="mg-btn primary sm" disabled={busy || !n || (mode === 'new' ? !name.trim() : !pid)}
              onclick={go}>
        <Icon name="folder" size={14} />{mode === 'new' ? 'Create project' : 'Move in'}
      </button>
    </div>
  {/snippet}
</Sheet>

<style>
  .body { display: flex; flex-direction: column; gap: 14px; }
  .fld { display: flex; flex-direction: column; gap: 6px; }
  .fld .mg-select, .fld .mg-select select { width: 100%; }
  .stages { display: flex; flex-direction: column; gap: 4px; }
  .stage {
    display: grid; grid-template-columns: minmax(0, 1fr) auto; grid-template-rows: auto auto;
    column-gap: 10px; text-align: left; padding: 8px 12px; border-radius: 12px; cursor: pointer;
    min-height: 44px; color: var(--mc-ink2); border: 1px solid var(--mc-line);
  }
  .stage b { font: 500 13px/1.3 var(--mc-font); color: var(--mc-ink); }
  .stage span { grid-row: 2; font: 400 11.5px/1.35 var(--mc-font); color: var(--mc-ink3); }
  .stage i { grid-row: 1 / 3; grid-column: 2; align-self: center; font-style: normal;
             font-size: 11.5px; color: var(--mc-ink3); }
  .stage.on { border-color: rgba(62, 207, 142, 0.5); background: rgba(62, 207, 142, 0.1); }
  .stage.on b { color: var(--mc-accent); }
  .hint { margin: 0; font: 400 12px/1.5 var(--mc-font); color: var(--mc-ink3); }
</style>
