<script>
  /* Every edit in the library — they are shared work, so everyone sees all
     of them. Create, rename, duplicate, delete; tap one to open it. */
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { say } from '$lib/media.svelte.js';
  import { fmtDuration } from '$lib/media.js';
  import { vapi, ASPECTS } from '$lib/media/video.js';
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import ClipPicker from './ClipPicker.svelte';

  let { canEdit = false } = $props();

  let rows = $state([]);
  let loading = $state(true);

  let sheet = $state(null);          // { mode: 'new'|'rename', id?, name, aspect }
  let confirmDel = $state(null);
  let pickSub = $state(false);

  async function load() {
    loading = true;
    try { rows = (await vapi.projects()) || []; }
    catch (e) { say(e.message, 'error'); }
    finally { loading = false; }
  }
  onMount(load);

  async function submit() {
    const s = sheet;
    if (!s?.name?.trim()) return;
    try {
      if (s.mode === 'new') {
        const p = await vapi.create({ name: s.name.trim(), aspect: s.aspect });
        sheet = null;
        goto(`/media/video?project=${p.id}`);
      } else {
        await vapi.save(s.id, { name: s.name.trim() });
        sheet = null;
        load();
      }
    } catch (e) { say(e.message, 'error'); }
  }

  async function dup(r) {
    try { await vapi.duplicate(r.id); say('Duplicated'); load(); }
    catch (e) { say(e.message, 'error'); }
  }

  async function remove(r) {
    try { await vapi.remove(r.id); confirmDel = null; say('Edit deleted'); load(); }
    catch (e) { say(e.message, 'error'); }
  }

  const when = (s) => (s ? new Date(s).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '');
</script>

