<script>
  /* Shoots — every property booked, shot, in the edit or posted.

     GET /api/shoots?q=&status= does the searching (it matches the address
     the way people type it, so "ocean view dr" finds "12 Ocean View Drive").
     A row opens /media/shoot?id=. */
  import { goto } from '$app/navigation';
  import { rise } from '$lib/motion.js';
  import { say } from '$lib/media.svelte.js';
  import { thumbUrl } from '$lib/media.js';
  import { shoots, STATUSES, STATUS, fmtWhen, centreOf } from '$lib/media/shoots.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import ShootsGate from '$lib/components/media/shoots/ShootsGate.svelte';
  import StatusChip from '$lib/components/media/shoots/StatusChip.svelte';
  import NewShootSheet from '$lib/components/media/shoots/NewShootSheet.svelte';

  let list = $state([]);
  let all = $state([]);           // unfiltered, for the counts and the map centre
  let loading = $state(true);
  let err = $state(null);
  let search = $state('');
  let status = $state('all');
  let making = $state(false);
  let started = false;

  const FILTERS = $derived([
    { value: 'all', label: `All ${all.length || ''}`.trim() },
    ...STATUSES.map((s) => {
      const n = all.filter((x) => x.status === s).length;
      return { value: s, label: `${STATUS[s].label}${n ? ' ' + n : ''}` };
    })
  ]);

  async function load() {
    loading = true; err = null;
    try {
      const params = { q: search.trim(), status };
      const r = await shoots.list(params);
      list = r?.shoots || [];
      if (!params.q && status === 'all') all = list;
      else if (!all.length) all = (await shoots.list())?.shoots || [];
    } catch (e) { err = e.message; say(e.message, 'error'); }
    finally { loading = false; }
  }

  /* Search as you type, gently. */
  let t;
  $effect(() => {
    search; status;
    if (!started) return;
    clearTimeout(t);
    t = setTimeout(load, 220);
    return () => clearTimeout(t);
  });

  function begin() { started = true; load(); }

  function created(s) {
    making = false;
    say(`Booked ${s.address}`);
    goto(`/media/shoot?id=${s.id}`);
  }
</script>

<svelte:head><title>Shoots · Media</title></svelte:head>

<ShootsGate onready={begin}>
  {#snippet children()}
    <div class="mg-row">
      <h2 class="mg-h2">Shoots</h2>
      {#if !loading}<span class="mg-count">{list.length} propert{list.length === 1 ? 'y' : 'ies'}</span>{/if}
      <div class="mg-actions">
        <a class="mg-btn secondary sm" href="/media/calendar"><Icon name="calendar" size={14} />Calendar</a>
        <button class="mg-btn primary sm" onclick={() => (making = true)}><Icon name="plus" size={14} />Book a shoot</button>
      </div>
    </div>

    <div class="mg-controls">
      <label class="mg-search">
        <span class="ic"><Icon name="search" size={15} /></span>
        <input class="mg-input" type="search" bind:value={search} placeholder="Find an address…" aria-label="Find an address" />
        {#if search}
          <button class="clear" type="button" onclick={() => (search = '')} aria-label="Clear"><Icon name="close" size={14} /></button>
        {/if}
      </label>
      <div class="segwrap mg-noscroll">
        <Seg options={FILTERS} value={status} onchange={(v) => (status = v)} label="Status" />
      </div>
    </div>

    {#if err}
      <div class="mg-strip crit">
        <span class="ic"><Icon name="alert" size={15} /></span>
        <span><b>Couldn't load the shoots</b> — {err}</span>
        <button class="mg-btn secondary sm retry" onclick={load}><Icon name="refresh" size={13} />Retry</button>
      </div>
    {/if}
    {#if loading && !list.length}
      <div class="list">
        {#each Array(4) as _, i (i)}<div class="mg-card"><Skeleton h="3rem" delay={i * 70} /></div>{/each}
      </div>
    {:else if !list.length && !err}
      {#if search || status !== 'all'}
        <Empty icon="search" title="No shoots match" hint="Try fewer words of the address, or another status." />
      {:else}
        <Empty icon="camera" title="No shoots yet"
               hint="A shoot is one property: its address, agent, booking and the library folders its photos and video live in.">
          {#snippet children()}
            <button class="mg-btn primary sm" onclick={() => (making = true)}><Icon name="plus" size={14} />Book a shoot</button>
          {/snippet}
        </Empty>
      {/if}
    {:else}
      <div class="list">
        {#each list as s, i (s.id)}
          <a class="mg-card row" href="/media/shoot?id={s.id}" in:rise={{ i }}>
            <span class="cover">
              {#if s.cover?.thumbnail_path}<img src={thumbUrl(s.cover)} alt="" loading="lazy" />
              {:else}<Icon name="camera" size={18} />{/if}
            </span>
            <span class="main">
              <b>{s.address}</b>
              <span class="sub">
                {#if s.suburb}<span>{s.suburb}</span>{/if}
                {#if s.agent}<span><Icon name="user" size={12} />{s.agent}</span>{/if}
                <span class="mg-tnum"><Icon name="calendar" size={12} />{fmtWhen(s)}</span>
              </span>
            </span>
            <span class="side">
              <StatusChip status={s.status} />
              {#if s.counts}
                <span class="n mg-tnum">{s.counts.photos} photo{s.counts.photos === 1 ? '' : 's'} · {s.counts.videos} video{s.counts.videos === 1 ? '' : 's'}</span>
              {/if}
            </span>
          </a>
        {/each}
      </div>
    {/if}

    <NewShootSheet open={making} near={centreOf(all)} onclose={() => (making = false)} oncreated={created} />
  {/snippet}
</ShootsGate>

<style>
  .segwrap { overflow-x: auto; max-width: 100%; }
  .retry { margin-left: auto; align-self: center; }
  .list { display: flex; flex-direction: column; gap: 10px; }
  .row { display: flex; align-items: center; gap: 12px; padding: 10px 12px; min-height: 64px; }
  .cover { flex: none; width: 72px; height: 50px; border-radius: var(--mc-r-sm); overflow: hidden;
           display: grid; place-items: center; background: var(--mc-inset); color: var(--mc-ink3); }
  .cover img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .main b { font: 600 14px/1.3 var(--mc-font); color: var(--mc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sub { display: flex; flex-wrap: wrap; gap: 3px 12px; font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); }
  .sub span { display: inline-flex; align-items: center; gap: 4px; }
  .side { flex: none; display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }
  .n { font: 400 11.5px/1 var(--mc-font); color: var(--mc-ink3); }
  @media (max-width: 520px) {
    .row { flex-wrap: wrap; }
    .cover { width: 56px; height: 42px; }
    .side { width: 100%; flex-direction: row; justify-content: space-between; align-items: center; }
  }
</style>
