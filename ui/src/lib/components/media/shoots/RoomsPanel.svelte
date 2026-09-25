<script>
  /* Room assignments (rooms.py): which photo is which room, so the listing
     pack names them Kitchen1, Bedroom2… The plan is kept per folder, under
     "folder:<id>" of the shoot's first indexed folder — the key the listing
     pack reads. Only rooms you add exist; an empty room is never exported. */
  import Icon from '$lib/components/glass/Icon.svelte';
  import { say } from '$lib/media.svelte.js';
  import { thumbUrl } from '$lib/media.js';
  import { shoots, ROOM_PRESETS } from '$lib/media/shoots.js';

  let { shoot, photos = [] } = $props();

  const folderId = $derived((shoot.folder_ids || []).find((x) => x != null) ?? null);
  const key = $derived(folderId != null ? `folder:${folderId}` : null);

  let rooms = $state([]);       // [{ id, name, ids: [] }]
  let style = $state('Bedroom1');
  let dirty = $state(false);
  let saving = $state(false);
  let adding = $state('');
  let open = $state(false);

  async function load(k) {
    if (!k) { rooms = []; return; }
    try {
      const r = await shoots.rooms(k);
      rooms = r?.rooms || [];
      style = r?.style || 'Bedroom1';
      dirty = false;
    } catch (e) { say(e.message, 'error'); }
  }
  $effect(() => { load(key); });

  const roomOf = (vid) => rooms.find((r) => r.ids.includes(vid))?.id || '';

  function assign(vid, rid) {
    rooms = rooms.map((r) => ({
      ...r,
      ids: r.id === rid ? [...r.ids.filter((x) => x !== vid), vid] : r.ids.filter((x) => x !== vid)
    }));
    dirty = true;
  }

  function addRoom() {
    const name = adding.trim();
    if (!name) return;
    /* One room per name: the export numbers within it (Bedroom1, Bedroom2…),
       so a second "Bedroom" would only split the numbering. */
    if (rooms.some((r) => r.name.toLowerCase() === name.toLowerCase())) {
      say(`There is already a ${name} — put every ${name.toLowerCase()} photo in it`, 'error');
      return;
    }
    rooms = [...rooms, { id: Math.random().toString(36).slice(2, 10), name, ids: [] }];
    adding = '';
    dirty = true;
  }

  function dropRoom(r) {
    rooms = rooms.filter((x) => x.id !== r.id);
    dirty = true;
  }

  async function save() {
    saving = true;
    try {
      await shoots.saveRooms(key, rooms, style);
      dirty = false;
      say('Rooms saved');
    } catch (e) { say(e.message, 'error'); }
    finally { saving = false; }
  }
</script>

<section class="mg-card">
  <div class="hd">
    <h3><Icon name="layers" size={15} />Rooms</h3>
    <span class="mg-count">{rooms.length} room{rooms.length === 1 ? '' : 's'}</span>
    {#if key && photos.length}
      <button class="mg-btn ghost sm" onclick={() => (open = !open)} aria-expanded={open}>
        {open ? 'Hide' : 'Assign photos'}<Icon name={open ? 'chevronUp' : 'chevronDown'} size={13} />
      </button>
    {/if}
  </div>

  {#if !key}
    <p class="none">Link an indexed folder to sort its photos into rooms.</p>
  {:else}
    <div class="rooms">
      {#each rooms as r (r.id)}
        <span class="mg-chip">
          {r.name}<b class="mg-tnum">{r.ids.length}</b>
          <button class="x" onclick={() => dropRoom(r)} aria-label="Remove {r.name}"><Icon name="x" size={11} /></button>
        </span>
      {/each}
    </div>
    <div class="add">
      <input class="mg-input" list="room-presets" bind:value={adding} placeholder="Add a room (Kitchen, Pool…)"
             onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addRoom(); } }} aria-label="Room name" />
      <datalist id="room-presets">{#each ROOM_PRESETS as p (p)}<option value={p}></option>{/each}</datalist>
      <button class="mg-btn secondary" onclick={addRoom} disabled={!adding.trim()}><Icon name="plus" size={14} />Add</button>
    </div>

    {#if open}
      <div class="photos">
        {#each photos as v (v.id)}
          <figure>
            <span class="im">{#if v.thumbnail_path}<img src={thumbUrl(v)} alt="" loading="lazy" />{/if}</span>
            <div class="mg-select">
              <select value={roomOf(v.id)} onchange={(e) => assign(v.id, e.currentTarget.value)} aria-label="Room for {v.filename}">
                <option value="">No room</option>
                {#each rooms as r (r.id)}<option value={r.id}>{r.name}</option>{/each}
              </select>
              <span class="ic"><Icon name="chevronDown" size={13} /></span>
            </div>
          </figure>
        {/each}
      </div>
      {#if !rooms.length}<p class="none">Add a room first, then pick it under each photo.</p>{/if}
    {/if}

    {#if dirty}
      <button class="mg-btn accent wide" onclick={save} disabled={saving}><Icon name="check" size={14} />Save rooms</button>
    {/if}
  {/if}
</section>

<style>
  .hd { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
  h3 { margin: 0; flex: 1; display: flex; align-items: center; gap: 7px; font: 600 14px/1.3 var(--mc-font); color: var(--mc-ink); }
  .none { margin: 0 0 8px; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink3); }
  .rooms { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
  .rooms:empty { display: none; }
  .rooms b { color: var(--mc-ink); font-weight: 600; }
  .x { border: 0; background: none; color: var(--mc-ink3); padding: 4px; margin: -4px -6px -4px 0; cursor: pointer; display: grid; place-items: center; }
  .x:hover { color: var(--mc-crit); }
  .add { display: flex; gap: 8px; }
  .add .mg-input { flex: 1; min-width: 0; }
  .photos { display: grid; gap: 8px; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); margin-top: 12px; }
  figure { margin: 0; display: flex; flex-direction: column; gap: 6px; }
  .im { display: block; aspect-ratio: 3 / 2; border-radius: 10px; overflow: hidden; background: var(--mc-inset); }
  .im img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .mg-select { display: block; }
  .mg-select select { height: 36px; font-size: 12.5px; }
  .wide { width: 100%; margin-top: 12px; }
</style>
