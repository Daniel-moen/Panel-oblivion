<script>
  /* A property you need to act on, with the actions right there:
     call · WhatsApp · log · snooze · done.

     Logging opens the QuickLog in a Sheet (a bottom sheet on a phone). The
     snooze menu is a popover moved to <body> and pinned to its button, so the
     section's rounded clip can never cut it off on the last row. On a narrow
     row the actions drop to their own line under the text. */
  import { tick } from 'svelte';
  import QuickLog from './QuickLog.svelte';
  import Photo from './Photo.svelte';
  import Sheet from './glass/Sheet.svelte';
  import Icon from './glass/Icon.svelte';
  import { slide } from '$lib/motion.js';
  import { waNumber, addrOf, snooze, taskDone, loadToday } from '$lib/leads.svelte.js';
  import { ago, MANDATE_LABEL } from '$lib/panel.js';
  import { fmtM } from '$lib/format.js';

  let { p, task = null, reason = '', tone = '', children } = $props();
  let logging = $state(false);
  let snoozeOpen = $state(false);
  let snoozeAt = $state({ left: 0 }); // where the menu sits; outlives the close so the exit animates
  let snoozeBtn = $state(null);
  let busy = $state(false);
  const wa = $derived(waNumber(p?.contact_phone));

  function openSnooze() {
    if (snoozeOpen) { snoozeOpen = false; return; }
    const r = snoozeBtn.getBoundingClientRect();
    const below = window.innerHeight - r.bottom > 170;
    // right-align to the button, but never past either edge of the screen
    const W = 188;
    const left = Math.max(8, Math.min(r.right - W, window.innerWidth - W - 8));
    snoozeAt = below ? { top: r.bottom + 6, left } : { bottom: window.innerHeight - r.top + 6, left };
    snoozeOpen = true;
    tick().then(() => document.querySelector('.lr-snooze button')?.focus());
  }
  async function act(fn) {
    busy = true; snoozeOpen = false;
    try { await fn(); } finally { busy = false; }
  }

  // the popover closes on Esc, an outside tap, a scroll or a resize
  $effect(() => {
    if (!snoozeOpen) return;
    const close = () => (snoozeOpen = false);
    const onDown = (e) => { if (!e.target.closest?.('.lr-snooze') && e.target !== snoozeBtn && !snoozeBtn?.contains(e.target)) close(); };
    const onKey = (e) => { if (e.key === 'Escape') { close(); snoozeBtn?.focus(); } };
    window.addEventListener('pointerdown', onDown, true);
    window.addEventListener('keydown', onKey);
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    return () => {
      window.removeEventListener('pointerdown', onDown, true);
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
    };
  });

  function portal(node) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }
</script>

