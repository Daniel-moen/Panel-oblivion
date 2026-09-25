<script>
  /* Making a portal: a handful of decisions taken once.

     The kind comes first because it decides everything else — a receiving
     portal shows the client nothing of the library, so it needs no folder,
     no downloads and no watermark; the form simply stops asking.

     "From a shoot" goes through /api/shoots/{id}/deliver rather than
     /api/shares: that is the one call that stamps the portal with the shoot,
     so it shows up on the property's page too. It only makes send portals
     and never lacks an expiry (1–365 days), which the form says. */
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import { say } from '$lib/media.svelte.js';
  import { portals, KINDS } from '$lib/media/portals.js';

  let { open = false, onclose, oncreated, folders = [], shoots = [], watermarks = [],
        canShoots = false, onwatermark } = $props();

  const blank = () => ({
    kind: 'send', source: 'folder', title: '', message: '', folder_id: '', shoot_id: '',
    shoot_folder: '', expires_days: '30', password: '',
    allow_download: true, allow_selects: true, allow_zip: true,
    watermark_previews: false, watermark_name: '', mark_delivered: false
  });
  let f = $state(blank());
  let busy = $state(false);
  let wmBusy = $state(false);

  $effect(() => { if (open) f = blank(); });

  const receiving = $derived(f.kind === 'receive');
  const fromShoot = $derived(f.kind === 'send' && f.source === 'shoot' && canShoots);
  const shoot = $derived(shoots.find((s) => String(s.id) === String(f.shoot_id)) || null);
  const kindHint = $derived(KINDS.find((k) => k.value === f.kind)?.hint || '');

  function close() { if (!busy) onclose?.(); }

  async function create() {
    if (busy) return;
    busy = true;
    try {
      let made;
      if (fromShoot) {
        if (!shoot) throw new Error('Choose a shoot to send');
        const body = {
          title: f.title || null, message: f.message || null,
          expires_days: Number(f.expires_days || 30),
          allow_download: f.allow_download, allow_zip: f.allow_zip,
          watermark_previews: f.watermark_previews,
          watermark_name: f.watermark_previews ? f.watermark_name || null : null,
          mark_delivered: f.mark_delivered
        };
        if ((shoot.folders || []).length > 1) {
          if (!f.shoot_folder) throw new Error('This shoot has several folders — say which one to send');
          body.folder_path = f.shoot_folder;
        }
        made = await portals.deliver(shoot.id, body);
      } else {
        if (!receiving && !f.folder_id) throw new Error('Pick a folder to share');
        const body = {
          kind: f.kind,
          title: f.title || null,
          message: f.message || null,
          password: f.password || null,
          allow_upload: f.kind !== 'send',
          allow_zip: f.allow_zip
        };
        if (!receiving) {
          Object.assign(body, {
            folder_id: Number(f.folder_id), include_subfolders: true,
            allow_download: f.allow_download, allow_selects: f.allow_selects,
            watermark_previews: f.watermark_previews,
            watermark_name: f.watermark_previews ? f.watermark_name || null : null
          });
        }
        if (f.expires_days) body.expires_days = Number(f.expires_days);
        made = await portals.create(body);
      }
      say('Portal created');
      oncreated?.(made);
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }

  async function addMark(e) {
    const file = e.currentTarget.files?.[0];
    e.currentTarget.value = '';
    if (!file) return;
    wmBusy = true;
    try {
      const r = await portals.addWatermark(file);
      await onwatermark?.();
      f.watermark_name = r?.name || '';
      say('Watermark added');
    } catch (err) { say(err.message, 'error'); }
    finally { wmBusy = false; }
  }
</script>

<Sheet {open} title="New portal" onclose={close}>
  <div class="fm">
    <div class="f">
      <span class="mg-label">What is it for</span>
      <div class="segwrap mg-noscroll">
        <Seg label="Portal kind" value={f.kind} onchange={(v) => (f.kind = v)}
             options={KINDS.map((k) => ({ value: k.value, label: k.label, icon: k.icon }))} />
      </div>
      <p class="hint">{kindHint}</p>
    </div>

    {#if f.kind === 'send' && canShoots && shoots.length}
      <div class="f">
        <span class="mg-label">Send from</span>
        <div class="segwrap">
          <Seg label="Source" value={f.source} onchange={(v) => (f.source = v)}
               options={[{ value: 'folder', label: 'A folder', icon: 'folder' },
                         { value: 'shoot', label: 'A shoot', icon: 'camera' }]} />
        </div>
      </div>
    {/if}

    <div class="two">
      <div class="f">
        <label class="mg-label" for="np-title">Title</label>
        <input id="np-title" class="mg-input" type="text" bind:value={f.title}
               placeholder={receiving ? 'Drone footage from Sam' : 'Camps Bay — first cut'} />
      </div>

      {#if fromShoot}
        <div class="f">
          <label class="mg-label" for="np-shoot">Shoot</label>
          <div class="mg-select">
            <select id="np-shoot" bind:value={f.shoot_id}>
              <option value="">Choose a shoot…</option>
              {#each shoots as s (s.id)}
                <option value={s.id}>{s.address}{s.suburb ? `, ${s.suburb}` : ''}</option>
              {/each}
            </select>
            <span class="ic"><Icon name="chevronDown" size={15} /></span>
          </div>
        </div>
      {:else if !receiving}
        <div class="f">
          <label class="mg-label" for="np-folder">Folder</label>
          <div class="mg-select">
            <select id="np-folder" bind:value={f.folder_id}>
              <option value="">Choose a folder…</option>
              {#each folders as fo (fo.id)}<option value={fo.id}>{fo.name}</option>{/each}
            </select>
            <span class="ic"><Icon name="chevronDown" size={15} /></span>
          </div>
        </div>
      {/if}
    </div>

    {#if fromShoot && shoot && (shoot.folders || []).length > 1}
      <div class="f">
        <label class="mg-label" for="np-sf">Which of its folders</label>
        <div class="mg-select">
          <select id="np-sf" bind:value={f.shoot_folder}>
            <option value="">Choose…</option>
            {#each shoot.folders as p (p)}<option value={p}>{p.split('/').pop()}</option>{/each}
          </select>
          <span class="ic"><Icon name="chevronDown" size={15} /></span>
        </div>
      </div>
    {:else if fromShoot && shoot && !(shoot.folders || []).length}
      <p class="warnline">This shoot has no folders yet, so there is nothing to send.</p>
    {/if}

    <div class="f">
      <label class="mg-label" for="np-msg">Message to the client</label>
      <input id="np-msg" class="mg-input" type="text" bind:value={f.message}
             placeholder={receiving ? 'Drop the raw files here — any size.' : "Here's the first pass — heart the ones you want."} />
    </div>

    <div class="two">
      <div class="f">
        <label class="mg-label" for="np-exp">Expires after</label>
        <div class="mg-select">
          <select id="np-exp" bind:value={f.expires_days}>
            {#if !fromShoot}<option value="">Never</option>{/if}
            <option value="7">7 days</option>
            <option value="30">30 days</option>
            <option value="90">90 days</option>
            {#if fromShoot}<option value="365">A year</option>{/if}
          </select>
          <span class="ic"><Icon name="chevronDown" size={15} /></span>
        </div>
      </div>
      {#if !fromShoot}
        <div class="f">
          <label class="mg-label" for="np-pw">Password <span class="opt">optional</span></label>
          <input id="np-pw" class="mg-input" type="text" autocomplete="off" bind:value={f.password}
                 placeholder="Leave empty for none" />
        </div>
      {/if}
    </div>

    {#if !receiving}
      <div class="f">
        <span class="mg-label">What the client may do</span>
        <div class="togs">
          <button type="button" class="mg-chip tog" class:on={f.allow_download} aria-pressed={f.allow_download}
                  onclick={() => (f.allow_download = !f.allow_download)}>
            {#if f.allow_download}<Icon name="check" size={13} />{/if}Download
          </button>
          <button type="button" class="mg-chip tog" class:on={f.allow_zip && f.allow_download}
                  aria-pressed={f.allow_zip && f.allow_download} disabled={!f.allow_download}
                  onclick={() => (f.allow_zip = !f.allow_zip)}>
            {#if f.allow_zip && f.allow_download}<Icon name="check" size={13} />{/if}Download all as zip
          </button>
          {#if !fromShoot}
            <button type="button" class="mg-chip tog" class:on={f.allow_selects} aria-pressed={f.allow_selects}
                    onclick={() => (f.allow_selects = !f.allow_selects)}>
              {#if f.allow_selects}<Icon name="check" size={13} />{/if}Picks, notes &amp; pins
            </button>
          {/if}
          <button type="button" class="mg-chip tog" class:on={f.watermark_previews} aria-pressed={f.watermark_previews}
                  onclick={() => (f.watermark_previews = !f.watermark_previews)}>
            {#if f.watermark_previews}<Icon name="check" size={13} />{/if}Watermark previews
          </button>
        </div>
        <p class="hint">
          {#if f.allow_download && !f.allow_zip}Files download one at a time — better for phones, where a zip lands in Files instead of Photos.
          {:else}A zip is never offered on a phone, whatever this says.{/if}
        </p>
      </div>

      {#if f.watermark_previews}
        <div class="f">
          <label class="mg-label" for="np-wm">Which watermark</label>
          <div class="wmrow">
            {#if watermarks.length}
              <div class="mg-select grow">
                <select id="np-wm" bind:value={f.watermark_name}>
                  <option value="">The first one ({watermarks[0].name})</option>
                  {#each watermarks as w (w.name)}<option value={w.name}>{w.name}</option>{/each}
                </select>
                <span class="ic"><Icon name="chevronDown" size={15} /></span>
              </div>
            {:else}
              <span class="hint grow">No watermarks yet — add a PNG logo with a transparent background.</span>
            {/if}
            <label class="mg-btn secondary sm file">
              <Icon name="upload" size={13} />{wmBusy ? 'Adding…' : 'Add PNG'}
              <input type="file" accept="image/png" onchange={addMark} disabled={wmBusy} />
            </label>
          </div>
          <p class="hint">Thumbnails and the viewer carry the mark; downloads (when on) are the clean originals.</p>
        </div>
      {/if}

      {#if fromShoot}
        <button type="button" class="mg-chip tog" class:on={f.mark_delivered} aria-pressed={f.mark_delivered}
                onclick={() => (f.mark_delivered = !f.mark_delivered)}>
          {#if f.mark_delivered}<Icon name="check" size={13} />{/if}Mark the shoot as posted
        </button>
      {/if}
    {:else}
      <p class="hint">Uploads land in their own inbox folder under <code>_Incoming</code>. Nothing reaches
        the library proper until you file it from this page.</p>
    {/if}
  </div>

  {#snippet footer()}
    <div class="right">
      <button type="button" class="mg-btn ghost" onclick={close}>Cancel</button>
      <button type="button" class="mg-btn primary" onclick={create} disabled={busy}>
        <Icon name="link" size={15} />{busy ? 'Making…' : 'Create the link'}
      </button>
    </div>
  {/snippet}
</Sheet>

<style>
  .fm { display: flex; flex-direction: column; gap: 14px; }
  .f { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
  .two { display: grid; gap: 14px; grid-template-columns: 1fr; }
  .mg-select { display: block; }
  .segwrap { overflow-x: auto; max-width: 100%; }
  .hint { margin: 2px 0 0; font: 400 12px/1.5 var(--mc-font); color: var(--mc-ink3); }
  .hint code { font: 11.5px/1.5 var(--mc-mono); color: var(--mc-ink2); }
  .warnline { margin: 0; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-warn); }
  .opt { color: var(--mc-ink3); font-weight: 400; }
  .togs { display: flex; flex-wrap: wrap; gap: 8px; }
  .tog { min-height: 40px; padding: 0 14px; font-size: 12.5px; cursor: pointer; }
  .tog:disabled { opacity: 0.45; cursor: default; }
  .wmrow { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .grow { flex: 1 1 180px; min-width: 0; }
  .file { position: relative; overflow: hidden; min-height: 40px; }
  @media (pointer: coarse) { .tog, .file { min-height: 44px; } }
  .file input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
  @media (min-width: 640px) { .two { grid-template-columns: 1fr 1fr; } }
</style>
