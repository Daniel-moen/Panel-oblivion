<script>
  /* Portals: links a client opens without an account.

     Three kinds (send / receive / both — see $lib/media/portals.js). Each
     card shows whether the client has said they are done, and one tap down,
     what they picked, the spots they marked on photos, what they sent in
     (and a way to file it), and the trail of what they did.

     The link a client opens is /media/s/<token>, rendered by share_page.py,
     so the URL is rebuilt here from the token rather than taken from Zerko's
     own "/s/<token>". Managing portals needs shares.manage; an account
     without it sees why instead of a page of broken buttons. */
  import { onMount } from 'svelte';
  import { mstate, boot, say } from '$lib/media.svelte.js';
  import { media } from '$lib/media.js';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import { portals, me, can, CAPS, portalLink, kindOf } from '$lib/media/portals.js';
  import NewPortal from '$lib/components/media/portals/NewPortal.svelte';
  import PortalCard from '$lib/components/media/portals/PortalCard.svelte';

  let who = $state(null);
  let shares = $state([]);
  let loading = $state(true);
  let folders = $state([]);
  let shoots = $state([]);
  let watermarks = $state([]);
  let open = $state(false);
  let show = $state('live');

  const canShares = $derived(can(who, CAPS.SHARES));
  const canShoots = $derived(can(who, CAPS.SHOOTS));
  const canOrganise = $derived(can(who, CAPS.ORGANISE));

  const shootName = (id) => {
    const s = shoots.find((x) => x.id === id);
    return s ? s.address + (s.suburb ? `, ${s.suburb}` : '') : id ? `Shoot ${id}` : null;
  };

  const live = $derived(shares.filter((s) => !s.revoked && !s.expired));
  const waiting = $derived(shares.filter((s) => (s.intake_waiting || 0) > 0 && !s.revoked));
  const listed = $derived(
    show === 'live' ? live
    : show === 'done' ? shares.filter((s) => s.confirmed_at)
    : show === 'inbox' ? waiting
    : shares
  );

  onMount(async () => {
    await boot();
    if (!mstate.ready) { loading = false; return; }
    try { who = await me(); } catch { /* treated as no rights below */ }
    if (!can(who, CAPS.SHARES)) { loading = false; return; }
    await Promise.all([
      load(),
      media.folderTree().then((f) => (folders = flat(f))).catch(() => {}),
      loadWatermarks(),
      can(who, CAPS.SHOOTS)
        ? portals.shoots().then((r) => (shoots = r?.shoots || [])).catch(() => {})
        : null
    ]);
  });

  function flat(nodes, depth = 0, out = []) {
    for (const n of nodes || []) {
      out.push({ id: n.id, name: '— '.repeat(depth) + n.name });
      if (n.children?.length) flat(n.children, depth + 1, out);
    }
    return out;
  }

  async function loadWatermarks() {
    try { watermarks = (await portals.watermarks())?.watermarks || []; } catch { /* optional */ }
  }

  async function load() {
    try { shares = (await portals.list()) || []; }
    catch (e) { say(e.message, 'error'); }
    finally { loading = false; }
  }

  async function created(made) {
    open = false;
    show = 'live';
    await load();
    if (made?.token) {
      try { await navigator.clipboard.writeText(portalLink(made.token)); say('Link copied'); }
      catch { /* the card has a copy button */ }
    }
  }

  const counts = $derived({
    live: live.length,
    done: shares.filter((s) => s.confirmed_at).length,
    inbox: waiting.length,
    all: shares.length
  });
  const receiving = $derived(shares.filter((s) => kindOf(s) !== 'send').length);
</script>

<svelte:head><title>Portals · Media</title></svelte:head>

<div class="mg-row">
  <h2 class="mg-h2">Portals</h2>
  {#if !loading && canShares}
    <span class="mg-count">{shares.length} link{shares.length === 1 ? '' : 's'}</span>
  {/if}
  <div class="mg-actions">
    {#if canShares}
      <button class="mg-btn primary sm" onclick={() => (open = true)} disabled={!mstate.ready}>
        <Icon name="plus" size={14} />New portal
      </button>
    {/if}
  </div>
</div>

{#if canShares}
  <NewPortal {open} onclose={() => (open = false)} oncreated={created}
             {folders} {shoots} {watermarks} {canShoots} onwatermark={loadWatermarks} />
{/if}

{#if loading}
  <div class="list">
    {#each Array(3) as _, i (i)}
      <div class="mg-card">
        <Skeleton h="1rem" w="35%" delay={i * 80} />
        <div style="height:0.6rem"></div>
        <Skeleton h="0.8rem" w="60%" delay={i * 80} />
      </div>
    {/each}
  </div>
{:else if !mstate.ready}
  <Empty icon="alert" title="The media library is offline"
         hint={mstate.error || 'The media backend is not reachable from this deployment.'} />
{:else if !canShares}
  <Empty icon="lock" title="Portals aren't part of your role"
         hint="Making and reading client links needs the Editor or Admin media role. Roles come from the dashboard's People page." />
{:else if !shares.length}
  <Empty icon="share" title="No portals yet"
         hint="Send a set for the client to watch, pick and comment on; or a receiving link they can drop their own files into. What they do comes back here.">
    {#snippet children()}
      <button class="mg-btn primary sm" onclick={() => (open = true)}>
        <Icon name="plus" size={14} />New portal
      </button>
    {/snippet}
  </Empty>
{:else}
  <div class="filter mg-noscroll">
    <Seg label="Show" value={show} onchange={(v) => (show = v)}
         options={[
           { value: 'live', label: 'Live', count: counts.live },
           { value: 'done', label: 'Said done', count: counts.done },
           ...(receiving ? [{ value: 'inbox', label: 'To file', count: counts.inbox }] : []),
           { value: 'all', label: 'All', count: counts.all }
         ]} />
  </div>

  {#if !listed.length}
    <p class="none">
      {show === 'done' ? 'No client has pressed “I’m done” yet.'
       : show === 'inbox' ? 'Nothing waiting to be filed.'
       : 'No live portals — switch to All to see the ones that are off or expired.'}
    </p>
  {:else}
    <div class="list">
      {#each listed as s, i (s.id)}
        <PortalCard share={s} shootName={s.shoot_id ? shootName(s.shoot_id) : null}
                    {folders} {watermarks} {canOrganise} onchanged={load}
                    delay={Math.min(i * 50, 300)} />
      {/each}
    </div>
  {/if}
{/if}

<style>
  .list { display: flex; flex-direction: column; gap: 12px; }
  .filter { overflow-x: auto; margin-bottom: 12px; max-width: 100%; }
  .none { margin: 8px 2px; font: 400 13px/1.5 var(--mg-font); color: var(--mg-i3); }
</style>
