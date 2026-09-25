<script>
  /* The Looks tab.

     A Look is the studio's own finish — a name, an instruction and up to two
     example photos. An image model (fal / Gemini / OpenAI with the studio's
     key) paints it onto a photo; Claude, when configured, first rewrites the
     instruction for what is really in that photo and marks the sky and the
     window views, so an outdoor shot gets a dusk sky and glowing windows
     while an interior at twilight keeps its walls and lights its lamps.

     The result is a layer over the photo's edit (recipe.gen_ref), never a
     slider move: "Use on photo" saves it into the edit, where the editor can
     fade it or take it off again. */
  import { onDestroy, untrack } from 'svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import { media, photoUrl } from '$lib/media.js';
  import { say } from '$lib/media.svelte.js';
  import { looks, aiPhoto, genPics, applyGen, clearGen, savedGenRef, poll, TWILIGHT_ROOMS } from '$lib/media/hdr.js';
  import LookEditor from './LookEditor.svelte';
  import PhotoPicker from './PhotoPicker.svelte';
  import BeforeAfter from './BeforeAfter.svelte';

  let { photoId = null, features = {}, canEdit = true, onphoto } = $props();

  /* ------------------------------------------------------------ looks */
  let list = $state([]);
  let loadingLooks = $state(true);
  let editing = $state(null);          // {look} while the sheet is open
  let pick = $state(false);

  async function loadLooks() {
    try {
      list = (await looks.list())?.looks || [];
      if (lookId == null && list.length) lookId = (list.find((l) => /twilight|dusk/i.test(l.name)) || list[0]).id;
    }
    catch (e) { say(e.message, 'error'); }
    finally { loadingLooks = false; }
  }
  loadLooks();

  function upsert(l) {
    const i = list.findIndex((x) => x.id === l.id);
    list = i >= 0 ? list.map((x) => (x.id === l.id ? l : x)) : [...list, l];
  }

  async function removeLook(l) {
    if (!confirm(`Delete the look “${l.name}” and its example photos?`)) return;
    try {
      await looks.remove(l.id);
      list = list.filter((x) => x.id !== l.id);
      if (lookId === l.id) lookId = null;
      say('Look deleted');
    } catch (e) { say(e.message, 'error'); }
  }

  async function nudge(i, d) {
    const j = i + d;
    if (j < 0 || j >= list.length) return;
    const next = [...list];
    [next[i], next[j]] = [next[j], next[i]];
    list = next;
    try { list = (await looks.order(next.map((x) => x.id)))?.looks || next; }
    catch (e) { say(e.message, 'error'); }
  }

  /* ------------------------------------------------------------ photo */
  let photo = $state(null);
  let savedRef = $state('');
  let history = $state([]);            // painted results still on disk, newest first

  $effect(() => {
    const id = photoId;
    untrack(() => loadPhoto(id));
  });

  async function loadPhoto(id) {
    photo = null; history = []; savedRef = ''; room = null; stopJob?.(); job = null;
    if (!id) return;
    try {
      photo = await media.video(id);
      if (photo.media_type !== 'photo') { say('Looks work on photos only', 'error'); photo = null; return; }
    } catch (e) { say(e.message, 'error'); return; }
    savedRef = await savedGenRef(id);
    try { history = (await aiPhoto.gens(id))?.items || []; } catch { history = []; }
  }

  /* ------------------------------------------------------------- room */
  let room = $state(null);             // {busy} | {name} | {error}
  let stopRoom = null;

  async function suggestRoom() {
    if (!photo) return;
    room = { busy: true };
    try {
      const j = await aiPhoto.rooms([photo.id]);
      stopRoom?.();
      stopRoom = poll(() => aiPhoto.job(j.id), (x) => x.state !== 'running', (x) => {
        if (x.state === 'running') return;
        const name = Object.keys(x.rooms || {}).find((k) => (x.rooms[k] || []).includes(photo?.id));
        room = name ? { name } : { error: x.error || 'Claude could not tell' };
      }, (e) => (room = { error: e.message }));
    } catch (e) { room = { error: e.message }; }
  }

  /* ------------------------------------------------------------ paint */
  let lookId = $state(null);           // null + words = "my words"
  let words = $state('');
  let ask = $state('');
  let variations = $state(1);
  let job = $state(null);
  let stopJob = null;

  const twilight = $derived(list.find((l) => /twilight|dusk/i.test(l.name)) || null);
  const chosenLook = $derived(list.find((l) => l.id === lookId) || null);
  const imageOn = $derived(!!features.image_ai);
  const canPaint = $derived(imageOn && canEdit && !!photo && !job?.running
                            && (lookId ? true : words.trim().length >= 3));
  const results = $derived.by(() => {
    const seen = new Set();
    const out = [];
    for (const it of [...(job?.items || []).slice().reverse(), ...history]) {
      if (!it?.ref || seen.has(it.ref)) continue;
      seen.add(it.ref); out.push(it);
    }
    return out;
  });

  async function paint() {
    if (!canPaint) return;
    const body = { video_ids: [photo.id], variations: Number(variations) || 1, ask: ask.trim().slice(0, 600) };
    if (lookId) body.look_id = lookId; else body.prompt = words.trim().slice(0, 2000);
    try {
      const j = await aiPhoto.gen(body);
      job = { ...j, running: true };
      stopJob?.();
      stopJob = poll(() => aiPhoto.job(j.id), (x) => x.state !== 'running', (x) => {
        job = { ...x, running: x.state === 'running' };
        if (x.state !== 'running') {
          if (x.error && !(x.items || []).length) say(x.error, 'error', 6000);
          else say(`${(x.items || []).length} result${(x.items || []).length === 1 ? '' : 's'} ready`);
        }
      }, (e) => { say(e.message, 'error'); job = { ...job, running: false }; });
    } catch (e) { say(e.message, 'error', 6000); }
  }

  let amount = $state({});             // ref -> 0..1
  async function use(it) {
    try {
      await applyGen(photo.id, it, amount[it.ref] ?? 1);
      savedRef = it.ref;
      say('Saved onto the photo — fine-tune it in the editor');
    } catch (e) { say(e.message, 'error'); }
  }
  async function takeOff() {
    try { await clearGen(photo.id); savedRef = ''; say('Look layer removed from the photo'); }
    catch (e) { say(e.message, 'error'); }
  }
  async function keep(it) {
    try { upsert(await aiPhoto.keepAsExample(it.ref, it.look_id)); say(`Kept as an example of “${it.look}”`); }
    catch (e) { say(e.message, 'error'); }
  }

  onDestroy(() => { stopJob?.(); stopRoom?.(); });

  const excerpt = (s, n = 140) => (s && s.length > n ? s.slice(0, n - 1) + '…' : s || '');
