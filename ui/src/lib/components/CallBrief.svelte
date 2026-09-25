<script>
  /* The sheet an agent reads while the phone is ringing. Everything here is
     deterministic and free; the AI pass is one button and one round-trip, so
     nothing spends a model call just because a drawer was opened. */
  import { api } from '$lib/api.js';
  import { app, toast } from '$lib/state.svelte.js';
  import { fmtR, fmtM, fmtArea } from '$lib/format.js';
  import Icon from './glass/Icon.svelte';
  import Skeleton from './Skeleton.svelte';

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
    <span class="hud">Call brief</span>
    {#if b}
      <span class="mg-chip {ai ? 'mgr' : ''}" title={ai ? 'Written by ' + ai.backend + ' from the facts below' : 'Built from the database — no model involved'}>
        {#if ai}<Icon name="sparkles" size={12} />{/if}{ai ? 'AI-written · ' + String(ai.backend).split(':')[0] : 'From the data'}
      </span>
    {/if}
  </div>

  {#if b}
    <div class="acts">
      {#if writing}
        <span class="mg-btn sm ghost busy"><span class="mg-spin"></span> Writing…</span>
      {:else}
        <button type="button" class="mg-btn sm secondary ai" onclick={writeAi} disabled={aiOff}
          title={aiOff ? app.status.ai_reason || 'No AI provider configured' : 'Rewrite the brief in spoken language'}>
          <Icon name={ai ? 'refresh' : 'sparkles'} size={14} /> {ai ? 'Rewrite' : 'Write with AI'}
        </button>
      {/if}
      <button type="button" class="mg-btn sm secondary" onclick={copy} title="Copy the whole brief as text"><Icon name="copy" size={14} /> Copy</button>
      <a class="mg-btn sm ghost" href="/brief/{encodeURIComponent(gid)}" target="_blank" rel="noopener"
         title="Open the printable page — the one to keep on your phone"><Icon name="external" size={14} /> Open as page</a>
    </div>
    {#if aiOff}<p class="mg-hint off">AI is off — {app.status.ai_reason || 'no AI provider configured'}. The brief below is built from the data.</p>{/if}
  {/if}

  {#if err}
    <div class="mg-strip crit state">
      <span class="ic"><Icon name="alert" size={14} /></span>
      <span class="grow">{err}</span>
      <button type="button" class="mg-btn sm secondary" onclick={load}><Icon name="refresh" size={13} /> Retry</button>
    </div>
  {:else if !b}
    <div class="loading" aria-label="Building the brief">
      <Skeleton h="64px" r="12px" />
      <Skeleton lines={4} h="14px" delay={80} />
    </div>
  {:else}
    {#if tracked}
      <div class="dial">
        <span class="hud">Before you dial</span>
        <div class="dline">
          <span class="mg-chip">Stage {String(tracked.stage).replace(/_/g, ' ')}</span>
          {#if tracked.contact?.phone}
            <a class="mg-btn sm accent" href="tel:{tracked.contact.phone}"><Icon name="phone" size={14} /> {tracked.contact.name || tracked.contact.phone}</a>
          {:else if tracked.contact?.name}
            <span class="dim">{tracked.contact.name} — no number yet</span>
          {/if}
        </div>
        {#if lastContact || tracked.open_tasks}
          <p class="dim small">
            {#if lastContact}Last: <span class="mg-mono">{String(lastContact.occurred_at).slice(0, 10)}</span> {lastContact.channel}
              {(lastContact.outcome || '').replace(/_/g, ' ')}{/if}{#if lastContact && tracked.open_tasks} · {/if}{#if tracked.open_tasks}{tracked.open_tasks} open task(s){/if}
          </p>
        {/if}
      </div>
    {/if}

    {#if opener}
      <h4 class="hud">Opener</h4>
      <div class="mg-strip ok pitch"><span class="ic"><Icon name="chat" size={14} /></span><span>{opener}</span></div>
    {/if}

    <h4 class="hud">Key numbers</h4>
    <dl class="mg-kv">
      {#each facts as [k, v] (k)}
        <div><dt>{k}</dt><dd class="mg-tnum">{v}</dd></div>
      {/each}
    </dl>

    {#if points.length}
      <h4 class="hud">Talking points</h4>
      <ul>{#each points as p, i (i)}<li>{p}</li>{/each}</ul>
    {/if}

    {#if cool.length}
      <h4 class="hud">Cool facts</h4>
      <ul>{#each cool as c, i (i)}
        <li>{c.text}{#if c.source === 'area'}&nbsp;<span class="mg-chip tag">area</span>{/if}</li>
      {/each}</ul>
    {/if}

    {#if questions.length}
      <h4 class="hud">Ask</h4>
      <ul>{#each questions as q, i (i)}<li>{q}</li>{/each}</ul>
    {/if}

    {#if objections.length}
      <h4 class="hud">If they say…</h4>
      <div class="mg-list objs">
        {#each objections as o, i (i)}
          <div class="obj"><b>{o.objection}</b><span>{o.response}</span></div>
        {/each}
      </div>
    {/if}

    {#if avoid.length}
      <h4 class="hud">Avoid</h4>
      <div class="mg-strip crit flags">
        <span class="ic"><Icon name="alert" size={14} /></span>
        <ul>{#each avoid as a, i (i)}<li>{a}</li>{/each}</ul>
      </div>
    {/if}
  {/if}
</div>

<style>
  .cb { font: 400 13px/1.55 var(--mc-font); color: var(--mc-ink2); }
  .top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .top .mg-chip { height: 24px; padding: 0 9px; font-size: 11.5px; }
  .acts { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 12px; }
  .ai :global(svg) { color: var(--mc-mgr); }
  .busy { color: var(--mc-mgr); }
  .off { margin-top: 8px; }

  h4.hud { margin: 20px 0 8px; }

  .state { margin: 14px 0 0; align-items: center; }
  .grow { flex: 1; min-width: 0; }
  .loading { display: flex; flex-direction: column; gap: 14px; margin-top: 16px; }
  /* the drawer is itself the raised plane, so a raised skeleton would vanish on it */
  .loading :global(.mg-skel) { background: var(--mc-line); }

  .dial { margin-top: 14px; padding: 12px 14px; background: var(--mc-surface); border: 1px solid var(--mc-line); border-radius: var(--mc-r-md); }
  .dline { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
  .dim { color: var(--mc-ink3); }
  .small { margin: 8px 0 0; font-size: 12px; }

  .pitch { margin: 0; font-size: 14px; line-height: 1.6; color: var(--mc-ink); }

  ul { margin: 0; padding-left: 18px; }
  li { margin-bottom: 6px; color: var(--mc-ink2); }
  li::marker { color: var(--mc-ink3); }
  .tag { height: 18px; padding: 0 6px; font-size: 10px; vertical-align: 1px; }

  .objs { background: var(--mc-surface); border: 1px solid var(--mc-line); border-radius: var(--mc-r-md); }
  .obj { display: flex; flex-direction: column; gap: 3px; padding: 10px 14px; }
  .obj b { font: 600 13px/1.4 var(--mc-font); color: var(--mc-ink); }
  .obj span { color: var(--mc-ink2); }

  .flags { margin: 0; }
  .flags ul { padding-left: 16px; }
  .flags li { color: var(--mc-ink); margin-bottom: 4px; }
  .flags li:last-child { margin-bottom: 0; }

  @media (pointer: coarse) { .acts :global(.mg-btn.sm) { height: 40px; } }
</style>
