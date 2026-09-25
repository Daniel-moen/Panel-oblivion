<script>
  /* Account — you, your devices, and (for an admin) the people and invites.

     Five sections, in the order you need them: **You** is who the server
     thinks you are and what you may do; **Passkeys** and **Sessions** are the
     doors into your own account and nobody else's — an admin manages people,
     not their devices. Below those, only for an admin or the owner:
     **People** and **Invites**.

     There is no "create a user" button anywhere, and that is the design: an
     account comes into existence only when somebody opens a sign-up link and
     registers a passkey on their own device. So the admin's verbs are invite,
     revoke, adjust, remove — and the one raw token a new invite produces is
     shown exactly once, here, before the server forgets it. */
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { api } from '$lib/api.js';
  import { toast } from '$lib/state.svelte.js';
  import { me as meStore, loadMe } from '$lib/me.svelte.js';
  import {
    decodeCreationOptions, encodeRegistration, supported
  } from '$lib/webauthn.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';

  const PRIVS = [
    { flag: 'crawl', label: 'Crawls', hint: 'Start crawls, re-score, resolve erven' },
    { flag: 'leads', label: 'Leads', hint: 'Track properties, contacts, tasks, deeds' },
    { flag: 'media', label: 'Media', hint: 'Open the media library and share rooms' },
    { flag: 'admin', label: 'People', hint: 'Manage accounts and invites' }
  ];

  let me = $state(null);
  let keys = $state([]);
  let sessions = $state([]);
  let loaded = $state(false);
  let busy = $state(false);
  let naming = $state(false);     // the inline "what should this be called" row
  let name = $state('');

  /* You */
  let displayName = $state('');
  let savingName = $state(false);

  /* People + Invites — only fetched when the account may see them. */
  let people = $state([]);
  let invites = $state([]);
  let edit = $state(null);        // the user open in the edit Sheet
  let inviteOpen = $state(false);
  let draft = $state({ role: 'member', privileges: ['leads'], note: '', days: 7 });
  let minted = $state(null);      // the one and only sighting of a raw token
  let saving = $state(false);

  const isAdmin = $derived(!!me?.privileges?.includes('admin'));
  const isOwner = $derived(!!me?.is_owner);

  /* Straight after a password sign-in with no passkey on file, auth.py sends
     the browser here with ?welcome=1 rather than to where it was going. */
  const welcome = $derived(page.url.searchParams.get('welcome') === '1');
  const canPasskey = supported();

  async function load() {
    const [m, p] = await Promise.all([api.me(), api.passkeys()]);
    me = m;
    displayName = m.display_name || m.username;
    keys = p.passkeys;
    sessions = p.sessions;
    loaded = true;
    if (m.privileges?.includes('admin')) await loadPeople();
  }

  async function loadPeople() {
    const [u, i] = await Promise.all([api.users(), api.invites()]);
    people = u.users;
    invites = i.invites;
  }

  let loadErr = $state(null);
  async function reload() {
    loadErr = null;
    try { await load(); } catch (e) { loadErr = e.message || String(e); toast(e.message, 'error'); }
  }
  onMount(reload);

  /* ——— you ——— */
  async function saveName() {
    const want = displayName.trim();
    if (!want || want === (me.display_name || me.username)) return;
    savingName = true;
    try {
      me = await api.updateMe({ display_name: want });
      displayName = me.display_name;
      Object.assign(meStore, me);
      toast('Name saved.');
    } catch (e) { toast(e.message, 'error'); }
    finally { savingName = false; }
  }

  /* ——— passkeys ——— */

  /* A rough guess at what to call this device, so the field is never empty.
     The server derives the same thing from the User-Agent if it is cleared. */
  function guessName() {
    const ua = navigator.userAgent;
    const os = /iPhone/.test(ua) ? 'iPhone' : /iPad/.test(ua) ? 'iPad'
      : /Android/.test(ua) ? 'Android' : /Macintosh|Mac OS/.test(ua) ? 'Mac'
      : /Windows/.test(ua) ? 'Windows' : /Linux/.test(ua) ? 'Linux' : 'Device';
    const br = /Edg\//.test(ua) ? 'Edge' : /Chrome|CriOS/.test(ua) ? 'Chrome'
      : /Firefox|FxiOS/.test(ua) ? 'Firefox' : /Safari/.test(ua) ? 'Safari' : 'Browser';
    return `${os} / ${br}`;
  }

  function startAdd() {
    name = guessName();
    naming = true;
  }

  async function add() {
    busy = true;
    try {
      const got = await api.passkeyRegisterOptions();
      const cred = await navigator.credentials.create({
        publicKey: decodeCreationOptions(got.options)
      });
      if (!cred) throw new Error('cancelled');
      await api.passkeyRegisterVerify(got.token, name.trim(), encodeRegistration(cred));
      naming = false;
      await load();
      toast('Passkey added. Next sign-in is just a touch.');
    } catch (e) {
      // A cancelled prompt is not an error worth shouting about, but an
      // already-registered device is worth explaining.
      const m = String(e?.message || e);
      if (e?.name === 'InvalidStateError') toast('This device already has a passkey here.', 'error');
      else if (e?.name !== 'NotAllowedError' && m !== 'cancelled') toast(m, 'error');
    } finally {
      busy = false;
    }
  }

  async function remove(k) {
    if (!confirm(`Remove “${k.name}”? That device will need to be invited again.`)) return;
    try { await api.passkeyDelete(k.id); await load(); }
    catch (e) { toast(e.message, 'error'); }
  }

  async function signOut(s) {
    if (s.current) {
      try { await api.logout(); } catch { /* the cookie is cleared either way */ }
      location.href = '/login';
      return;
    }
    try { await api.sessionRevoke(s.id); await load(); toast('Signed that device out.'); }
    catch (e) { toast(e.message, 'error'); }
  }

  /* ——— people ——— */
  function openEdit(u) {
    edit = { ...u, privileges: [...(u.granted || [])] };
  }

  function togglePriv(list, flag) {
    return list.includes(flag) ? list.filter((f) => f !== flag) : [...list, flag];
  }

  async function saveUser() {
    saving = true;
    try {
      const body = {
        display_name: edit.display_name,
        privileges: edit.privileges,
        disabled: !!edit.disabled
      };
      if (isOwner && !edit.is_owner) body.role = edit.role;
      await api.updateUser(edit.id, body);
      edit = null;
      await loadPeople();
      toast('Saved.');
    } catch (e) { toast(e.message, 'error'); }
    finally { saving = false; }
  }

  async function removeUser(u) {
    if (!confirm(`Remove ${u.display_name}? Their passkeys go with the account `
      + `and they are signed out everywhere.`)) return;
    try {
      await api.deleteUser(u.id);
      edit = null;
      await loadPeople();
      toast(`${u.username} removed.`);
    } catch (e) { toast(e.message, 'error'); }
  }

  async function reinvite(u) {
    try {
      minted = await api.reinvite(u.id);
      edit = null;
      inviteOpen = true;
      await loadPeople();
    } catch (e) { toast(e.message, 'error'); }
  }

  /* ——— invites ——— */
  function newInvite() {
    minted = null;
    draft = { role: 'member', privileges: ['leads'], note: '', days: 7 };
    inviteOpen = true;
  }

  async function createInvite() {
    saving = true;
    try {
      minted = await api.createInvite({
        role: draft.role,
        privileges: draft.role === 'admin' ? [] : draft.privileges,
        note: draft.note,
        days: Number(draft.days) || 7
      });
      await loadPeople();
    } catch (e) { toast(e.message, 'error'); }
    finally { saving = false; }
  }

  async function revokeInvite(inv) {
    if (!confirm('Withdraw this link? Anyone holding it can no longer sign up.')) return;
    try { await api.revokeInvite(inv.id); await loadPeople(); toast('Link withdrawn.'); }
    catch (e) { toast(e.message, 'error'); }
  }

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast('Link copied — send it to them.');
    } catch { toast('Copy failed — select the link and copy it.', 'error'); }
  }

  const day = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
    return d.toLocaleDateString('en-ZA', { day: 'numeric', month: 'short', year: 'numeric' });
  };
  const ago = (iso) => {
    if (!iso) return 'never';
    const s = (Date.now() - new Date(iso.endsWith('Z') ? iso : iso + 'Z')) / 1000;
    if (s < 120) return 'just now';
    if (s < 5400) return `${Math.round(s / 60)} min ago`;
    if (s < 172800) return `${Math.round(s / 3600)} h ago`;
    return `${Math.round(s / 86400)} days ago`;
  };
  const privLabel = (f) => PRIVS.find((p) => p.flag === f)?.label || f;
