<script>
  /* Settings and jobs — the replacement for Zerko's first-run wizard.

     The wizard is blocked at the mount (media.py) because it can browse any
     folder on the host and because this install is configured by environment
     variables, not by clicking through a setup screen. So this page is
     read-mostly: it shows where everything is pointed, what is running, and
     the handful of maintenance passes worth starting by hand.

     On top of that sit the Zerko 1.2–1.4 settings: who you are (roles follow
     the dashboard's People page), which heavy features this server has, and
     the admin switches — AI keys, caption defaults, trash retention, the
     library check and tag rules. Each card is only drawn for a role that can
     use it (/api/me capabilities); the server checks again regardless. */
  import { onMount } from 'svelte';
  import { rise } from '$lib/motion.js';
  import { mstate, boot, watchJobs, runRescan, runProxies, runAutoTag, say } from '$lib/media.svelte.js';
  import { media, fmtBytes } from '$lib/media.js';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import { me, can, CAPS } from '$lib/media/portals.js';
  import AccessCard from '$lib/components/media/settings/AccessCard.svelte';
  import FeaturesCard from '$lib/components/media/settings/FeaturesCard.svelte';
  import AiCard from '$lib/components/media/settings/AiCard.svelte';
  import CaptionsCard from '$lib/components/media/settings/CaptionsCard.svelte';
  import TrashCard from '$lib/components/media/settings/TrashCard.svelte';
  import LibraryCheckCard from '$lib/components/media/settings/LibraryCheckCard.svelte';
  import TagRulesCard from '$lib/components/media/settings/TagRulesCard.svelte';

  let server = $state(null);
  let storage = $state(null);
  let who = $state(null);
  let whoErr = $state('');

  const isAdmin = $derived(can(who, CAPS.ADMIN));

  onMount(() => {
    let stop = () => {};
    (async () => {
      await boot();
      stop = watchJobs();
      if (mstate.ready) {
        me().then((w) => (who = w)).catch((e) => (whoErr = e.message));
        media.serverStats().then((s) => (server = s)).catch(() => {});
        media.storage().then((s) => (storage = s)).catch(() => {});
      }
    })();
    return () => stop();
  });

  /* After an AI key changes, the feature flags on the status payload are
     stale; fetch them again so every page's greyed-out buttons catch up. */
  async function refreshStatus() {
    try { mstate.status = await media.status(); } catch { /* keep the old one */ }
  }

  const root = $derived(mstate.status?.media_root);
  const jobs = $derived(mstate.jobs?.running || []);
  const recent = $derived((mstate.jobs?.recent || []).slice(0, 8));

  /* Indexing reports a percentage when it knows one; when it doesn't, the bar
     sweeps rather than inventing a number. */
  const scanPct = $derived.by(() => {
    const r = mstate.rescan;
    if (!r?.running) return null;
    const done = r.done ?? r.processed;
    return r.total ? Math.round((done / r.total) * 100) : null;
  });

  const tone = (s) => (s === 'completed' ? 'ok' : s === 'failed' ? 'crit' : 'warn');

  async function repair() {
    try { await media.repairThumbs(); say('Redrawing missing thumbnails'); }
    catch (e) { say(e.message, 'error'); }
  }
  async function clearJobs() {
    try { await media.clearJobs(); say('Cleared finished jobs'); }
    catch (e) { say(e.message, 'error'); }
  }
</script>

<svelte:head><title>Settings · Media</title></svelte:head>

<!-- —————————————————————————————————————————————————————— header row ——— -->
<div class="mg-row">
  <h2 class="mg-h2">Settings</h2>
  <span class="mg-count">{mstate.status?.version ? `Zerko ${mstate.status.version}` : mstate.status?.prefix || '/zerko'}</span>
</div>