<div class="lr {tone}">
  <div class="in">
    <a class="ph" href="/leads/properties/{p.group_id}" tabindex="-1" aria-hidden="true"><Photo r={p} /></a>
    <div class="main">
      <div class="top">
        <a class="addr" href="/leads/properties/{p.group_id}">{addrOf(p)}</a>
        {#if p.mandate_type}<span class="mg-chip {p.mandate_type === 'none_lost' ? 'crit' : 'ok'} sm">{MANDATE_LABEL[p.mandate_type]}</span>{/if}
      </div>
      <div class="meta">
        {[p.suburb, p.price_zar ? fmtM(p.price_zar) : null].filter(Boolean).join(' · ')}
      </div>
      <div class="why">
        {#if reason}<span class="r">{reason}</span>{/if}
        {#if task}<span class="r">{task.title}</span>{/if}
        {#if p.contact_name}
          <a class="c" href="/leads/contacts/{p.contact_id}"><Icon name="user" size={12} />{p.contact_name}</a>
          {#if p.contact_phone}<span class="dim mg-tnum">{p.contact_phone}</span>{/if}
        {:else}<span class="dim">no contact yet</span>{/if}
        {#if p.last_contact_at}<span class="dim">last {p.last_channel} {ago(p.last_contact_at)} · {String(p.last_outcome || '').replace(/_/g, ' ')}</span>{/if}
      </div>
      {@render children?.()}
    </div>
    <div class="acts">
      {#if p.contact_phone}
        <a class="mg-btn secondary icon sm" href="tel:{p.contact_phone}" title="Call" aria-label="Call {p.contact_name || ''}"><Icon name="phone" size={15} /></a>
        {#if wa}<a class="mg-btn secondary icon sm" href="https://wa.me/{wa}" target="_blank" rel="noopener" title="WhatsApp" aria-label="WhatsApp"><Icon name="message" size={15} /></a>{/if}
      {/if}
      <button type="button" class="mg-btn secondary icon sm" class:on={logging} onclick={() => (logging = true)}
              title="Log a contact attempt" aria-label="Log a contact attempt"><Icon name="pencil" size={15} /></button>
      {#if task}
        <button type="button" class="mg-btn secondary icon sm" class:on={snoozeOpen} bind:this={snoozeBtn} onclick={openSnooze}
                disabled={busy} title="Snooze" aria-label="Snooze" aria-haspopup="menu" aria-expanded={snoozeOpen}><Icon name="clock" size={15} /></button>
        <button type="button" class="mg-btn secondary icon sm done" onclick={() => act(() => taskDone(task))} disabled={busy}
                title="Mark done" aria-label="Mark done"><Icon name="check" size={15} stroke={2} /></button>
      {/if}
    </div>
  </div>
</div>

{#if snoozeOpen}
  <div class="mg-portal" use:portal>
    <div class="lr-snooze mg-popover" role="menu" aria-label="Snooze until"
         style:top={snoozeAt.top != null ? snoozeAt.top + 'px' : null}
         style:bottom={snoozeAt.bottom != null ? snoozeAt.bottom + 'px' : null}
         style:left="{snoozeAt.left}px"
         transition:slide={{ y: snoozeAt.top != null ? -6 : 6, duration: 180 }}>
      <span class="hud">Snooze until</span>
      <button type="button" role="menuitem" onclick={() => act(() => snooze(task, 1))}>Tomorrow</button>
      <button type="button" role="menuitem" onclick={() => act(() => snooze(task, 3))}>In 3 days</button>
      <button type="button" role="menuitem" onclick={() => act(() => snooze(task, 7))}>Next week</button>
    </div>
  </div>
{/if}

<Sheet open={logging} title="Log a contact · {addrOf(p)}" onclose={() => (logging = false)}>
  <QuickLog gid={p.group_id} contacts={p.contact_id ? [{ id: p.contact_id, name: p.contact_name, phone: p.contact_phone }] : []}
    onsaved={async () => { logging = false; if (task) await taskDone(task); else await loadToday(); }}
    oncancel={() => (logging = false)} />
</Sheet>

<style>
  .lr { container-type: inline-size; transition: background var(--mc-t-fast); }
  .lr:hover { background: rgba(255, 255, 255, 0.05); }
  .in { display: flex; gap: 12px; padding: 12px 16px; align-items: flex-start; position: relative; }
  .lr.late .in::before, .lr.warn .in::before {
    content: ''; position: absolute; left: 0; top: 10px; bottom: 10px; width: 3px; border-radius: 0 3px 3px 0;
  }
  .lr.late .in::before { background: var(--mc-crit); }
  .lr.warn .in::before { background: var(--mc-warn); }

  .ph {
    width: 52px; height: 52px; flex: none; border-radius: 10px; overflow: hidden;
    background: var(--mc-inset); border: 1px solid var(--mc-line);
  }
  .main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .top { display: flex; gap: 8px; align-items: center; min-width: 0; }
  .addr {
    min-width: 0; font: 600 14px/1.35 var(--mc-font); color: var(--mc-ink);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .addr:hover { color: var(--mc-accent); }
  .mg-chip.sm { height: 22px; padding: 0 8px; font-size: 11px; }
  .meta { font: 400 12.5px/1.4 var(--mc-font); color: var(--mc-ink3); font-variant-numeric: tabular-nums; }
  .why { display: flex; gap: 4px 12px; flex-wrap: wrap; font: 400 12.5px/1.45 var(--mc-font); color: var(--mc-ink2); }
  .r { color: var(--mc-ink); font-weight: 500; }
  .late .r { color: var(--mc-crit); }
  .warn .r { color: var(--mc-warn); }
  .c { display: inline-flex; align-items: center; gap: 5px; color: var(--mc-ink2); min-width: 0; }
  a.c:hover { color: var(--mc-accent); }
  .dim { color: var(--mc-ink3); }

  .acts { display: flex; gap: 6px; align-items: center; flex: none; }
  .done:hover { background: var(--mc-ok-soft); border-color: var(--mc-ok-line); color: var(--mc-accent); }

  /* a narrow row: the actions take their own line under the text */
  @container (max-width: 520px) {
    .in { flex-wrap: wrap; }
    .acts { flex-basis: 100%; padding-left: 64px; }
  }
  @media (pointer: coarse) {
    .acts .mg-btn { width: 44px; height: 44px; border-radius: 12px; }
  }

  .lr-snooze {
    position: fixed; z-index: 95; width: 188px;
    display: flex; flex-direction: column;
  }
  .lr-snooze .hud { padding: 6px 10px 4px; }
  @media (pointer: coarse) { .lr-snooze > button { min-height: 44px; } }
</style>
