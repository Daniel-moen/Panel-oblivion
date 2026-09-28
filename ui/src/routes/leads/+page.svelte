<script>
  /* Today — what lead management needs from you right now.

     Left: the work, in order of urgency (overdue → today → ready to call →
     gone quiet → coming up), every row actionable in place. Right: what is
     worth knowing (mandates expiring, hot prospects not tracked yet, recent
     wins, what the engine noticed). One column until there is room for two. */
  import { onMount } from 'svelte';
  import { api, propertyPath } from '$lib/api.js';
  import { app, toast } from '$lib/state.svelte.js';
  import { leads, loadToday } from '$lib/leads.svelte.js';
  import LeadRow from '$lib/components/LeadRow.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import { ago, shortDate, MANDATE_LABEL } from '$lib/panel.js';
  import { fmtM } from '$lib/format.js';
  import { staggerIn } from '$lib/motion.js';

  onMount(loadToday);
  const t = $derived(leads.today);
  const hour = new Date().getHours();
  const hello = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
  const date = new Date().toLocaleDateString('en-ZA', { weekday: 'long', day: 'numeric', month: 'long' });

  const clear = $derived(t && !t.overdue.length && !t.due_today.length && !t.expiring.length && !t.stale.length && !t.ready.length);
  const followUps = $derived(t ? t.overdue.length + t.due_today.length : 0);
  const plural = (n, one, many = one + 's') => `${n} ${n === 1 ? one : many}`;

  let tracking = $state(null);
  let retrying = $state(false);
  async function trackHot(h) {
    tracking = h.group_id;
    try {
      await api.track(h.group_id, { stage: 'researching' }); app.tracked[h.group_id] = 'researching';
      toast('Tracking — find the owner next', 'ok'); await loadToday();
    } catch (e) { toast(e.message, 'error'); }
    finally { tracking = null; }
  }
  async function retry() { retrying = true; await loadToday(); retrying = false; }
</script>

<svelte:head><title>Today — Leads</title></svelte:head>

