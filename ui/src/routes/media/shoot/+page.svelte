<script>
  /* One shoot: /media/shoot?id=3.

     The business record for a property — booking, status, the folders its
     media lives in — and the three things you do with it once shot: write
     the captions, export the listing pack by room, and deliver a client
     link. No [param] route (adapter-static), so the id is a query param. */
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { mstate, say } from '$lib/media.svelte.js';
  import { thumbUrl } from '$lib/media.js';
  import { shoots, STATUSES, STATUS, fmtWhen, can, CAP_SHARES } from '$lib/media/shoots.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import ShootsGate from '$lib/components/media/shoots/ShootsGate.svelte';
  import StatusChip from '$lib/components/media/shoots/StatusChip.svelte';
  import ShootForm from '$lib/components/media/shoots/ShootForm.svelte';
  import FoldersPanel from '$lib/components/media/shoots/FoldersPanel.svelte';
  import FactsCard from '$lib/components/media/shoots/FactsCard.svelte';
  import CaptionsPanel from '$lib/components/media/shoots/CaptionsPanel.svelte';
  import RoomsPanel from '$lib/components/media/shoots/RoomsPanel.svelte';
  import ListingPack from '$lib/components/media/shoots/ListingPack.svelte';
  import DeliverPanel from '$lib/components/media/shoots/DeliverPanel.svelte';

  const id = $derived(Number(page.url.searchParams.get('id')) || null);

  let who = $state(null);
  let shoot = $state(null);
  let missing = $state(false);
  let items = $state([]);
  let form = $state(null);
  let agents = $state([]);
  let editing = $state(false);
  let saving = $state(false);

  const photos = $derived(items.filter((v) => v.media_type === 'photo'));
  const features = $derived(mstate.status?.features || {});
  const STATUS_OPTS = STATUSES.map((s) => ({ value: s, label: STATUS[s].label }));
  const unnamed = $derived(/^shoot (at|in) /i.test(shoot?.address || ''));

  async function ready(me) {
    who = me;
    shoots.agents().then((r) => (agents = r?.agents || [])).catch(() => {});
  }

  /* (Re)load whenever the id changes — including after the gate opens. */
  $effect(() => {
    if (who && id) load(id);
  });

  async function load(sid) {
    missing = false;
    try {
      set(await shoots.get(sid));
    } catch (e) {
      if (e.status === 404) missing = true; else say(e.message, 'error');
    }
  }

  function set(s) {
    const refetch = !shoot || JSON.stringify(shoot.folder_ids) !== JSON.stringify(s.folder_ids);
    shoot = s;
    if (refetch) loadMedia();
  }

  async function loadMedia() {
    const ids = (shoot?.folder_ids || []).filter((x) => x != null);
    const seen = new Set();
    const out = [];
    for (const fid of ids) {
      try {
        for (const v of (await shoots.media(fid)) || []) if (!seen.has(v.id)) { seen.add(v.id); out.push(v); }
      } catch { /* one folder failing is not the page failing */ }
    }
    items = out;
  }

  function startEdit() {
    form = { address: shoot.address, suburb: shoot.suburb || '', agent: shoot.agent || '',
             shoot_date: shoot.shoot_date || '', shoot_time: shoot.shoot_time || '', note: shoot.note || '',
             lat: shoot.lat, lng: shoot.lng, clear_location: false };
    editing = true;
  }

  async function saveEdit(e) {
    e?.preventDefault();
    saving = true;
    try {
      const body = {
        address: form.address.trim(), suburb: form.suburb ?? '', agent: form.agent ?? '',
        shoot_date: form.shoot_date || '', shoot_time: form.shoot_time || '', note: form.note ?? ''
      };
      if (form.lat != null && form.lng != null) { body.lat = form.lat; body.lng = form.lng; }
      else if (form.clear_location) body.clear_location = true;
      set(await shoots.update(shoot.id, body));
      editing = false;
      say('Saved');
    } catch (e2) { say(e2.message, 'error'); }
    finally { saving = false; }
  }

  async function setStatus(v) {
    if (v === shoot.status) return;
    const before = shoot.status;
    shoot.status = v;
    try { set(await shoots.update(shoot.id, { status: v })); say(`Marked ${STATUS[v].label.toLowerCase()}`); }
    catch (e) { shoot.status = before; say(e.message, 'error'); }
  }

  async function setCover(v) {
    try { set(await shoots.update(shoot.id, { cover_video_id: v.id })); say('Cover set'); }
    catch (e) { say(e.message, 'error'); }
  }

  async function lookup() {
    try { set(await shoots.lookupAddress(shoot.id)); say('Found the street address'); }
    catch (e) { say(e.message, 'error'); }
  }

  async function remove() {
    if (!confirm(`Forget ${shoot.address}? Files and folders stay exactly where they are.`)) return;
    try { await shoots.remove(shoot.id); say('Shoot removed'); goto('/media/shoots'); }
    catch (e) { say(e.message, 'error'); }
  }

  const since = (v) => (v ? new Date(v + 'Z').toLocaleDateString('en-ZA', { day: 'numeric', month: 'short' }) : null);
