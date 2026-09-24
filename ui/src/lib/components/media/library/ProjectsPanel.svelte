<script>
  /* Projects on the Overview: one row per shoot, one chip per stage with its
     count. A chip opens Browse filtered to that stage's folder, which is the
     project filter — a stage IS a folder, so the folder filter already does
     the work. */
  import { onMount } from 'svelte';
  import { fly } from 'svelte/transition';
  import { media } from '$lib/media.js';
  import { say, can, CAP } from '$lib/media.svelte.js';
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';

  let projects = $state(null);
  let stages = $state([]);
  let making = $state(false);
  let name = $state('');
  let busy = $state(false);
  let showAll = $state(false);

  async function load() {
    try {
      const r = await media.projects();
      projects = r?.projects || [];
      stages = r?.stages || [];
    } catch { projects = []; }
  }
  onMount(load);

  async function create() {
    if (!name.trim()) return;
    busy = true;
    try {
      const p = await media.createProject({ name: name.trim() });
      say(`Made “${p.name}”`);
      name = '';
      making = false;
      await load();
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }

  const shown = $derived(showAll ? projects || [] : (projects || []).slice(0, 4));
  const total = (p) => Object.values(p.stages || {}).reduce((a, s) => a + (s.count || 0), 0);
</script>

<section class="projects">
  <div class="mg-row rh">
    <h3 class="mg-h2 sm">Projects</h3>
    {#if projects?.length}<span class="mg-count">{projects.length}</span>{/if}
    <div class="mg-actions">
      {#if can(CAP.ORGANISE)}
        <button class="mg-btn secondary sm" onclick={() => (making = true)}>
          <Icon name="plus" size={14} />New project
        </button>
      {/if}
    </div>
  </div>

  {#if projects == null}
    <div class="list">
      {#each [0, 1] as i (i)}<div class="mg-glass-soft card"><Skeleton h="44px" delay={i * 80} /></div>{/each}
    </div>
  {:else if !projects.length}
    <p class="none">
      No projects yet. A project is one folder per shoot with 01 Originals → 05 Exports inside, so each
      step's output lands in the right place. Start one here, or select clips in Browse and choose
      “Add to project”.
    </p>
  {:else}
    <div class="list">
      {#each shown as p, i (p.id)}
        <article class="mg-glass-soft card" in:fly={{ y: 8, duration: 260, delay: i * 40 }}>
          <div class="top">
            <b title={p.path}>{p.name}</b>
            <span class="mg-tnum">{total(p)} file{total(p) === 1 ? '' : 's'}</span>
          </div>
          <div class="stages mg-noscroll">
            {#each stages as s (s.key)}
              {@const st = p.stages?.[s.key]}
              {#if st && !p.skipped?.includes(s.key)}
                {#if st.folder_id}
                  <a class="mg-chip st" class:has={st.count} href="/media/browse?folder={st.folder_id}"
                     title={s.hint}>
                    {st.name}<i class="mg-tnum">{st.count}</i>
                  </a>
                {:else}
                  <span class="mg-chip st" title="Folder not indexed yet">{st.name}<i>–</i></span>
                {/if}
              {/if}
            {/each}
          </div>
        </article>
      {/each}
    </div>
    {#if projects.length > 4}
      <button class="mg-btn ghost sm more" onclick={() => (showAll = !showAll)}>
        {showAll ? 'Show fewer' : `Show all ${projects.length}`}
      </button>
    {/if}
  {/if}
</section>

<Sheet open={making} title="New project" size="sm" onclose={() => (making = false)}>
  <label class="fld">
    <span class="mg-label">Name</span>
    <input class="mg-input" type="text" bind:value={name} maxlength="120"
           placeholder="e.g. 20 Main Rd Greenpoint"
           onkeydown={(e) => { if (e.key === 'Enter') create(); }} />
  </label>
  <p class="hint">Creates the folder on the footage drive with 01 Originals, 02 HDR, 03 Edited,
    04 Selects and 05 Exports inside it.</p>
  {#snippet footer()}
    <div class="right">
      <button class="mg-btn ghost sm" onclick={() => (making = false)}>Cancel</button>
      <button class="mg-btn primary sm" disabled={busy || !name.trim()} onclick={create}>
        <Icon name="plus" size={14} />Create
      </button>
    </div>
  {/snippet}
</Sheet>

<style>
  .projects { margin-top: 26px; }
  .rh { margin-bottom: 10px; }
  .mg-h2.sm { font-size: 15px; }
  .list { display: grid; gap: 8px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 420px), 1fr)); }
  .card { border-radius: var(--mg-r-in); padding: 12px 14px; min-width: 0; }
  .top { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-bottom: 9px; }
  .top b { font: 600 14px/1.3 var(--mg-font); color: var(--mg-i); min-width: 0;
           overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .top span { font: 400 12px/1 var(--mg-font); color: var(--mg-i3); flex: none; }
  .stages { display: flex; gap: 5px; overflow-x: auto; padding-bottom: 2px; }
  .st { flex: none; gap: 6px; text-decoration: none; color: var(--mg-i3); min-height: 32px; }
  .st.has { color: var(--mg-i2); }
  a.st:hover { color: var(--mg-i); border-color: var(--mg-line2); }
  .st i { font-style: normal; font-size: 11px; color: var(--mg-i3); }
  .st.has i { color: var(--mg-ok); }
  .none { margin: 0; font-size: 13px; line-height: 1.55; color: var(--mg-i3); max-width: 680px; }
  .more { margin-top: 8px; }
  .fld { display: flex; flex-direction: column; gap: 6px; }
  .hint { margin: 12px 0 0; font: 400 12px/1.5 var(--mg-font); color: var(--mg-i3); }
  @media (pointer: coarse) { .st { min-height: 40px; } }
</style>
