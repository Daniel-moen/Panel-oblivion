<script>
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { api } from '$lib/api.js';
  import { toast, app } from '$lib/state.svelte.js';
  import { loadToday, waNumber, addrOf } from '$lib/leads.svelte.js';
  import QuickLog from '$lib/components/QuickLog.svelte';
  import CallBrief from '$lib/components/CallBrief.svelte';
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
  onMount(load);
  $effect(() => { gid; load(); });
  const refresh = async () => { await load(); loadToday(); };

  async function setStage(v) {
    try { await api.updateTracked(gid, { stage: v }); app.tracked[gid] = v; await refresh(); }
    catch (e) { toast(e.message, 'error'); }
  }
  async function togglePriority() {
    const v = d.priority === 'high' ? 'normal' : 'high';
    try { await api.updateTracked(gid, { priority: v }); d.priority = v; } catch (e) { toast(e.message, 'error'); }
  }
  async function add(kind, body, after) {
    try { await api.child.add(gid, kind, body); after?.(); await refresh(); toast('Saved', 'ok'); }
    catch (e) { toast(e.message, 'error'); }
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

  const today = () => new Date().toISOString().slice(0, 10);
  let cf = $state({ role: 'owner', name: '', phone: '', email: '', company: '', notes: '' });
  let mf = $state({ type: 'sole', signed_at: today(), duration_days: 90, listing_price: '', commission_pct: '',
                    competing_agencies: '', lost_reason: 'went_with_other_agency', lost_to: '', notes: '' });
  function saveMandate() {
    const b = { ...mf, listing_price: mf.listing_price ? Number(mf.listing_price) : null,
                commission_pct: mf.commission_pct ? Number(mf.commission_pct) : null,
                duration_days: mf.duration_days ? Number(mf.duration_days) : null };
    if (mf.type === 'none_lost') { b.signed_at = null; b.duration_days = null; } else { b.lost_reason = null; b.lost_to = null; }
    add('mandates', b, () => (showMandate = false));
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
  const ICON = { call: '📞', whatsapp: '💬', sms: '✉️', email: '📧', visit: '🚪', letter: '📮' };
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

{#if err === 'notfound'}
  <div class="empty panel"><h3>Not tracked</h3><p>This property isn't in lead management yet.</p>
    <button class="btn primary" onclick={async () => { await api.track(gid); app.tracked[gid] = 'new'; load(); }}>+ Track it</button></div>
{:else if err}
  <div class="empty panel"><h3>Couldn't load</h3><p>{err}</p></div>
{:else if d}
  <a class="back" href="/leads/properties">← Properties</a>

  <header class="hd panel">
    <div class="ph" style:background-image={d.photo_url ? `url(/api/photo/${encodeURIComponent(d.listing_key)})` : null}></div>
    <div class="hl">
      <div class="badges">
        {#if d.tier}<span class="tier {d.tier}">{d.tier}</span>{/if}
        {#if d.mandate_verdict}<span class="mv {d.mandate_verdict}">{label(d.mandate_verdict)}</span>{/if}
        {#if mandate}<span class="mand m-{mandate.type}">{mandate.type === 'none_lost' ? 'Lost' : MANDATE_LABEL[mandate.type] + ' mandate'}{mandate.expires_at && mandate.type !== 'none_lost' ? ' · exp ' + shortDate(mandate.expires_at) : ''}</span>{/if}
        <button class="star" class:on={d.priority === 'high'} onclick={togglePriority} title="Toggle high priority">★</button>
      </div>
      <h1>{addrOf(d)}</h1>
      <p class="sub">{[d.suburb, d.property_type, d.bedrooms ? d.bedrooms + ' bed' : null, d.erf_number ? 'Erf ' + d.erf_number : null].filter(Boolean).join(' · ')}</p>
      <p class="price">{d.price_zar ? fmtR(d.price_zar) : 'POA'}{#if d.listing_count > 1}<span class="dim"> · {d.listing_count} listings · {d.agency_count} agencies</span>{/if}</p>
      <div class="acts">
        {#if primary?.phone}<a class="btn sm" href="tel:{primary.phone}">📞 Call {primary.name?.split(' ')[0] || ''}</a>{/if}
        {#if wa}<a class="btn sm" href="https://wa.me/{wa}" target="_blank" rel="noopener">💬 WhatsApp</a>{/if}
        <button class="btn sm" onclick={openBrief} title="What to say when you phone the owner">Call brief</button>
        {#if d.url}<a class="btn sm" href={d.url} target="_blank" rel="noopener">Listing ↗</a>{/if}
        {#if d.cma_url}<a class="btn sm" href={d.cma_url}>CMA report</a>{/if}
        <a class="btn sm" href="/prospects?open={encodeURIComponent(d.listing_key)}" title="Open in the prospect engine: score, signals, erf tools">Engine view</a>
        <a class="btn sm" href="/map?focus={encodeURIComponent(gid)}">Map</a>
      </div>
    </div>
  </header>

  <div class="stepper panel">
    {#each FLOW as s, i (s)}
      <button class="step" class:done={i < flowIdx} class:cur={s === d.stage} onclick={() => setStage(s)} title={STAGE_LABEL[s]}>
        <i>{i < flowIdx ? '✓' : i + 1}</i><span>{STAGE_LABEL[s]}</span>
      </button>
    {/each}
    <span class="sep"></span>
    {#each ENDS as s (s)}
      <button class="step end" class:cur={s === d.stage} onclick={() => setStage(s)}><span>{STAGE_LABEL[s]}</span></button>
    {/each}
  </div>

  <div class="cols">
    <div class="col main">
      <section class="panel pad brief" bind:this={briefEl}>
        {#if showBrief}
          <CallBrief gid={gid} />
        {:else}
          <div class="row">
            <h2>Call brief</h2>
            <span class="grow"></span>
            <button class="btn sm" onclick={openBrief}>Show call brief</button>
          </div>
        {/if}
      </section>

      <section class="panel composer">
        <div class="ctabs">
          <button class:on={compose === 'log'} onclick={() => (compose = 'log')}>Log contact attempt</button>
          <button class:on={compose === 'note'} onclick={() => (compose = 'note')}>Add note</button>
          <span class="kbd">⌘↵</span>
        </div>
        {#if compose === 'log'}
          <QuickLog {gid} contacts={d.contacts} onsaved={refresh} />
        {:else}
          <form class="row" onsubmit={(e) => { e.preventDefault(); if (note.trim()) add('notes', { body: note.trim() }, () => (note = '')); }}>
            <input type="text" bind:value={note} placeholder="Anything worth remembering…" />
            <button class="btn sm primary" type="submit">Save note</button>
          </form>
        {/if}
      </section>

      <section class="panel stream">
        {#if !stream.length}<p class="hint">Nothing yet. Log your first call above.</p>{/if}
        {#each stream as s (s.kind + (s.i?.id ?? s.n?.id ?? s.a?.id))}
          <div class="ev {s.kind}">
            <div class="ico">
              {#if s.kind === 'interaction'}{ICON[s.i.channel] || '•'}{:else if s.kind === 'note'}📝{:else if s.kind === 'mandate'}🏆{:else if s.kind === 'stage_change'}→{:else}•{/if}
            </div>
            <div class="body">
              {#if s.kind === 'interaction'}
                <div class="l1"><b>{label(s.i.channel)}</b>
                  <span class="oc o-{s.i.outcome}">{label(s.i.outcome)}</span>
                  {#if s.i.contact_name}<span class="dim">with {s.i.contact_name}</span>{/if}</div>
                {#if s.i.summary}<p>{s.i.summary}</p>{/if}
                {#if s.i.next_follow_up_at}<p class="dim">follow-up {shortDate(s.i.next_follow_up_at)}</p>{/if}
              {:else if s.kind === 'note'}
                <p>{s.n.body}</p>
              {:else}
                <p class="sys">{actText(s.a)}</p>
              {/if}
            </div>
            <div class="when" title={s.t}>{ago(s.t)}</div>
            {#if s.kind === 'interaction'}<button class="x" onclick={() => remove('interactions', s.i.id)}>×</button>
            {:else if s.kind === 'note'}<button class="x" onclick={() => remove('notes', s.n.id)}>×</button>{/if}
          </div>
        {/each}
      </section>
    </div>

    <div class="col side">
      <section class="panel pad">
        <h2>Contacts</h2>
        {#each d.contacts as c (c.id)}
          <div class="contact">
            <div class="cn"><a class="pn" href="/leads/contacts/{c.id}"><b>{c.name || '—'}</b></a><span class="pill">{c.role}</span><button class="x" onclick={() => remove('contacts', c.id)} title="Delete (POPIA)">×</button></div>
            {#if c.company}<span class="dim">{c.company}</span>{/if}
            {#if c.phone}<a href="tel:{c.phone}">{c.phone}</a>{/if}
            {#if c.email}<a href="mailto:{c.email}">{c.email}</a>{/if}
            {#if c.notes}<span class="dim small">{prettyNotes(c.notes)}</span>{/if}
            <span class="dim small">via {c.provider}</span>
          </div>
        {/each}
        {#if !d.contacts.length}<p class="hint">No owner details yet.</p>{/if}
        {#if showContact}
          <form class="form" onsubmit={(e) => { e.preventDefault(); if (cf.name || cf.phone) add('contacts', { ...cf, provider: 'manual' }, () => { showContact = false; cf = { role: 'owner', name: '', phone: '', email: '', company: '', notes: '' }; }); }}>
            <div class="two"><input type="text" placeholder="Name" bind:value={cf.name} />
              <select bind:value={cf.role}>{#each meta.roles as r (r)}<option value={r}>{r}</option>{/each}</select></div>
            <div class="two"><input type="text" placeholder="Phone" bind:value={cf.phone} /><input type="text" placeholder="Email" bind:value={cf.email} /></div>
            <input type="text" placeholder="Company / notes" bind:value={cf.notes} />
            <div class="row"><button class="btn sm primary" type="submit">Save</button><button class="btn sm" type="button" onclick={() => (showContact = false)}>Cancel</button></div>
          </form>
        {:else}
          <div class="row">
            <button class="btn sm" onclick={() => (showContact = true)}>+ Add</button>
            {#if d.cma_url}<button class="btn sm" onclick={deedLookup} title="Look up the registered owner via the deeds office">Deeds lookup</button>{/if}
          </div>
        {/if}
      </section>

      <section class="panel pad">
        <h2>Mandate</h2>
        {#if mandate}
          <div class="mcard m-{mandate.type}">
            <b>{mandate.type === 'none_lost' ? 'Lost' : MANDATE_LABEL[mandate.type]}</b>
            {#if mandate.type === 'none_lost'}
              <span>{label(mandate.lost_reason)}{mandate.lost_to ? ' · to ' + mandate.lost_to : ''}</span>
            {:else}
              <span>Signed {shortDate(mandate.signed_at)}{mandate.expires_at ? ` · expires ${shortDate(mandate.expires_at)} (${ago(mandate.expires_at)})` : ''}</span>
              <span>{mandate.listing_price ? fmtM(mandate.listing_price) : ''}{mandate.commission_pct ? ` · ${mandate.commission_pct}%` : ''}</span>
            {/if}
            {#if mandate.notes}<span class="dim">{mandate.notes}</span>{/if}
          </div>
        {/if}
        {#if showMandate}
          <form class="form" onsubmit={(e) => { e.preventDefault(); saveMandate(); }}>
            <select bind:value={mf.type}>{#each meta.mandate_types as t (t)}<option value={t}>{t === 'none_lost' ? 'Lost — no mandate' : MANDATE_LABEL[t] + ' mandate'}</option>{/each}</select>
            {#if mf.type === 'none_lost'}
              <select bind:value={mf.lost_reason}>{#each meta.lost_reasons as r (r)}<option value={r}>{label(r)}</option>{/each}</select>
              <input type="text" placeholder="Lost to which agency?" bind:value={mf.lost_to} />
            {:else}
              <div class="two"><label>Signed <input type="date" bind:value={mf.signed_at} /></label><label>Days <input type="number" bind:value={mf.duration_days} /></label></div>
              <div class="two"><input type="number" placeholder="Listing price (R)" bind:value={mf.listing_price} /><input type="number" step="0.1" placeholder="Commission %" bind:value={mf.commission_pct} /></div>
              <input type="text" placeholder="Competing agencies" bind:value={mf.competing_agencies} />
            {/if}
            <input type="text" placeholder="Notes" bind:value={mf.notes} />
            <div class="row"><button class="btn sm primary" type="submit">Save</button><button class="btn sm" type="button" onclick={() => (showMandate = false)}>Cancel</button></div>
          </form>
        {:else}
          <button class="btn sm" class:primary={!mandate && d.stage === 'valuation_sent'} onclick={() => (showMandate = true)}>{mandate ? 'Record new outcome' : 'Record outcome'}</button>
        {/if}
      </section>

      <section class="panel pad">
        <h2>Tasks {#if openTasks.length}<span class="cnt">{openTasks.length}</span>{/if}</h2>
        {#each openTasks as t (t.id)}
          <label class="task"><input type="checkbox" onchange={() => toggleTask(t)} />
            <span><b>{t.title}</b><small class:late={isPast(t.due_at)}>{t.due_at ? `${shortDate(t.due_at)} · ${ago(t.due_at)}` : 'no date'}</small></span>
            <button class="x" type="button" onclick={() => remove('tasks', t.id)}>×</button></label>
        {/each}
        <form class="row" onsubmit={(e) => { e.preventDefault(); if (newTask.trim()) add('tasks', { title: newTask.trim(), kind: 'other' }, () => (newTask = '')); }}>
          <input type="text" placeholder="Add a task…" bind:value={newTask} /><button class="btn sm" type="submit">+</button>
        </form>
        {#if doneTasks.length}<details><summary class="dim small">{doneTasks.length} done</summary>
          {#each doneTasks as t (t.id)}<label class="task done"><input type="checkbox" checked onchange={() => toggleTask(t)} /><span>{t.title}</span></label>{/each}</details>{/if}
      </section>

      <section class="panel pad">
        <h2>Listings</h2>
        {#each d.listings as l (l.listing_key)}
          <div class="lst"><a href={l.url} target="_blank" rel="noopener"><b>{l.source}</b> ↗</a>
            <span>{l.agency || ''}{l.agent_name ? ' · ' + l.agent_name : ''}</span>
            <span class="dim">{l.price_zar ? fmtM(l.price_zar) : 'POA'} · seen {ago(l.last_seen)}{l.lifecycle && l.lifecycle !== 'active' ? ' · ' + l.lifecycle : ''}</span></div>
        {/each}
        {#if d.price_history.length > 1}
          <details><summary class="dim small">Price history ({d.price_history.length})</summary>
            {#each d.price_history as p (p.listing_key + p.observed_at)}<div class="dim small">{shortDate(p.observed_at)} · {fmtR(p.price_zar)} · {p.listing_key.split(':')[0]}</div>{/each}</details>
        {/if}
      </section>
    </div>
  </div>
{/if}

<style>
  .back { display: inline-block; margin-bottom: 0.7rem; font-size: 0.82rem; color: var(--ink-3); }
  .empty { padding: 3rem 2rem; text-align: center; max-width: 520px; margin: 3rem auto; }
  .empty p { color: var(--ink-2); margin: 0.5rem 0 1.2rem; }

  .hd { display: flex; gap: 1.3rem; padding: 1.2rem; margin-bottom: 0.8rem; }
  .ph { width: 150px; height: 120px; flex: none; border-radius: 12px; background: var(--bg-3) center/cover; }
  .hl { flex: 1; min-width: 0; }
  .badges { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.4rem; }
  .star { margin-left: auto; background: none; border: 0; font-size: 1.2rem; color: var(--line-3); cursor: pointer; }
  .star.on { color: var(--warm); }
  h1 { font-size: 1.45rem; font-weight: 800; letter-spacing: -0.02em; margin: 0 0 0.2rem; }
  .sub { color: var(--ink-2); font-size: 0.86rem; }
  .price { font-size: 1.1rem; font-weight: 700; margin: 0.4rem 0 0.7rem; }
  .acts { display: flex; gap: 0.4rem; flex-wrap: wrap; }
  .dim { color: var(--ink-3); } .small { font-size: 0.74rem; }

  .stepper { display: flex; align-items: center; gap: 0.15rem; padding: 0.5rem; margin-bottom: 1rem; overflow-x: auto; }
  .step { display: flex; align-items: center; gap: 0.4rem; background: none; border: 0; padding: 0.4rem 0.6rem; border-radius: 8px;
          color: var(--ink-3); font-size: 0.76rem; font-weight: 500; cursor: pointer; white-space: nowrap; }
  .step i { font-style: normal; width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center;
            font-size: 0.66rem; font-weight: 700; background: var(--bg-3); color: var(--ink-3); }
  .step.done { color: var(--ink-2); } .step.done i { background: var(--open-soft); color: var(--open); }
  .step.cur { background: var(--accent-soft); color: var(--accent-2); font-weight: 700; }
  .step.cur i { background: var(--accent); color: #fff; }
  .step:hover:not(.cur) { background: var(--bg-3); color: var(--ink); }
  .sep { flex: 1; min-width: 0.5rem; }
  .step.end.cur { background: var(--red-soft); color: var(--bad); }

  .cols { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 1rem; align-items: start; }
  .col { display: flex; flex-direction: column; gap: 1rem; }
  @media (max-width: 1000px) { .cols { grid-template-columns: 1fr; } }

  .brief h2 { margin: 0; }
  .brief .grow { flex: 1; }
  .composer { padding: 0.9rem 1rem 1rem; }
  .ctabs { display: flex; gap: 0.2rem; margin-bottom: 0.7rem; align-items: center; }
  .ctabs button { background: none; border: 0; padding: 0.3rem 0.6rem; border-radius: 6px; font-size: 0.8rem; font-weight: 600; color: var(--ink-3); cursor: pointer; }
  .ctabs button.on { background: var(--bg-3); color: var(--ink); }
  .kbd { margin-left: auto; font-size: 0.68rem; color: var(--ink-3); border: 1px solid var(--line-2); border-radius: 4px; padding: 0 0.3rem; }
  .row { display: flex; gap: 0.5rem; align-items: center; }
  .row input[type='text'] { flex: 1; }

  .stream { padding: 0.3rem 0; }
  .hint { padding: 0.8rem 1rem; color: var(--ink-3); font-size: 0.84rem; }
  .pad .hint { padding: 0 0 0.6rem; }
  .ev { display: flex; gap: 0.8rem; padding: 0.7rem 1rem; border-top: 1px solid var(--line); align-items: flex-start; }
  .ev:first-child { border-top: 0; }
  .ico { width: 30px; height: 30px; border-radius: 50%; background: var(--bg-3); display: grid; place-items: center; font-size: 0.9rem; flex: none; }
  .ev.mandate .ico { background: var(--open-soft); }
  .ev.stage_change .ico, .ev.tracked .ico, .ev.contact_added .ico { background: transparent; color: var(--ink-3); }
  .body { flex: 1; min-width: 0; font-size: 0.86rem; }
  .l1 { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
  .body p { margin: 0.2rem 0 0; }
  .sys { color: var(--ink-3); font-size: 0.8rem; }
  .when { font-size: 0.74rem; color: var(--ink-3); white-space: nowrap; }
  .x { background: none; border: 0; color: var(--ink-3); cursor: pointer; font-size: 1rem; padding: 0 0.2rem; opacity: 0; }
  .ev:hover .x, .contact:hover .x, .task:hover .x { opacity: 1; }
  .x:hover { color: var(--bad); }
  .oc { font-size: 0.7rem; font-weight: 600; padding: 0.08rem 0.45rem; border-radius: 4px; background: var(--bg-3); color: var(--ink-2); }
  .o-spoke, .o-interested, .o-meeting_set { background: var(--open-soft); color: var(--open); }
  .o-not_interested { background: var(--red-soft); color: var(--sole); }
  .o-callback_requested { background: var(--popen-soft); color: var(--popen); }

  .pad { padding: 0.9rem 1rem; }
  h2 { font-size: 0.74rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-2); margin-bottom: 0.6rem; display: flex; gap: 0.4rem; align-items: center; }
  .cnt { background: var(--accent-soft); color: var(--accent-2); padding: 0 0.45rem; border-radius: 999px; font-size: 0.68rem; }
  .contact { display: flex; flex-direction: column; gap: 0.1rem; font-size: 0.84rem; padding: 0.5rem 0; border-top: 1px solid var(--line); }
  .contact:first-of-type { border-top: 0; }
  .cn { display: flex; gap: 0.4rem; align-items: center; }
  .cn .x { margin-left: auto; }
  .pn { color: var(--ink); } .pn:hover { color: var(--accent); }
  .pill { font-size: 0.66rem; padding: 0.05rem 0.4rem; border-radius: 999px; background: var(--bg-3); color: var(--ink-2); }
  .form { display: flex; flex-direction: column; gap: 0.4rem; margin-top: 0.5rem; }
  .form input, .form select { width: 100%; font-size: 0.82rem; }
  .form label { font-size: 0.7rem; color: var(--ink-3); display: flex; flex-direction: column; gap: 0.15rem; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 0.4rem; }
  .mand { font-size: 0.7rem; font-weight: 700; padding: 0.12rem 0.5rem; border-radius: 4px; background: var(--open-soft); color: var(--open); }
  .m-none_lost { background: var(--red-soft); color: var(--sole); }
  .mcard { display: flex; flex-direction: column; gap: 0.15rem; font-size: 0.82rem; padding: 0.7rem 0.8rem; border-radius: var(--r-sm);
           background: var(--open-soft); border: 1px solid transparent; margin-bottom: 0.6rem; }
  .mcard b { font-size: 0.95rem; color: var(--open); }
  .mcard.m-none_lost { background: var(--red-soft); } .mcard.m-none_lost b { color: var(--sole); }
  .task { display: flex; gap: 0.5rem; align-items: flex-start; padding: 0.4rem 0; font-size: 0.84rem; cursor: pointer; }
  .task span { display: flex; flex-direction: column; flex: 1; }
  .task small { color: var(--ink-3); font-size: 0.72rem; } .task small.late { color: var(--bad); font-weight: 600; }
  .task.done { opacity: 0.55; text-decoration: line-through; }
  .task .x { align-self: center; }
  .lst { display: flex; flex-direction: column; font-size: 0.8rem; padding: 0.4rem 0; border-top: 1px solid var(--line); }
  .lst:first-of-type { border-top: 0; }
  details { margin-top: 0.4rem; } summary { cursor: pointer; }
</style>
