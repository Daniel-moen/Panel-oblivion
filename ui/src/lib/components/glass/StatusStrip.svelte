<script>
  /* The strip along the top of every route: link state, where you are,
     what the app is doing, and the buttons that must always be in reach.

     On a phone it carries the brand; from 1024px the Rail has the brand and
     the strip shows the section's name instead. It is sticky and slightly
     translucent, exactly like the panel's header.

     Right-hand cluster, left to right: the page's own posted actions
     (`shell.actions`), team chat (with the unread count), library search
     (on Media), account, and — on a phone only — the primary action.

     Drawn ONCE, by routes/+layout.svelte. Pages never draw their own; they
     post to `$lib/shell.svelte.js` instead. */
  import { page } from '$app/state';
  import { app } from '$lib/state.svelte.js';
  import { shell, slots, engineStatus, SECTIONS, inSection } from '$lib/shell.svelte.js';
  import { can } from '$lib/me.svelte.js';
  import { chat, toggleChat } from '$lib/chat.svelte.js';
  import Icon from './Icon.svelte';
  import PrimaryButton from './PrimaryButton.svelte';

  const path = $derived(page.url.pathname);
  const onMedia = $derived(path.startsWith('/media') && can('media'));
  const here = $derived(
    [...SECTIONS, ...slots.nav].reduce((best, s) => (inSection(s.href, path) ? s : best), null)
  );
  const title = $derived(path.startsWith('/account') ? 'Account' : here?.label || 'Oblivion');

  /* A section's own status wins; with nothing posted the readout falls back
     to the engine, which is the one thing that is true on every page. */
  const status = $derived(shell.status || engineStatus(app.status));
  const hot = $derived(app.prospects.reduce((n, r) => n + (r.tier === 'hot' ? 1 : 0), 0));
  const unread = $derived(chat.unread > 9 ? '9+' : String(chat.unread));
</script>

<header class="strip">
  <div class="in">
    <span class="link" aria-hidden="true">
      <span class="mg-dot {status.tone === 'off' ? '' : status.tone}">{#if status.ping}<i class="mg-ping"></i>{/if}</span>
    </span>
    <a class="brand" href="/" aria-label="Home">Oblivion</a>
    <span class="where">{title}</span>

    <span class="gap"></span>

    <!-- compact status readout -->
    {#if status.href}
      <a class="readout mg-tnum" href={status.href} title={status.title || status.label}>
        <span class="st {status.tone}">{status.label}</span>
      </a>
    {:else}
      <span class="readout mg-tnum" title={status.title || status.label}>
        <span class="st {status.tone}">{status.label}</span>
        {#if hot && !app.status.running}<span class="hot"><b>{hot}</b> hot</span>{/if}
      </span>
    {/if}

    {#each shell.actions as a (a.id)}
      {#if a.href}
        <a class="ib" href={a.href} aria-label={a.label} title={a.label}><Icon name={a.icon} size={18} /></a>
      {:else}
        <button type="button" class="ib" onclick={a.onclick} aria-label={a.label} title={a.label}>
          <Icon name={a.icon} size={18} />
        </button>
      {/if}
    {/each}

    <button type="button" class="ib" class:on={chat.open} onclick={toggleChat} aria-expanded={chat.open}
            aria-label={chat.open ? 'Close team chat' : `Open team chat${chat.unread ? ` (${chat.unread} unread)` : ''}`}
            title="Team chat">
      <Icon name="message" size={18} />
      {#if chat.unread && !chat.open}<i class="count" aria-hidden="true">{unread}</i>{/if}
    </button>

    {#if onMedia}
      <a class="ib" href="/media/search" aria-label="Search the library" title="Search"><Icon name="search" size={18} /></a>
    {/if}

    <a class="ib" class:on={path.startsWith('/account')} href="/account" aria-label="Account" title="Account">
      <Icon name="user" size={18} />
    </a>

    <span class="phone-go"><PrimaryButton /></span>
  </div>
</header>

<style>
  .strip {
    position: sticky; top: 0; z-index: 40;
    padding-top: var(--sat);
    background: var(--mc-glass-strong);
    -webkit-backdrop-filter: blur(var(--mc-blur)) saturate(150%); backdrop-filter: blur(var(--mc-blur)) saturate(150%);
    border-bottom: 1px solid var(--mc-glass-line);
  }
  .in { display: flex; align-items: center; gap: 6px; height: var(--mc-strip-h); padding: 0 12px 0 16px; min-width: 0; overflow: hidden; }

  .link { display: inline-flex; margin-right: 4px; }
  .brand { font: 600 15px/1 var(--mc-font); letter-spacing: -0.01em; color: var(--mc-ink); }
  .where { display: none; font: 600 15px/1 var(--mc-font); letter-spacing: -0.01em; color: var(--mc-ink); }
  .gap { flex: 1; min-width: 4px; }

  .readout { display: inline-flex; align-items: baseline; gap: 10px; margin-right: 4px; min-width: 0; max-width: 42vw; font: 500 12px/1 var(--mc-font); color: var(--mc-ink3); white-space: nowrap; }
  .st { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .hot { flex: none; }
  .st.ok { color: var(--mc-accent); font-weight: 600; }
  .st.warn { color: var(--mc-warn); font-weight: 600; }
  .st.crit { color: var(--mc-crit); font-weight: 600; }
  .hot b { color: var(--mc-crit); font-weight: 600; }
  a.readout:hover .st { text-decoration: underline; text-underline-offset: 3px; }

  .ib {
    position: relative; flex: none; width: 40px; height: 40px; border: 0; border-radius: 9999px; padding: 0;
    display: grid; place-items: center; background: none; color: var(--mc-ink3); cursor: pointer;
    transition: background var(--mc-t-fast), color var(--mc-t-fast);
  }
  .ib:hover { background: rgba(255, 255, 255, 0.08); color: var(--mc-ink2); }
  .ib.on { background: var(--mc-glass-on); color: var(--mc-ink); }
  .count {
    position: absolute; top: 4px; right: 4px; min-width: 16px; height: 16px; padding: 0 4px;
    display: inline-flex; align-items: center; justify-content: center; border-radius: 9999px;
    background: var(--mc-crit); color: #fff; border: 2px solid var(--mc-bg);
    font: 700 9.5px/1 var(--mc-font); font-style: normal; font-variant-numeric: tabular-nums;
  }
  .phone-go { display: inline-flex; margin-left: 4px; }

  @media (max-width: 480px) {
    .hot { display: none; }
    .readout { max-width: 34vw; }
  }
  @media (pointer: coarse) { .ib { width: 44px; height: 44px; } .in { gap: 2px; } }

  /* from the rail breakpoint the brand moves into the rail */
  @media (min-width: 1024px) {
    .brand, .link { display: none; }
    .where { display: inline; }
    .phone-go { display: none; }
    .in { padding: 0 20px 0 24px; }
  }
</style>