</script>

<svelte:head><title>{shoot?.address || 'Shoot'} · Media</title></svelte:head>

<ShootsGate onready={ready}>
  {#snippet children()}
    <div class="back"><a class="mg-btn ghost sm" href="/media/shoots"><Icon name="chevronLeft" size={14} />Shoots</a></div>

    {#if !id || missing}
      <Empty icon="camera" title="No such shoot" hint="It may have been removed. Pick one from the list.">
        {#snippet children()}<a class="mg-btn primary sm" href="/media/shoots">All shoots</a>{/snippet}
      </Empty>
    {:else if !shoot}
      <div class="sk"><Skeleton h="1.6rem" w="45%" /><Skeleton h="8rem" /><Skeleton h="8rem" delay={80} /></div>
    {:else}
      <header class="head">
        <span class="cover">
          {#if shoot.cover?.thumbnail_path}<img src={thumbUrl(shoot.cover)} alt="" />{:else}<Icon name="camera" size={22} />{/if}
        </span>
        <div class="ttl">
          <h2 class="mg-h2">{shoot.address}</h2>
          <p class="sub">
            {#if shoot.suburb}<span>{shoot.suburb}</span>{/if}
            {#if shoot.agent}<span><Icon name="user" size={12} />{shoot.agent}</span>{/if}
            <span class="mg-tnum"><Icon name="calendar" size={12} />{fmtWhen(shoot)}</span>
            <StatusChip status={shoot.status} />
          </p>
        </div>
      </header>

      <div class="statusrow">
        <Seg options={STATUS_OPTS} value={shoot.status} onchange={setStatus} label="Status" />
        <span class="stamps mg-tnum">
          {#if since(shoot.editing_at)}editing since {since(shoot.editing_at)}{/if}
          {#if since(shoot.posted_at)} · posted {since(shoot.posted_at)}{/if}
        </span>
      </div>

      {#if unnamed && shoot.lat != null}
        <div class="mg-strip warn">
          <span class="ic"><Icon name="mapPin" size={15} /></span>
          <span>This property is a pin without a street address. <button class="mg-btn secondary sm" onclick={lookup}>Look it up</button></span>
        </div>
      {/if}

      <div class="cols">
        <div class="col">
          <section class="mg-card">
            <div class="hd">
              <h3><Icon name="edit" size={15} />Booking</h3>
              {#if !editing}<button class="mg-btn ghost sm" onclick={startEdit}><Icon name="pencil" size={13} />Edit</button>{/if}
            </div>
            {#if editing}
              <form onsubmit={saveEdit}>
                <ShootForm bind:value={form} {agents} near={shoot.lat != null ? { lat: shoot.lat, lng: shoot.lng } : null} idp="ed" />
                <div class="acts">
                  <button type="button" class="mg-btn ghost sm" onclick={() => (editing = false)}>Cancel</button>
                  <button type="submit" class="mg-btn primary sm" disabled={saving}><Icon name="check" size={13} />Save</button>
                </div>
              </form>
            {:else}
              <dl class="mg-kv">
                <div><dt>Address</dt><dd>{shoot.address}</dd></div>
                <div><dt>Suburb</dt><dd>{shoot.suburb || '—'}</dd></div>
                <div><dt>Agent</dt><dd>{shoot.agent || '—'}</dd></div>
                <div><dt>Booked for</dt><dd class="mg-tnum">{fmtWhen(shoot)}</dd></div>
                {#if shoot.lat != null}<div><dt>Pin</dt><dd class="mg-tnum">{shoot.lat.toFixed(5)}, {shoot.lng.toFixed(5)}</dd></div>{/if}
                <div><dt>Notes</dt><dd class="note">{shoot.note || '—'}</dd></div>
                {#if shoot.created_by}<div><dt>Booked by</dt><dd>{shoot.created_by}</dd></div>{/if}
              </dl>
            {/if}
          </section>

          <FoldersPanel {shoot} onchange={set} />

          <section class="mg-card">
            <div class="hd">
              <h3><Icon name="image" size={15} />Media</h3>
              <span class="mg-count">{items.length} file{items.length === 1 ? '' : 's'}</span>
            </div>
            {#if items.length}
              <div class="thumbs">
                {#each items.slice(0, 60) as v (v.id)}
                  <figure class:cov={shoot.cover?.id === v.id}>
                    <a href="/media/browse?open={v.id}" title={v.filename}>
                      {#if v.thumbnail_path}<img src={thumbUrl(v)} alt={v.filename} loading="lazy" />
                      {:else}<span class="ph"><Icon name={v.media_type === 'video' ? 'film' : 'image'} size={16} /></span>{/if}
                      {#if v.media_type === 'video'}<span class="vid"><Icon name="play" size={10} /></span>{/if}
                    </a>
                    {#if shoot.cover?.id !== v.id}
                      <button class="setc" onclick={() => setCover(v)} aria-label="Use {v.filename} as the cover" title="Use as cover"><Icon name="star" size={12} /></button>
                    {:else}
                      <span class="setc on" title="Cover"><Icon name="star" size={12} /></span>
                    {/if}
                  </figure>
                {/each}
              </div>
              {#if items.length > 60}<p class="more">+ {items.length - 60} more in the library</p>{/if}
            {:else}
              <p class="none">{shoot.folders?.length ? 'No media indexed in these folders yet — rescan the library.' : 'Link a folder to see its photos and video here.'}</p>
            {/if}
          </section>

          <FactsCard {shoot} onchange={set} />
        </div>

        <div class="col">
          <CaptionsPanel {shoot} {items} aiFeature={features.ai} />
          <RoomsPanel {shoot} {photos} />
          <ListingPack {shoot} {features} photoCount={photos.length} />
          <DeliverPanel {shoot} canShare={can(who, CAP_SHARES)} onchange={() => load(shoot.id)} />
        </div>
      </div>

      <div class="foot">
        <button class="mg-btn danger sm" onclick={remove}><Icon name="trash" size={13} />Forget this shoot</button>
      </div>
    {/if}
  {/snippet}
</ShootsGate>

<style>
  .back { margin: -4px 0 10px; }
  .sk { display: flex; flex-direction: column; gap: 12px; }
  .head { display: flex; align-items: center; gap: 14px; margin-bottom: 14px; min-width: 0; }
  .cover { flex: none; width: 96px; height: 68px; border-radius: 14px; overflow: hidden; display: grid; place-items: center;
           background: var(--mg-term); color: var(--mg-i3); }
  .cover img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .ttl { min-width: 0; flex: 1; }
  .ttl .mg-h2 { overflow-wrap: anywhere; }
  .sub { margin: 6px 0 0; display: flex; flex-wrap: wrap; align-items: center; gap: 4px 12px; font: 400 12.5px/1.4 var(--mg-font); color: var(--mg-i3); }
  .sub span { display: inline-flex; align-items: center; gap: 4px; }
  .statusrow { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
  .stamps { font: 400 12px/1.3 var(--mg-font); color: var(--mg-i3); }

  .cols { display: grid; gap: 12px; grid-template-columns: minmax(0, 1fr); }
  .col { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  @media (min-width: 980px) { .cols { grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); align-items: start; } }

  .hd { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
  h3 { margin: 0; flex: 1; display: flex; align-items: center; gap: 7px; font: 600 14px/1.3 var(--mg-font); color: var(--mg-i); }
  .acts { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
  .note { white-space: pre-wrap; }
  .none { margin: 0; font: 400 12.5px/1.5 var(--mg-font); color: var(--mg-i3); }
  .more { margin: 8px 0 0; font: 400 12px/1.4 var(--mg-font); color: var(--mg-i3); }

  .thumbs { display: grid; gap: 6px; grid-template-columns: repeat(auto-fill, minmax(92px, 1fr)); }
  figure { position: relative; margin: 0; aspect-ratio: 3 / 2; border-radius: 10px; overflow: hidden; background: var(--mg-term);
           border: 1px solid transparent; }
  figure.cov { border-color: rgba(62, 207, 142, 0.6); }
  figure a { display: block; width: 100%; height: 100%; }
  figure img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .ph { display: grid; place-items: center; width: 100%; height: 100%; color: var(--mg-i3); }
  .vid { position: absolute; left: 5px; bottom: 5px; width: 18px; height: 18px; border-radius: 50%; display: grid; place-items: center;
         background: rgba(8, 8, 10, 0.72); color: var(--mg-i); }
  .setc { position: absolute; right: 3px; top: 3px; width: 28px; height: 28px; border-radius: 50%; border: 0; padding: 0;
          display: grid; place-items: center; background: rgba(8, 8, 10, 0.6); color: var(--mg-i2); cursor: pointer;
          opacity: 0; transition: opacity 0.18s; }
  figure:hover .setc, .setc:focus-visible, .setc.on { opacity: 1; }
  .setc.on { color: var(--mg-ok); cursor: default; }
  @media (hover: none) { .setc { opacity: 0.85; } }

  .foot { margin-top: 20px; display: flex; justify-content: flex-end; }
  @media (max-width: 520px) { .cover { width: 72px; height: 52px; } }
</style>
