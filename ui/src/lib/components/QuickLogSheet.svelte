<script>
  /* The global Quick log: the strip's pencil (and Home's) opens this sheet
     from anywhere, to log a call, a WhatsApp or a visit in a few taps.

     Mounted ONCE by routes/+layout.svelte; no props. It reads and closes
     `chrome.quickLog` ({open, gid}, shell.svelte.js):
       - gid set (the strip passes it on /leads/properties/<gid>): straight
         to the composer, about that property;
       - gid null: pick the property first (PropertyPick, the same search
         the task card uses), then the composer.

     The composer is the one the property page uses (QuickLog.svelte), fed
     the property's contacts. A property that is not tracked yet can still
     be logged: the server starts tracking it on the first interaction
     (panel.py `_child_routes`), and we say so rather than surprise anyone.

     After a save QuickLog has already toasted; we refresh the tracked badges,
     tell an open property page to reload (`mc:logged`), and close. */
  import { api } from '$lib/api.js';
  import { app, loadTracked } from '$lib/state.svelte.js';
  import { chrome, closeQuickLog } from '$lib/shell.svelte.js';
  import { can } from '$lib/me.svelte.js';
  import { addrOf } from '$lib/leads.svelte.js';
  import Sheet from './glass/Sheet.svelte';
  import Icon from './glass/Icon.svelte';
  import PropertyPick from './PropertyPick.svelte';
  import QuickLog from './QuickLog.svelte';

  let picked = $state(null);           // {group_id, label, suburb} from the picker
  let contacts = $state([]);
  let loading = $state(false);
  let err = $state(null);

  const open = $derived(chrome.quickLog.open);
  const gid = $derived(chrome.quickLog.gid || (picked ? String(picked.group_id) : null));
  const tracked = $derived(!!gid && gid in app.tracked);

  /* What to call the property: the picker's label, else a prospect we
     already hold, else nothing (the page behind is about it anyway). */
  const name = $derived.by(() => {
    if (picked && String(picked.group_id) === gid) return { label: picked.label, suburb: picked.suburb };
    const r = gid && app.prospects.find((p) => String(p.group_id ?? 'solo-' + p.listing_key) === gid);
    return r ? { label: addrOf(r), suburb: r.suburb } : null;
  });

  // a closed sheet forgets its pick, so the next open starts clean
  $effect(() => { if (!open) { picked = null; contacts = []; err = null; } });

  // one contacts fetch per property (an untracked one simply has none)
  $effect(() => {
    const g = open ? gid : null;
    if (!g) return;
    let live = true;
    loading = true; err = null; contacts = [];
    api.child.list(g, 'contacts')
      .then((rows) => { if (live) contacts = Array.isArray(rows) ? rows : []; })
      .catch((e) => { if (live) err = e.message; })
      .finally(() => { if (live) loading = false; });
    return () => { live = false; };
  });

  function change() {
    picked = null;
    if (chrome.quickLog.gid) chrome.quickLog = { open: true, gid: null };
  }

  function saved() {
    const g = gid;
    loadTracked();
    window.dispatchEvent(new CustomEvent('mc:logged', { detail: { gid: g } }));
    closeQuickLog();
  }
</script>

<Sheet {open} title="Quick log" size="md" onclose={closeQuickLog}>
  <div class="qls" data-quicklog-sheet>
    {#if !can('leads')}
      <p class="mg-hint">Your account can't log contact attempts. Ask an admin for the leads privilege.</p>
    {:else if !gid}
      <p class="lead">Which property?</p>
      <PropertyPick bind:value={picked} placeholder="Search an address, suburb or title…" />
    {:else}
      <div class="about">
        <Icon name="property" size={15} />
        <span class="lb">
          {#if name}<b>{name.label}</b>{#if name.suburb}<i>{' · ' + name.suburb}</i>{/if}{:else}<b>This property</b>{/if}
        </span>
        <a class="mg-btn ghost sm" href="/leads/properties/{encodeURIComponent(gid)}" onclick={closeQuickLog}>Open</a>
        <button type="button" class="mg-btn secondary sm" onclick={change}>Change</button>
      </div>
      {#if !tracked}
        <p class="mg-hint note">Not tracked yet — logging this starts tracking it in Leads.</p>
      {/if}

      {#if loading}
        <p class="mg-hint"><span class="mg-spin"></span> Loading contacts…</p>
      {:else if err}
        <p class="mg-hint crit">Couldn't load the contacts: {err}</p>
      {:else}
        {#key gid}
          <QuickLog {gid} {contacts} onsaved={saved} oncancel={closeQuickLog} />
        {/key}
      {/if}
    {/if}
  </div>
</Sheet>

<style>
  .qls { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
  .lead { margin: 0; font: 500 13.5px/1.3 var(--mc-font); color: var(--mc-ink2); }
  .about { display: flex; align-items: center; gap: 8px; min-width: 0; color: var(--mc-ink2); }
  .about .lb { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .about b { font: 600 14px/1.3 var(--mc-font); color: var(--mc-ink); }
  .about i { font-style: normal; font-size: 13px; color: var(--mc-ink3); }
  .note { margin: -6px 0 0; }
  .crit { color: var(--mc-crit); }
  .mg-hint { display: flex; align-items: center; gap: 8px; }
</style>
