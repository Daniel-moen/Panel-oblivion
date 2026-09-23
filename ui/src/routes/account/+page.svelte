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

  onMount(async () => {
    try { await load(); } catch (e) { toast(e.message, 'error'); }
  });

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
  <h1 class="mg-h2">Account</h1>
  {#if me}<span class="mg-count">signed in as {me.username}</span>{/if}
</div>

{#if welcome && !keys.length}
  <div class="mg-strip">
    <span class="ic"><Icon name="sparkles" size={16} /></span>
    <span><b>Add this device</b> so next time is just Touch ID.</span>
  </div>
{/if}

<!-- ————————————————————————————————————————————————————————— you ——— -->
<section class="mg-card">
  <header>
    <div>
      <h2>You</h2>
      <p class="sub">Your name is yours to change. What you may do is set by
        the owner — the server checks it on every write.</p>
    </div>
  </header>

  {#if me}
    <div class="you">
      <div class="namer">
        <input class="mg-input" bind:value={displayName} maxlength="60"
               aria-label="Your name" onblur={saveName}
               onkeydown={(e) => e.key === 'Enter' && saveName()} />
        <button class="mg-btn secondary sm" onclick={saveName} disabled={savingName}>
          {#if savingName}<span class="mg-spin"></span>{/if}Save
        </button>
      </div>
      <div class="chips">
        <span class="mg-chip" class:ok={me.is_owner} class:mgr={me.role === 'admin'}>
          <Icon name={me.is_owner ? 'shield' : me.role === 'admin' ? 'shield' : 'user'} size={13} />
          {me.role}
        </span>
        <span class="mg-chip">@{me.username}</span>
        {#each me.privileges as p (p)}
          <span class="mg-chip on">{privLabel(p)}</span>
        {/each}
        {#if !me.privileges.length}
          <span class="mg-chip">read only</span>
        {/if}
      </div>
    </div>
  {/if}
</section>

<!-- ———————————————————————————————————————————————————— passkeys ——— -->
<section class="mg-card">
  <header>
    <div>
      <h2>Passkeys</h2>
      <p class="sub">The passkey stays on this device (or in iCloud Keychain /
        Windows Hello). Nothing biometric is sent to the server.</p>
    </div>
    {#if canPasskey && !naming}
      <button class="mg-btn primary sm" onclick={startAdd} disabled={busy}>
        <Icon name="plus" size={16} /> Add this device
      </button>
    {/if}
  </header>

  {#if naming}
    <div class="namer">
      <input class="mg-input" bind:value={name} placeholder="Name this device"
             onkeydown={(e) => e.key === 'Enter' && add()} />
      <button class="mg-btn primary sm" onclick={add} disabled={busy}>
        {#if busy}<span class="mg-spin"></span>{/if}Add
      </button>
      <button class="mg-btn ghost sm" onclick={() => (naming = false)}>Cancel</button>
    </div>
  {/if}

  {#if !canPasskey}
    <p class="none">This browser has no passkey support, so sign-in here has to
      happen on another device.</p>
  {:else if loaded && !keys.length}
    <p class="none">No passkeys on this account yet.</p>
  {/if}

  <ul class="rows">
    {#each keys as k (k.id)}
      <li>
        <span class="ic"><Icon name="key" size={16} /></span>
        <div class="who">
          <b>{k.name}</b>
          <i>added {day(k.created_at)} · last used {ago(k.last_used_at)}</i>
        </div>
        <button class="mg-btn danger sm" onclick={() => remove(k)}>Remove</button>
      </li>
    {/each}
  </ul>
</section>

<!-- ———————————————————————————————————————————————————— sessions ——— -->
<section class="mg-card">
  <header>
    <div>
      <h2>Sessions</h2>
      <p class="sub">Every browser currently holding a sign-in cookie. Signing
        one out takes effect immediately.</p>
    </div>
  </header>

  <ul class="rows">
    {#each sessions as s (s.id)}
      <li>
        <span class="ic"><Icon name="user" size={16} /></span>
        <div class="who">
          <b>{s.label}{#if s.current}<span class="here">this browser</span>{/if}</b>
          <i>signed in {day(s.created_at)} · active {ago(s.last_seen_at)}</i>
        </div>
        <button class="mg-btn sm" class:danger={!s.current} class:secondary={s.current}
                onclick={() => signOut(s)}>Sign out</button>
      </li>
    {/each}
  </ul>
</section>

{#if isAdmin}
  <!-- ———————————————————————————————————————————————————— people ——— -->
  <section class="mg-card">
    <header>
      <div>
        <h2>People <span class="mg-count">{people.length}</span></h2>
        <p class="sub">Everyone who can sign in. Accounts are passkey-only —
          nobody here has a password.</p>
      </div>
    </header>

    <div class="tablewrap">
      <table class="mg-table">
        <thead>
          <tr>
            <th>Person</th><th>Role</th><th>Can</th>
            <th>Devices</th><th>Last seen</th><th></th>
          </tr>
        </thead>
        <tbody>
          {#each people as u (u.id)}
            <tr class:off={u.disabled}>
              <td class="b">
                {u.display_name}
                <i class="at">@{u.username}</i>
              </td>
              <td>
                <span class="mg-chip" class:ok={u.is_owner} class:mgr={u.role === 'admin'}>
                  {u.role}
                </span>
                {#if u.disabled}<span class="mg-chip crit">off</span>{/if}
              </td>
              <td>
                <span class="privs">
                  {#each u.privileges as p (p)}<span class="mg-chip">{privLabel(p)}</span>{/each}
                  {#if !u.privileges.length}<i class="dim">read only</i>{/if}
                </span>
              </td>
              <td class="num">{u.passkeys}</td>
              <td>{ago(u.last_seen_at)}</td>
              <td>
                {#if !u.is_owner}
                  <button class="mg-btn ghost sm" onclick={() => openEdit(u)}>
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
  <section class="mg-card">
    <header>
      <div>
        <h2>Invites</h2>
        <p class="sub">A sign-up link creates one account, once. The link is
          shown a single time — copy it before you close the panel.</p>
      </div>
      <button class="mg-btn primary sm" onclick={newInvite}>
        <Icon name="plus" size={16} /> New invite
      </button>
    </header>

    {#if !invites.length}
      <Empty icon="ticket" title="No invites yet"
             hint="Create a link, send it to the person, and they register a passkey on their own device.">
        <button class="mg-btn primary sm" onclick={newInvite}>New invite</button>
      </Empty>
    {:else}
      <ul class="rows">
        {#each invites as inv (inv.id)}
          <li class:spent={inv.state !== 'ok'}>
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
              <button class="mg-btn ghost sm" onclick={() => revokeInvite(inv)}>Withdraw</button>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </section>
{/if}

<!-- ——————————————————————————————————————————————————— edit sheet ——— -->
<Sheet open={!!edit} title={edit ? edit.display_name : ''} size="sm"
       onclose={() => (edit = null)}>
  {#if edit}
    <p class="sub">@{edit.username} · signs in with {edit.passkeys}
      {edit.passkeys === 1 ? 'passkey' : 'passkeys'}.</p>

    <label class="mg-label" for="ed-name">Name</label>
    <input id="ed-name" class="mg-input full" bind:value={edit.display_name} maxlength="60" />

    {#if isOwner}
      <span class="mg-label spaced">Role</span>
      <Seg options={[{ value: 'member', label: 'Member' }, { value: 'admin', label: 'Admin' }]}
           value={edit.role} label="Role"
           onchange={(v) => (edit.role = v)} />
      <p class="hint">An admin can invite people and adjust anyone but the
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
      <p class="hint">Everyone signed in can read everything. These are the
        things that change data.</p>
    {:else}
      <p class="hint spaced">An admin has every privilege, including people
        and invites.</p>
    {/if}

    <label class="switch">
      <input type="checkbox" bind:checked={edit.disabled} />
      <span>Signed out and locked out</span>
    </label>

    <div class="danger-row">
      <button class="mg-btn secondary sm" onclick={() => reinvite(edit)}>
        <Icon name="key" size={14} /> New sign-up link
      </button>
      <button class="mg-btn danger sm" onclick={() => removeUser(edit)}>
        <Icon name="trash" size={14} /> Remove
      </button>
    </div>
    <p class="hint">Lost every device? A new sign-up link is the recovery —
      there is no password to reset.</p>
  {/if}

  {#snippet footer()}
    <button class="mg-btn ghost" onclick={() => (edit = null)}>Cancel</button>
    <div class="right">
      <button class="mg-btn primary" onclick={saveUser} disabled={saving}>
        {#if saving}<span class="mg-spin"></span>{/if}Save
      </button>
    </div>
  {/snippet}
</Sheet>

<!-- ————————————————————————————————————————————————— invite sheet ——— -->
<Sheet open={inviteOpen} title={minted ? 'Send this link' : 'New invite'} size="sm"
       onclose={() => (inviteOpen = false)}>
  {#if minted}
    <p class="sub">This is the only time the link is shown. The server keeps
      just a hash of it.</p>
    <div class="namer">
      <input class="mg-input" readonly value={minted.url}
             onfocus={(e) => e.currentTarget.select()} aria-label="Sign-up link" />
      <button class="mg-btn primary sm" onclick={() => copy(minted.url)}>
        <Icon name="copy" size={14} /> Copy
      </button>
    </div>
    <p class="hint">Send it however you normally talk to them. They open it,
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
      <p class="hint spaced">An admin gets everything, including people and
        invites.</p>
    {/if}

    <label class="mg-label spaced" for="inv-note">Note</label>
    <input id="inv-note" class="mg-input full" bind:value={draft.note}
           placeholder="Who is this for?" maxlength="200" />

    <label class="mg-label spaced" for="inv-days">Good for</label>
    <div class="days">
      <input id="inv-days" class="mg-input" type="number" min="1" max="90"
             bind:value={draft.days} />
      <span class="dim">days</span>
    </div>
  {/if}

  {#snippet footer()}
    {#if minted}
      <div class="right">
        <button class="mg-btn primary" onclick={() => (inviteOpen = false)}>Done</button>
      </div>
    {:else}
      <button class="mg-btn ghost" onclick={() => (inviteOpen = false)}>Cancel</button>
      <div class="right">
        <button class="mg-btn primary" onclick={createInvite} disabled={saving}>
          {#if saving}<span class="mg-spin"></span>{/if}Create link
        </button>
      </div>
    {/if}
  {/snippet}
</Sheet>

<style>
  .mg-card { margin-bottom: 14px; }
  header { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 12px; }
  header > div { min-width: 0; }
  header button { margin-left: auto; flex: none; }
  h2 { margin: 0; font: 600 15px/1.2 var(--mg-font); color: var(--mg-i); }
  .sub { margin: 4px 0 0; max-width: 58ch; font: 400 12.5px/1.6 var(--mg-font); color: var(--mg-i3); }

  .namer { display: flex; gap: 8px; margin-bottom: 12px; }
  .namer .mg-input { flex: 1 1 200px; max-width: 26rem; }

  .none { margin: 0; font: 400 13px/1.5 var(--mg-font); color: var(--mg-i3); }

  .you .chips { margin-top: 2px; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }

  .rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
  .rows li { display: flex; align-items: center; gap: 12px; padding: 11px 0;
             border-top: 1px solid var(--mg-line); }
  .rows li:first-child { border-top: 0; }
  .rows li.spent { opacity: 0.55; }
  .rows .ic { flex: none; display: flex; color: var(--mg-i3); }
  .who { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .who b { display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
           font: 500 13.5px/1.3 var(--mg-font); color: var(--mg-i); }
  .who i { font: 400 12px/1.4 var(--mg-font); font-style: normal; color: var(--mg-i3); }
  .rows li button { margin-left: auto; flex: none; }

  .here { margin-left: 8px; padding: 1px 7px; border-radius: 9999px;
          background: rgba(62, 207, 142, 0.14); color: var(--mg-ok);
          font: 500 11px/1.6 var(--mg-font); }

  /* people table: a row list, so it scrolls sideways on a phone rather than
     wrapping into an unreadable stack */
  .tablewrap { overflow-x: auto; }
  .mg-table td.b .at { display: block; font-style: normal; font-weight: 400;
                       font-size: 12px; color: var(--mg-i3); }
  .mg-table tr.off { opacity: 0.55; }
  .privs { display: inline-flex; flex-wrap: wrap; gap: 4px; }
  .privs .mg-chip { padding: 3px 9px; font-size: 11px; }
  .dim { font-style: normal; color: var(--mg-i3); }
  .sm-chip { padding: 2px 8px; font-size: 11px; }

  /* sheet innards */
  .mg-input.full { width: 100%; }
  .spaced { margin-top: 16px; }
  .hint { margin: 8px 0 0; font: 400 12px/1.6 var(--mg-font); color: var(--mg-i3); }
  .days { display: flex; align-items: center; gap: 8px; }
  .days .mg-input { width: 6rem; }
  .switch { display: flex; align-items: center; gap: 9px; margin-top: 18px;
            font: 400 13px/1.4 var(--mg-font); color: var(--mg-i2); cursor: pointer; }
  .switch input { width: 16px; height: 16px; accent-color: var(--mg-crit); }
  .danger-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px;
                padding-top: 16px; border-top: 1px solid var(--mg-line); }
</style>
