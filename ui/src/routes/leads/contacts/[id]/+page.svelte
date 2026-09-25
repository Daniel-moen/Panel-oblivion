<script>
  /* One person, across every property they are on: the header (reach them),
     the composer (log what happened, about which property), the history,
     and on the side their properties, mandates and merged records. Editing
     the person's details opens a Sheet. */
  import { untrack } from 'svelte';
  import { page } from '$app/state';
  import { api } from '$lib/api.js';
  import { toast } from '$lib/state.svelte.js';
  import { waNumber, loadToday } from '$lib/leads.svelte.js';
  import QuickLog from '$lib/components/QuickLog.svelte';
  import Photo from '$lib/components/Photo.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import { STAGE_LABEL, MANDATE_LABEL, ago, shortDate, label, isPast } from '$lib/panel.js';
  import { fmtM } from '$lib/format.js';

  const id = $derived(page.params.id);
  let p = $state(null);
  let err = $state(null);
  let editing = $state(false);
  let saving = $state(false);
  let ef = $state({});
  let logFor = $state(null);   // group_id being logged against

  async function load() {
    try {
      p = await api.contact(id); err = null;
      /* keep the chosen property only if it belongs to THIS person — moving
         to another contact must not log against the last one's property */
      if (!p.properties.some((x) => x.group_id === logFor)) logFor = p.properties[0]?.group_id || null;
    } catch (e) { err = e.status === 404 ? 'notfound' : e.message; }
  }
  // one load per id (the old onMount + effect pair fetched twice)
  $effect(() => { id; untrack(() => { p = null; err = null; load(); }); });

  function startEdit() {
    ef = { name: p.contact.name || '', phone: p.contact.phone || '', email: p.contact.email || '',
           company: p.contact.company || '', role: p.contact.role, notes: p.contact.notes || '' };
    editing = true;
  }
  async function saveEdit() {
    saving = true;
    try { await api.updateContact(p.contact.id, ef); editing = false; await load(); toast('Saved', 'ok'); }
    catch (e) { toast(e.message, 'error'); }
    finally { saving = false; }
  }

  const wa = $derived(waNumber(p?.phone));
  const initials = (n) => (n || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
  const CH_ICON = { call: 'phone', whatsapp: 'message', sms: 'text', email: 'send', visit: 'home', letter: 'inbox' };
  const GOOD = ['spoke', 'interested', 'meeting_set'];
  const outTone = (o) => (GOOD.includes(o) ? 'ok' : o === 'not_interested' ? 'crit' : o === 'callback_requested' ? 'warn' : '');
  const spoke = $derived(p ? p.interactions.filter((i) => GOOD.includes(i.outcome)).length : 0);
  const prettyNotes = (n) => String(n || '').replace(/\{[^}]*\}/g, (j) => {
    try { return Object.entries(JSON.parse(j)).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`).join(' · '); } catch { return j; }
  });
  const logContacts = $derived(p ? p.records.filter((r) => r.group_id === logFor) : []);
  const stageTone = (s) => ({ mandate_signed: 'ok', listed: 'ok', sold: 'ok', lost: 'crit' }[s] || '');
  const addrOfX = (x) => x.street_address_raw || x.official_address || x.title;
</script>

<svelte:head><title>{p?.name || 'Contact'} — Leads</title></svelte:head>

<a class="mg-btn ghost sm back" href="/leads/contacts"><Icon name="chevronLeft" size={15} /> Contacts</a>

{#if err === 'notfound'}
  <Empty icon="user" title="Contact not found" hint="This person may have been deleted (POPIA) or merged into another record.">
    <a class="mg-btn secondary" href="/leads/contacts">All contacts</a>
  </Empty>
{:else if err}
  <div class="mg-strip crit"><span class="ic"><Icon name="alert" size={15} /></span><span><b>Couldn't load this contact</b> — {err}</span></div>
  <Empty icon="user" title="Contact unavailable" hint="Try again in a moment.">
    <button type="button" class="mg-btn secondary" onclick={load}><Icon name="refresh" size={15} /> Try again</button>
  </Empty>
{:else if !p}
  <div class="mg-panel hd">
    <Skeleton h="64px" w="64px" r="50%" />
    <div class="hl"><Skeleton h="24px" w="50%" /><Skeleton h="13px" w="35%" /><Skeleton h="32px" w="180px" r="10px" /></div>
  </div>
{:else}
  <header class="mg-panel hd mg-rise">
    <span class="av" aria-hidden="true">{initials(p.name)}</span>
    <div class="hl">
      <div class="nm">
        <h1 class="mg-h1">{p.name || p.phone || '—'}</h1>
        <span class="mg-chip xs">{p.role}</span>
        <button type="button" class="mg-btn ghost icon sm" onclick={startEdit} title="Edit details" aria-label="Edit details"><Icon name="pencil" size={15} /></button>
      </div>
      {#if p.company}<p class="mg-sub">{p.company}</p>{/if}
      <p class="mg-sub reach">
        {#if p.phone}<a class="mg-tnum" href="tel:{p.phone}">{p.phone}</a>{/if}
        {#if p.phone && p.email}<span class="dim">·</span>{/if}
        {#if p.email}<a href="mailto:{p.email}">{p.email}</a>{/if}
      </p>
      {#if !p.phone && !p.email}
        <div class="mg-strip warn nomb"><span class="ic"><Icon name="alert" size={14} /></span>
          <span>No number or email yet — <button type="button" class="linkish" onclick={startEdit}>add one</button> to start calling.</span></div>
      {/if}
      {#if p.contact.notes}<p class="notes">{prettyNotes(p.contact.notes)}</p>{/if}
      {#if p.phone || p.email}
        <div class="acts">
          {#if p.phone}<a class="mg-btn primary sm" href="tel:{p.phone}"><Icon name="phone" size={14} stroke={2} /> Call</a>{/if}
          {#if wa}<a class="mg-btn secondary sm" href="https://wa.me/{wa}" target="_blank" rel="noopener"><Icon name="message" size={14} /> WhatsApp</a>{/if}
          {#if p.email}<a class="mg-btn secondary sm" href="mailto:{p.email}"><Icon name="send" size={14} /> Email</a>{/if}
        </div>
      {/if}
    </div>
  </header>

  <div class="kp">
    <div class="mg-stat-tile mg-rise" style:--i={1}><span class="hud">Properties</span><div class="v">{p.properties.length}</div></div>
    <div class="mg-stat-tile mg-rise" style:--i={2}><span class="hud">Attempts</span><div class="v">{p.interactions.length}</div></div>
    <div class="mg-stat-tile mg-rise" style:--i={3}><span class="hud">Conversations</span><div class="v" class:ok={spoke}>{spoke}</div></div>
    <div class="mg-stat-tile mg-rise" style:--i={4}><span class="hud">Mandates</span><div class="v" class:ok={p.mandates.some((m) => m.type !== 'none_lost')}>{p.mandates.filter((m) => m.type !== 'none_lost').length}</div></div>
  </div>

  <div class="cols">
    <div class="col">
      <section class="mg-section mg-rise" style:--i={5}>
        <div class="head wrap">
          <h2>Log a contact attempt</h2>
          {#if p.properties.length > 1}
            <div class="mg-actions">
              <div class="mg-select about">
                <select bind:value={logFor} aria-label="About which property">
                  {#each p.properties as x (x.group_id)}<option value={x.group_id}>about {addrOfX(x)}</option>{/each}
                </select>
                <span class="ic"><Icon name="chevronDown" size={14} /></span>
              </div>
            </div>
          {:else if p.properties[0]}<span class="mg-count about1">about {addrOfX(p.properties[0])}</span>{/if}
        </div>
        <div class="body">
          {#if logFor}
            {#key logFor}
              <QuickLog gid={logFor} contacts={logContacts} onsaved={async () => { await load(); loadToday(); }} />
            {/key}
          {:else}
            <p class="mg-hint">This person isn't linked to a tracked property, so there is nothing to log against.</p>
          {/if}
        </div>
      </section>

      <section class="mg-section mg-rise" style:--i={6}>
        <div class="head"><h2>Conversation history</h2><span class="mg-count">{p.interactions.length || ''}</span></div>
        {#if !p.interactions.length}
          <p class="note">No contact attempts with {p.name?.split(' ')[0] || 'this person'} yet.</p>
        {:else}
          <div class="mg-list">
            {#each p.interactions as i (i.id)}
              <div class="ev">
                <span class="ico"><Icon name={CH_ICON[i.channel] || 'phone'} size={14} /></span>
                <div class="evb">
                  <div class="l1"><b>{label(i.channel)}</b><span class="mg-chip xs {outTone(i.outcome)}">{label(i.outcome)}</span>
                    {#if p.properties.length > 1}<a class="re" href="/leads/properties/{i.group_id}">re {i.address}</a>{/if}</div>
                  {#if i.summary}<p>{i.summary}</p>{/if}
                  {#if i.next_follow_up_at}<p class="dim" class:late={isPast(i.next_follow_up_at)}>follow-up {shortDate(i.next_follow_up_at)}</p>{/if}
                </div>
                <span class="when" title={i.occurred_at}>{ago(i.occurred_at)}</span>
              </div>
            {/each}
          </div>
        {/if}
      </section>
    </div>

    <div class="col">
      <section class="mg-section mg-rise" style:--i={6}>
        <div class="head"><h2>Properties</h2><span class="mg-count">{p.properties.length || ''}</span></div>
        {#if !p.properties.length}
          <p class="note">Not linked to a tracked property.</p>
        {:else}
          <div class="mg-list">
            {#each p.properties as x (x.group_id)}
              <a class="mg-listrow prop" href="/leads/properties/{x.group_id}">
                <span class="ph"><Photo r={x} /></span>
                <span class="t">
                  <b>{addrOfX(x)}</b>
                  <span>{[x.suburb, x.price_zar ? fmtM(x.price_zar) : null].filter(Boolean).join(' · ')}</span>
                  <span class="st {stageTone(x.stage)}">{STAGE_LABEL[x.stage] || x.stage}{x.mandate_type ? ' · ' + MANDATE_LABEL[x.mandate_type] : ''}{x.next_task_due ? ' · due ' + ago(x.next_task_due) : ''}</span>
                </span>
                <Icon name="chevronRight" size={15} class="chev" />
              </a>
            {/each}
          </div>
        {/if}
      </section>

      {#if p.mandates.length}
        <section class="mg-section mg-rise" style:--i={7}>
          <div class="head"><h2>Mandates</h2></div>
          <div class="mg-list">
            {#each p.mandates as m (m.id)}
              <a class="mg-listrow" href="/leads/properties/{m.group_id}">
                <span class="mg-chip xs {m.type === 'none_lost' ? 'crit' : 'ok'}">{m.type === 'none_lost' ? 'Lost' : MANDATE_LABEL[m.type]}</span>
                <span class="t"><b>{m.address}</b>
                  <span>{m.type === 'none_lost' ? (m.lost_to ? 'to ' + m.lost_to : label(m.lost_reason)) : `${shortDate(m.signed_at)}${m.expires_at ? ' → ' + shortDate(m.expires_at) : ''}${m.listing_price ? ' · ' + fmtM(m.listing_price) : ''}`}</span></span>
                <Icon name="chevronRight" size={15} class="chev" />
              </a>
            {/each}
          </div>
        </section>
      {/if}

      {#if p.records.length > 1}
        <section class="mg-section mg-rise" style:--i={8}>
          <div class="head"><h2>Records merged</h2><span class="mg-count">{p.records.length}</span></div>
          <p class="note">Same person matched by {p.key.startsWith('p:') ? 'phone number' : p.key.startsWith('e:') ? 'email' : 'name'} across {p.records.length} properties.</p>
          <dl class="mg-kv recs">
            {#each p.records as r (r.id)}
              <div><dt>{r.name}</dt><dd>via {r.provider} · <span class="mg-tnum">{shortDate(r.created_at)}</span></dd></div>
            {/each}
          </dl>
        </section>
      {/if}
    </div>
  </div>

  <Sheet open={editing} title="Edit contact" size="sm" onclose={() => (editing = false)}>
    <form id="eform" class="form" onsubmit={(e) => { e.preventDefault(); saveEdit(); }}>
      <label><span class="hud">Name</span><input class="mg-input" type="text" bind:value={ef.name} autocomplete="off" /></label>
      <label><span class="hud">Role</span>
        <div class="mg-select full"><select bind:value={ef.role}>{#each ['owner', 'agent', 'attorney', 'tenant', 'other'] as r (r)}<option value={r}>{r}</option>{/each}</select><span class="ic"><Icon name="chevronDown" size={14} /></span></div></label>
      <div class="two">
        <label><span class="hud">Phone</span><input class="mg-input" type="tel" bind:value={ef.phone} autocomplete="off" /></label>
        <label><span class="hud">Email</span><input class="mg-input" type="email" bind:value={ef.email} autocomplete="off" /></label>
      </div>
      <label><span class="hud">Company</span><input class="mg-input" type="text" bind:value={ef.company} /></label>
      <label><span class="hud">Notes</span><textarea class="mg-input" rows="3" bind:value={ef.notes}></textarea></label>
    </form>
    {#snippet footer()}
      <div class="right">
        <button type="button" class="mg-btn ghost" onclick={() => (editing = false)}>Cancel</button>
        <button type="submit" form="eform" class="mg-btn primary" disabled={saving}>{#if saving}<span class="mg-spin"></span>{/if} Save</button>
      </div>
    {/snippet}
  </Sheet>
{/if}

<style>
  .back { margin: -4px 0 10px -8px; }
  .hd { display: flex; gap: 16px; padding: 16px; margin-bottom: 12px; align-items: flex-start; }
  .av {
    width: 64px; height: 64px; flex: none; border-radius: 50%; display: grid; place-items: center;
    background: var(--mc-raised); border: 1px solid var(--mc-line2); color: var(--mc-ink2); font: 600 20px/1 var(--mc-font);
  }
  .hl { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .nm { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .nm .mg-h1 { min-width: 0; overflow-wrap: anywhere; }
  .mg-chip.xs { height: 22px; padding: 0 8px; font-size: 11px; }
  .reach { display: flex; gap: 6px; flex-wrap: wrap; }
  .reach:empty { display: none; }
  .reach a { color: var(--mc-ink); }
  .reach a:hover { color: var(--mc-accent); }
  .nomb { margin: 6px 0 0; }
  .linkish { background: none; border: 0; padding: 0; font: inherit; color: var(--mc-ink); text-decoration: underline; cursor: pointer; }
  .notes { margin: 4px 0 0; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink3); }
  .acts { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
  .dim { color: var(--mc-ink3); }
  .late { color: var(--mc-crit); }
  @media (max-width: 639px) {
    .hd { padding: 12px; gap: 12px; }
    .av { width: 48px; height: 48px; font-size: 16px; }
  }

  .kp { display: grid; gap: 10px; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-bottom: 14px; }
  @media (min-width: 700px) { .kp { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
  .kp .mg-stat-tile { padding: 12px 14px; }
  .kp .v { font-size: 22px; }

  .cols { display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; align-items: start; }
  .col { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
  @media (min-width: 1180px) { .cols { grid-template-columns: minmax(0, 1fr) 340px; } }

  .mg-section > .head { align-items: center; min-height: 48px; padding-top: 8px; padding-bottom: 8px; }
  .head.wrap { flex-wrap: wrap; }
  .about { max-width: 100%; }
  .about select { height: 34px; max-width: 280px; }
  .about1 { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .note { margin: 0; padding: 12px 16px; font: 400 13px/1.5 var(--mc-font); color: var(--mc-ink3); }

  .ev { display: flex; gap: 12px; padding: 12px 16px; align-items: flex-start; }
  .ico { width: 30px; height: 30px; flex: none; border-radius: 50%; display: grid; place-items: center; background: var(--mc-raised); border: 1px solid var(--mc-line); color: var(--mc-ink2); }
  .evb { flex: 1; min-width: 0; font: 400 13px/1.5 var(--mc-font); color: var(--mc-ink2); padding-top: 4px; }
  .l1 { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .l1 b { color: var(--mc-ink); font-weight: 600; text-transform: capitalize; }
  .re { color: var(--mc-ink3); }
  .re:hover { color: var(--mc-accent); }
  .evb p { margin: 4px 0 0; overflow-wrap: anywhere; }
  .when { flex: none; padding-top: 6px; font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); white-space: nowrap; }

  .prop { align-items: center; }
  .ph { width: 56px; height: 44px; flex: none; border-radius: 8px; overflow: hidden; background: var(--mc-inset); border: 1px solid var(--mc-line); }
  .st { font-weight: 600; }
  .st.ok { color: var(--mc-accent) !important; }
  .st.crit { color: var(--mc-crit) !important; }
  .mg-listrow:hover .t b { color: var(--mc-accent); }
  .mg-section :global(.chev) { flex: none; color: var(--mc-ink3); }
  .recs { padding: 0 16px 8px; }

  .form { display: flex; flex-direction: column; gap: 12px; }
  .form label { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .mg-select.full { display: block; }
  @media (pointer: coarse) {
    .form .mg-input:not(textarea), .mg-select.full select { height: 44px; font-size: 16px; }
    .about select { height: 44px; }
  }
</style>