<div class="mg-row">
  <h2 class="mg-h2">Video editor</h2>
  {#if rows.length}<span class="mg-count">{rows.length} edit{rows.length === 1 ? '' : 's'}</span>{/if}
  <div class="mg-actions">
    <button type="button" class="mg-btn secondary" onclick={() => (pickSub = true)}>
      <Icon name="scissors" size={15} />Sub-clips
    </button>
    {#if canEdit}
      <button type="button" class="mg-btn accent" onclick={() => (sheet = { mode: 'new', name: 'Untitled edit', aspect: '9:16' })}>
        <Icon name="plus" size={15} />New edit
      </button>
    {/if}
  </div>
</div>

{#if loading}
  <div class="mg-grid c3">
    {#each Array(6) as _, i (i)}<div class="gh"><Skeleton h="100%" r="var(--mc-r)" delay={i * 60} /></div>{/each}
  </div>
{:else if !rows.length}
  <Empty icon="film" title="No edits yet"
         hint="An edit strings library clips into one video — trim, reorder, set speed, transitions and a look, then render it here or hand the timeline to DaVinci Resolve.">
    {#snippet children()}
      {#if canEdit}
        <button type="button" class="mg-btn accent sm" onclick={() => (sheet = { mode: 'new', name: 'Untitled edit', aspect: '9:16' })}>
          <Icon name="plus" size={14} />New edit
        </button>
      {/if}
    {/snippet}
  </Empty>
{:else}
  <div class="mg-grid c3">
    {#each rows as r (r.id)}
      <div class="card mg-card">
        <a class="cov" href="/media/video?project={r.id}" aria-label="Open {r.name}">
          {#if r.cover}<img src={vapi.frameUrl(r.cover, 1, 320)} alt="" loading="lazy" />{:else}<Icon name="film" size={24} />{/if}
          <span class="asp">{r.aspect}</span>
        </a>
        <div class="meta">
          <a class="nm" href="/media/video?project={r.id}">{r.name}</a>
          <span class="sub mg-tnum">{r.clips} clip{r.clips === 1 ? '' : 's'} · {fmtDuration(r.duration)} · {when(r.updated_at)}</span>
        </div>
        {#if canEdit}
          <div class="acts">
            <button type="button" class="mg-btn ghost icon" title="Rename" aria-label="Rename {r.name}"
                    onclick={() => (sheet = { mode: 'rename', id: r.id, name: r.name })}><Icon name="edit" size={15} /></button>
            <button type="button" class="mg-btn ghost icon" title="Duplicate" aria-label="Duplicate {r.name}"
                    onclick={() => dup(r)}><Icon name="copy" size={15} /></button>
            <button type="button" class="mg-btn ghost icon" title="Delete" aria-label="Delete {r.name}"
                    onclick={() => (confirmDel = r)}><Icon name="trash" size={15} /></button>
          </div>
        {/if}
      </div>
    {/each}
  </div>
{/if}

<Sheet open={!!sheet} title={sheet?.mode === 'new' ? 'New edit' : 'Rename edit'} size="sm" onclose={() => (sheet = null)}>
  {#if sheet}
    <form class="frm" onsubmit={(e) => { e.preventDefault(); submit(); }}>
      <label class="f"><span class="mg-label">Name</span>
        <input class="mg-input" bind:value={sheet.name} maxlength="160" autofocus /></label>
      {#if sheet.mode === 'new'}
        <span class="mg-label">Shape</span>
        <Seg options={ASPECTS.map((a) => ({ value: a, label: a }))} value={sheet.aspect}
             onchange={(v) => (sheet.aspect = v)} label="Aspect ratio" />
      {/if}
      <button class="mg-btn accent" type="submit" disabled={!sheet.name?.trim()}>
        {sheet.mode === 'new' ? 'Create and open' : 'Save'}
      </button>
    </form>
  {/if}
</Sheet>

<ClipPicker open={pickSub} single title="Mark sub-clips on…" onclose={() => (pickSub = false)}
            onpick={(v) => { pickSub = false; if (v[0]) goto(`/media/video?clip=${v[0].id}`); }} />

<Sheet open={!!confirmDel} title="Delete this edit?" size="sm" onclose={() => (confirmDel = null)}>
  {#if confirmDel}
    <p class="why"><b>{confirmDel.name}</b> goes, with its timeline. The clips it used stay in the library.</p>
  {/if}
  {#snippet footer()}
    <div class="right">
      <button type="button" class="mg-btn ghost" onclick={() => (confirmDel = null)}>Keep it</button>
      <button type="button" class="mg-btn danger" onclick={() => remove(confirmDel)}><Icon name="trash" size={14} />Delete</button>
    </div>
  {/snippet}
</Sheet>

<style>
  .gh { aspect-ratio: 16 / 12; }
  .card { display: flex; flex-direction: column; padding: 0; overflow: hidden; min-width: 0; }
  .cov {
    position: relative; aspect-ratio: 16 / 9; background: var(--mc-inset); display: grid; place-items: center;
    color: var(--mc-ink3);
  }
  .cov img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
  .asp {
    position: absolute; top: 8px; left: 8px; padding: 4px 8px; border-radius: 9999px;
    background: var(--mc-raised); border: 1px solid var(--mc-line2); color: var(--mc-ink); font: 600 11px/1 var(--mc-font);
  }
  .meta { padding: 12px 14px 4px; display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  .nm { font: 600 14px/1.3 var(--mc-font); color: var(--mc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sub { font-size: 12px; color: var(--mc-ink3); }
  .acts { display: flex; gap: 2px; padding: 4px 8px 8px; }
  @media (pointer: coarse) { .acts :global(.mg-btn.sm) { min-height: 44px; } .acts :global(.mg-btn.icon.sm) { min-width: 44px; } }
  .frm { display: flex; flex-direction: column; gap: 12px; padding-top: 4px; }
  .f { display: flex; flex-direction: column; gap: 5px; }
  .why { margin: 0; font-size: 13px; line-height: 1.55; color: var(--mc-ink2); }
</style>
