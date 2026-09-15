<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { app, toast } from '$lib/state.svelte.js';
  import { leads, loadToday } from '$lib/leads.svelte.js';
  import LeadRow from '$lib/components/LeadRow.svelte';
  import { ago, shortDate, MANDATE_LABEL } from '$lib/panel.js';
  import { fmtM } from '$lib/format.js';

  onMount(loadToday);
  const t = $derived(leads.today);
  const hour = new Date().getHours();
  const hello = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';

  const clear = $derived(t && !t.overdue.length && !t.due_today.length && !t.expiring.length && !t.stale.length && !t.ready.length);

  async function trackHot(h) {
    try { await api.track(h.group_id, { stage: 'researching' }); app.tracked[h.group_id] = 'researching';
          toast('Tracking — find the owner next', 'ok'); await loadToday(); }
    catch (e) { toast(e.message, 'error'); }
  }
</script>

<svelte:head><title>Today — Leads</title></svelte:head>

{#if !t}
  <p class="dim">Loading your day…</p>
{:else}
  <header class="hd">
    <div>
      <h1>{hello}.</h1>
      <p class="sub">
        {#if clear}Nothing is waiting on you. {t.counts.active} active lead{t.counts.active === 1 ? '' : 's'}, {t.counts.interactions_7d} contact{t.counts.interactions_7d === 1 ? '' : 's'} this week.
        {:else}{t.overdue.length + t.due_today.length} follow-up{t.overdue.length + t.due_today.length === 1 ? '' : 's'} · {t.ready.length} ready to call · {t.stale.length} gone quiet · {t.expiring.length} expiring · {t.counts.interactions_7d} contacts this week{/if}
      </p>
    </div>
    <div class="kp">
      <div><b>{t.counts.active}</b><span>active</span></div>
      <div><b>{t.counts.tracked}</b><span>tracked</span></div>
      <div><b>{t.counts.interactions_7d}</b><span>contacts / 7d</span></div>
    </div>
  </header>

  <div class="cols">
    <div class="col main">
      {#if t.overdue.length}
        <section class="panel">
          <h2 class="bad">Overdue <span>{t.overdue.length}</span></h2>
          {#each t.overdue as k (k.id)}<LeadRow p={k.property} task={k} tone="late" reason="due {ago(k.due_at)}" />{/each}
        </section>
      {/if}

      <section class="panel">
        <h2>Today <span>{t.due_today.length}</span></h2>
        {#if !t.due_today.length}<p class="empty">No follow-ups due today{t.overdue.length ? ' — clear the overdue ones above' : ''}.</p>{/if}
        {#each t.due_today as k (k.id)}<LeadRow p={k.property} task={k} />{/each}
      </section>

      {#if t.ready.length}
        <section class="panel">
          <h2 class="go">Ready to call <span>{t.ready.length}</span></h2>
          <p class="hint">Owner details found, no contact attempt yet. Hit ✎ after the call.</p>
          {#each t.ready as p (p.group_id)}<LeadRow {p} reason={p.tier === 'hot' ? 'hot prospect' : ''} />{/each}
        </section>
      {/if}

      {#if t.stale.length}
        <section class="panel">
          <h2 class="warn">Gone quiet <span>{t.stale.length}</span></h2>
          <p class="hint">Active leads with no contact attempt in {t.stale[0].days_quiet >= 10 ? '10+' : ''} days and nothing scheduled.</p>
          {#each t.stale as p (p.group_id)}<LeadRow {p} tone="warn" reason="{p.days_quiet} days quiet" />{/each}
        </section>
      {/if}

      {#if t.upcoming.length}
        <section class="panel">
          <h2>Coming up <span>{t.upcoming.length}</span></h2>
          {#each t.upcoming as k (k.id)}<LeadRow p={k.property} task={k} reason="{shortDate(k.due_at)} · {ago(k.due_at)}" />{/each}
        </section>
      {/if}
    </div>

    <div class="col side">
      {#if t.expiring.length}
        <section class="panel pad">
          <h2>Mandates expiring</h2>
          {#each t.expiring as m (m.id)}
            <a class="mini" href="/leads/properties/{m.group_id}">
              <b>{m.property.street_address_raw || m.property.title}</b>
              <span><i class="mand">{MANDATE_LABEL[m.type]}</i> expires {shortDate(m.expires_at)} · {ago(m.expires_at)}</span>
            </a>
          {/each}
        </section>
      {/if}

      {#if t.hot_untracked.length}
        <section class="panel pad">
          <h2>Hot in the engine</h2>
          <p class="hint">Open-mandate, top-scored — not tracked yet.</p>
          {#each t.hot_untracked as h (h.group_id)}
            <div class="mini row">
              <div>
                <b>{h.street_address_raw || h.title}</b>
                <span>{h.suburb} · {h.price_zar ? fmtM(h.price_zar) : 'POA'} · score {h.prospect_score}</span>
              </div>
              <button class="btn sm" onclick={() => trackHot(h)}>+ Track</button>
            </div>
          {/each}
          <a class="more" href="/prospects">All prospects →</a>
        </section>
      {/if}

      {#if t.recent_wins.length}
        <section class="panel pad">
          <h2>Recent wins</h2>
          {#each t.recent_wins as w (w.id)}
            <a class="mini" href="/leads/properties/{w.group_id}">
              <b>{w.property.street_address_raw || w.property.title}</b>
              <span><i class="mand">{MANDATE_LABEL[w.type]}</i> {shortDate(w.signed_at || w.created_at)}{w.listing_price ? ' · ' + fmtM(w.listing_price) : ''}</span>
            </a>
          {/each}
        </section>
      {/if}

      {#if t.engine_events.length}
        <section class="panel pad">
          <h2>Engine noticed</h2>
          {#each t.engine_events as e (e.group_id + e.occurred_at)}
            <a class="mini" href="/leads/properties/{e.group_id}">
              <b>{e.property.street_address_raw || e.property.title}</b>
              <span>{e.kind.replace('_', ' ')} · {ago(e.occurred_at)}</span>
            </a>
          {/each}
        </section>
      {/if}
    </div>
  </div>
{/if}

<style>
  .hd { display: flex; justify-content: space-between; align-items: flex-end; gap: 2rem; margin-bottom: 1.4rem; flex-wrap: wrap; }
  h1 { font-size: 1.9rem; font-weight: 800; letter-spacing: -0.03em; margin: 0 0 0.2rem; }
  .sub { color: var(--ink-2); font-size: 0.92rem; }
  .kp { display: flex; gap: 1.4rem; }
  .kp div { display: flex; flex-direction: column; align-items: flex-end; }
  .kp b { font-size: 1.4rem; font-weight: 800; letter-spacing: -0.02em; }
  .kp span { font-size: 0.72rem; color: var(--ink-3); }

  .cols { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 1.2rem; align-items: start; }
  .col { display: flex; flex-direction: column; gap: 1.2rem; }
  @media (max-width: 1000px) { .cols { grid-template-columns: 1fr; } }

  section.panel { overflow: hidden; }
  h2 { font-size: 0.82rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-2);
       padding: 0.8rem 1rem 0.6rem; display: flex; gap: 0.5rem; align-items: center; }
  .pad h2 { padding: 0 0 0.6rem; }
  h2 span { background: var(--bg-3); color: var(--ink-2); font-size: 0.7rem; padding: 0.05rem 0.45rem; border-radius: 999px; }
  h2.bad { color: var(--bad); } h2.bad span { background: var(--red-soft); color: var(--bad); }
  h2.warn { color: var(--warm); }
  h2.go { color: var(--accent-2); } h2.go span { background: var(--accent-soft); color: var(--accent-2); }
  .empty, .hint { padding: 0 1rem 0.9rem; font-size: 0.84rem; color: var(--ink-3); }
  .pad { padding: 1rem; }
  .pad .hint { padding: 0 0 0.6rem; }
  .dim { color: var(--ink-3); }

  .mini { display: flex; flex-direction: column; gap: 0.1rem; padding: 0.55rem 0; border-top: 1px solid var(--line); color: var(--ink); }
  .mini:first-of-type { border-top: 0; }
  .mini.row { flex-direction: row; justify-content: space-between; align-items: center; gap: 0.6rem; }
  .mini.row > div { display: flex; flex-direction: column; min-width: 0; }
  .mini b { font-size: 0.86rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .mini span { font-size: 0.76rem; color: var(--ink-3); }
  a.mini:hover b { color: var(--accent); }
  .mand { font-style: normal; font-size: 0.66rem; font-weight: 700; padding: 0.05rem 0.4rem; border-radius: 4px; background: var(--open-soft); color: var(--open); }
  .more { display: inline-block; margin-top: 0.6rem; font-size: 0.8rem; color: var(--accent); }
</style>
