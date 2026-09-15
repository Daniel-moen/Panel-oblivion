<script>
  /* A property you need to act on, with the actions right there:
     call · WhatsApp · log · snooze · done. */
  import QuickLog from './QuickLog.svelte';
  import { waNumber, addrOf, snooze, taskDone, loadToday } from '$lib/leads.svelte.js';
  import { ago, shortDate, MANDATE_LABEL } from '$lib/panel.js';
  import { fmtM } from '$lib/format.js';

  let { p, task = null, reason = '', tone = '', children } = $props();
  let logging = $state(false);
  const wa = $derived(waNumber(p?.contact_phone));
</script>

<div class="lr {tone}">
  <a class="ph" href="/leads/properties/{p.group_id}" style:background-image={p.photo_url ? `url(/api/photo/${encodeURIComponent(p.listing_key || '')})` : null}>
    {#if !p.photo_url}<span>{(p.suburb || '?')[0]}</span>{/if}
  </a>
  <div class="main">
    <div class="top">
      <a class="addr" href="/leads/properties/{p.group_id}">{addrOf(p)}</a>
      <span class="meta">{[p.suburb, p.price_zar ? fmtM(p.price_zar) : null].filter(Boolean).join(' · ')}</span>
      {#if p.mandate_type}<span class="mand">{MANDATE_LABEL[p.mandate_type]}</span>{/if}
    </div>
    <div class="why">
      {#if reason}<span class="r">{reason}</span>{/if}
      {#if task}<span class="r">{task.title}</span>{/if}
      {#if p.contact_name}<a class="c" href="/leads/contacts/{p.contact_id}">👤 {p.contact_name}</a>{#if p.contact_phone}<span class="dim">{p.contact_phone}</span>{/if}
      {:else}<span class="c dim">no contact yet</span>{/if}
      {#if p.last_contact_at}<span class="dim">last {p.last_channel} {ago(p.last_contact_at)} · {String(p.last_outcome || '').replace(/_/g, ' ')}</span>{/if}
    </div>
    {@render children?.()}
    {#if logging}
      <div class="log"><QuickLog gid={p.group_id} contacts={p.contact_id ? [{ id: p.contact_id, name: p.contact_name, phone: p.contact_phone }] : []}
        onsaved={async () => { logging = false; if (task) await taskDone(task); else await loadToday(); }}
        oncancel={() => (logging = false)} /></div>
    {/if}
  </div>
  <div class="acts">
    {#if p.contact_phone}
      <a class="ib" href="tel:{p.contact_phone}" title="Call">📞</a>
      {#if wa}<a class="ib" href="https://wa.me/{wa}" target="_blank" rel="noopener" title="WhatsApp">💬</a>{/if}
    {/if}
    <button class="ib" class:on={logging} onclick={() => (logging = !logging)} title="Log a contact attempt">✎</button>
    {#if task}
      <div class="sn">
        <button class="ib" title="Snooze">⏰</button>
        <div class="menu">
          <button onclick={() => snooze(task, 1)}>Tomorrow</button>
          <button onclick={() => snooze(task, 3)}>3 days</button>
          <button onclick={() => snooze(task, 7)}>Next week</button>
        </div>
      </div>
      <button class="ib ok" onclick={() => taskDone(task)} title="Mark done">✓</button>
    {/if}
  </div>
</div>

<style>
  .lr { display: flex; gap: 0.9rem; padding: 0.8rem 1rem; border-top: 1px solid var(--line); align-items: flex-start; }
  .lr:first-child { border-top: 0; }
  .lr:hover { background: var(--hover); }
  .lr.late { box-shadow: inset 3px 0 0 var(--bad); }
  .lr.warn { box-shadow: inset 3px 0 0 var(--warm); }
  .ph { width: 52px; height: 52px; flex: none; border-radius: 10px; background: var(--bg-3) center/cover;
        display: grid; place-items: center; color: var(--ink-3); font-weight: 700; }
  .main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 0.25rem; }
  .top { display: flex; gap: 0.6rem; align-items: baseline; flex-wrap: wrap; }
  .addr { font-weight: 650; color: var(--ink); font-size: 0.95rem; }
  .addr:hover { color: var(--accent); }
  .meta { font-size: 0.8rem; color: var(--ink-3); }
  .mand { font-size: 0.68rem; font-weight: 700; padding: 0.1rem 0.45rem; border-radius: 4px; background: var(--open-soft); color: var(--open); }
  .why { display: flex; gap: 0.7rem; flex-wrap: wrap; font-size: 0.8rem; }
  .r { color: var(--ink); font-weight: 500; }
  .late .r { color: var(--bad); }
  .c { color: var(--ink-2); }
  a.c:hover { color: var(--accent); }
  .dim { color: var(--ink-3); }
  .log { margin-top: 0.5rem; padding: 0.8rem; background: var(--bg-3); border-radius: var(--r-sm); }

  .acts { display: flex; gap: 0.3rem; align-items: center; flex: none; }
  .ib { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 9px; border: 1px solid var(--line);
        background: var(--bg-2); color: var(--ink-2); font-size: 0.95rem; cursor: pointer; transition: all 0.12s; text-decoration: none; }
  .ib:hover { border-color: var(--line-3); background: var(--bg-3); transform: translateY(-1px); }
  .ib.on { background: var(--accent); color: #fff; border-color: var(--accent); }
  .ib.ok:hover { background: var(--open-soft); color: var(--open); border-color: var(--open); }
  .sn { position: relative; }
  .sn .menu { display: none; position: absolute; right: 0; top: 100%; z-index: 10; margin-top: 0.2rem; padding: 0.25rem;
              background: var(--bg-2); border: 1px solid var(--line-2); border-radius: 8px; box-shadow: var(--shadow-2); min-width: 120px; }
  .sn:hover .menu, .sn:focus-within .menu { display: flex; flex-direction: column; }
  .menu button { background: none; border: 0; text-align: left; padding: 0.4rem 0.6rem; border-radius: 6px; font-size: 0.8rem; color: var(--ink); cursor: pointer; }
  .menu button:hover { background: var(--bg-3); }
</style>
