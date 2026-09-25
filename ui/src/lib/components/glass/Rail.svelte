<script>
  /* The iPad / desktop rail (from 1024px): brand + link state, the sections
     as a vertical list, and the actions that must always be in reach — the
     primary action and the signed-in account. Fixed to the left edge; the
     layout pads the page to clear it. Hidden below 1024px, where the Dock
     takes over.

     Sections added with `addNav()` (shell.svelte.js) appear after the
     built-in six. */
  import { page } from '$app/state';
  import Icon from './Icon.svelte';
  import PrimaryButton from './PrimaryButton.svelte';
  import { app } from '$lib/state.svelte.js';
  import { shell, slots, engineStatus, SECTIONS, inSection } from '$lib/shell.svelte.js';
  import { me, can } from '$lib/me.svelte.js';

  const ITEMS = $derived([...SECTIONS, ...slots.nav].filter((it) => !it.need || can(it.need)));
  const path = $derived(page.url.pathname);
  const active = $derived(ITEMS.reduce((best, it) => (inSection(it.href, path) ? it.href : best), null));
  const status = $derived(shell.status || engineStatus(app.status));
  const who = $derived(me.display_name || me.username || 'Signed in');
  const initial = $derived((who[0] || 'O').toUpperCase());
</script>

<aside class="rail">
  <div class="brand">
    <span class="mg-dot {status.tone === 'off' ? '' : status.tone}">{#if status.ping}<i class="mg-ping"></i>{/if}</span>
    <a class="name" href="/">Oblivion</a>
    <span class="st mg-tnum" title={status.title || status.label}>{status.label}</span>
  </div>

  <nav class="nav" aria-label="Sections">
    {#each ITEMS as it (it.href)}
      <a href={it.href} class:on={it.href === active} aria-current={it.href === active ? 'page' : undefined}>
        <Icon name={it.icon} size={17} stroke={it.href === active ? 2 : 1.8} />
        <span>{it.label}</span>
      </a>
    {/each}
    <a href="/cma" class="ext">
      <Icon name="list" size={17} stroke={1.8} />
      <span>CMA reports</span>
      <Icon name="external" size={13} class="ext-ic" />
    </a>
  </nav>

  <div class="foot">
    <PrimaryButton wide />
    <a class="acct" href="/account" class:on={path.startsWith('/account')} title="Account">
      <span class="av">{initial}</span>
      <span class="t">
        <b>{who}</b>
        <span>{me.is_owner ? 'Owner' : me.role || 'Member'} · {me.passkeys ? `${me.passkeys} passkey${me.passkeys === 1 ? '' : 's'}` : 'no passkey'}</span>
      </span>
      <Icon name="settings" size={16} />
    </a>
  </div>
</aside>

<style>
  .rail {
    display: none;
    position: fixed; left: 0; top: 0; bottom: 0; z-index: 45;
    width: var(--mc-rail-w);
    flex-direction: column;
    padding: var(--sat) 0 0;
    background: var(--mc-glass);
    border-right: 1px solid var(--mc-glass-line);
    -webkit-backdrop-filter: blur(var(--mc-blur)) saturate(150%); backdrop-filter: blur(var(--mc-blur)) saturate(150%);
  }
  @media (min-width: 1024px) { .rail { display: flex; } }

  .brand { display: flex; align-items: center; gap: 10px; padding: 16px 16px 12px; }
  .name { font: 600 15px/1 var(--mc-font); letter-spacing: -0.01em; color: var(--mc-ink); }
  .st { margin-left: auto; font: 500 11px/1 var(--mc-font); color: var(--mc-ink3); max-width: 40%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .nav { display: flex; flex-direction: column; gap: 2px; margin: 0 12px; padding-top: 10px; border-top: 1px solid var(--mc-line); min-height: 0; overflow-y: auto; }
  .nav a {
    display: flex; align-items: center; gap: 10px; height: 40px; padding: 0 12px; border-radius: 12px;
    color: var(--mc-ink2); font: 500 13.5px/1 var(--mc-font);
    transition: background var(--mc-t-fast), color var(--mc-t-fast);
  }
  .nav a:hover { background: rgba(255, 255, 255, 0.07); color: var(--mc-ink); }
  .nav a.on { background: var(--mc-glass-on); color: var(--mc-ink); }
  .nav a.ext { margin-top: 8px; color: var(--mc-ink3); }
  .nav a.ext :global(.ext-ic) { margin-left: auto; opacity: 0.7; }

  .foot { margin-top: auto; display: flex; flex-direction: column; gap: 8px; padding: 10px 12px calc(10px + var(--sab)); border-top: 1px solid var(--mc-line); }
  .acct {
    display: flex; align-items: center; gap: 10px; min-height: 48px; padding: 6px 8px; border-radius: 14px;
    color: var(--mc-ink3); transition: background var(--mc-t-fast);
  }
  .acct:hover, .acct.on { background: rgba(255, 255, 255, 0.07); }
  .av {
    flex: none; width: 30px; height: 30px; border-radius: 9999px; display: grid; place-items: center;
    background: var(--mc-glass-soft); border: 1px solid var(--mc-glass-line); color: var(--mc-ink);
    font: 600 12px/1 var(--mc-font);
  }
  .t { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }
  .t b { font: 600 13px/1.3 var(--mc-font); color: var(--mc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .t span { font: 400 11px/1.3 var(--mc-font); color: var(--mc-ink3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