{#if mstate.ready}
  <AccessCard {who} error={whoErr} />
{/if}
<FeaturesCard status={mstate.status} />

<!-- ————————————————————————————————————————————————— where things are ——— -->
<section class="sec">
  <span class="mg-label">Where things are</span>

  <div class="set mg-panel">
    <div class="l">
      <b>Footage drive</b>
      <span class="hint mono">{root?.path || 'not configured'}</span>
      {#if !root?.ok && root?.message}<span class="hint">{root.message}</span>{/if}
    </div>
    <span class="mg-chip {root?.ok ? 'ok' : 'warn'}">
      <span class="dot"></span>{root?.ok ? 'Mounted' : 'Missing'}
    </span>
  </div>

  <div class="set mg-panel">
    <div class="l">
      <b>Catalogue</b>
      <span class="hint mono">{mstate.status?.data_dir || '—'}</span>
    </div>
  </div>

  <div class="set mg-panel">
    <div class="l">
      <b>API mount</b>
      <span class="hint">Where the media backend answers</span>
    </div>
    <span class="val mono">{mstate.status?.prefix || '/zerko'}</span>
  </div>

  <div class="set mg-panel">
    <div class="l">
      <b>Backend</b>
      <span class="hint">
        {mstate.status?.backend ? 'Running in this process' : 'Not installed'}
      </span>
      {#if mstate.status?.backend_error}<span class="hint">{mstate.status.backend_error}</span>{/if}
    </div>
    <span class="mg-chip {mstate.status?.backend ? 'ok' : 'crit'}">
      <span class="dot"></span>{mstate.status?.backend ? 'Live' : 'Down'}
    </span>
  </div>

  <p class="note">
    The drive is set with the <code>MEDIA_ROOT</code> environment variable and
    read once at startup, so changing it needs a restart. Everything derived
    from it — catalogue, thumbnails, proxies — lives under
    <code>DATA_DIR</code> so it survives a redeploy.
  </p>
</section>

<!-- ———————————————————————————————————————————————————— maintenance ——— -->
<section class="sec">
  <span class="mg-label">Maintenance</span>

  <div class="set mg-panel">
    <div class="l">
      <b>Re-index the drive</b>
      <span class="hint">Pick up anything new on the footage drive</span>
    </div>
    <button class="mg-btn secondary sm" onclick={runRescan} disabled={!mstate.ready}>
      <Icon name="refresh" size={14} />Run
    </button>
  </div>

  <div class="set mg-panel">
    <div class="l">
      <b>Build missing proxies</b>
      <span class="hint">
        {#if mstate.proxies}
          {mstate.proxies.completed ?? 0} clips have a proxy,
          {mstate.proxies.pending ?? 0} still need one
        {:else}
          Small, seekable copies for the browser
        {/if}
      </span>
    </div>
    <button class="mg-btn secondary sm" onclick={runProxies} disabled={!mstate.ready || !can(who, CAPS.PROXY)}
            title={can(who, CAPS.PROXY) ? null : 'Proxy control is admin-only'}>
      <Icon name="film" size={14} />Run
    </button>
  </div>

  <div class="set mg-panel">
    <div class="l">
      <b>Auto-tag</b>
      <span class="hint">Camera, stage and spoken-word tags</span>
    </div>
    <button class="mg-btn secondary sm" onclick={runAutoTag} disabled={!mstate.ready || !isAdmin}
            title={isAdmin ? null : 'Tagging passes are admin-only'}>
      <Icon name="sparkles" size={14} />Run
    </button>
  </div>

  <div class="set mg-panel">
    <div class="l">
      <b>Repair thumbnails</b>
      <span class="hint">Redraw anything that lost its still</span>
    </div>
    <button class="mg-btn secondary sm" onclick={repair} disabled={!mstate.ready || !isAdmin}
            title={isAdmin ? null : 'Thumbnail repair is admin-only'}>
      <Icon name="image" size={14} />Run
    </button>
  </div>

</section>

<!-- ————————————————————————————————————————— role-gated settings cards ——— -->
{#if who}
  {#if isAdmin}<AiCard onchanged={refreshStatus} />{/if}
  {#if can(who, CAPS.SHOOTS)}<CaptionsCard />{/if}
  {#if can(who, CAPS.HARD_DELETE)}<TrashCard />{/if}
  {#if isAdmin}
    <LibraryCheckCard />
    <TagRulesCard transcription={!!mstate.status?.features?.transcription} />
  {/if}
{/if}

<!-- ————————————————————————————————————————————————————— running now ——— -->
<section class="sec">
  <span class="mg-label">Running now</span>

  {#if mstate.rescan?.running}
    <div class="job mg-panel" in:rise>
      <div class="jh">
        <span class="pulse" aria-hidden="true"><span class="ring mg-ping"></span><span class="core"></span></span>
        <b>Indexing</b>
        <span class="dim">{mstate.rescan.message || ''}</span>
        {#if scanPct != null}<span class="pct mg-tnum">{scanPct}%</span>{/if}
      </div>
      <div class="mg-bar" class:indeterminate={scanPct == null}>
        <i style:width={scanPct != null ? scanPct + '%' : null}></i>
      </div>
    </div>
  {/if}

  {#each jobs as j (j.id ?? j.video_id)}
    <div class="job mg-panel" in:rise>
      <div class="jh">
        <span class="pulse" aria-hidden="true"><span class="ring mg-ping"></span><span class="core"></span></span>
        <b class="cap">{j.type || 'job'}</b>
        <span class="dim">{j.filename || j.video_id}</span>
        {#if j.progress != null}<span class="pct mg-tnum">{Math.round(j.progress)}%</span>{/if}
      </div>
      <div class="mg-bar" class:indeterminate={j.progress == null}>
        <i style:width={j.progress != null ? Math.round(j.progress) + '%' : null}></i>
      </div>
    </div>
  {/each}

  {#if !jobs.length && !mstate.rescan?.running}
    <Empty icon="clock" title="Nothing running"
           hint="Passes you start from here — indexing, proxies, tags — show their progress in this spot." />
  {/if}
</section>

<!-- ———————————————————————————————————————————————— recently finished ——— -->
{#if recent.length}
  <section class="sec">
    <span class="mg-label">Recently finished</span>
    {#each recent as j (j.id ?? j.video_id)}
      <div class="past">
        <span class="mg-chip {tone(j.status)}"><span class="dot"></span>{j.status}</span>
        <span class="pn">{j.filename || j.type}</span>
      </div>
    {/each}
    <div class="after">
      <button class="mg-btn ghost sm" onclick={clearJobs}><Icon name="trash" size={14} />Clear the list</button>
    </div>
  </section>
{/if}

<!-- ————————————————————————————————————————————————————————— machine ——— -->
<section class="sec">
  <span class="mg-label">Machine</span>
  {#if !server}
    {#each Array(4) as _, i (i)}
      <div class="skel"><Skeleton h="56px" r="12px" delay={i * 60} /></div>
    {/each}
  {:else}
    {#if server.cpu_percent != null}
      <div class="set mg-panel">
        <div class="l"><b>CPU</b></div>
        <span class="val mg-tnum">{Math.round(server.cpu_percent)}%</span>
      </div>
    {/if}
    {#if server.memory_percent != null}
      <div class="set mg-panel">
        <div class="l"><b>Memory</b></div>
        <span class="val mg-tnum">{Math.round(server.memory_percent)}%</span>
      </div>
    {/if}
    {#if server.disk_free != null}
      <div class="set mg-panel">
        <div class="l"><b>Disk free</b></div>
        <span class="val mg-tnum">{fmtBytes(server.disk_free)}</span>
      </div>
    {/if}
    {#if storage?.total != null}
      <div class="set mg-panel">
        <div class="l"><b>Library</b></div>
        <span class="val mg-tnum">{fmtBytes(storage.total)}</span>
      </div>
    {/if}
  {/if}
</section>

<style>
  /* Sections are told apart by air and one quiet label, not by boxes. */
  .sec { margin-bottom: 24px; }
  .sec:last-of-type { margin-bottom: 0; }
  .sec > .mg-label { margin-bottom: 10px; }

  /* —————————————————————————————————————————————————— a setting row ——— */
  .set {
    display: flex; align-items: center; gap: 12px;
    min-height: 56px; padding: 11px 14px; margin-bottom: 6px;
    border-radius: var(--mc-r-md);
  }
  .set:last-child { margin-bottom: 0; }
  .l { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .l b { font: 500 13.5px/1.25 var(--mc-font); letter-spacing: -0.01em; color: var(--mc-ink); }
  .hint { font: 400 12px/1.45 var(--mc-font); color: var(--mc-ink3); overflow-wrap: anywhere; }
  .mono { font: 12px/1.45 var(--mc-mono); }
  .val { flex: none; font: 500 13px/1 var(--mc-font); color: var(--mc-ink); }
  .val.mono { font: 12px/1 var(--mc-mono); color: var(--mc-ink2); }

  .note { margin: 10px 2px 0; font: 400 12.5px/1.6 var(--mc-font); color: var(--mc-ink3); }
  .note code { font: 11.5px/1.5 var(--mc-mono); color: var(--mc-ink2); }

  /* ———————————————————————————————————————————————————— a live job ——— */
  .job { border-radius: var(--mc-r-md); padding: 12px 14px; margin-bottom: 6px; }
  .jh { display: flex; align-items: center; gap: 9px; margin-bottom: 9px; }
  .jh b { flex: none; font: 600 13px/1 var(--mc-font); color: var(--mc-ink); }
  .cap { text-transform: capitalize; }
  .jh .dim { flex: 1; min-width: 0; font: 400 12px/1 var(--mc-font); color: var(--mc-ink3);
             overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pct { flex: none; font: 600 12.5px/1 var(--mc-font); color: var(--mc-accent); }
  .pulse { position: relative; display: flex; width: 8px; height: 8px; flex: none; }
  .core, .ring { position: absolute; inset: 0; border-radius: 50%; background: var(--mc-accent); }
  .ring { opacity: 0.6; }

  /* —————————————————————————————————————————————— what already ran ——— */
  .past { display: flex; align-items: center; gap: 10px; min-height: 34px; padding: 3px 2px; }
  .past .mg-chip { flex: none; text-transform: capitalize; }
  .pn { min-width: 0; font: 400 12.5px/1.3 var(--mc-font); color: var(--mc-ink2);
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .after { margin-top: 8px; }

  .skel { margin-bottom: 6px; }
  @media (pointer: coarse) { .set .mg-btn, .after .mg-btn { min-height: 44px; } }
</style>