</script>

{#if !imageOn}
  <div class="mg-strip warn">
    <span class="ic"><Icon name="alert" size={15} /></span>
    <span><b>Image AI isn't configured</b> — add a fal, Gemini or OpenAI key in
      <a class="lnk" href="/media/settings">Media › Settings</a> to paint looks. You can still set up the looks themselves.
      (The local ComfyUI option needs an NVIDIA card and isn't available on this server.)</span>
  </div>
{/if}

<div class="lay">
  <!-- ————————————————————————————————————————— the photo + painting ——— -->
  <section class="col">
    <div class="mg-glass-soft card">
      <div class="hd">
        <span class="mg-label">Photo</span>
        {#if photo}
          <button class="mg-btn ghost sm" onclick={() => (pick = true)}><Icon name="image" size={13} />Change</button>
          <a class="mg-btn ghost sm" href="/media/edit?id={photo.id}"><Icon name="sliders" size={13} />Editor</a>
        {/if}
      </div>
      {#if photo}
        <div class="ph">
          <img src={photoUrl(photo, 1200)} alt={photo.filename} />
        </div>
        <div class="meta">
          <b title={photo.filename}>{photo.filename}</b>
          {#if savedRef}<span class="mg-chip ok"><span class="dot"></span>Look layer on</span>{/if}
          {#if features.ai}
            {#if room?.name}
              <span class="mg-chip mgr">{room.name}</span>
              <span class="hint">{TWILIGHT_ROOMS.has(room.name) ? 'An outdoor shot — a good twilight candidate.' : 'An interior — twilight lights its lamps and shows a dusk view.'}</span>
            {:else if room?.error}
              <span class="hint err">{room.error}</span>
            {:else}
              <button class="mg-btn ghost sm" onclick={suggestRoom} disabled={room?.busy || !canEdit}>
                {#if room?.busy}<span class="mg-spin"></span>{:else}<Icon name="sparkles" size={13} />{/if}Suggest room type
              </button>
            {/if}
          {/if}
        </div>
      {:else if photoId}
        <div class="mg-bar indeterminate"><i></i></div>
      {:else}
        <Empty icon="image" title="Choose a photo" hint="Pick the photo to paint a look onto — or open this page from the photo editor.">
          {#snippet children()}
            <button class="mg-btn secondary sm" onclick={() => (pick = true)}><Icon name="image" size={14} />Choose a photo</button>
          {/snippet}
        </Empty>
      {/if}
    </div>

    <div class="mg-glass-soft card">
      <span class="mg-label">Look to paint</span>
      <div class="chips">
        {#if twilight}
          <button type="button" class="mg-chip tw" class:on={lookId === twilight.id} onclick={() => (lookId = twilight.id)}>
            <Icon name="moon" size={13} />{twilight.name}
          </button>
        {/if}
        {#each list.filter((l) => l.id !== twilight?.id) as l (l.id)}
          <button type="button" class="mg-chip" class:on={lookId === l.id} onclick={() => (lookId = l.id)}>{l.name}</button>
        {/each}
        <button type="button" class="mg-chip" class:on={lookId == null} onclick={() => (lookId = null)}>
          <Icon name="pencil" size={12} />My words
        </button>
      </div>
      {#if chosenLook}
        <p class="hint">{excerpt(chosenLook.prompt, 220)}</p>
        {#if twilight && chosenLook.id === twilight.id}
          <p class="hint">Outdoor twilight: exteriors get a blue-hour sky and every real window and garden light lit;
            interiors keep their walls and light their own lamps. {features.ai ? 'Claude marks the sky and window views per photo.' : 'Without Claude configured the instruction is used as written.'}</p>
        {/if}
      {:else}
        <textarea class="mg-input ta" rows="3" maxlength="2000" bind:value={words}
                  placeholder="Say what the finished photo should look like…" aria-label="Your own look"></textarea>
      {/if}
      <label class="fld">
        <span class="mg-label">Adjust (optional)</span>
        <input class="mg-input" maxlength="600" bind:value={ask} placeholder="e.g. less orange, keep the lawn green" />
      </label>
      <div class="row">
        <span class="mg-label">Variations</span>
        <Seg options={[1, 2, 3, 4].map((n) => ({ value: n, label: String(n) }))} value={variations}
             onchange={(v) => (variations = v)} label="Variations" />
      </div>
      <div class="row">
        {#if job?.running}
          <div class="grow">
            <div class="mg-bar indeterminate"><i></i></div>
            <p class="hint">Painting… this takes 20–60 seconds a result.</p>
          </div>
        {:else}
          <button class="mg-btn accent lg" onclick={paint} disabled={!canPaint}
                  title={!imageOn ? 'Image AI is not configured' : !photo ? 'Choose a photo first' : ''}>
            <Icon name="wand" size={16} />Paint {chosenLook ? chosenLook.name : 'look'}
          </button>
        {/if}
      </div>
      {#if !canEdit}<p class="hint">Your account has view-only access.</p>{/if}
    </div>

    {#if results.length}
      <div class="mg-glass-soft card">
        <div class="hd">
          <span class="mg-label">Results · {results.length}</span>
          {#if savedRef}<button class="mg-btn ghost sm" onclick={takeOff} disabled={!canEdit}><Icon name="undo" size={13} />Remove look layer</button>{/if}
        </div>
        <div class="res">
          {#each results as it (it.ref)}
            {@const pics = genPics(it.ref)}
            <article class="ri">
              <BeforeAfter before={pics.before} after={pics.after} alt={it.look} />
              <div class="rm">
                <b>{it.look || 'Look'}</b>
                {#if it.scene}<span class="mg-chip">{it.scene}</span>{/if}
                {#if savedRef === it.ref}<span class="mg-chip ok"><span class="dot"></span>On the photo</span>{/if}
              </div>
              {#if it.prompt}<details><summary>Instruction used</summary><p class="hint">{it.prompt}</p></details>{/if}
              <label class="amt">
                <span class="mg-label">Strength</span>
                <input type="range" min="0" max="1" step="0.05" value={amount[it.ref] ?? 1}
                       oninput={(e) => (amount = { ...amount, [it.ref]: Number(e.currentTarget.value) })} />
                <span class="mg-tnum v">{Math.round((amount[it.ref] ?? 1) * 100)}%</span>
              </label>
              <div class="acts">
                <button class="mg-btn secondary sm" onclick={() => use(it)} disabled={!canEdit}><Icon name="check" size={13} />Use on photo</button>
                {#if it.look_id}
                  <button class="mg-btn ghost sm" onclick={() => keep(it)} disabled={!canEdit}><Icon name="star" size={13} />Keep as example</button>
                {/if}
                <a class="mg-btn ghost sm" href={pics.after} download="{(photo?.filename || 'photo').replace(/\.[^.]+$/, '')}_{(it.look || 'look').replace(/\W+/g, '-')}.png">
                  <Icon name="download" size={13} />Download
                </a>
              </div>
            </article>
          {/each}
        </div>
      </div>
    {/if}
  </section>

  <!-- ———————————————————————————————————————————————— the library ——— -->
  <aside class="col side">
    <div class="mg-glass-soft card">
      <div class="hd">
        <span class="mg-label">Studio looks · {list.length}</span>
        {#if canEdit}
          <button class="mg-btn secondary sm" onclick={() => (editing = { look: null })}><Icon name="plus" size={13} />New look</button>
        {/if}
      </div>
      {#if loadingLooks}
        <div class="mg-bar indeterminate"><i></i></div>
      {:else if !list.length}
        <Empty icon="palette" title="No looks yet" hint="A look is a named instruction plus a couple of example photos." />
      {:else}
        <ul class="looks">
          {#each list as l, i (l.id)}
            <li class:on={lookId === l.id}>
              <button type="button" class="pick" onclick={() => (lookId = l.id)}>
                <b>{#if l.id === twilight?.id}<Icon name="moon" size={12} />{/if}{l.name}</b>
                <span class="hint">{excerpt(l.prompt, 90)}</span>
                {#if l.examples?.length}
                  <span class="exs">
                    {#each l.examples as n (n)}<img src={looks.exampleUrl(l.id, n)} alt="" loading="lazy" />{/each}
                  </span>
                {/if}
              </button>
              {#if canEdit}
                <div class="la">
                  <button class="mg-btn ghost icon sm" aria-label="Move up" onclick={() => nudge(i, -1)} disabled={i === 0}><Icon name="chevronUp" size={14} /></button>
                  <button class="mg-btn ghost icon sm" aria-label="Move down" onclick={() => nudge(i, 1)} disabled={i === list.length - 1}><Icon name="chevronDown" size={14} /></button>
                  <button class="mg-btn ghost icon sm" aria-label="Edit {l.name}" onclick={() => (editing = { look: l })}><Icon name="edit" size={14} /></button>
                  <button class="mg-btn ghost icon sm" aria-label="Delete {l.name}" onclick={() => removeLook(l)}><Icon name="trash" size={14} /></button>
                </div>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  </aside>
</div>

<LookEditor open={!!editing} look={editing?.look ?? null} editable={canEdit}
            onclose={() => (editing = null)} onsaved={upsert} />
<PhotoPicker open={pick} onclose={() => (pick = false)}
             onpick={(p) => { pick = false; onphoto?.(p.id); }} />

<style>
  .lay { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 16px; align-items: start; }
  .col { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  .side { position: sticky; top: 16px; }
  .card { border-radius: var(--mc-r-md); padding: 16px; display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  .hd { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .hd .mg-label { margin-right: auto; }
  .row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .grow { flex: 1; display: flex; flex-direction: column; gap: 6px; }
  .fld { display: flex; flex-direction: column; gap: 5px; }
  .fld .mg-input { width: 100%; }
  .ta { width: 100%; height: auto; min-height: 84px; padding: 10px 12px; resize: vertical; font: 400 13px/1.5 var(--mc-font); }
  .hint { margin: 0; font: 400 12px/1.5 var(--mc-font); color: var(--mc-ink3); }
  .err { color: var(--mc-crit); }
  .lnk { color: var(--mc-accent) !important; text-decoration: underline !important; }
  .ph { border-radius: 12px; overflow: hidden; background: var(--mc-inset); }
  .ph img { display: block; width: 100%; max-height: 420px; object-fit: contain; }
  .meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-width: 0; }
  .meta b { font: 600 13px/1.3 var(--mc-font); color: var(--mc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; }
  .chips .mg-chip { min-height: 36px; cursor: pointer; gap: 6px; }
  .mg-chip.tw:not(.on) { color: var(--mc-mgr); border-color: rgba(167, 139, 250, 0.35); }
  .mg-btn.lg { flex: 1 1 auto; max-width: 360px; }

  .res { display: grid; gap: 14px; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); }
  .ri { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .rm { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .rm b { font: 600 13px/1.3 var(--mc-font); color: var(--mc-ink); }
  details summary { cursor: pointer; font: 500 12px/1.4 var(--mc-font); color: var(--mc-ink2); }
  .amt { display: flex; align-items: center; gap: 10px; }
  .amt input { flex: 1; accent-color: var(--mc-accent); height: 28px; }
  .amt .v { font: 500 12px/1 var(--mc-font); color: var(--mc-ink); width: 36px; text-align: right; }
  .acts { display: flex; gap: 6px; flex-wrap: wrap; }

  .looks { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
  .looks li { border: 1px solid var(--mc-line); border-radius: 14px; padding: 8px; display: flex; flex-direction: column; gap: 6px; }
  .looks li.on { border-color: rgba(62, 207, 142, 0.5); background: rgba(62, 207, 142, 0.06); }
  .pick { border: 0; background: none; padding: 2px 4px; text-align: left; cursor: pointer; display: flex; flex-direction: column; gap: 4px; color: inherit; min-height: 40px; }
  .pick b { display: inline-flex; align-items: center; gap: 6px; font: 600 13px/1.3 var(--mc-font); color: var(--mc-ink); }
  .exs { display: flex; gap: 4px; }
  .exs img { width: 56px; aspect-ratio: 3 / 2; object-fit: cover; border-radius: 6px; }
  .la { display: flex; gap: 2px; justify-content: flex-end; }

  @media (max-width: 960px) {
    .lay { grid-template-columns: minmax(0, 1fr); }
    .side { position: static; }
  }
  @media (max-width: 560px) {
    .acts .mg-btn, .hd .mg-btn, .meta .mg-btn { height: 40px; }
    .la .mg-btn.icon.sm { width: 40px; height: 40px; }
    .res { grid-template-columns: minmax(0, 1fr); }
  }
</style>
