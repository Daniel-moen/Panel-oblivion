<script>
  /* The strip along the top of every route, in the language of Home's scene:
     link state and a small date over a light clock on the left, the status
     readout and a row of round glass buttons on the right.

     The clock replaces the brand (the Dock's Home tab already says where
     you are), so the strip reads the same on a phone, an iPad and a
     desktop. It is sticky and translucent, like the panel's header; the
     buttons carry no blur of their own.

     Right-hand cluster, left to right: the page's own posted actions
     (`shell.actions`), Search (focuses the page's search box, or goes to
     one — `$lib/search.js`; also on "/"), Quick log (the global sheet;
     about this property when you are on one), team chat (with the unread
     count) and the account — the signed-in person's initial, which is where
     the old sidebar's foot (name, role, passkeys, settings) lives now. The
     primary action is not here: it is the Dock's raised button, at every
     width.

     Props:
       scene   true on Home while something is happening (a crawl): a slim
               strip with just the status dot and the readout, linked to
               /prospects. Home draws its own clock and buttons.

     Drawn ONCE, by routes/+layout.svelte. Pages never draw their own; they
     post to `$lib/shell.svelte.js` instead. */
  import { page } from '$app/state';
  import { app } from '$lib/state.svelte.js';
  import { shell, chrome, engineStatus, openQuickLog } from '$lib/shell.svelte.js';
  import { chat, toggleChat, chatBadge } from '$lib/chat.svelte.js';
  import { openSearch, searchKey } from '$lib/search.js';
  import Icon from './Icon.svelte';
  import AccountButton from './AccountButton.svelte';

  let { scene = false } = $props();

  const path = $derived(page.url.pathname);

  /* A section's own status wins; with nothing posted the readout falls back
     to the engine, which is the one thing that is true on every page. */
  const status = $derived(shell.status || engineStatus(app.status));
  const crawling = $derived(!!app.status.running);
  const hot = $derived(app.prospects.reduce((n, r) => n + (r.tier === 'hot' ? 1 : 0), 0));
  const badge = $derived(chatBadge());

  /* ——— the clock: browser locale, 24-hour, refreshed on the minute ——— */
  const LOCALE = (typeof navigator !== 'undefined' && navigator.language) || 'en-ZA';
  const fmt = (o) => { try { return new Intl.DateTimeFormat(LOCALE, o); } catch { return new Intl.DateTimeFormat('en-ZA', o); } };
  const DAY = fmt({ weekday: 'long', day: 'numeric', month: 'long' });
  const DAY_SHORT = fmt({ weekday: 'short', day: 'numeric', month: 'short' });
  const TIME = fmt({ hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

  let now = $state(new Date());
  const day = $derived(DAY.format(now));
  const dayShort = $derived(DAY_SHORT.format(now));
  const time = $derived(TIME.format(now));

  /* Land on the next minute boundary, then check every 15 s (cheap, and it
     self-corrects after a sleep); a tab coming back re-reads at once. */
  $effect(() => {
    if (scene) return;
    let iv = null;
    const set = () => (now = new Date());
    const to = setTimeout(() => { set(); iv = setInterval(set, 15000); }, 60000 - (Date.now() % 60000) + 50);
    const vis = () => { if (!document.hidden) set(); };
    document.addEventListener('visibilitychange', vis);
    set();
    return () => { clearTimeout(to); clearInterval(iv); document.removeEventListener('visibilitychange', vis); };
  });

  /* Quick log: about this property when you are standing on one. */
  function quickLog() {
    const m = path.match(/^\/leads\/properties\/([^/]+)/);
    openQuickLog(m ? decodeURIComponent(m[1]) : null);
  }
</script>

<svelte:window onkeydown={scene ? null : searchKey} />

{#if scene}
  <header class="strip scene" data-strip="scene">
    <div class="in">
      <a class="slim mg-tnum" href={status.href || '/prospects'} title={status.title || status.label}>
        <span class="mg-dot {status.tone === 'off' ? '' : status.tone}">{#if status.ping}<i class="mg-ping"></i>{/if}</span>
        <span class="st {status.tone}">{status.label}</span>
      </a>
    </div>
  </header>
{:else}
  <header class="strip" class:busy={crawling || !!shell.status?.ping} class:crowded={shell.actions.length > 0}>
    <div class="in">
      <span class="link" aria-hidden="true">
        <span class="mg-dot {status.tone === 'off' ? '' : status.tone}">{#if status.ping}<i class="mg-ping"></i>{/if}</span>
      </span>
      <div class="when">
        <span class="day"><span class="long">{day}</span><span class="short">{dayShort}</span></span>
        <time class="clock" datetime={now.toISOString()}>{time}</time>
      </div>

      <span class="gap"></span>

      <!-- compact status readout -->
      {#if status.href}
        <a class="readout mg-tnum" href={status.href} title={status.title || status.label}>
          <span class="st {status.tone}">{status.label}</span>
        </a>
      {:else}
        <span class="readout mg-tnum" title={status.title || status.label}>
          <span class="st {status.tone}">{status.label}</span>
          {#if hot && !crawling}<span class="hot"><b>{hot}</b> hot</span>{/if}
        </span>
      {/if}

      <div class="btns">
        {#each shell.actions as a (a.id)}
          {#if a.href}
            <a class="mg-round" href={a.href} aria-label={a.label} title={a.label}><Icon name={a.icon} size={18} /></a>
          {:else}
            <button type="button" class="mg-round" onclick={a.onclick} aria-label={a.label} title={a.label}>
              <Icon name={a.icon} size={18} />
            </button>
          {/if}
        {/each}

        <button type="button" class="mg-round" onclick={() => openSearch()} aria-label="Search" title="Search (/)">
          <Icon name="search" size={18} />
        </button>

        <button type="button" class="mg-round" class:on={chrome.quickLog.open} onclick={quickLog}
                aria-label="Quick log" title="Quick log">
          <Icon name="pencil" size={18} />
        </button>

        <button type="button" class="mg-round" class:on={chat.open} onclick={toggleChat} aria-expanded={chat.open}
                data-testid="chat-launcher" aria-label={badge.label} title="Team chat">
          <Icon name="message" size={18} />
          {#if badge.show}<i class="count" class:mention={badge.kind === 'mention'} data-testid="chat-badge"
                              data-kind={badge.kind} aria-hidden="true">{badge.txt}</i>{/if}
        </button>

        <AccountButton />
      </div>
    </div>
  </header>
{/if}

<style>
  .strip {
    position: sticky; top: 0; z-index: 40;
    padding-top: var(--sat); padding-left: var(--sal); padding-right: var(--sar);
    background: var(--mc-glass-strong);
    -webkit-backdrop-filter: blur(var(--mc-blur)) saturate(150%); backdrop-filter: blur(var(--mc-blur)) saturate(150%);
    border-bottom: 1px solid var(--mc-glass-line);
  }
  .in { display: flex; align-items: center; gap: 8px; height: var(--mc-strip-h); padding: 0 12px 0 16px; min-width: 0; overflow: hidden; }

  .link { display: inline-flex; flex: none; }
  .when { display: flex; flex-direction: column; justify-content: center; gap: 2px; min-width: 0; flex: 0 1 auto; }
  .day { font: 500 11.5px/1.15 var(--mc-font); color: var(--mc-ink2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .day .short { display: none; }
  .clock { font: 300 21px/1 var(--mc-font); letter-spacing: -0.01em; color: #fff; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .gap { flex: 1; min-width: 4px; }

  .readout { display: inline-flex; align-items: baseline; gap: 10px; min-width: 0; max-width: 42vw; font: 500 12px/1 var(--mc-font); color: var(--mc-ink3); white-space: nowrap; }
  .st { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .hot { flex: none; }
  .st.ok { color: var(--mc-accent); font-weight: 600; }
  .st.warn { color: var(--mc-warn); font-weight: 600; }
  .st.crit { color: var(--mc-crit); font-weight: 600; }
  .hot b { color: var(--mc-crit); font-weight: 600; }
  a.readout:hover .st { text-decoration: underline; text-underline-offset: 3px; }

  .btns { display: flex; align-items: center; gap: 8px; flex: none; }
  .count {
    position: absolute; top: -3px; right: -3px; min-width: 16px; height: 16px; padding: 0 4px;
    display: inline-flex; align-items: center; justify-content: center; border-radius: 9999px;
    background: #3a3a42; color: var(--mc-ink); border: 2px solid var(--mc-bg);
    font: 700 9.5px/1 var(--mc-font); font-style: normal; font-variant-numeric: tabular-nums;
  }
  .count.mention { background: var(--mc-accent); color: var(--mc-accent-ink); }

  /* the scene's slim strip: just the dot and what is happening */
  .scene .in { justify-content: center; }
  .slim { display: inline-flex; align-items: center; gap: 10px; min-width: 0; max-width: 100%; font: 500 12.5px/1 var(--mc-font); color: var(--mc-ink2); white-space: nowrap; }
  .slim:hover .st { text-decoration: underline; text-underline-offset: 3px; }

  /* a phone: the readout steps aside (the dot still says it) unless a crawl
     runs, the date goes short, the gaps tighten — four round buttons and
     the clock fit 390px */
  @media (max-width: 480px) {
    .in { gap: 6px; padding: 0 10px 0 14px; }
    .btns { gap: 4px; }
    .hot { display: none; }
    .readout { display: none; }
    .busy .readout { display: inline-flex; max-width: 24vw; }
  }
  @media (max-width: 420px) {
    .day .long { display: none; }
    .day .short { display: inline; }
    .clock { font-size: 20px; }
    /* a page posted its own buttons: the clock alone holds the left */
    .crowded .day { display: none; }
    .crowded .btns { gap: 2px; }
  }

  /* a wide screen: roomier sides */
  @media (min-width: 1024px) {
    .in { padding: 0 20px 0 24px; gap: 10px; }
  }
</style>
