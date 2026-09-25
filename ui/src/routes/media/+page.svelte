<script>
  /* The Media overview.

     The stage plays the library back at you: up to five of its own clips,
     muted and looping, crossfading one into the next. It is the fastest way to
     say "this is your footage, it is indexed, it is here" — and on a deploy
     with no footage drive it falls back to the same hero photograph the scene
     is standing on, so the page is never a grey box.

     Everything below it is a read: counts that arrive, whatever is running
     shown as a moving bar rather than a number, and the four things anyone
     actually comes here to start. */
  import { onMount } from 'svelte';
  import { fly } from 'svelte/transition';
  import { mstate, boot, runRescan, runProxies, runAutoTag, can, CAP } from '$lib/media.svelte.js';
  import { media, streamUrl, thumbUrl, fmtBytes, fmtHours } from '$lib/media.js';
  import CountUp from '$lib/components/CountUp.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import ActivityBell from '$lib/components/media/library/ActivityBell.svelte';
  import ProjectsPanel from '$lib/components/media/library/ProjectsPanel.svelte';

  let reel = $state([]);          // clips with proxies, for the montage
  let shot = $state(0);           // which one is on screen
  let heroFail = $state(false);
  let recent = $state([]);
  let timer;

  const hour = new Date().getHours();
  const stillHero = hour < 10 ? 'morning' : hour < 17 ? 'day' : 'dusk';

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

  const tiles = $derived(s ? [
    { k: 'Clips', v: s.total_videos || 0, f: (n) => Math.round(n).toLocaleString('en-ZA').replace(/,/g, ' ') },
    { k: 'Storage', v: s.total_storage || 0, f: fmtBytes },
    { k: 'Hours', v: (s.avg_duration || 0) * (s.total_videos || 0), f: fmtHours },
    { k: 'Folders', v: s.total_projects || 0, f: (n) => String(Math.round(n)) }
  ] : []);

  const clipCount = $derived(s?.total_videos ?? null);
</script>

<svelte:head><title>Media · Oblivion</title></svelte:head>

