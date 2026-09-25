<script>
  /* The Media overview.

     The stage plays the library back at you: up to five of its own clips,
     muted and looping, crossfading one into the next. It is the fastest way to
     say "this is your footage, it is indexed, it is here". With nothing to
     play (no drive, no proxies yet) there is no stage at all: the page opens
     on the numbers rather than on a black box.

     Everything below it is a read: counts that arrive, whatever is running
     shown as a moving bar rather than a number, and the four things anyone
     actually comes here to start. */
  import { onMount } from 'svelte';
  import { mstate, boot, runRescan, runProxies, runAutoTag, can, CAP } from '$lib/media.svelte.js';
  import { media, streamUrl, thumbUrl, fmtBytes, fmtHours } from '$lib/media.js';
  import CountUp from '$lib/components/CountUp.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import ActivityBell from '$lib/components/media/library/ActivityBell.svelte';
  import ProjectsPanel from '$lib/components/media/library/ProjectsPanel.svelte';

  let reel = $state([]);          // clips with proxies, for the montage
  let shot = $state(0);           // which one is on screen
  let heroFail = $state(false);
  let recent = $state([]);
  let timer;

  onMount(async () => {
    await boot();
    if (!mstate.ready) return;
    try {
      const all = await media.videos({ sort_by: 'date', sort_order: 'desc', media_type: 'video' });
      recent = (all || []).slice(0, 12);
      /* Only proxies: the montage must not pull a 4K master over the wire,
         and a clip with no proxy would stall the stage on a black frame. */
      reel = (all || []).filter((v) => v.has_proxy).slice(0, 5);
    } catch { /* the stage simply falls back */ }
    if (reel.length > 1) {
      const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
      if (!reduce) timer = setInterval(() => { shot = (shot + 1) % reel.length; }, 7000);
    }
    return () => clearInterval(timer);
  });

  const s = $derived(mstate.stats);
  const rescan = $derived(mstate.rescan);
  const running = $derived(mstate.jobs?.running || []);

  /* Indexing has a real percentage when it reports one; otherwise the bar
     runs as an indeterminate sweep rather than lying about progress. */
  const scanPct = $derived.by(() => {
    if (!rescan?.running) return null;
    const done = rescan.done ?? rescan.processed;
    const total = rescan.total;
    return total ? Math.round((done / total) * 100) : null;
  });

  const pending = $derived(mstate.proxies?.pending || 0);
  const tiles = $derived(s ? [
    { k: 'Clips', icon: 'film', href: '/media/browse', v: s.total_videos || 0,
      f: (n) => Math.round(n).toLocaleString('en-ZA').replace(/,/g, ' '),
      sub: pending ? `${pending} still need a proxy` : 'All with proxies', tone: pending ? 'warn' : '' },
    { k: 'Storage', icon: 'box', href: '/media/settings', v: s.total_storage || 0, f: fmtBytes, sub: 'On the footage drive' },
    { k: 'Hours', icon: 'clock', href: '/media/browse', v: (s.avg_duration || 0) * (s.total_videos || 0), f: fmtHours, sub: 'Of footage indexed' },
    { k: 'Folders', icon: 'folder', href: '/media/browse', v: s.total_projects || 0, f: (n) => String(Math.round(n)), sub: 'Shoots and projects' }
  ] : []);

  const live = $derived(reel.length > 0 && !heroFail);

  const clipCount = $derived(s?.total_videos ?? null);
</script>

<svelte:head><title>Media · Oblivion</title></svelte:head>

