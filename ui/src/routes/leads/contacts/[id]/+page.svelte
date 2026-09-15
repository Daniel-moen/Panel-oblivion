<script>
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { api } from '$lib/api.js';
  import { toast } from '$lib/state.svelte.js';
  import { waNumber, loadToday } from '$lib/leads.svelte.js';
  import QuickLog from '$lib/components/QuickLog.svelte';
  import { STAGE_LABEL, MANDATE_LABEL, ago, shortDate, label, isPast } from '$lib/panel.js';
  import { fmtM } from '$lib/format.js';

  const id = $derived(page.params.id);
  let p = $state(null);
  let err = $state(null);
  let editing = $state(false);
  let ef = $state({});
  let logFor = $state(null);   // group_id being logged against

  async function load() {
    try { p = await api.contact(id); err = null; logFor = logFor || p.properties[0]?.group_id || null; }
    catch (e) { err = e.status === 404 ? 'Contact not found' : e.message; }
  }
  onMount(load);
  $effect(() => { id; load(); });

  function startEdit() { ef = { name: p.contact.name || '', phone: p.contact.phone || '', email: p.contact.email || '', company: p.contact.company || '', role: p.contact.role, notes: p.contact.notes || '' }; editing = true; }
  async function saveEdit() {
    try { await api.updateContact(p.contact.id, ef); editing = false; await load(); toast('Saved', 'ok'); }
    catch (e) { toast(e.message, 'error'); }
  }

  const wa = $derived(waNumber(p?.phone));
  const initials = (n) => (n || '?').split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
  const hue = (s) => [...String(s || '')].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 0);
  const ICON = { call: '📞', whatsapp: '💬', sms: '✉️', email: '📧', visit: '🚪', letter: '📮' };
  const spoke = $derived(p ? p.interactions.filter((i) => ['spoke', 'interested', 'meeting_set'].includes(i.outcome)).length : 0);
  const prettyNotes = (n) => String(n || '').replace(/\{[^}]*\}/g, (j) => {
    try { return Object.entries(JSON.parse(j)).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`).join(' · '); } catch { return j; }
  });
  const logContacts = $derived(p ? p.records.filter((r) => r.group_id === logFor) : []);
</script>

<svelte:head><title>{p?.name || 'Contact'} — Leads</title></svelte:head>

{#if err}
  <div class="empty panel"><p>{err}</p><a class="btn" href="/leads/contacts">← Contacts</a></div>
{:else if p}
  <a class="back" href="/leads/contacts">← Contacts</a>

  <header class="hd panel">
    <div class="av" style:background="hsl({hue(p.name)} 45% 45%)">{initials(p.name)}</div>
    <div class="hl">
      {#if editing}
        <div class="form">
          <div class="two"><input type="text" placeholder="Name" bind:value={ef.name} />
            <select bind:value={ef.role}>{#each ['owner', 'agent', 'attorney', 'tenant', 'other'] as r (r)}<option value={r}>{r}</option>{/each}</select></div>
          <div class="two"><input type="text" placeholder="Phone" bind:value={ef.phone} /><input type="text" placeholder="Email" bind:value={ef.email} /></div>
          <input type="text" placeholder="Company" bind:value={ef.company} />
          <input type="text" placeholder="Notes" bind:value={ef.notes} />
          <div class="row"><button class="btn sm primary" onclick={saveEdit}>Save</button><button class="btn sm" onclick={() => (editing = false)}>Cancel</button></div>
        </div>
      {:else}
        <div class="nm"><h1>{p.name || p.phone || '—'}</h1><span class="pill">{p.role}</span>
          <button class="edit" onclick={startEdit} title="Edit details">✎</button></div>
        {#if p.company}<p class="sub">{p.company}</p>{/if}
        <p class="sub">
          {#if p.phone}<a href="tel:{p.phone}">{p.phone}</a>{/if}
          {#if p.email} · <a href="mailto:{p.email}">{p.email}</a>{/if}
          {#if !p.phone && !p.email}<span class="warn">No number or email yet — add one to start calling.</span>{/if}
        </p>
        {#if p.contact.notes}<p class="notes">{prettyNotes(p.contact.notes)}</p>{/if}
        <div class="acts">
          {#if p.phone}<a class="btn sm primary" href="tel:{p.phone}">📞 Call</a>{/if}
          {#if wa}<a class="btn sm" href="https://wa.me/{wa}" target="_blank" rel="noopener">💬 WhatsApp</a>{/if}
          {#if p.email}<a class="btn sm" href="mailto:{p.email}">📧 Email</a>{/if}
        </div>
      {/if}
    </div>
    <div class="kp">
      <div><b>{p.properties.length}</b><span>propert{p.properties.length === 1 ? 'y' : 'ies'}</span></div>
      <div><b>{p.interactions.length}</b><span>attempts</span></div>
      <div><b>{spoke}</b><span>conversations</span></div>
      <div><b>{p.mandates.filter((m) => m.type !== 'none_lost').length}</b><span>mandates</span></div>
    </div>
  </header>

  <div class="cols">
    <div class="col">
      <section class="panel composer">
        <div class="ctabs">
          <span class="lbl">Log a contact attempt</span>
          {#if p.properties.length > 1}
            <select bind:value={logFor} class="about">
              {#each p.properties as x (x.group_id)}<option value={x.group_id}>about {x.street_address_raw || x.title}</option>{/each}
            </select>
          {:else if p.properties[0]}<span class="dim">about {p.properties[0].street_address_raw || p.properties[0].title}</span>{/if}
        </div>
        {#if logFor}
          <QuickLog gid={logFor} contacts={logContacts} onsaved={async () => { await load(); loadToday(); }} />
        {/if}
      </section>

      <section class="panel stream">
        <h2>Conversation history</h2>
        {#if !p.interactions.length}<p class="hint">No contact attempts with {p.name?.split(' ')[0] || 'this person'} yet.</p>{/if}
        {#each p.interactions as i (i.id)}
          <div class="ev">
            <div class="ico">{ICON[i.channel] || '•'}</div>
            <div class="body">
              <div class="l1"><b>{label(i.channel)}</b><span class="oc o-{i.outcome}">{label(i.outcome)}</span>
                {#if p.properties.length > 1}<a class="dim" href="/leads/properties/{i.group_id}">re {i.address}</a>{/if}</div>
              {#if i.summary}<p>{i.summary}</p>{/if}
              {#if i.next_follow_up_at}<p class="dim" class:late={isPast(i.next_follow_up_at)}>follow-up {shortDate(i.next_follow_up_at)}</p>{/if}
            </div>
            <div class="when" title={i.occurred_at}>{ago(i.occurred_at)}</div>
          </div>
        {/each}
      </section>
    </div>

    <div class="col side">
      <section class="panel pad">
        <h2>Properties</h2>
        {#each p.properties as x (x.group_id)}
          <a class="prop" href="/leads/properties/{x.group_id}">
            <div class="ph" style:background-image={x.photo_url ? `url(/api/photo/${encodeURIComponent(x.listing_key)})` : null}></div>
            <div class="pb">
              <b>{x.street_address_raw || x.official_address || x.title}</b>
              <span>{[x.suburb, x.price_zar ? fmtM(x.price_zar) : null].filter(Boolean).join(' · ')}</span>
              <span class="st s-{x.stage}">{STAGE_LABEL[x.stage] || x.stage}{x.mandate_type ? ' · ' + MANDATE_LABEL[x.mandate_type] : ''}{x.next_task_due ? ' · ⏰ ' + ago(x.next_task_due) : ''}</span>
            </div>
          </a>
        {/each}
      </section>

      {#if p.mandates.length}
        <section class="panel pad">
          <h2>Mandates</h2>
          {#each p.mandates as m (m.id)}
            <a class="mrow" href="/leads/properties/{m.group_id}">
              <span class="mand m-{m.type}">{m.type === 'none_lost' ? 'Lost' : MANDATE_LABEL[m.type]}</span>
              <span><b>{m.address}</b><i>{m.type === 'none_lost' ? (m.lost_to ? 'to ' + m.lost_to : label(m.lost_reason)) : `${shortDate(m.signed_at)}${m.expires_at ? ' → ' + shortDate(m.expires_at) : ''}${m.listing_price ? ' · ' + fmtM(m.listing_price) : ''}`}</i></span>
            </a>
          {/each}
        </section>
      {/if}

      {#if p.records.length > 1}
        <section class="panel pad">
          <h2>Records merged</h2>
          <p class="hint">Same person matched by {p.key.startsWith('p:') ? 'phone number' : p.key.startsWith('e:') ? 'email' : 'name'} across {p.records.length} properties.</p>
          {#each p.records as r (r.id)}
            <div class="rec"><span>{r.name}</span><span class="dim">via {r.provider} · {shortDate(r.created_at)}</span></div>
          {/each}
        </section>
      {/if}
    </div>
  </div>
{/if}

<style>
  .back { display: inline-block; margin-bottom: 0.7rem; font-size: 0.82rem; color: var(--ink-3); }
  .empty { padding: 2rem; text-align: center; color: var(--ink-2); }
  .hd { display: flex; gap: 1.2rem; padding: 1.2rem 1.3rem; margin-bottom: 1rem; align-items: flex-start; flex-wrap: wrap; }
  .av { width: 64px; height: 64px; border-radius: 50%; display: grid; place-items: center; color: #fff; font-weight: 800; font-size: 1.3rem; flex: none; }
  .hl { flex: 1; min-width: 260px; }
  .nm { display: flex; gap: 0.6rem; align-items: center; }
  h1 { font-size: 1.5rem; font-weight: 800; letter-spacing: -0.02em; margin: 0; }
  .pill { font-size: 0.7rem; padding: 0.1rem 0.5rem; border-radius: 999px; background: var(--bg-3); color: var(--ink-2); }
  .edit { background: none; border: 0; color: var(--ink-3); cursor: pointer; font-size: 0.95rem; }
  .edit:hover { color: var(--accent); }
  .sub { color: var(--ink-2); font-size: 0.88rem; margin-top: 0.15rem; }
  .sub a { color: var(--ink); }
  .sub a:hover { color: var(--accent); }
  .notes { font-size: 0.8rem; color: var(--ink-3); margin-top: 0.3rem; }
  .warn { color: var(--warm); }
  .acts { display: flex; gap: 0.4rem; margin-top: 0.7rem; flex-wrap: wrap; }
  .kp { display: flex; gap: 1.3rem; }
  .kp div { display: flex; flex-direction: column; align-items: flex-end; }
  .kp b { font-size: 1.3rem; font-weight: 800; }
  .kp span { font-size: 0.7rem; color: var(--ink-3); }
  .form { display: flex; flex-direction: column; gap: 0.4rem; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 0.4rem; }
  .row { display: flex; gap: 0.5rem; }
  .dim { color: var(--ink-3); }

  .cols { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 1rem; align-items: start; }
  .col { display: flex; flex-direction: column; gap: 1rem; }
  @media (max-width: 1000px) { .cols { grid-template-columns: 1fr; } }

  .composer { padding: 0.9rem 1rem 1rem; }
  .ctabs { display: flex; gap: 0.6rem; align-items: center; margin-bottom: 0.7rem; font-size: 0.8rem; }
  .lbl { font-weight: 700; color: var(--ink); }
  .about { font-size: 0.78rem; padding: 0.25rem 1.6rem 0.25rem 0.5rem; }

  h2 { font-size: 0.74rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-2); margin-bottom: 0.5rem; }
  .stream h2 { padding: 0.9rem 1rem 0.2rem; margin: 0; }
  .hint { padding: 0.5rem 1rem 0.9rem; color: var(--ink-3); font-size: 0.84rem; }
  .pad .hint { padding: 0 0 0.5rem; }
  .ev { display: flex; gap: 0.8rem; padding: 0.7rem 1rem; border-top: 1px solid var(--line); align-items: flex-start; }
  .ico { width: 30px; height: 30px; border-radius: 50%; background: var(--bg-3); display: grid; place-items: center; font-size: 0.9rem; flex: none; }
  .body { flex: 1; font-size: 0.86rem; }
  .l1 { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
  .body p { margin: 0.2rem 0 0; }
  .late { color: var(--bad); }
  .when { font-size: 0.74rem; color: var(--ink-3); white-space: nowrap; }
  .oc { font-size: 0.7rem; font-weight: 600; padding: 0.08rem 0.45rem; border-radius: 4px; background: var(--bg-3); color: var(--ink-2); }
  .o-spoke, .o-interested, .o-meeting_set { background: var(--open-soft); color: var(--open); }
  .o-not_interested { background: var(--red-soft); color: var(--sole); }

  .pad { padding: 0.9rem 1rem; }
  .prop { display: flex; gap: 0.7rem; padding: 0.55rem 0; border-top: 1px solid var(--line); color: var(--ink); }
  .prop:first-of-type { border-top: 0; }
  .prop:hover b { color: var(--accent); }
  .ph { width: 56px; height: 44px; border-radius: 8px; background: var(--bg-3) center/cover; flex: none; }
  .pb { display: flex; flex-direction: column; font-size: 0.8rem; min-width: 0; }
  .pb b { font-size: 0.86rem; font-weight: 600; }
  .pb span { color: var(--ink-3); font-size: 0.74rem; }
  .st { font-weight: 600; }
  .s-contacted, .s-meeting, .s-valuation_sent { color: var(--accent-2) !important; }
  .s-mandate_signed, .s-listed, .s-sold { color: var(--good) !important; }
  .s-lost { color: var(--bad) !important; }
  .mrow { display: flex; gap: 0.6rem; align-items: flex-start; padding: 0.5rem 0; border-top: 1px solid var(--line); color: var(--ink); font-size: 0.82rem; }
  .mrow:first-of-type { border-top: 0; }
  .mrow span { display: flex; flex-direction: column; }
  .mrow i { font-style: normal; color: var(--ink-3); font-size: 0.74rem; }
  .mand { font-size: 0.68rem; font-weight: 700; padding: 0.15rem 0.45rem; border-radius: 4px; background: var(--open-soft); color: var(--open); flex: none; }
  .m-none_lost { background: var(--red-soft); color: var(--sole); }
  .rec { display: flex; justify-content: space-between; font-size: 0.8rem; padding: 0.3rem 0; }
</style>
