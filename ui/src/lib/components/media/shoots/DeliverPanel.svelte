<script>
  /* Deliver: a client portal that belongs to this property (delivery.py).
     POST /api/shoots/{id}/deliver makes the link — the address is the
     title, the shoot's folder the contents — and GET …/deliveries lists what
     went out and what the other side did with it (opened, downloaded…).
     Portals are managed on /media/shares; the client link is /media/s/<token>. */
  import Icon from '$lib/components/glass/Icon.svelte';
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import { say } from '$lib/media.svelte.js';
  import { shoots, folderName, deliveryLink, copyText } from '$lib/media/shoots.js';

  let { shoot, canShare = true, onchange } = $props();

  let list = $state([]);
  let open = $state(false);
  let busy = $state(false);
  let err = $state('');
  let form = $state({});

  const folders = $derived(shoot.folders || []);

  const sid = $derived(shoot.id);

  async function load(id = sid) {
    if (!canShare) return;
    try { list = (await shoots.deliveries(id))?.deliveries || []; }
    catch (e) { say(e.message, 'error'); }
  }
  $effect(() => { load(sid); });

  function start() {
    form = { folder_path: folders.length === 1 ? folders[0] : '', title: '', message: '', expires_days: 30,
             allow_download: true, allow_zip: true, watermark_previews: true, mark_delivered: shoot.status !== 'posted' };
    err = '';
    open = true;
  }

  async function make(e) {
    e?.preventDefault();
    if (folders.length > 1 && !form.folder_path) { err = 'Pick which folder to send.'; return; }
    busy = true; err = '';
    try {
      const body = { ...form, folder_path: form.folder_path || null, title: form.title || null,
                     message: form.message || null, expires_days: Number(form.expires_days) };
      const d = await shoots.deliver(shoot.id, body);
      open = false;
      const ok = await copyText(deliveryLink(d));
      say(ok ? 'Client link made and copied' : 'Client link made');
      load();
      if (form.mark_delivered) onchange?.();
    } catch (e2) { err = e2.message; }
    finally { busy = false; }
  }

  async function copy(d) {
    const ok = await copyText(deliveryLink(d));
    say(ok ? 'Link copied' : 'Could not copy', ok ? 'ok' : 'error');
  }

  const day = (v) => (v ? new Date(v + 'Z').toLocaleDateString('en-ZA', { day: 'numeric', month: 'short', year: 'numeric' }) : '');
  const expired = (d) => d.expires_at && new Date(d.expires_at + 'Z') < new Date();
  const ACT = { viewed: 'opened', downloaded: 'files taken', downloaded_zip: 'zips', uploaded: 'sent in', confirmed: 'done' };
</script>