{#if !t && leads.failed}
  <div class="mg-strip crit">
    <span class="ic"><Icon name="alert" size={15} /></span>
    <span><b>Couldn't load your day</b> — lead management isn't answering.</span>
  </div>
  <Empty icon="clock" title="Today is unavailable" hint="The follow-ups, ready-to-call list and mandates will show here once the server answers.">
    <button type="button" class="mg-btn secondary" onclick={retry} disabled={retrying}>
      {#if retrying}<span class="mg-spin"></span>{:else}<Icon name="refresh" size={15} />{/if} Try again
    </button>
  </Empty>
{:else if !t}
  <div class="mg-row hd">
    <div class="titles"><Skeleton h="11px" w="120px" /><Skeleton h="26px" w="220px" /><Skeleton h="13px" w="320px" /></div>
  </div>
  <div class="cols">
    <div class="col">
      {#each Array(2) as _, s (s)}
        <section class="mg-section">
          <div class="head"><Skeleton h="13px" w="110px" /></div>
          <div class="mg-list">
            {#each Array(3) as _, i (i)}
              <div class="skrow"><Skeleton h="52px" w="52px" r="10px" delay={i * 60} />
                <span class="sk"><Skeleton h="14px" w="55%" delay={i * 60} /><Skeleton h="11px" w="35%" delay={i * 60 + 40} /></span></div>
            {/each}
          </div>
        </section>
      {/each}
    </div>
  </div>
{:else}
  <div class="mg-row hd">
    <div class="titles">
      <span class="hud">{date}</span>
      <h1 class="mg-h1">{hello}.</h1>
      <p class="mg-sub">
        {#if clear}Nothing is waiting on you. {plural(t.counts.active, 'active lead')}, {plural(t.counts.interactions_7d, 'contact')} this week.
        {:else}{plural(followUps, 'follow-up')} · {t.ready.length} ready to call · {t.stale.length} gone quiet · {t.expiring.length} expiring{/if}
      </p>
    </div>
    <div class="mg-actions kp">
      <span class="mg-stat pill"><span class="v">{t.counts.active}</span><span class="k">active</span></span>
      <span class="mg-stat pill"><span class="v">{t.counts.tracked}</span><span class="k">tracked</span></span>
      <span class="mg-stat pill"><span class="v">{t.counts.interactions_7d}</span><span class="k">contacts / 7d</span></span>
    </div>
  </div>

  <div class="cols">
    <div class="col">
      {#if t.overdue.length}
        <section class="mg-section" in:staggerIn|global={{ i: 0 }}>
          <div class="head"><span class="mg-dot crit"></span><h2 class="crit">Overdue</h2><span class="mg-count">{t.overdue.length}</span></div>
          <div class="mg-list">
            {#each t.overdue as k, i (k.id)}<LeadRow {i} p={k.property} task={k} tone="late" reason="due {ago(k.due_at)}" />{/each}
          </div>
        </section>
      {/if}

      <section class="mg-section" in:staggerIn|global={{ i: 1 }}>
        <div class="head"><span class="mg-dot" class:warn={t.due_today.length}></span><h2>Today</h2><span class="mg-count">{t.due_today.length}</span></div>
        {#if !t.due_today.length}
          <p class="note"><Icon name="check" size={14} /> No follow-ups due today{t.overdue.length ? ' — clear the overdue ones above' : ''}.</p>
        {:else}
          <div class="mg-list">
            {#each t.due_today as k, i (k.id)}<LeadRow {i} p={k.property} task={k} />{/each}
          </div>
        {/if}
      </section>

      {#if t.ready.length}
        <section class="mg-section" in:staggerIn|global={{ i: 2 }}>
          <div class="head"><span class="mg-dot ok"></span><h2>Ready to call</h2><span class="mg-count">{t.ready.length}</span></div>
          <p class="note">Owner details found, no contact attempt yet. Tap <Icon name="pencil" size={13} /> after the call.</p>
          <div class="mg-list">
            {#each t.ready as p, i (p.group_id)}<LeadRow {i} {p} reason={p.tier === 'hot' ? 'hot prospect' : ''} />{/each}
          </div>
        </section>
      {/if}

      {#if t.stale.length}
        <section class="mg-section" in:staggerIn|global={{ i: 3 }}>
          <div class="head"><span class="mg-dot warn"></span><h2>Gone quiet</h2><span class="mg-count">{t.stale.length}</span></div>
          <p class="note">Active leads with no contact attempt in {t.stale[0].days_quiet >= 10 ? '10+ ' : ''}days and nothing scheduled.</p>
          <div class="mg-list">
            {#each t.stale as p, i (p.group_id)}<LeadRow {i} {p} tone="warn" reason="{p.days_quiet} days quiet" />{/each}
          </div>
        </section>
      {/if}

      {#if t.upcoming.length}
        <section class="mg-section" in:staggerIn|global={{ i: 4 }}>
          <div class="head"><span class="mg-dot"></span><h2>Coming up</h2><span class="mg-count">{t.upcoming.length}</span></div>
          <div class="mg-list">
            {#each t.upcoming as k, i (k.id)}<LeadRow {i} p={k.property} task={k} reason="{shortDate(k.due_at)} · {ago(k.due_at)}" />{/each}
          </div>
        </section>
      {/if}
    </div>

    <div class="col side">
      {#if t.expiring.length}
        <section class="mg-section" in:staggerIn|global={{ i: 2 }}>
          <div class="head"><span class="mg-dot warn"></span><h2>Mandates expiring</h2><span class="mg-count">{t.expiring.length}</span></div>
          <div class="mg-list">
            {#each t.expiring as m (m.id)}
              <a class="mg-listrow" href="/leads/properties/{m.group_id}">
                <span class="t"><b>{m.property.street_address_raw || m.property.title}</b>
                  <span>{MANDATE_LABEL[m.type]} · expires {shortDate(m.expires_at)} · {ago(m.expires_at)}</span></span>
                <Icon name="chevronRight" size={15} class="chev" />
              </a>
            {/each}
          </div>
        </section>
      {/if}

      {#if t.hot_untracked.length}
        <section class="mg-section" in:staggerIn|global={{ i: 3 }}>
          <div class="head"><span class="mg-dot crit"></span><h2>Hot in the engine</h2>
            <div class="mg-actions"><a class="mg-btn sm ghost" href="/prospects">All <Icon name="arrowRight" size={13} /></a></div></div>
          <p class="note">Open-mandate, top-scored — not tracked yet.</p>
          <div class="mg-list">
            {#each t.hot_untracked as h (h.group_id)}
              <div class="mg-listrow">
                <a class="t" href={propertyPath(h.listing_key || h.group_id)}>
                  <b>{h.street_address_raw || h.title}</b>
                  <span>{h.suburb} · {h.price_zar ? fmtM(h.price_zar) : 'POA'} · score {h.prospect_score}</span>
                </a>
                <button type="button" class="mg-btn secondary sm" onclick={() => trackHot(h)} disabled={tracking === h.group_id}>
                  {#if tracking === h.group_id}<span class="mg-spin"></span>{:else}<Icon name="plus" size={14} />{/if} Track
                </button>
              </div>
            {/each}
          </div>
        </section>
      {/if}

      {#if t.recent_wins.length}
        <section class="mg-section" in:staggerIn|global={{ i: 4 }}>
          <div class="head"><span class="mg-dot ok"></span><h2>Recent wins</h2></div>
          <div class="mg-list">
            {#each t.recent_wins as w (w.id)}
              <a class="mg-listrow" href="/leads/properties/{w.group_id}">
                <span class="t"><b>{w.property.street_address_raw || w.property.title}</b>
                  <span>{MANDATE_LABEL[w.type]} · {shortDate(w.signed_at || w.created_at)}{w.listing_price ? ' · ' + fmtM(w.listing_price) : ''}</span></span>
                <Icon name="chevronRight" size={15} class="chev" />
              </a>
            {/each}
          </div>
        </section>
      {/if}

      {#if t.engine_events.length}
        <section class="mg-section" in:staggerIn|global={{ i: 5 }}>
          <div class="head"><span class="mg-dot mgr"></span><h2>Engine noticed</h2></div>
          <div class="mg-list">
            {#each t.engine_events as e (e.group_id + e.occurred_at)}
              <a class="mg-listrow" href="/leads/properties/{e.group_id}">
                <span class="t"><b>{e.property.street_address_raw || e.property.title}</b>
                  <span>{e.kind.replace(/_/g, ' ')} · {ago(e.occurred_at)}</span></span>
                <Icon name="chevronRight" size={15} class="chev" />
              </a>
            {/each}
          </div>
        </section>
      {/if}
    </div>
  </div>
{/if}

<style>
  .hd { align-items: flex-end; }
  .titles { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .titles .mg-h1 { font-size: 26px; }
  .kp { gap: 6px; }
  .kp .mg-stat.pill { align-items: center; }

  .cols { display: grid; gap: 14px; grid-template-columns: minmax(0, 1fr); align-items: start; }
  .col { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
  .side:empty { display: none; }
  @media (min-width: 1240px) { .cols { grid-template-columns: minmax(0, 1fr) 340px; } }

  .mg-section > .head { align-items: center; }
  .mg-section > .head > h2.crit { color: var(--mc-crit); }
  .note {
    display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
    margin: 0; padding: 10px 16px; border-bottom: 1px solid var(--mc-line);
    font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink3);
  }
  .mg-section > .note:last-child { border-bottom: 0; }

  .mg-listrow > a.t:hover b, a.mg-listrow:hover .t b { color: var(--mc-accent); }
  .mg-section :global(.chev) { flex: none; color: var(--mc-ink3); }

  .skrow { display: flex; gap: 12px; align-items: center; padding: 12px 16px; }
  .sk { flex: 1; display: flex; flex-direction: column; gap: 8px; }
</style>
