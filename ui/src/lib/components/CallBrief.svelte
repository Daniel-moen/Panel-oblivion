<script>
  /* The sheet an agent reads while the phone is ringing. Everything here is
     deterministic and free; the AI pass is one button and one round-trip, so
     nothing spends a model call just because a drawer was opened. */
  import { api } from '$lib/api.js';
  import { app, toast } from '$lib/state.svelte.js';
  import { fmtR, fmtM, fmtArea } from '$lib/format.js';

  let { gid } = $props();

  let b = $state(null);
  let err = $state(null);
  let writing = $state(false);

  async function load() {
    b = null; err = null;
    const want = gid;
    try {
      const got = await api.brief(want);
      if (want === gid) b = got;         // a fast click moved on already
    } catch (e) {
      if (want === gid) err = e.status === 404 ? "This property isn't in the book any more." : e.message;
    }
  }
  $effect(() => { gid; load(); });

  async function writeAi() {
    writing = true;
    try {
      b = await api.briefAi(gid);
      toast('Brief rewritten by ' + (b.ai?.backend || 'AI'), 'ok');
    } catch (e) {
      toast(e.code === 'ai_unavailable' ? e.message : 'Could not reach the model — ' + e.message, 'error');
    } finally { writing = false; }
  }

  async function copy() {
    try {
      const res = await fetch('/api/brief/' + encodeURIComponent(gid) + '/text');
      await navigator.clipboard.writeText(await res.text());
      toast('Call brief copied', 'ok');
    } catch { toast('Could not copy the brief', 'error'); }
  }

  const ai = $derived(b?.ai || null);
  const n = $derived(b?.numbers || {});
  const opener = $derived(ai?.opener || b?.talking_points?.[0] || null);
  const points = $derived(ai?.talking_points || b?.talking_points || []);
  const questions = $derived(ai?.questions || b?.questions || []);
  const objections = $derived(ai?.objections || b?.objections || []);
  const avoid = $derived(ai?.avoid || b?.avoid || []);
  /* The AI marks its own area facts '(area)' inline, so its list is plain
     strings while the deterministic one carries the source per fact. */
  const cool = $derived(
    ai?.cool_facts
      ? ai.cool_facts.map((t) => ({ text: t, source: 'ai' }))
      : b?.cool_facts || []
  );

  const facts = $derived.by(() => {
    if (!b) return [];
    const out = [['Asking', n.asking_zar ? fmtR(n.asking_zar) : 'POA']];
    if (n.r_per_m2_floor) out.push(['R / m² floor', fmtR(n.r_per_m2_floor)]);
    if (n.gv_value) out.push(['Municipal GV', fmtM(n.gv_value) + (n.gv_roll ? ' · ' + n.gv_roll : '')]);
    if (n.price_vs_gv) out.push(['Asking vs GV', n.price_vs_gv + '×']);
    if (n.days_on_market != null) out.push(['Days on market', String(n.days_on_market)]);
    if (n.suburb_median_zar)
      out.push(['Suburb median', fmtM(n.suburb_median_zar) +
        (n.vs_median_pct != null ? ` (${n.vs_median_pct > 0 ? '+' : ''}${n.vs_median_pct}%)` : '')]);
    if (n.cut_count) out.push(['Price cuts', `${n.cut_count} · ${fmtM(n.price_first_zar)} → ${fmtM(n.price_latest_zar)}`]);
    out.push(['Agencies / portals', `${n.brand_count ?? '?'} / ${n.source_count ?? '?'}`]);
    out.push(['Mandate', (n.mandate_verdict || 'unknown').replace(/_/g, ' ')]);
    if (n.erf_number)
      out.push(['Erf', `${n.erf_number} · ${fmtArea(n.parcel_area_m2) || '—'}` +
        (n.coverage_pct ? ` · ${n.coverage_pct}% built` : '')]);
    if (n.photo_count) out.push(['Photos', String(n.photo_count)]);
    if (n.prospect_score != null) out.push(['Score', `${n.prospect_score} (${n.tier || '—'})`]);
    return out;
  });

  const aiOff = $derived(app.status.ai_ok === false);
  const tracked = $derived(b?.tracked || null);
  const lastContact = $derived(tracked?.interactions?.[0] || null);
</script>