<!-- ————————————————————————————————————————————————————— header row ——— -->
<div class="mg-row">
  <h2 class="mg-h2">Media</h2>
  {#if clipCount != null}
    <span class="mg-count">{clipCount.toLocaleString('en-ZA').replace(/,/g, ' ')} clips</span>
  {/if}
  <div class="mg-actions">
    {#if mstate.ready}<ActivityBell />{/if}
    <a class="mg-btn secondary sm" href="/media/search"><Icon name="search" size={14} />Search</a>
    <a class="mg-btn primary sm" href="/media/browse"><Icon name="grid" size={14} />Browse</a>
  </div>
</div>

<!-- ————————————————————————————————————————————————————— the stage ——— -->
<section class="stage" class:still={!reel.length || heroFail}>
  <div class="film" aria-hidden="true">
    {#if reel.length && !heroFail}
      {#each reel as clip, i (clip.id)}
        <video
          class:on={i === shot}
          src={streamUrl(clip)}
          poster={thumbUrl(clip)}
          muted autoplay loop playsinline preload={i === 0 ? 'auto' : 'none'}
          onerror={() => { if (i === 0) heroFail = true; }}
        ></video>
      {/each}
    {:else}
      <div class="still-img" style:background-image="url(/hero-{stillHero}.jpg)"></div>
    {/if}
  </div>
  <div class="veil" aria-hidden="true"></div>

  <div class="caption">
    <span class="mg-label">Media library</span>
    <p class="line">{s ? 'Everything you have shot, findable.' : 'Media library'}</p>
    {#if reel.length && !heroFail}
      <p class="now">{reel[shot]?.filename}</p>
    {/if}
  </div>

  {#if reel.length > 1 && !heroFail}
    <div class="dots" role="tablist" aria-label="Montage">
      {#each reel as clip, i (clip.id)}
        <button role="tab" aria-selected={i === shot} aria-label={clip.filename}
                class:on={i === shot} onclick={() => (shot = i)}></button>
      {/each}
    </div>
  {/if}
</section>

<!-- ————————————————————————————————————————————————————— the numbers ——— -->
<section class="mg-grid c4 tiles">
  {#if !s}
    {#each [0, 1, 2, 3] as i (i)}
      <div class="mg-glass-soft tile">
        <Skeleton h="0.68rem" w="42%" delay={i * 90} />
        <div style="height:0.6rem"></div>
        <Skeleton h="1.5rem" w="66%" delay={i * 90} />
      </div>
    {/each}
  {:else}
    {#each tiles as t, i (t.k)}
      <div class="mg-glass-soft tile" in:fly={{ y: 10, duration: 320, delay: i * 60 }}>
        <span class="mg-label">{t.k}</span>
        <b class="mg-tnum"><CountUp value={t.v} format={t.f} /></b>
      </div>
    {/each}
  {/if}
</section>

<!-- ————————————————————————————————————————————————— what's running ——— -->
{#if rescan?.running || running.length}
  <section class="mg-glass-soft work" in:fly={{ y: 10, duration: 300 }}>
    <div class="wh">
      <span class="dot" aria-hidden="true"><span class="ring mg-ping"></span><span class="core"></span></span>
      <b>{rescan?.running ? 'Indexing the library' : `${running.length} job${running.length === 1 ? '' : 's'} running`}</b>
      <span class="dim">{rescan?.message || running[0]?.filename || ''}</span>
      {#if scanPct != null}<span class="pct mg-tnum">{scanPct}%</span>{/if}
    </div>
    <div class="mg-bar" class:indeterminate={scanPct == null}>
      <i style:width={scanPct != null ? scanPct + '%' : null}></i>
    </div>
  </section>
{/if}

<!-- ————————————————————————————————————————————————— quick actions ——— -->
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

{#if mstate.ready}<ProjectsPanel />{/if}

<!-- —————————————————————————————————————————————————————————— recent ——— -->
<section class="recent">
  <div class="mg-row rh">
    <h3 class="mg-h2 sm">Latest in</h3>
    <div class="mg-actions">
      <a class="mg-btn ghost sm" href="/media/browse">All clips<Icon name="chevronRight" size={14} /></a>
    </div>
  </div>
  <div class="strip mg-noscroll">
    {#if !mstate.ready && !mstate.error}
      {#each Array(8) as _, i (i)}
        <div class="rcard"><Skeleton h="100%" r="14px" delay={i * 60} /></div>
      {/each}
    {:else if !recent.length}
      <p class="none">Nothing indexed yet. Run a re-index once the drive is connected.</p>
    {:else}
      {#each recent as v, i (v.id)}
        <a class="rcard real mg-glass-soft" href="/media/browse?open={v.id}"
           in:fly={{ y: 12, duration: 340, delay: Math.min(i * 40, 320) }}>
          {#if thumbUrl(v)}
            <img src={thumbUrl(v)} alt="" loading="lazy" />
          {:else}
            <span class="noimg">no thumbnail</span>
          {/if}
          <span class="cap">{v.filename}</span>
        </a>
      {/each}
    {/if}
  </div>
</section>

<style>
  /* ————————————————————————————————————————————————————————— stage ——— */
  .stage {
    position: relative; isolation: isolate; overflow: hidden;
    border-radius: 18px; border: 1px solid var(--mc-line);
    min-height: clamp(220px, 34vh, 380px);
    display: flex; flex-direction: column; justify-content: flex-end;
    padding: clamp(14px, 2.4vw, 26px);
    background: var(--mc-inset);
  }
  .film { position: absolute; inset: 0; z-index: -2; }
  .film video, .still-img {
    position: absolute; inset: 0; width: 100%; height: 100%;
    object-fit: cover; opacity: 0; transition: opacity 1.4s ease; will-change: opacity;
  }
  .film video.on { opacity: 1; }
  .still-img { opacity: 1; background-size: cover; background-position: center; }
  .veil {
    position: absolute; inset: 0; z-index: -1;
    background: linear-gradient(180deg, rgba(0, 0, 0, 0.45) 0%, rgba(0, 0, 0, 0.1) 38%,
                                rgba(0, 0, 0, 0.3) 66%, rgba(0, 0, 0, 0.78) 100%);
  }

  .caption { max-width: 620px; min-width: 0; }
  .caption .mg-label { color: rgba(255, 255, 255, 0.72); }
  .line {
    margin: 4px 0 0; font: 600 clamp(19px, 2.6vw, 30px)/1.15 var(--mc-font);
    letter-spacing: -0.02em; color: #fff; text-shadow: 0 2px 22px rgba(0, 0, 0, 0.5);
  }
  .now {
    margin: 7px 0 0; font: 400 12px/1.4 var(--mc-mono); color: rgba(255, 255, 255, 0.72);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }

  .dots { position: absolute; right: clamp(14px, 2.4vw, 26px); bottom: clamp(14px, 2.4vw, 26px);
          display: flex; gap: 5px; }
  .dots button {
    width: 22px; height: 3px; border-radius: 2px; border: 0; padding: 0; cursor: pointer;
    background: rgba(255, 255, 255, 0.35); transition: background 0.25s, transform 0.25s;
  }
  .dots button.on { background: #fff; transform: scaleY(1.6); }

  /* ————————————————————————————————————————————————————————— tiles ——— */
  .tiles { margin-top: 12px; }
  .tile { border-radius: var(--mc-r-md); padding: 13px 15px; }
  .tile b { display: block; margin-top: 3px; font: 600 24px/1.1 var(--mc-font);
            letter-spacing: -0.025em; color: var(--mc-ink); }

  /* ——————————————————————————————————————————————————————— running ——— */
  .work { margin-top: 12px; padding: 13px 15px; border-radius: var(--mc-r-md); }
  .wh { display: flex; align-items: center; gap: 9px; margin-bottom: 10px; flex-wrap: wrap; }
  .wh b { font: 600 13.5px/1 var(--mc-font); color: var(--mc-ink); }
  .wh .dim { flex: 1; min-width: 0; font-size: 12.5px; color: var(--mc-ink3);
             overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pct { font: 600 12.5px/1 var(--mc-font); color: var(--mc-accent); }
  .dot { position: relative; display: flex; width: 8px; height: 8px; flex: none; }
  .core, .ring { position: absolute; inset: 0; border-radius: 50%; background: var(--mc-accent); }
  .ring { opacity: 0.6; }

  /* ——————————————————————————————————————————————————————— actions ——— */
  .acts { margin-top: 12px; }
  .act { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; }
  .act .ic {
    width: 34px; height: 34px; border-radius: 11px; margin-bottom: 8px;
    display: grid; place-items: center; color: var(--mc-ink2);
    background: rgba(255, 255, 255, 0.07); border: 1px solid var(--mc-line);
  }
  .act b { font: 600 14px/1.3 var(--mc-font); letter-spacing: -0.01em; color: var(--mc-ink); }
  .act .hint { font: 400 12px/1.45 var(--mc-font); color: var(--mc-ink3); }

  /* ———————————————————————————————————————————————————————— recent ——— */
  .recent { margin-top: 26px; }
  .rh { margin-bottom: 10px; }
  .mg-h2.sm { font-size: 15px; }
  .strip { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 4px; }
  .rcard {
    flex: none; width: min(190px, 62vw); aspect-ratio: 16 / 10; border-radius: 14px;
    overflow: hidden; position: relative; background: rgba(255, 255, 255, 0.05);
  }
  .rcard.real { transition: transform 0.24s cubic-bezier(0.2, 0.8, 0.2, 1), border-color 0.2s; }
  .rcard.real:hover { transform: translateY(-3px); border-color: var(--mc-line2); }
  .rcard img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .noimg { position: absolute; inset: 0; display: grid; place-items: center;
           font-size: 11.5px; color: var(--mc-ink3); }
  .cap {
    position: absolute; left: 0; right: 0; bottom: 0; padding: 22px 9px 7px;
    font: 500 11.5px/1.3 var(--mc-font); color: #fff;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    background: linear-gradient(180deg, transparent, rgba(0, 0, 0, 0.85));
  }
  .none { margin: 0; padding: 22px 0; font-size: 13px; color: var(--mc-ink3); }

  @media (max-width: 560px) {
    .acts { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .act .hint { display: none; }
    .tile b { font-size: 20px; }
  }

  @media (prefers-reduced-motion: reduce) {
    .film video { transition: none; }
    .rcard.real:hover { transform: none; }
  }
</style>