</script>

<svelte:head><title>Account — Oblivion</title></svelte:head>

<div class="mg-row">
  <div class="titles">
    <h1 class="mg-h2">Account</h1>
    {#if me}<p class="mg-hint">Signed in as <span class="mg-mono">@{me.username}</span></p>{/if}
  </div>
</div>

{#if welcome && !keys.length}
  <div class="mg-strip ok">
    <span class="ic"><Icon name="passkey" size={16} /></span>
    <span><b>Add this device</b> so next time is just Touch ID.</span>
  </div>
{/if}

{#if loadErr}
  <div class="mg-strip crit">
    <span class="ic"><Icon name="alert" size={16} /></span>
    <span class="grow"><b>Could not load your account.</b> {loadErr}</span>
    <button type="button" class="mg-btn secondary sm" onclick={reload}><Icon name="refresh" size={13} /> Retry</button>
  </div>
{/if}

<div class="stack">
<!-- ————————————————————————————————————————————————————————— you ——— -->
<section class="mg-section mg-rise" style:--i={0}>
  <div class="head"><span class="hud">You</span></div>
  <p class="mg-hint lede">Your name is yours to change. What you may do is set by
    the owner — the server checks it on every write.</p>

  {#if !me}
    <div class="pad"><Skeleton lines={3} h="14px" /></div>
  {:else}
    <div class="rows">
      <div class="row wrap">
        <label class="k" for="me-name">Name</label>
        <div class="v namer">
          <input id="me-name" class="mg-input" bind:value={displayName} maxlength="60"
                 aria-label="Your name" onblur={saveName}
                 onkeydown={(e) => e.key === 'Enter' && saveName()} />
          <button type="button" class="mg-btn secondary sm" onclick={saveName} disabled={savingName}>
            {#if savingName}<span class="mg-spin"></span>{/if}Save
          </button>
        </div>
      </div>
      <div class="row">
        <span class="k">Username</span>
        <span class="v mg-mono val">@{me.username}</span>
      </div>
      <div class="row">
        <span class="k">Role</span>
        <span class="v">
          <span class="mg-chip" class:ok={me.is_owner} class:mgr={me.role === 'admin'}>
            <Icon name={me.is_owner || me.role === 'admin' ? 'shield' : 'user'} size={13} />
            {me.role}
          </span>
        </span>
      </div>
      <div class="row wrap">
        <span class="k">Can do</span>
        <span class="v chips">
          {#each me.privileges as p (p)}
            <span class="mg-chip on">{privLabel(p)}</span>
          {/each}
          {#if !me.privileges.length}
            <span class="mg-chip">Read only</span>
          {/if}
        </span>
      </div>
    </div>
  {/if}
</section>

<!-- ———————————————————————————————————————————————————— passkeys ——— -->
<section class="mg-section mg-rise" style:--i={1}>
  <div class="head">
    <span class="hud">Passkeys</span>
    {#if loaded}<span class="mg-count">{keys.length}</span>{/if}
    {#if canPasskey && !naming}
      <div class="mg-actions">
        <button type="button" class="mg-btn primary sm" onclick={startAdd} disabled={busy}>
          <Icon name="plus" size={15} /> Add this device
        </button>
      </div>
    {/if}
  </div>
  <p class="mg-hint lede">The passkey stays on this device (or in iCloud Keychain /
    Windows Hello). Nothing biometric is sent to the server.</p>

  <div class="rows">
    {#if naming}
      <div class="row wrap adding">
        <label class="k" for="pk-name">Name this device</label>
        <div class="v namer">
          <input id="pk-name" class="mg-input" bind:value={name} placeholder="Name this device"
                 onkeydown={(e) => e.key === 'Enter' && add()} />
          <button type="button" class="mg-btn primary sm" onclick={add} disabled={busy}>
            {#if busy}<span class="mg-spin"></span>{:else}<Icon name="passkey" size={14} />{/if}Add
          </button>
          <button type="button" class="mg-btn ghost sm" onclick={() => (naming = false)}>Cancel</button>
        </div>
      </div>
    {/if}

    {#if !canPasskey}
      <div class="row"><span class="k none">This browser has no passkey support, so sign-in here has to
        happen on another device.</span></div>
    {:else if !loaded}
      <div class="pad"><Skeleton lines={2} h="14px" /></div>
    {:else if !keys.length}
      <div class="row"><span class="k none">No passkeys on this account yet.</span></div>
    {/if}

    {#each keys as k (k.id)}
      <div class="row item">
        <span class="ic"><Icon name="key" size={16} /></span>
        <div class="who">
          <b>{k.name}</b>
          <i>added {day(k.created_at)} · last used {ago(k.last_used_at)}</i>
        </div>
        <button type="button" class="mg-btn danger sm" onclick={() => remove(k)}>Remove</button>
      </div>
    {/each}
  </div>
</section>

<!-- ———————————————————————————————————————————————————— sessions ——— -->
<section class="mg-section mg-rise" style:--i={2}>
  <div class="head">
    <span class="hud">Signed-in devices</span>
    {#if loaded}<span class="mg-count">{sessions.length}</span>{/if}
  </div>
  <p class="mg-hint lede">Every browser currently holding a sign-in cookie. Signing
    one out takes effect immediately.</p>

  <div class="rows">
    {#if !loaded}
      <div class="pad"><Skeleton lines={2} h="14px" /></div>
    {:else if !sessions.length}
      <div class="row"><span class="k none">No other sign-ins.</span></div>
    {/if}
    {#each sessions as s (s.id)}
      <div class="row item">
        <span class="ic" class:live={s.current}><Icon name={s.current ? 'check' : 'user'} size={16} /></span>
        <div class="who">
          <b>{s.label}{#if s.current}<span class="mg-chip ok here">This browser</span>{/if}</b>
          <i>signed in {day(s.created_at)} · active {ago(s.last_seen_at)}</i>
        </div>
        <button type="button" class="mg-btn sm" class:danger={!s.current} class:secondary={s.current}
                onclick={() => signOut(s)}>{#if s.current}<Icon name="power" size={13} />{/if}Sign out</button>
      </div>
    {/each}
  </div>
</section>

{#if isAdmin}
  <!-- ———————————————————————————————————————————————————— people ——— -->
  <section class="mg-section mg-rise" style:--i={3}>
    <div class="head">
      <span class="hud">People</span>
      <span class="mg-count">{people.length}</span>
    </div>
    <p class="mg-hint lede">Everyone who can sign in. Accounts are passkey-only —
      nobody here has a password.</p>

    <div class="mg-tablewrap">
      <table class="mg-table">
        <thead>
          <tr>
            <th>Person</th><th>Role</th><th>Can</th>
            <th class="r">Devices</th><th>Last seen</th><th></th>
          </tr>
        </thead>
        <tbody>
          {#each people as u (u.id)}
            <tr class:off={u.disabled}>
              <td class="b">
                {u.display_name}
                <i class="at mg-mono">@{u.username}</i>
              </td>
              <td>
                <span class="tags">
                  <span class="mg-chip" class:ok={u.is_owner} class:mgr={u.role === 'admin'}>{u.role}</span>
                  {#if u.disabled}<span class="mg-chip crit">off</span>{/if}
                </span>
              </td>
              <td>
                <span class="tags">
                  {#each u.privileges as p (p)}<span class="mg-chip">{privLabel(p)}</span>{/each}
                  {#if !u.privileges.length}<i class="dim">read only</i>{/if}
                </span>
              </td>
              <td class="r mg-mono">{u.passkeys}</td>
              <td class="nowrap">{ago(u.last_seen_at)}</td>
              <td class="r">
                {#if !u.is_owner}
                  <button type="button" class="mg-btn secondary sm" onclick={() => openEdit(u)}>
                    <Icon name="edit" size={14} /> Edit
                  </button>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>

  <!-- ——————————————————————————————————————————————————— invites ——— -->
  <section class="mg-section mg-rise" style:--i={4}>
    <div class="head">
      <span class="hud">Invites</span>
      {#if invites.length}<span class="mg-count">{invites.length}</span>{/if}
      <div class="mg-actions">
        <button type="button" class="mg-btn primary sm" onclick={newInvite}>
          <Icon name="plus" size={15} /> New invite
        </button>
      </div>
    </div>
    <p class="mg-hint lede">A sign-up link creates one account, once. The link is
      shown a single time — copy it before you close the panel.</p>

    {#if !invites.length}
      <Empty icon="ticket" title="No invites yet"
             hint="Create a link, send it to the person, and they register a passkey on their own device.">
        <button type="button" class="mg-btn secondary sm" onclick={newInvite}>New invite</button>
      </Empty>
    {:else}
      <div class="rows">
        {#each invites as inv (inv.id)}
          <div class="row item" class:spent={inv.state !== 'ok'}>
            <span class="ic"><Icon name="ticket" size={16} /></span>
            <div class="who">
              <b>
                {inv.for_user ? `Re-register ${inv.for_user}` : inv.note || 'Sign-up link'}
                <span class="mg-chip sm-chip" class:mgr={inv.role === 'admin'}>{inv.role}</span>
                {#each inv.privileges as p (p)}<span class="mg-chip sm-chip">{privLabel(p)}</span>{/each}
              </b>
              <i>
                {#if inv.state === 'ok'}expires {day(inv.expires_at)}
                {:else if inv.state === 'used'}used {day(inv.used_at)}
                {:else if inv.state === 'revoked'}withdrawn
                {:else}expired {day(inv.expires_at)}{/if}
                {#if inv.created_by} · from {inv.created_by}{/if}
              </i>
            </div>
            {#if inv.state === 'ok'}
              <button type="button" class="mg-btn danger sm" onclick={() => revokeInvite(inv)}>Withdraw</button>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  </section>
{/if}
</div>

<!-- ——————————————————————————————————————————————————— edit sheet ——— -->
<Sheet open={!!edit} title={edit ? edit.display_name : ''} size="sm"
       onclose={() => (edit = null)}>
  {#if edit}
    <p class="mg-sub">@{edit.username} · signs in with {edit.passkeys}
      {edit.passkeys === 1 ? 'passkey' : 'passkeys'}.</p>

    <label class="mg-label" for="ed-name">Name</label>
    <input id="ed-name" class="mg-input full" bind:value={edit.display_name} maxlength="60" />

    {#if isOwner}
      <span class="mg-label spaced">Role</span>
      <Seg options={[{ value: 'member', label: 'Member' }, { value: 'admin', label: 'Admin' }]}
           value={edit.role} label="Role"
           onchange={(v) => (edit.role = v)} />
      <p class="mg-hint hint">An admin can invite people and adjust anyone but the
        owner and other admins.</p>
    {/if}

    {#if edit.role !== 'admin'}
      <span class="mg-label spaced">Can do</span>
      <div class="chips">
        {#each PRIVS.filter((p) => p.flag !== 'admin') as p (p.flag)}
          <button type="button" class="mg-chip" class:on={edit.privileges.includes(p.flag)}
                  title={p.hint}
                  onclick={() => (edit.privileges = togglePriv(edit.privileges, p.flag))}>
            {#if edit.privileges.includes(p.flag)}<Icon name="check" size={13} />{/if}
            {p.label}
          </button>
        {/each}
      </div>
      <p class="mg-hint hint">Everyone signed in can read everything. These are the
        things that change data.</p>
    {:else}
      <p class="mg-hint hint spaced">An admin has every privilege, including people
        and invites.</p>
    {/if}

    <label class="switch">
      <input type="checkbox" bind:checked={edit.disabled} />
      <span>Signed out and locked out</span>
    </label>

    <div class="danger-row">
      <button type="button" class="mg-btn secondary sm" onclick={() => reinvite(edit)}>
        <Icon name="key" size={14} /> New sign-up link
      </button>
      <button type="button" class="mg-btn danger sm" onclick={() => removeUser(edit)}>
        <Icon name="trash" size={14} /> Remove
      </button>
    </div>
    <p class="mg-hint hint">Lost every device? A new sign-up link is the recovery —
      there is no password to reset.</p>
  {/if}

  {#snippet footer()}
    <button type="button" class="mg-btn ghost" onclick={() => (edit = null)}>Cancel</button>
    <div class="right">
      <button type="button" class="mg-btn primary" onclick={saveUser} disabled={saving}>
        {#if saving}<span class="mg-spin"></span>{/if}Save
      </button>
    </div>
  {/snippet}
</Sheet>

<!-- ————————————————————————————————————————————————— invite sheet ——— -->
<Sheet open={inviteOpen} title={minted ? 'Send this link' : 'New invite'} size="sm"
       onclose={() => (inviteOpen = false)}>
  {#if minted}
    <p class="mg-sub">This is the only time the link is shown. The server keeps
      just a hash of it.</p>
    <div class="namer">
      <input class="mg-input" readonly value={minted.url}
             onfocus={(e) => e.currentTarget.select()} aria-label="Sign-up link" />
      <button type="button" class="mg-btn primary sm" onclick={() => copy(minted.url)}>
        <Icon name="copy" size={14} /> Copy
      </button>
    </div>
    <p class="mg-hint hint">Send it however you normally talk to them. They open it,
      pick a name and register a passkey — that is the whole sign-up.</p>
  {:else}
    <span class="mg-label">Role</span>
    <Seg options={[{ value: 'member', label: 'Member' }, ...(isOwner ? [{ value: 'admin', label: 'Admin' }] : [])]}
         value={draft.role} label="Role" onchange={(v) => (draft.role = v)} />

    {#if draft.role === 'member'}
      <span class="mg-label spaced">Can do</span>
      <div class="chips">
        {#each PRIVS.filter((p) => p.flag !== 'admin') as p (p.flag)}
          <button type="button" class="mg-chip" class:on={draft.privileges.includes(p.flag)}
                  title={p.hint}
                  onclick={() => (draft.privileges = togglePriv(draft.privileges, p.flag))}>
            {#if draft.privileges.includes(p.flag)}<Icon name="check" size={13} />{/if}
            {p.label}
          </button>
        {/each}
      </div>
    {:else}
      <p class="mg-hint hint spaced">An admin gets everything, including people and
        invites.</p>
    {/if}

    <label class="mg-label spaced" for="inv-note">Note</label>
    <input id="inv-note" class="mg-input full" bind:value={draft.note}
           placeholder="Who is this for?" maxlength="200" />

    <label class="mg-label spaced" for="inv-days">Good for</label>
    <div class="days">
      <input id="inv-days" class="mg-input" type="number" min="1" max="90"
             bind:value={draft.days} />
      <span class="mg-hint">days</span>
    </div>
  {/if}

  {#snippet footer()}
    {#if minted}
      <div class="right">
        <button type="button" class="mg-btn primary" onclick={() => (inviteOpen = false)}>Done</button>
      </div>
    {:else}
      <button type="button" class="mg-btn ghost" onclick={() => (inviteOpen = false)}>Cancel</button>
      <div class="right">
        <button type="button" class="mg-btn primary" onclick={createInvite} disabled={saving}>
          {#if saving}<span class="mg-spin"></span>{/if}Create link
        </button>
      </div>
    {/if}
  {/snippet}
</Sheet>

<style>
  .titles { min-width: 0; }
  .titles .mg-hint { margin-top: 3px; }
  .mg-strip.crit { align-items: center; }
  .grow { flex: 1; min-width: 0; }
  .stack { display: flex; flex-direction: column; gap: 14px; max-width: 880px; }

  /* the Settings-sheet shape: a quiet uppercase title, a line of context,
     then 44px rows — label left, value or action right, hairline between */
  .mg-section > .head { align-items: center; min-height: 48px; padding: 8px 16px; border-bottom: 0; }
  .mg-section > .head .hud { color: var(--mc-ink3); }
  .lede { padding: 0 16px 12px; max-width: 64ch; }
  .pad { padding: 12px 16px 16px; border-top: 1px solid var(--mc-line); }

  .rows { display: flex; flex-direction: column; }
  .row {
    display: flex; align-items: center; gap: 12px; min-height: 44px; padding: 10px 16px;
    border-top: 1px solid var(--mc-line);
  }
  .row .k { flex: none; min-width: 7rem; font: 400 13px/1.4 var(--mc-font); color: var(--mc-ink3); }
  .row .k.none { flex: 1; min-width: 0; }
  .row .v { margin-left: auto; min-width: 0; display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
  .val { font-size: 12.5px; color: var(--mc-ink); }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .row .mg-chip { height: 26px; padding: 0 10px; }

  .namer { flex: 1; display: flex; align-items: center; gap: 8px; min-width: 0; }
  .namer .mg-btn { flex: none; }
  .namer .mg-input { flex: 1 1 200px; max-width: 22rem; }
  .adding { background: rgba(255, 255, 255, 0.03); }

  .item .ic { flex: none; display: grid; place-items: center; width: 32px; height: 32px; border-radius: 10px;
              background: var(--mc-raised); border: 1px solid var(--mc-line); color: var(--mc-ink3); }
  .item .ic.live { color: var(--mc-accent); border-color: var(--mc-ok-line); background: var(--mc-ok-soft); }
  .who { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .who b { display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
           font: 500 13.5px/1.3 var(--mc-font); color: var(--mc-ink); }
  .who i { font: 400 12px/1.4 var(--mc-font); font-style: normal; color: var(--mc-ink3); }
  .item > .mg-btn { flex: none; }
  .spent { opacity: 0.55; }
  .who b .mg-chip { height: 20px; padding: 0 8px; font-size: 11px; }

  /* people table */
  .mg-tablewrap { border-top: 1px solid var(--mc-line); }
  .mg-table th:first-child, .mg-table td:first-child { padding-left: 16px; }
  .mg-table th:last-child, .mg-table td:last-child { padding-right: 16px; }
  .mg-table td.b .at { display: block; font-style: normal; font-weight: 400; font-size: 11.5px; color: var(--mc-ink3); }
  .mg-table tr.off { opacity: 0.55; }
  .mg-table td.r.mg-mono { color: var(--mc-ink); }
  /* chips stay on one line: the table scrolls sideways rather than growing tall */
  .tags { display: inline-flex; flex-wrap: nowrap; gap: 4px; }
  .tags .mg-chip { height: 22px; padding: 0 8px; font-size: 11px; }
  .nowrap { white-space: nowrap; }
  .dim { font-style: normal; color: var(--mc-ink3); }

  /* sheet innards */
  .mg-sub { margin-bottom: 16px; }
  .mg-input.full { width: 100%; }
  .mg-label { margin-bottom: 6px; }
  .spaced { margin-top: 16px; }
  .hint { margin-top: 8px; }
  .days { display: flex; align-items: center; gap: 8px; }
  .days .mg-input { width: 6rem; font-family: var(--mc-mono); }
  .switch { display: flex; align-items: center; gap: 10px; min-height: 44px; margin-top: 12px;
            font: 400 13px/1.4 var(--mc-font); color: var(--mc-ink2); cursor: pointer; }
  .switch input { width: 18px; height: 18px; accent-color: var(--mc-crit); }
  .danger-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px;
                padding-top: 16px; border-top: 1px solid var(--mc-line); }

  @media (max-width: 639px) {
    /* a row holding a field puts the label above it */
    .row.wrap { flex-wrap: wrap; gap: 8px; }
    .row.wrap .v { margin-left: 0; flex: 1 1 100%; justify-content: flex-start; }
    .namer .mg-input { max-width: none; }
  }
  @media (pointer: coarse) {
    .row .mg-btn.sm, .item > .mg-btn { height: 40px; }
    .namer .mg-input { height: 44px; }
  }
</style>