<section class="mg-card">
  <div class="hd">
    <h3><Icon name="send" size={15} />Deliver</h3>
    {#if canShare}
      <button class="mg-btn primary sm" onclick={start} disabled={!folders.length}><Icon name="link" size={13} />Make a client link</button>
    {/if}
  </div>

  {#if !canShare}
    <p class="none">Your account can't manage portals, so deliveries are hidden.</p>
  {:else}
    {#if !folders.length}<p class="none">Link a folder first — that's what the client gets.</p>{/if}
    {#if list.length}
      <ul class="dl">
        {#each list as d (d.id)}
          <li>
            <div class="top">
              <b>{d.title}</b>
              {#if d.revoked}<span class="mg-chip">off</span>
              {:else if expired(d)}<span class="mg-chip warn">expired</span>
              {:else if d.confirmed_at}<span class="mg-chip ok">client done</span>
              {:else}<span class="mg-chip ok"><span class="dot"></span>live</span>{/if}
            </div>
            <p class="meta mg-tnum">
              sent {day(d.created_at)}{#if d.expires_at} · until {day(d.expires_at)}{/if}
              {#each Object.entries(d.activity || {}) as [k, n] (k)} · {n} {ACT[k] || k}{/each}
              {#if !Object.keys(d.activity || {}).length} · not opened yet{/if}
            </p>
            <div class="acts">
              <button class="mg-btn secondary sm" onclick={() => copy(d)}><Icon name="copy" size={13} />Copy link</button>
              <a class="mg-btn secondary sm" href={deliveryLink(d)} target="_blank" rel="noopener"><Icon name="external" size={13} />Open</a>
              <a class="mg-btn ghost sm" href="/media/shares"><Icon name="share" size={13} />Portals</a>
            </div>
          </li>
        {/each}
      </ul>
    {:else if folders.length}
      <p class="none">Nothing sent for this property yet.</p>
    {/if}
  {/if}
</section>

<Sheet {open} title="Deliver {shoot.address}" size="sm" onclose={() => (open = false)}>
  <form id="deliver-form" class="fm" onsubmit={make}>
    {#if folders.length > 1}
      <div class="f">
        <label class="mg-label" for="dv-folder">Folder to send</label>
        <div class="mg-select">
          <select id="dv-folder" bind:value={form.folder_path}>
            <option value="">Choose…</option>
            {#each folders as p (p)}<option value={p}>{folderName(p)}</option>{/each}
          </select>
          <span class="ic"><Icon name="chevronDown" size={15} /></span>
        </div>
      </div>
    {/if}
    <div class="f">
      <label class="mg-label" for="dv-title">Title</label>
      <input id="dv-title" class="mg-input" bind:value={form.title} placeholder={shoot.address} maxlength="200" />
    </div>
    <div class="f">
      <label class="mg-label" for="dv-msg">Message</label>
      <input id="dv-msg" class="mg-input" bind:value={form.message} maxlength="1000" placeholder="Here are the final photos — enjoy!" />
    </div>
    <div class="f">
      <label class="mg-label" for="dv-exp">Link lasts</label>
      <div class="mg-select">
        <select id="dv-exp" bind:value={form.expires_days}>
          {#each [7, 14, 30, 60, 90, 365] as n (n)}<option value={n}>{n} days{n === 30 ? ' (default)' : ''}</option>{/each}
        </select>
        <span class="ic"><Icon name="chevronDown" size={15} /></span>
      </div>
    </div>
    <div class="togs">
      {#each [['allow_download', 'Downloads'], ['allow_zip', 'Download all as ZIP'], ['watermark_previews', 'Watermark previews'], ['mark_delivered', 'Mark as posted']] as [k, l] (k)}
        <button type="button" class="mg-chip tog" class:on={form[k]} aria-pressed={!!form[k]} onclick={() => (form[k] = !form[k])}>
          {#if form[k]}<Icon name="check" size={12} />{/if}{l}
        </button>
      {/each}
    </div>
    {#if err}<p class="err">{err}</p>{/if}
  </form>
  {#snippet footer()}
    <div class="right">
      <button type="button" class="mg-btn ghost" onclick={() => (open = false)}>Cancel</button>
      <button type="submit" form="deliver-form" class="mg-btn primary" disabled={busy}>
        {#if busy}<span class="mg-spin"></span>Making…{:else}<Icon name="send" size={14} />Make the link{/if}
      </button>
    </div>
  {/snippet}
</Sheet>

<style>
  .hd { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
  h3 { margin: 0; flex: 1; display: flex; align-items: center; gap: 7px; font: 600 14px/1.3 var(--mg-font); color: var(--mg-i); }
  .none { margin: 0; font: 400 12.5px/1.5 var(--mg-font); color: var(--mg-i3); }
  .dl { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
  .dl li { padding: 10px 12px; border-radius: 12px; background: rgba(255, 255, 255, 0.03); }
  .top { display: flex; align-items: center; gap: 8px; }
  .top b { flex: 1; min-width: 0; font: 500 13px/1.3 var(--mg-font); color: var(--mg-i); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .meta { margin: 4px 0 8px; font: 400 11.5px/1.45 var(--mg-font); color: var(--mg-i3); }
  .acts { display: flex; flex-wrap: wrap; gap: 6px; }
  .fm { display: flex; flex-direction: column; gap: 12px; }
  .f { display: flex; flex-direction: column; gap: 5px; }
  .mg-select { display: block; }
  .togs { display: flex; flex-wrap: wrap; gap: 6px; }
  .tog { min-height: 40px; padding: 0 12px; }
  .err { margin: 0; font: 400 12.5px/1.45 var(--mg-font); color: var(--mg-crit); }
</style>