<!-- ————————————————————————————————————————————————————— header row ——— -->
<div class="mg-row">
  <h1 class="mg-h2">Media</h1>
  {#if clipCount != null}
    <span class="mg-count">{clipCount.toLocaleString('en-ZA').replace(/,/g, ' ')} clips</span>
  {/if}
  <div class="mg-actions">
    {#if mstate.ready}<ActivityBell />{/if}
    <a class="mg-btn secondary sm" href="/media/search"><Icon name="search" size={14} />Search</a>
    <a class="mg-btn primary sm" href="/media/browse"><Icon name="grid" size={14} />Browse</a>
  </div>
</div>

{#if mstate.error}
  <!-- the layout's red strip already says why; this says what still works -->
  <section class="mg-section mg-rise">
    <Empty icon="film" title="The media library is offline"
           hint="Nothing can be indexed or played until the media backend is back. Portals and the file store come back with it.">
      <a class="mg-btn secondary" href="/media/settings"><Icon name="settings" size={15} />Media settings</a>
    </Empty>
  </section>
{:else}
  <!-- ——————————————————————————————————————————————————— the stage ——— -->
  {#if live}
    <section class="stage mg-rise">
      <div class="film" aria-hidden="true">
        {#each reel as clip, i (clip.id)}
          <video
            class:on={i === shot}
            src={streamUrl(clip)}
            poster={thumbUrl(clip)}
            muted autoplay loop playsinline preload={i === 0 ? 'auto' : 'none'}
            onerror={() => { if (i === 0) heroFail = true; }}
          ></video>
        {/each}
      </div>
      <div class="veil" aria-hidden="true"></div>

      <div class="caption">
        <span class="mg-label">Media library</span>
        <p class="line">Everything you have shot, findable.</p>
        <p class="now">{reel[shot]?.filename}</p>
      </div>

      {#if reel.length > 1}
        <div class="dots" role="tablist" aria-label="Montage">
          {#each reel as clip, i (clip.id)}
            <button role="tab" aria-selected={i === shot} aria-label={clip.filename}
                    class:on={i === shot} onclick={() => (shot = i)}><i></i></button>
          {/each}
        </div>
      {/if}
    </section>
  {/if}

  <!-- ————————————————————————————————————————————————— the numbers ——— -->
  <section class="tiles">
    {#if !s}
      {#each [0, 1, 2, 3] as i (i)}
        <div class="mg-stat-tile">
          <Skeleton h="11px" w="42%" delay={i * 90} />
          <div style="height:12px"></div>
          <Skeleton h="26px" w="62%" delay={i * 90} />
          <div style="height:8px"></div>
          <Skeleton h="11px" w="70%" delay={i * 90} />
        </div>
      {/each}
    {:else}
      {#each tiles as t, i (t.k)}
        <a class="mg-stat-tile mg-rise" style:--i={i} href={t.href}>
          <span class="hud"><Icon name={t.icon} size={13} />{t.k}</span>
          <span class="v"><CountUp value={t.v} format={t.f} /></span>
          <span class="sub" class:warn={t.tone === 'warn'}>{t.sub}</span>
        </a>
      {/each}
    {/if}
  </section>

  <!-- ——————————————————————————————————————————————— what's running ——— -->
  {#if rescan?.running || running.length}
    <section class="mg-section work mg-rise">
      <div class="head">
        <span class="mg-dot warn"><i class="mg-ping"></i></span>
        <h2>{rescan?.running ? 'Indexing the library' : `${running.length} job${running.length === 1 ? '' : 's'} running`}</h2>
        {#if scanPct != null}<span class="mg-count pct">{scanPct}%</span>{/if}
      </div>
      <div class="body">
        {#if rescan?.message || running[0]?.filename}
          <p class="mg-hint dim">{rescan?.message || running[0]?.filename}</p>
        {/if}
        <div class="mg-bar warn" class:indeterminate={scanPct == null}>
          <i style:width={scanPct != null ? scanPct + '%' : null}></i>
        </div>
      </div>
    </section>
  {/if}

  <!-- ——————————————————————————————————————————————— quick actions ——— -->
  <span class="mg-label lab">Start something</span>
  <section class="mg-grid acts">
    {#if can(CAP.ORGANISE)}
      <button class="mg-card act" onclick={runRescan} disabled={mstate.busy || !mstate.ready}>
        <span class="ic"><Icon name="refresh" size={17} /></span>
        <b>Re-index</b><span class="hint">Pick up anything new on the drive</span>
      </button>
    {/if}
    {#if can(CAP.PROXY)}
      <button class="mg-card act" onclick={runProxies} disabled={!mstate.ready}>
        <span class="ic"><Icon name="film" size={17} /></span>
        <b>Build proxies</b><span class="hint">{mstate.proxies?.pending ?? '—'} clips still need one</span>
      </button>
    {/if}
    {#if can(CAP.ADMIN)}
      <button class="mg-card act" onclick={runAutoTag} disabled={!mstate.ready}>
        <span class="ic"><Icon name="sparkles" size={17} /></span>
        <b>Auto-tag</b><span class="hint">Camera, stage and spoken-word tags</span>
      </button>
    {/if}
    {#if can(CAP.SHARES)}
      <a class="mg-card act" href="/media/shares">
        <span class="ic"><Icon name="link" size={17} /></span>
        <b>New share link</b><span class="hint">Send a reel to a client</span>
      </a>
    {/if}
    <a class="mg-card act" href="/media/browse?trash=1">
      <span class="ic"><Icon name="trash" size={17} /></span>
      <b>Trash</b><span class="hint">Restore what was deleted</span>
    </a>
  </section>

  {#if mstate.ready}<div class="projects"><ProjectsPanel /></div>{/if}

  <!-- ———————————————————————————————————————————————————————— recent ——— -->
  <section class="mg-section recent">
    <div class="head">
      <h2>Latest in</h2>
      {#if recent.length}<span class="mg-count">{recent.length}</span>{/if}
      <div class="mg-actions">
        <a class="mg-btn ghost sm" href="/media/browse">All clips<Icon name="chevronRight" size={14} /></a>
      </div>
    </div>
    {#if mstate.ready && !recent.length}
      <Empty icon="film" title="Nothing indexed yet" hint="Run a re-index once the footage drive is connected." />
    {:else}
      <div class="strip mg-noscroll">
        {#if !mstate.ready}
          {#each Array(8) as _, i (i)}
            <div class="rcard"><Skeleton h="100%" r="12px" delay={i * 60} /></div>
          {/each}
        {:else}
          {#each recent as v, i (v.id)}
            <a class="rcard real mg-rise" style:--i={i} href="/media/browse?open={v.id}">
              {#if thumbUrl(v)}
                <img src={thumbUrl(v)} alt="" loading="lazy" />
              {:else}
                <span class="noimg"><Icon name="film" size={18} /></span>
              {/if}
              <span class="cap">{v.filename}</span>
            </a>
          {/each}
        {/if}
      </div>
    {/if}
  </section>
{/if}

<style>
  /* ————————————————————————————————————————————————————————— stage ——— */
  .stage {
    position: relative; isolation: isolate; overflow: hidden;
    border-radius: var(--mc-r); border: 1px solid var(--mc-line);
    min-height: clamp(200px, 30vh, 340px); margin-bottom: 12px;
    display: flex; flex-direction: column; justify-content: flex-end;
    padding: clamp(16px, 2.4vw, 24px);
    background: var(--mc-inset);
  }
  .film { position: absolute; inset: 0; z-index: -2; }
  .film video {
    position: absolute; inset: 0; width: 100%; height: 100%;
    object-fit: cover; opacity: 0; transition: opacity 1.2s ease; will-change: opacity;
  }
  .film video.on { opacity: 1; }
  /* footage is the one place a photographic scrim is earned: it keeps the
     caption legible over whatever frame is playing */
  .veil {
    position: absolute; inset: 0; z-index: -1;
    background: linear-gradient(180deg, rgba(0, 0, 0, 0) 40%, rgba(0, 0, 0, 0.72) 100%);
  }
  .caption { max-width: 620px; min-width: 0; padding-right: 96px; }
  .caption .mg-label { color: var(--mc-ink2); }
  .line { margin: 4px 0 0; font: 600 clamp(18px, 2.4vw, 26px)/1.2 var(--mc-font); letter-spacing: -0.02em; color: var(--mc-ink); }
  .now {
    margin: 6px 0 0; font: 400 12px/1.4 var(--mc-mono); color: var(--mc-ink2);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .dots { position: absolute; right: clamp(8px, 2vw, 16px); bottom: clamp(8px, 2vw, 16px); display: flex; }
  /* a 44px hit area around a 22×3 bar */
  .dots button { width: 32px; height: 44px; border: 0; padding: 0; background: none; cursor: pointer; display: grid; place-items: center; }
  .dots i { display: block; width: 22px; height: 3px; border-radius: 2px; background: var(--mc-line3); transition: background var(--mc-t-fast), transform var(--mc-t) var(--mc-ease); }
  .dots button.on i { background: var(--mc-ink); transform: scaleY(1.6); }

  /* ————————————————————————————————————————————————————————— tiles ——— */
  .tiles { display: grid; gap: 12px; grid-template-columns: repeat(4, minmax(0, 1fr)); }
  a.mg-stat-tile { transition: border-color var(--mc-t-fast); }
  a.mg-stat-tile:hover { border-color: var(--mc-line2); }

  /* ——————————————————————————————————————————————————————— running ——— */
  .work { margin-top: 12px; }
  .work > .head { align-items: center; }
  .pct { margin-left: auto; color: var(--mc-warn); }
  .dim { margin-bottom: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  /* ——————————————————————————————————————————————————————— actions ——— */
  .lab { margin: 24px 0 10px; }
  .act { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; min-height: 44px; }
  .act .ic {
    width: 34px; height: 34px; border-radius: 10px; margin-bottom: 10px;
    display: grid; place-items: center; color: var(--mc-ink2);
    background: var(--mc-raised); border: 1px solid var(--mc-line);
  }
  .act b { font: 600 14px/1.3 var(--mc-font); letter-spacing: -0.01em; color: var(--mc-ink); }
  .act .hint { font: 400 12px/1.45 var(--mc-font); color: var(--mc-ink3); }
  .projects { margin-top: 24px; }

  /* ———————————————————————————————————————————————————————— recent ——— */
  .recent { margin-top: 24px; }
  .recent > .head { align-items: center; padding-top: 6px; padding-bottom: 6px; min-height: 48px; }
  .recent > .head > .mg-actions { margin-left: auto; }
  .strip { display: flex; gap: 10px; overflow-x: auto; padding: 16px; }
  .rcard {
    flex: none; width: min(190px, 58vw); aspect-ratio: 16 / 10; border-radius: var(--mc-r-md);
    overflow: hidden; position: relative; background: var(--mc-inset); border: 1px solid var(--mc-line);
  }
  .rcard.real { transition: border-color var(--mc-t-fast), transform var(--mc-t) var(--mc-ease); }
  .rcard.real:hover { border-color: var(--mc-line2); transform: translateY(-2px); }
  .rcard img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .noimg { position: absolute; inset: 0; display: grid; place-items: center; color: var(--mc-ink3); }
  .cap {
    position: absolute; left: 0; right: 0; bottom: 0; padding: 22px 10px 8px;
    font: 500 11.5px/1.3 var(--mc-font); color: var(--mc-ink);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    background: linear-gradient(180deg, transparent, rgba(0, 0, 0, 0.8));
  }

  @media (max-width: 760px) {
    .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  }
  @media (max-width: 560px) {
    .acts { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .act .hint { display: none; }
    .caption { padding-right: 0; }
    .dots { top: 8px; bottom: auto; }
  }
  @media (prefers-reduced-motion: reduce) {
    .film video { transition: none; }
    .rcard.real:hover { transform: none; }
  }
</style>