<div class="cb">
  <div class="top">
    <h3>Call brief</h3>
    {#if b}
      <span class="chip" title={ai ? 'Written by ' + ai.backend + ' from the facts below' : 'Built from the database — no model involved'}>
        {ai ? 'AI-written · ' + String(ai.backend).split(':')[0] : 'From the data'}
      </span>
    {/if}
    <span class="grow"></span>
    {#if b}
      {#if writing}
        <span class="act busy"><span class="spin"></span>&nbsp;Writing…</span>
      {:else}
        <button class="act" class:primary={!ai} onclick={writeAi} disabled={aiOff}
          title={aiOff ? app.status.ai_reason || 'No AI provider configured' : 'Rewrite the brief in spoken language'}>
          {ai ? '↻ Rewrite' : '✦ Write with AI'}
        </button>
      {/if}
      <button class="act" onclick={copy} title="Copy the whole brief as text">Copy</button>
      <a class="act" href="/brief/{encodeURIComponent(gid)}" target="_blank" rel="noopener"
         title="Open the printable page — the one to keep on your phone">Open as page ↗</a>
    {/if}
  </div>

  {#if err}
    <p class="err">{err} <button class="act" onclick={load}>Retry</button></p>
  {:else if !b}
    <p class="load"><span class="spin"></span>&nbsp;Building the brief…</p>
  {:else}
    {#if tracked}
      <div class="dial">
        <b>Before you dial</b>
        <span>Stage {String(tracked.stage).replace(/_/g, ' ')}</span>
        {#if tracked.contact?.phone}
          <a href="tel:{tracked.contact.phone}">📞 {tracked.contact.name || tracked.contact.phone}</a>
        {:else if tracked.contact?.name}
          <span>{tracked.contact.name} — no number yet</span>
        {/if}
        {#if lastContact}
          <span class="dim">last: {String(lastContact.occurred_at).slice(0, 10)} {lastContact.channel}
            {(lastContact.outcome || '').replace(/_/g, ' ')}</span>
        {/if}
        {#if tracked.open_tasks}<span class="dim">{tracked.open_tasks} open task(s)</span>{/if}
      </div>
    {/if}

    {#if opener}
      <h4>Opener</h4>
      <div class="pitch">{opener}</div>
    {/if}

    <h4>Key numbers</h4>
    <div class="facts">
      {#each facts as [k, v] (k)}
        <div class="fact"><span>{k}</span><b>{v}</b></div>
      {/each}
    </div>

    {#if points.length}
      <h4>Talking points</h4>
      <ul>{#each points as p, i (i)}<li>{p}</li>{/each}</ul>
    {/if}

    {#if cool.length}
      <h4>Cool facts</h4>
      <ul>{#each cool as c, i (i)}
        <li>{c.text}{#if c.source === 'area'}&nbsp;<span class="tag">area</span>{/if}</li>
      {/each}</ul>
    {/if}

    {#if questions.length}
      <h4>Ask</h4>
      <ul>{#each questions as q, i (i)}<li>{q}</li>{/each}</ul>
    {/if}

    {#if objections.length}
      <h4>If they say…</h4>
      {#each objections as o, i (i)}
        <div class="obj"><b>{o.objection}</b><span>{o.response}</span></div>
      {/each}
    {/if}

    {#if avoid.length}
      <h4>Avoid</h4>
      <div class="flags"><ul>{#each avoid as a, i (i)}<li>{a}</li>{/each}</ul></div>
    {/if}
  {/if}
</div>

<style>
  .cb { font-size: 0.84rem; }
  .top { display: flex; gap: 0.45rem; align-items: center; flex-wrap: wrap; }
  .grow { flex: 1; }
  h3 { margin: 0; font-size: 0.82rem; font-weight: 700; color: var(--ink); }
  h4 { margin: 1rem 0 0.5rem; padding-top: 0.8rem; border-top: 1px solid var(--line);
       font-size: 0.72rem; font-weight: 700; letter-spacing: 0.05em;
       text-transform: uppercase; color: var(--ink-3); }
  .act.primary { color: #fff; background: var(--accent); border-color: var(--accent); }
  .act.primary:hover { background: var(--accent-2); border-color: var(--accent-2); }
  .act.busy { color: var(--accent-2); border-color: transparent; background: none; }
  .load, .err { margin: 1rem 0; color: var(--ink-3); display: flex;
                align-items: center; gap: 0.5rem; }
  .err { color: var(--bad); }

  .dial { display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap;
          margin-top: 0.8rem; padding: 0.5rem 0.7rem; border-radius: var(--r-sm);
          background: var(--bg-3); font-size: 0.78rem; }
  .dial b { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em;
            color: var(--ink-3); }
  .dim { color: var(--ink-3); }

  .pitch { background: var(--accent-soft); border: 1px solid var(--accent-line);
           border-radius: var(--r); padding: 0.75rem 0.9rem;
           font-size: 0.9rem; line-height: 1.6; color: var(--accent-ink); }

  .facts { display: grid; grid-template-columns: 1fr 1fr; gap: 0.55rem 1.2rem; }
  .fact span { display: block; font-size: 0.72rem; color: var(--ink-3); }
  .fact b { font-weight: 600; font-size: 0.86rem; }

  ul { margin: 0; padding-left: 1.05rem; }
  li { line-height: 1.55; margin-bottom: 0.35rem; }
  .tag { font-size: 0.6rem; font-weight: 700; text-transform: uppercase;
         letter-spacing: 0.06em; padding: 0.05rem 0.35rem; border-radius: 4px;
         background: var(--bg-3); color: var(--ink-3); vertical-align: 1px; }

  .obj { padding: 0.4rem 0; border-top: 1px solid var(--line); }
  .obj:first-of-type { border-top: 0; padding-top: 0; }
  .obj b { display: block; }
  .obj span { color: var(--ink-2); }

  .flags { background: var(--red-soft); border: 1px solid var(--red-line);
           border-radius: var(--r); padding: 0.7rem 0.9rem 0.7rem 0.5rem;
           color: var(--bad-ink); }
  .flags li { margin-bottom: 0.3rem; }
</style>
