<script>
  /* One tracked property: who owns it, every call, the stage, the mandate.

     Header panel (photo, badges, price, the actions you take from here) →
     the stage stepper → two columns: the work (call brief, composer, the
     timeline) and the facts (contacts, mandate, tasks, listings). Adding a
     contact and recording a mandate outcome open a Sheet. */
  import { tick, untrack } from 'svelte';
  import { page } from '$app/state';
  import { api } from '$lib/api.js';
  import { toast, app } from '$lib/state.svelte.js';
  import { loadToday, waNumber, addrOf } from '$lib/leads.svelte.js';
  import QuickLog from '$lib/components/QuickLog.svelte';
  import CallBrief from '$lib/components/CallBrief.svelte';
  import Photo from '$lib/components/Photo.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import { fmtR, fmtM } from '$lib/format.js';
  import { STAGE_LABEL, MANDATE_LABEL, ago, isPast, shortDate, label } from '$lib/panel.js';

  const gid = $derived(page.params.gid);
  let d = $state(null);
  let meta = $state(null);
  let err = $state(null);
  let compose = $state('log');      // log | note
  let note = $state('');
  let showContact = $state(false);
  let showMandate = $state(false);
  let newTask = $state('');
  let saving = $state(false);
  let stepper = $state(null);
  /* Collapsed by default: the brief costs a round-trip and this page is
     opened far more often to log a call than to prepare one. */
  let showBrief = $state(false);
  let briefEl = $state(null);
  function openBrief() {
    showBrief = true;
    setTimeout(() => briefEl?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
  }

  const FLOW = ['new', 'researching', 'contact_found', 'contacted', 'meeting', 'valuation_sent', 'mandate_signed', 'listed', 'sold'];
  const ENDS = ['lost', 'parked'];

  async function load() {
    try {
      const [dd, mm] = await Promise.all([api.trackedOne(gid), meta || api.panelMeta()]);
      d = dd; meta = mm; err = null;
    } catch (e) { err = e.status === 404 ? 'notfound' : e.message; }
  }
  // one load per gid (the old onMount + effect pair fetched everything twice)
  $effect(() => { gid; untrack(() => { d = null; err = null; load(); }); });
  const refresh = async () => { await load(); loadToday(); };
  // the global Quick log sheet saved something about this property
  $effect(() => {
    const on = (e) => { if (String(e.detail?.gid) === String(gid)) refresh(); };
    window.addEventListener('mc:logged', on);
    return () => window.removeEventListener('mc:logged', on);
  });

  // keep the current stage in view on a narrow stepper
  $effect(() => {
    d?.stage;
    tick().then(() => stepper?.querySelector('.step.cur')?.scrollIntoView?.({ block: 'nearest', inline: 'center' }));
  });

  async function setStage(v) {
    if (d.stage === v) return;
    const prev = d.stage;
    d.stage = v;
    try { await api.updateTracked(gid, { stage: v }); app.tracked[gid] = v; toast('Moved to ' + STAGE_LABEL[v], 'ok'); await refresh(); }
    catch (e) { d.stage = prev; toast(e.message, 'error'); }
  }
  async function togglePriority() {
    const v = d.priority === 'high' ? 'normal' : 'high';
    try { await api.updateTracked(gid, { priority: v }); d.priority = v; } catch (e) { toast(e.message, 'error'); }
  }
  async function add(kind, body, after) {
    saving = true;
    try { await api.child.add(gid, kind, body); after?.(); await refresh(); toast('Saved', 'ok'); }
    catch (e) { toast(e.message, 'error'); }
    finally { saving = false; }
  }
  async function remove(kind, id) {
    if (!confirm('Delete this entry?')) return;
    try { await api.child.remove(gid, kind, id); await refresh(); } catch (e) { toast(e.message, 'error'); }
  }
  async function toggleTask(t) {
    try { await api.taskDone(t.id, !t.done_at); await refresh(); } catch (e) { toast(e.message, 'error'); }
  }
  async function deedLookup() {
    try { toast('Asking the deeds office…'); await api.deed(gid); await refresh(); }
    catch (e) { toast(e.message, 'error'); }
  }
  async function trackIt() {
    try { await api.track(gid); app.tracked[gid] = 'new'; load(); } catch (e) { toast(e.message, 'error'); }
  }

  const today = () => new Date().toISOString().slice(0, 10);
  const blankContact = () => ({ role: 'owner', name: '', phone: '', email: '', company: '', notes: '' });
  let cf = $state(blankContact());
  let mf = $state({ type: 'sole', signed_at: today(), duration_days: 90, listing_price: '', commission_pct: '',
                    competing_agencies: '', lost_reason: 'went_with_other_agency', lost_to: '', notes: '' });
  function saveContact() {
    if (!(cf.name || cf.phone)) { toast('Add a name or a phone number', 'error'); return; }
    add('contacts', { ...cf, provider: 'manual' }, () => { showContact = false; cf = blankContact(); });
  }
  function saveMandate() {
    const b = { ...mf, listing_price: mf.listing_price ? Number(mf.listing_price) : null,
                commission_pct: mf.commission_pct ? Number(mf.commission_pct) : null,
                duration_days: mf.duration_days ? Number(mf.duration_days) : null };
    if (mf.type === 'none_lost') { b.signed_at = null; b.duration_days = null; } else { b.lost_reason = null; b.lost_to = null; }
    add('mandates', b, () => (showMandate = false));
  }
  function saveNote(e) {
    e.preventDefault();
    if (note.trim()) add('notes', { body: note.trim() }, () => (note = ''));
  }
  function saveTask(e) {
    e.preventDefault();
    if (newTask.trim()) add('tasks', { title: newTask.trim(), kind: 'other' }, () => (newTask = ''));
  }

  const primary = $derived(d?.contacts?.[0] || null);
  const wa = $derived(waNumber(primary?.phone));
  const mandate = $derived(d?.mandates?.[0] || null);
  const openTasks = $derived(d?.tasks?.filter((t) => !t.done_at) || []);
  const doneTasks = $derived(d?.tasks?.filter((t) => t.done_at) || []);
  const flowIdx = $derived(d ? FLOW.indexOf(d.stage) : -1);

  /* One stream: interactions, notes, mandates and stage changes, newest first.
     Interactions/notes come from their own tables (deletable); the rest from
     the activity log. */
  const stream = $derived.by(() => {
    if (!d) return [];
    const items = [];
    for (const i of d.interactions) items.push({ t: i.occurred_at, kind: 'interaction', i });
    for (const n of d.notes) items.push({ t: n.created_at, kind: 'note', n });
    for (const a of d.activities) if (['stage_change', 'mandate', 'tracked', 'contact_added', 'price_cut', 'delisted', 'relisted'].includes(a.kind))
      items.push({ t: a.occurred_at, kind: a.kind, a });
    return items.sort((x, y) => String(y.t).localeCompare(String(x.t)));
  });
  /* Rows migrated from the old owner store carry their deed facts as JSON. */
  const prettyNotes = (n) => String(n || '').replace(/\{[^}]*\}/g, (j) => {
    try { return Object.entries(JSON.parse(j)).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`).join(' · '); } catch { return j; }
  });
  const CH_ICON = { call: 'phone', whatsapp: 'message', sms: 'text', email: 'send', visit: 'home', letter: 'inbox' };
  const EV_ICON = { note: 'pencil', mandate: 'ticket', stage_change: 'arrowRight', tracked: 'eye', contact_added: 'userPlus',
                    price_cut: 'dollar', delisted: 'eyeOff', relisted: 'refresh' };
  const evIcon = (s) => (s.kind === 'interaction' ? CH_ICON[s.i.channel] || 'phone' : EV_ICON[s.kind] || 'clock');
  const GOOD = ['spoke', 'interested', 'meeting_set'];
  const outTone = (o) => (GOOD.includes(o) ? 'ok' : o === 'not_interested' ? 'crit' : o === 'callback_requested' ? 'warn' : '');
  const actText = (a) => {
    const p = a.payload || {};
    if (a.kind === 'stage_change') return `Moved to ${STAGE_LABEL[p.to] || p.to}${p.reason ? ' — ' + p.reason : ''}`;
    if (a.kind === 'mandate') return p.type === 'none_lost' ? `Mandate lost${p.lost_to ? ' to ' + p.lost_to : ''}` : `${MANDATE_LABEL[p.type] || p.type} mandate signed${p.expires_at ? ', expires ' + p.expires_at : ''}`;
    if (a.kind === 'tracked') return 'Started tracking';
    if (a.kind === 'contact_added') return `Contact added: ${p.name || '—'}`;
    return label(a.kind);
  };
</script>

<svelte:head><title>{d ? addrOf(d) : 'Property'} — Leads</title></svelte:head>

<a class="mg-btn ghost sm back" href="/leads/properties"><Icon name="chevronLeft" size={15} /> Properties</a>

{#if err === 'notfound'}
  <Empty icon="building" title="Not tracked" hint="This property isn't in lead management yet.">
    <button type="button" class="mg-btn primary" onclick={trackIt}><Icon name="plus" size={15} /> Track it</button>
    <a class="mg-btn secondary" href="/leads/properties">All properties</a>
  </Empty>
{:else if err}
  <div class="mg-strip crit"><span class="ic"><Icon name="alert" size={15} /></span><span><b>Couldn't load this property</b> — {err}</span></div>
  <Empty icon="building" title="Property unavailable" hint="Try again in a moment.">
    <button type="button" class="mg-btn secondary" onclick={load}><Icon name="refresh" size={15} /> Try again</button>
  </Empty>
{:else if !d}
  <div class="mg-panel hd">
    <Skeleton h="120px" w="160px" r="12px" />
    <div class="hl"><Skeleton h="22px" w="120px" /><Skeleton h="24px" w="70%" /><Skeleton h="13px" w="45%" /><Skeleton h="18px" w="30%" /></div>
  </div>
  <div class="mg-panel"><Skeleton h="40px" /></div>
{:else}
  <header class="mg-panel hd mg-rise">
    <div class="ph"><Photo r={d} eager alt={addrOf(d)} /></div>
    <div class="hl">
      <div class="badges">
        {#if d.tier}<span class="tier {d.tier}">{d.tier}</span>{/if}
        {#if d.mandate_verdict}<span class="mv {d.mandate_verdict}">{label(d.mandate_verdict)}</span>{/if}
        {#if mandate}<span class="mg-chip xs {mandate.type === 'none_lost' ? 'crit' : 'ok'}">{mandate.type === 'none_lost' ? 'Lost' : MANDATE_LABEL[mandate.type] + ' mandate'}{mandate.expires_at && mandate.type !== 'none_lost' ? ' · exp ' + shortDate(mandate.expires_at) : ''}</span>{/if}
        <button type="button" class="mg-btn icon sm star" class:secondary={d.priority !== 'high'} class:warn={d.priority === 'high'}
                onclick={togglePriority} aria-pressed={d.priority === 'high'}
                title={d.priority === 'high' ? 'High priority — tap to clear' : 'Mark high priority'} aria-label="High priority">
          <Icon name="star" size={15} />
        </button>
      </div>
      <h1 class="mg-h1">{addrOf(d)}</h1>
      <p class="mg-sub">{[d.suburb, d.property_type, d.bedrooms ? d.bedrooms + ' bed' : null, d.erf_number ? 'Erf ' + d.erf_number : null].filter(Boolean).join(' · ')}</p>
      <p class="amt"><span class="mg-tnum">{d.price_zar ? fmtR(d.price_zar) : 'POA'}</span>{#if d.listing_count > 1}<span class="dim"> · {d.listing_count} listings · {d.agency_count} agencies</span>{/if}</p>
      <div class="acts">
        {#if primary?.phone}<a class="mg-btn primary sm" href="tel:{primary.phone}"><Icon name="phone" size={14} stroke={2} /> Call {primary.name?.split(' ')[0] || ''}</a>{/if}
        {#if wa}<a class="mg-btn secondary sm" href="https://wa.me/{wa}" target="_blank" rel="noopener"><Icon name="message" size={14} /> WhatsApp</a>{/if}
        <button type="button" class="mg-btn secondary sm" onclick={openBrief} title="What to say when you phone the owner"><Icon name="list" size={14} /> Call brief</button>
        {#if d.cma_url}<a class="mg-btn secondary sm" href={d.cma_url}><Icon name="ruler" size={14} /> CMA report</a>{/if}
        <a class="mg-btn secondary sm" href="/prospects?open={encodeURIComponent(d.listing_key)}" title="Open in the prospect engine: score, signals, erf tools"><Icon name="bolt" size={14} /> Engine view</a>
        <a class="mg-btn secondary sm" href="/map?focus={encodeURIComponent(gid)}"><Icon name="mapPin" size={14} /> Map</a>
        {#if d.url}<a class="mg-btn ghost sm" href={d.url} target="_blank" rel="noopener">Listing <Icon name="external" size={13} /></a>{/if}
      </div>
    </div>
  </header>

  <nav class="mg-panel stepper mg-noscroll mg-rise" style:--i={1} bind:this={stepper} aria-label="Stage">
    {#each FLOW as s, i (s)}
      <button type="button" class="step" class:done={i < flowIdx} class:cur={s === d.stage} aria-current={s === d.stage ? 'step' : undefined}
              onclick={() => setStage(s)} title="Move to {STAGE_LABEL[s]}">
        <i class="mg-tnum">{#if i < flowIdx}<Icon name="check" size={11} stroke={2.5} />{:else}{i + 1}{/if}</i><span>{STAGE_LABEL[s]}</span>
      </button>
    {/each}
    <span class="sep"></span>
    {#each ENDS as s (s)}
      <button type="button" class="step end {s}" class:cur={s === d.stage} aria-current={s === d.stage ? 'step' : undefined}
              onclick={() => setStage(s)} title="Move to {STAGE_LABEL[s]}"><span>{STAGE_LABEL[s]}</span></button>
    {/each}
  </nav>

  <div class="cols">
    <div class="col">
      <section class="mg-section mg-rise" style:--i={2} bind:this={briefEl}>
        {#if showBrief}
          <div class="body"><CallBrief gid={gid} /></div>
        {:else}
          <div class="head">
            <h2>Call brief</h2>
            <div class="mg-actions"><button type="button" class="mg-btn secondary sm" onclick={openBrief}>Show call brief</button></div>
          </div>
        {/if}
      </section>

      <section class="mg-section mg-rise" style:--i={3}>
        <div class="mg-tabs tabs" role="tablist">
          <button type="button" role="tab" aria-selected={compose === 'log'} onclick={() => (compose = 'log')}>Log contact attempt</button>
          <button type="button" role="tab" aria-selected={compose === 'note'} onclick={() => (compose = 'note')}>Add note</button>
        </div>
        <div class="body">
          {#if compose === 'log'}
            <QuickLog {gid} contacts={d.contacts} onsaved={refresh} />
          {:else}
            <form class="line" onsubmit={saveNote}>
              <input class="mg-input" type="text" bind:value={note} placeholder="Anything worth remembering…" aria-label="Note" />
              <button class="mg-btn primary" type="submit" disabled={!note.trim() || saving}>Save note</button>
            </form>
          {/if}
        </div>
      </section>

      <section class="mg-section mg-rise" style:--i={4}>
        <div class="head"><h2>Timeline</h2><span class="mg-count">{stream.length || ''}</span></div>
        {#if !stream.length}
          <p class="note">Nothing yet. Log your first call above.</p>
        {:else}
          <div class="mg-list">
            {#each stream as s (s.kind + (s.i?.id ?? s.n?.id ?? s.a?.id))}
              <div class="ev {s.kind}">
                <span class="ico"><Icon name={evIcon(s)} size={14} /></span>
                <div class="evb">
                  {#if s.kind === 'interaction'}
                    <div class="l1"><b>{label(s.i.channel)}</b>
                      <span class="mg-chip xs {outTone(s.i.outcome)}">{label(s.i.outcome)}</span>
                      {#if s.i.contact_name}<span class="dim">with {s.i.contact_name}</span>{/if}</div>
                    {#if s.i.summary}<p>{s.i.summary}</p>{/if}
                    {#if s.i.next_follow_up_at}<p class="dim">follow-up {shortDate(s.i.next_follow_up_at)}</p>{/if}
                  {:else if s.kind === 'note'}
                    <p class="nb">{s.n.body}</p>
                  {:else}
                    <p class="sys">{actText(s.a)}</p>
                  {/if}
                </div>
                <span class="when" title={s.t}>{ago(s.t)}</span>
                {#if s.kind === 'interaction'}<button type="button" class="mg-btn ghost icon sm x" onclick={() => remove('interactions', s.i.id)} aria-label="Delete this entry" title="Delete"><Icon name="trash" size={14} /></button>
                {:else if s.kind === 'note'}<button type="button" class="mg-btn ghost icon sm x" onclick={() => remove('notes', s.n.id)} aria-label="Delete this note" title="Delete"><Icon name="trash" size={14} /></button>{/if}
              </div>
            {/each}
          </div>
        {/if}
      </section>
    </div>

    <div class="col">
      <section class="mg-section mg-rise" style:--i={3}>
        <div class="head"><h2>Contacts</h2><span class="mg-count">{d.contacts.length || ''}</span>
          <div class="mg-actions">
            {#if d.cma_url}<button type="button" class="mg-btn ghost sm" onclick={deedLookup} title="Look up the registered owner via the deeds office">Deeds lookup</button>{/if}
            <button type="button" class="mg-btn secondary sm" onclick={() => (showContact = true)}><Icon name="plus" size={14} /> Add</button>
          </div>
        </div>
        {#if !d.contacts.length}
          <p class="note">No owner details yet.</p>
        {:else}
          <div class="mg-list">
            {#each d.contacts as c (c.id)}
              <div class="contact">
                <div class="cn">
                  <a class="pn" href="/leads/contacts/{c.id}">{c.name || '—'}</a>
                  <span class="mg-chip xs">{c.role}</span>
                  <button type="button" class="mg-btn ghost icon sm x" onclick={() => remove('contacts', c.id)} title="Delete (POPIA)" aria-label="Delete contact"><Icon name="trash" size={14} /></button>
                </div>
                {#if c.company}<span class="dim">{c.company}</span>{/if}
                {#if c.phone}<a class="lnk mg-tnum" href="tel:{c.phone}"><Icon name="phone" size={12} />{c.phone}</a>{/if}
                {#if c.email}<a class="lnk" href="mailto:{c.email}"><Icon name="send" size={12} />{c.email}</a>{/if}
                {#if c.notes}<span class="dim small">{prettyNotes(c.notes)}</span>{/if}
                <span class="dim small">via {c.provider}</span>
              </div>
            {/each}
          </div>
        {/if}
      </section>

      <section class="mg-section mg-rise" style:--i={4}>
        <div class="head"><h2>Mandate</h2>
          <div class="mg-actions">
            <button type="button" class="mg-btn sm" class:accent={!mandate && d.stage === 'valuation_sent'} class:secondary={mandate || d.stage !== 'valuation_sent'}
                    onclick={() => (showMandate = true)}>{mandate ? 'Record new outcome' : 'Record outcome'}</button>
          </div>
        </div>
        {#if mandate}
          <div class="body">
            <span class="mg-chip {mandate.type === 'none_lost' ? 'crit' : 'ok'}">{mandate.type === 'none_lost' ? 'Lost' : MANDATE_LABEL[mandate.type] + ' mandate'}</span>
            <dl class="mg-kv">
              {#if mandate.type === 'none_lost'}
                <div><dt>Reason</dt><dd>{label(mandate.lost_reason) || '—'}</dd></div>
                {#if mandate.lost_to}<div><dt>Lost to</dt><dd>{mandate.lost_to}</dd></div>{/if}
              {:else}
                <div><dt>Signed</dt><dd class="mg-tnum">{shortDate(mandate.signed_at)}</dd></div>
                {#if mandate.expires_at}<div><dt>Expires</dt><dd class="mg-tnum" class:late={isPast(mandate.expires_at)}>{shortDate(mandate.expires_at)} · {ago(mandate.expires_at)}</dd></div>{/if}
                {#if mandate.listing_price}<div><dt>Listing price</dt><dd class="mg-tnum">{fmtM(mandate.listing_price)}</dd></div>{/if}
                {#if mandate.commission_pct}<div><dt>Commission</dt><dd class="mg-tnum">{mandate.commission_pct}%</dd></div>{/if}
              {/if}
              {#if mandate.notes}<div><dt>Notes</dt><dd>{mandate.notes}</dd></div>{/if}
            </dl>
          </div>
        {:else}
          <p class="note">No outcome recorded yet.</p>
        {/if}
      </section>

      <section class="mg-section mg-rise" style:--i={5}>
        <div class="head"><h2>Tasks</h2>{#if openTasks.length}<span class="mg-count">{openTasks.length} open</span>{/if}</div>
        {#if openTasks.length}
          <div class="mg-list">
            {#each openTasks as t (t.id)}
              <div class="task">
                <label class="tl"><input type="checkbox" onchange={() => toggleTask(t)} aria-label="Mark “{t.title}” done" />
                  <span><b>{t.title}</b><small class:late={isPast(t.due_at)}>{t.due_at ? `${shortDate(t.due_at)} · ${ago(t.due_at)}` : 'no date'}</small></span></label>
                <button type="button" class="mg-btn ghost icon sm x" onclick={() => remove('tasks', t.id)} aria-label="Delete task" title="Delete"><Icon name="trash" size={14} /></button>
              </div>
            {/each}
          </div>
        {/if}
        <form class="line addtask" onsubmit={saveTask}>
          <input class="mg-input" type="text" placeholder="Add a task…" bind:value={newTask} aria-label="New task" />
          <button class="mg-btn secondary icon" type="submit" aria-label="Add task" disabled={!newTask.trim() || saving}><Icon name="plus" size={16} /></button>
        </form>
        {#if doneTasks.length}
          <details class="more">
            <summary>{doneTasks.length} done</summary>
            {#each doneTasks as t (t.id)}
              <label class="tl done"><input type="checkbox" checked onchange={() => toggleTask(t)} aria-label="Reopen “{t.title}”" /><span>{t.title}</span></label>
            {/each}
          </details>
        {/if}
      </section>

      <section class="mg-section mg-rise" style:--i={6}>
        <div class="head"><h2>Listings</h2><span class="mg-count">{d.listings.length || ''}</span></div>
        <div class="mg-list">
          {#each d.listings as l (l.listing_key)}
            <a class="mg-listrow" href={l.url} target="_blank" rel="noopener">
              <span class="t"><b>{l.source}</b>
                <span>{l.agency || ''}{l.agent_name ? ' · ' + l.agent_name : ''}</span>
                <span>{l.price_zar ? fmtM(l.price_zar) : 'POA'} · seen {ago(l.last_seen)}{l.lifecycle && l.lifecycle !== 'active' ? ' · ' + l.lifecycle : ''}</span></span>
              <Icon name="external" size={14} class="chev" />
            </a>
          {/each}
        </div>
        {#if d.price_history.length > 1}
          <details class="more">
            <summary>Price history ({d.price_history.length})</summary>
            {#each d.price_history as p (p.listing_key + p.observed_at)}
              <div class="ph-row mg-tnum"><span>{shortDate(p.observed_at)}</span><b>{fmtR(p.price_zar)}</b><span class="dim">{p.listing_key.split(':')[0]}</span></div>
            {/each}
          </details>
        {/if}
      </section>
    </div>
  </div>

  <Sheet open={showContact} title="Add a contact" size="sm" onclose={() => (showContact = false)}>
    <form id="cform" class="form" onsubmit={(e) => { e.preventDefault(); saveContact(); }}>
      <label><span class="hud">Name</span><input class="mg-input" type="text" bind:value={cf.name} autocomplete="off" /></label>
      <label><span class="hud">Role</span>
        <div class="mg-select full"><select bind:value={cf.role}>{#each meta?.roles || ['owner'] as r (r)}<option value={r}>{r}</option>{/each}</select><span class="ic"><Icon name="chevronDown" size={14} /></span></div></label>
      <div class="two">
        <label><span class="hud">Phone</span><input class="mg-input" type="tel" bind:value={cf.phone} autocomplete="off" /></label>
        <label><span class="hud">Email</span><input class="mg-input" type="email" bind:value={cf.email} autocomplete="off" /></label>
      </div>
      <label><span class="hud">Company / notes</span><input class="mg-input" type="text" bind:value={cf.notes} /></label>
    </form>
    {#snippet footer()}
      <div class="right">
        <button type="button" class="mg-btn ghost" onclick={() => (showContact = false)}>Cancel</button>
        <button type="submit" form="cform" class="mg-btn primary" disabled={saving || !(cf.name || cf.phone)}>Save contact</button>
      </div>
    {/snippet}
  </Sheet>

  <Sheet open={showMandate} title="Record the mandate outcome" size="sm" onclose={() => (showMandate = false)}>
    <form id="mform" class="form" onsubmit={(e) => { e.preventDefault(); saveMandate(); }}>
      <label><span class="hud">Outcome</span>
        <div class="mg-select full"><select bind:value={mf.type}>{#each meta?.mandate_types || [] as t (t)}<option value={t}>{t === 'none_lost' ? 'Lost — no mandate' : MANDATE_LABEL[t] + ' mandate'}</option>{/each}</select><span class="ic"><Icon name="chevronDown" size={14} /></span></div></label>
      {#if mf.type === 'none_lost'}
        <label><span class="hud">Why</span>
          <div class="mg-select full"><select bind:value={mf.lost_reason}>{#each meta?.lost_reasons || [] as r (r)}<option value={r}>{label(r)}</option>{/each}</select><span class="ic"><Icon name="chevronDown" size={14} /></span></div></label>
        <label><span class="hud">Lost to which agency?</span><input class="mg-input" type="text" bind:value={mf.lost_to} /></label>
      {:else}
        <div class="two">
          <label><span class="hud">Signed</span><input class="mg-input" type="date" bind:value={mf.signed_at} /></label>
          <label><span class="hud">Days</span><input class="mg-input" type="number" inputmode="numeric" bind:value={mf.duration_days} /></label>
        </div>
        <div class="two">
          <label><span class="hud">Listing price (R)</span><input class="mg-input" type="number" inputmode="numeric" bind:value={mf.listing_price} /></label>
          <label><span class="hud">Commission %</span><input class="mg-input" type="number" inputmode="decimal" step="0.1" bind:value={mf.commission_pct} /></label>
        </div>
        <label><span class="hud">Competing agencies</span><input class="mg-input" type="text" bind:value={mf.competing_agencies} /></label>
      {/if}
      <label><span class="hud">Notes</span><input class="mg-input" type="text" bind:value={mf.notes} /></label>
    </form>
    {#snippet footer()}
      <div class="right">
        <button type="button" class="mg-btn ghost" onclick={() => (showMandate = false)}>Cancel</button>
        <button type="submit" form="mform" class="mg-btn primary" disabled={saving}>Save outcome</button>
      </div>
    {/snippet}
  </Sheet>
{/if}

<style>
  .back { margin: -4px 0 10px -8px; }

  .hd { display: flex; gap: 16px; padding: 16px; margin-bottom: 12px; }
  .ph { width: 180px; height: 136px; flex: none; border-radius: var(--mc-r-md); overflow: hidden; background: var(--mc-inset); border: 1px solid var(--mc-line); }
  .hl { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
  .badges { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .star { margin-left: auto; }
  .hl .mg-h1 { overflow-wrap: anywhere; }
  .amt { margin: 2px 0 6px; font: 600 18px/1.3 var(--mc-font); letter-spacing: -0.01em; color: var(--mc-ink); }
  .acts { display: flex; gap: 6px; flex-wrap: wrap; }
  .dim { color: var(--mc-ink3); font-weight: 400; font-size: 13px; }
  .small { font-size: 12px; }
  .late { color: var(--mc-crit) !important; }
  .mg-chip.xs { height: 22px; padding: 0 8px; font-size: 11px; }
  @media (max-width: 639px) {
    .hd { flex-direction: column; padding: 12px; }
    .ph { width: 100%; height: auto; aspect-ratio: 16 / 9; }
    .acts .mg-btn { flex: 1 1 auto; }
  }

  .stepper { display: flex; align-items: center; gap: 2px; padding: 6px; margin-bottom: 14px; overflow-x: auto; }
  .step {
    flex: none; display: flex; align-items: center; gap: 8px; height: 36px; padding: 0 10px;
    background: none; border: 1px solid transparent; border-radius: 10px;
    color: var(--mc-ink3); font: 500 12.5px/1 var(--mc-font); cursor: pointer; white-space: nowrap;
    transition: background var(--mc-t-fast), color var(--mc-t-fast), border-color var(--mc-t-fast);
  }
  .step i {
    font-style: normal; width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center;
    font-size: 11px; font-weight: 600; background: var(--mc-raised); border: 1px solid var(--mc-line); color: var(--mc-ink3);
  }
  .step.done { color: var(--mc-ink2); }
  .step.done i { background: var(--mc-ok-soft); border-color: var(--mc-ok-line); color: var(--mc-accent); }
  .step.cur { background: var(--mc-ok-soft); border-color: var(--mc-ok-line); color: var(--mc-accent); font-weight: 600; }
  .step.cur i { background: var(--mc-accent); border-color: var(--mc-accent); color: var(--mc-accent-ink); }
  .step:hover:not(.cur) { background: rgba(255, 255, 255, 0.04); color: var(--mc-ink); }
  .sep { flex: 1 0 12px; }
  .step.end.lost.cur { background: var(--mc-crit-soft); border-color: var(--mc-crit-line); color: var(--mc-crit); }
  .step.end.parked.cur { background: var(--mc-raised); border-color: var(--mc-line2); color: var(--mc-ink); }
  @media (pointer: coarse) { .step { height: 44px; } }

  .cols { display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; align-items: start; }
  .col { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
  @media (min-width: 1180px) { .cols { grid-template-columns: minmax(0, 1fr) 340px; } }

  .mg-section > .head { align-items: center; min-height: 48px; padding-top: 8px; padding-bottom: 8px; }
  .tabs { padding: 0 8px; }
  .note { margin: 0; padding: 12px 16px; font: 400 13px/1.5 var(--mc-font); color: var(--mc-ink3); }
  .line { display: flex; gap: 8px; align-items: center; }
  .line .mg-input { flex: 1; min-width: 0; }

  .ev { display: flex; gap: 12px; padding: 12px 16px; align-items: flex-start; }
  .ico {
    width: 30px; height: 30px; flex: none; border-radius: 50%; display: grid; place-items: center;
    background: var(--mc-raised); border: 1px solid var(--mc-line); color: var(--mc-ink2);
  }
  .ev.mandate .ico { background: var(--mc-ok-soft); border-color: var(--mc-ok-line); color: var(--mc-accent); }
  .ev.stage_change .ico, .ev.tracked .ico, .ev.contact_added .ico, .ev.price_cut .ico, .ev.delisted .ico, .ev.relisted .ico {
    background: transparent; color: var(--mc-ink3);
  }
  .evb { flex: 1; min-width: 0; font: 400 13px/1.5 var(--mc-font); color: var(--mc-ink2); padding-top: 4px; }
  .l1 { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .l1 b { color: var(--mc-ink); font-weight: 600; text-transform: capitalize; }
  .evb p { margin: 4px 0 0; overflow-wrap: anywhere; }
  .evb p.nb { margin: 0; color: var(--mc-ink); white-space: pre-wrap; }
  .evb p.sys { margin: 0; color: var(--mc-ink3); }
  .when { flex: none; padding-top: 6px; font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); white-space: nowrap; }
  .x { flex: none; color: var(--mc-ink3); }
  .x:hover { color: var(--mc-crit); background: var(--mc-crit-soft); }
  /* on a pointer that can hover, delete appears with the row; on touch it is always there */
  @media (hover: hover) {
    .ev .x, .contact .x, .task .x { opacity: 0; transition: opacity var(--mc-t-fast); }
    .ev:hover .x, .contact:hover .x, .task:hover .x, .x:focus-visible { opacity: 1; }
  }

  .contact { display: flex; flex-direction: column; gap: 3px; padding: 10px 16px; font: 400 13px/1.45 var(--mc-font); }
  .cn { display: flex; gap: 8px; align-items: center; min-width: 0; }
  .pn { min-width: 0; font-weight: 600; color: var(--mc-ink); overflow-wrap: anywhere; }
  .pn:hover { color: var(--mc-accent); }
  .cn .x { margin-left: auto; }
  .lnk { display: inline-flex; align-items: center; gap: 6px; color: var(--mc-ink2); width: fit-content; }
  .lnk:hover { color: var(--mc-accent); }

  .mg-section > .body .mg-kv { margin-top: 8px; }

  .task { display: flex; align-items: center; gap: 8px; padding: 6px 12px 6px 16px; }
  .tl { flex: 1; min-width: 0; display: flex; gap: 10px; align-items: flex-start; padding: 6px 0; cursor: pointer; font: 400 13px/1.4 var(--mc-font); color: var(--mc-ink2); }
  .tl input { margin-top: 2px; width: 16px; height: 16px; flex: none; }
  .tl > span { display: flex; flex-direction: column; min-width: 0; }
  .tl b { font-weight: 500; color: var(--mc-ink); }
  .tl small { font-size: 12px; color: var(--mc-ink3); }
  .tl.done { opacity: 0.55; text-decoration: line-through; padding: 6px 16px; }
  .addtask { padding: 12px 16px; border-top: 1px solid var(--mc-line); }
  .head + .addtask { border-top: 0; }

  .more { border-top: 1px solid var(--mc-line); }
  .more summary { padding: 12px 16px; cursor: pointer; font: 500 12.5px/1 var(--mc-font); color: var(--mc-ink3); }
  .more summary:hover { color: var(--mc-ink2); }
  .ph-row { display: flex; gap: 10px; padding: 4px 16px; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink2); }
  .ph-row:last-child { padding-bottom: 12px; }
  .ph-row b { color: var(--mc-ink); font-weight: 500; }
  .mg-section :global(.chev) { flex: none; color: var(--mc-ink3); }

  .form { display: flex; flex-direction: column; gap: 12px; }
  .form label { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .mg-select.full { display: block; }
  @media (pointer: coarse) {
    .form .mg-input, .mg-select.full select { height: 44px; font-size: 16px; }
    .x { width: 44px; height: 44px; }
    .tl input { width: 20px; height: 20px; }
  }
</style>
