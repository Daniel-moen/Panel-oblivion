<script>
  /* The library's trash (Zerko 1.3). A trashed clip is a row with
     is_active=false whose file sits under _Trash; restoring puts the file
     back where it came from (or beside it, renamed, if something took the
     name). Emptying and the auto-empty timer destroy files for good, so they
     are an administrator's (media.harddelete) — everyone who can trash can
     also restore. */
  import { onMount } from 'svelte';
  import { staggerIn } from '$lib/motion.js';
  import { media, murl } from '$lib/media.js';
  import { say, can, CAP, loadClips } from '$lib/media.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';

  let { oncount } = $props();

  let data = $state(null);
  let busy = $state(false);
  let confirm = $state(false);

  async function load() {
    try { data = await media.trash(); oncount?.(data.count); }
    catch (e) { say(e.message, 'error'); data = { items: [], count: 0 }; }
  }
  onMount(load);

  async function restore(item) {
    busy = true;
    try {
      await media.restore(item.id);
      say(`Restored ${item.filename}`);
      await load();
      loadClips();
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }

  async function restoreAll() {
    busy = true;
    try {
      const r = await media.restoreAll();
      say(`Restored ${r.restored} item${r.restored === 1 ? '' : 's'}` +
          (r.failed?.length ? ` · ${r.failed.length} could not be` : ''), r.failed?.length ? 'error' : 'ok');
      await load();
      loadClips();
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }

  async function empty() {
    busy = true;
    try {
      const r = await media.emptyTrash();
      say(`Deleted ${r.removed} for good · ${r.freed_formatted} freed`);
      confirm = false;
      await load();
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }

  async function setDays(v) {
    const n = Number(v);
    try { await media.trashSettings(n); data.auto_days = n;
          say(n ? `Trash empties itself after ${n} days` : 'Trash never empties by itself'); }
    catch (e) { say(e.message, 'error'); }
  }

  const ago = (s) => {
    if (!s) return 'date unknown';
    const days = Math.floor((Date.now() - new Date(s).getTime()) / 86400000);
    return days < 1 ? 'today' : days === 1 ? 'yesterday' : `${days} days ago`;
  };
  const left = (s) => {
    if (!data?.auto_days || !s) return null;
    const d = data.auto_days - Math.floor((Date.now() - new Date(s).getTime()) / 86400000);
    return d <= 0 ? 'goes within the hour' : `${d} day${d === 1 ? '' : 's'} left`;
  };

  const DAYS = [0, 7, 14, 30, 60, 90];
</script>

<div class="head">
  <div class="sum">
    <b>Trash</b>
    {#if data}
      {@const n = data.count ?? data.items?.length ?? 0}
      <span class="mg-tnum">{n} item{n === 1 ? '' : 's'}{data.total_size_formatted ? ' · ' + data.total_size_formatted : ''}</span>
    {/if}
  </div>
  <div class="acts">
    {#if can(CAP.HARD_DELETE) && data}
      <label class="mg-select days" title="Empty the trash automatically">
        <select aria-label="Auto-empty" value={String(data.auto_days || 0)}
                onchange={(e) => setDays(e.currentTarget.value)}>
          {#each DAYS as d (d)}
            <option value={String(d)}>{d ? `Auto-empty after ${d} days` : 'Never auto-empty'}</option>
          {/each}
        </select>
        <span class="ic"><Icon name="chevronDown" size={15} /></span>
      </label>
    {:else if data?.auto_days}
      <span class="hint">Empties itself after {data.auto_days} days</span>
    {/if}
    {#if data?.count && can(CAP.TRASH)}
      <button class="mg-btn secondary sm" disabled={busy} onclick={restoreAll}>
        <Icon name="undo" size={14} />Restore all
      </button>
    {/if}
    {#if data?.count && can(CAP.HARD_DELETE)}
      <button class="mg-btn danger sm" disabled={busy} onclick={() => (confirm = true)}>
        <Icon name="trash" size={14} />Empty trash
      </button>
    {/if}
  </div>
</div>

{#if !data}
  {#each Array(4) as _, i (i)}
    <div class="row sk"><Skeleton h="46px" r="12px" delay={i * 60} /></div>
  {/each}
{:else if !data.items.length}
  <Empty icon="trash" title="The trash is empty"
         hint="Anything moved to the trash from Browse waits here until it is restored or emptied." />
{:else}
  <ul class="rows">
    {#each data.items as it, i (it.id)}
      <li class="row mg-tile" in:staggerIn|global={{ i }}>
        <span class="th">
          {#if it.thumbnail_path}<img src={murl(it.thumbnail_path)} alt="" loading="lazy" />
          {:else}<Icon name={it.media_type === 'photo' ? 'image' : 'film'} size={16} />{/if}
        </span>
        <span class="meta">
          <b>{it.filename}</b>
          <span>{it.file_size_formatted} · trashed {ago(it.trashed_at)}{left(it.trashed_at) ? ' · ' + left(it.trashed_at) : ''}</span>
          <span class="path" title={it.original_path}>{it.original_path}</span>
        </span>
        {#if can(CAP.TRASH)}
          <button class="mg-btn secondary sm" disabled={busy} onclick={() => restore(it)}>
            <Icon name="undo" size={14} /><span class="lbl">Restore</span>
          </button>
        {/if}
      </li>
    {/each}
  </ul>
{/if}

<Sheet open={confirm} title="Empty the trash?" size="sm" onclose={() => (confirm = false)}>
  <p class="warn">
    {data?.count} item{data?.count === 1 ? '' : 's'} ({data?.total_size_formatted}) will be deleted from
    the drive for good. This cannot be undone.
  </p>
  {#snippet footer()}
    <div class="right">
      <button class="mg-btn ghost sm" onclick={() => (confirm = false)}>Cancel</button>
      <button class="mg-btn danger sm" disabled={busy} onclick={empty}>
        <Icon name="trash" size={14} />Delete for good
      </button>
    </div>
  {/snippet}
</Sheet>

<style>
  .head { display: flex; align-items: center; justify-content: space-between; gap: 10px;
          flex-wrap: wrap; margin-bottom: 12px; }
  .sum { display: flex; align-items: baseline; gap: 10px; }
  .sum b { font: 600 15px/1 var(--mc-font); color: var(--mc-ink); }
  .sum span { font: 400 12.5px/1 var(--mc-font); color: var(--mc-ink3); }
  .acts { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .days > select { width: 200px; }
  .hint { font: 400 12px/1 var(--mc-font); color: var(--mc-ink3); }

  .rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
  .row { display: grid; grid-template-columns: 64px minmax(0, 1fr) auto; gap: 12px;
         align-items: center; padding: 6px 10px 6px 6px; border-radius: var(--mc-r-md); }
  .row.sk { display: block; padding: 0; margin-bottom: 6px; background: none; }
  .th { width: 64px; height: 42px; border-radius: var(--mc-r-sm); overflow: hidden; background: var(--mc-inset);
        display: grid; place-items: center; color: var(--mc-ink3); }
  .th img { width: 100%; height: 100%; object-fit: cover; display: block; opacity: 0.8; }
  .meta { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
  .meta b { font: 500 13px/1.35 var(--mc-font); color: var(--mc-ink);
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .meta span { font: 400 11.5px/1.4 var(--mc-font); color: var(--mc-ink3);
               overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .meta .path { font-family: var(--mc-mono); font-size: 10.5px; }
  .warn { margin: 0; font: 400 13.5px/1.55 var(--mc-font); color: var(--mc-ink2); }

  @media (max-width: 560px) {
    .row { grid-template-columns: 52px minmax(0, 1fr) auto; gap: 10px; }
    .th { width: 52px; height: 36px; }
    .lbl { display: none; }
    .row .mg-btn { width: 44px; height: 44px; padding: 0; }
    .days > select { width: 100%; }
    .days { flex: 1 1 100%; }
    .meta .path { display: none; }
  }
</style>
