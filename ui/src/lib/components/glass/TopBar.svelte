<script>
  /* The top of the scene: what time it is, and what the app is doing.

     Left: today's date over a big light clock (Inter 200, tabular, so it
     never jitters). Right: the status pill, then round glass buttons —
     whatever the current page posted into `shell.actions`, then anything the
     layout passed as children, then the permanent three: team chat, search
     (on Media, where there is a search page to go to) and home.

     It is drawn ONCE, by routes/+layout.svelte, for every route. Pages never
     draw their own — they post to `$lib/shell.svelte.js` instead.

     Props:
       children   optional snippet rendered between the page's own buttons
                  and the permanent ones. Use it for round `.mg-btn.icon`
                  buttons only; anything wider belongs in the pane's header.

     The clock ticks every 15s: a clock that is wrong is worse than no clock,
     and one that ticks every second is a battery bill for a digit nobody
     reads. */
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { app } from '$lib/state.svelte.js';
  import { shell, engineStatus } from '$lib/shell.svelte.js';
  import { can } from '$lib/me.svelte.js';
  import { chat, toggleChat } from '$lib/chat.svelte.js';
  import Icon from './Icon.svelte';
  import StatusPill from './StatusPill.svelte';

  let { children } = $props();

  let now = $state(new Date());
  onMount(() => {
    const t = setInterval(() => (now = new Date()), 15000);
    return () => clearInterval(t);
  });

  const p2 = (n) => String(n).padStart(2, '0');
  const clock = $derived(`${p2(now.getHours())}:${p2(now.getMinutes())}`);
  const date = $derived(
    now.toLocaleDateString('en-ZA', { weekday: 'long', day: 'numeric', month: 'long' })
  );

  const path = $derived(page.url.pathname);
  /* The library's search button only makes sense for someone who can open
     the library; the Dock hides the section itself the same way. */
  const onMedia = $derived(path.startsWith('/media') && can('media'));

  /* A section's own status wins; with nothing posted the pill falls back to
     the engine, which is the one thing that is true on every page. */
  const status = $derived(shell.status || engineStatus(app.status));
  const unread = $derived(chat.unread > 9 ? '9+' : String(chat.unread));
</script>

<header>
  <div class="when">
    <div class="date">{date}</div>
    <div class="clock mg-tnum">{clock}</div>
  </div>

  <div class="tools">
    <StatusPill
      tone={status.tone}
      label={status.label}
      ping={!!status.ping}
      title={status.title}
      href={status.href} />

    {#each shell.actions as a (a.id)}
      {#if a.href}
        <a class="mg-btn secondary icon" href={a.href} aria-label={a.label} title={a.label}>
          <Icon name={a.icon} size={18} />
        </a>
      {:else}
        <button type="button" class="mg-btn secondary icon" onclick={a.onclick}
                aria-label={a.label} title={a.label}>
          <Icon name={a.icon} size={18} />
        </button>
      {/if}
    {/each}

    {#if children}{@render children()}{/if}

    <!-- the team's own line; the panel it opens lives in ChatWidget -->
    <button type="button" class="mg-btn secondary icon chat" class:on={chat.open}
            onclick={toggleChat} aria-expanded={chat.open}
            aria-label={chat.open ? 'Close team chat' : `Open team chat${chat.unread ? ` (${chat.unread} unread)` : ''}`}
            title="Team chat">
      <Icon name="message" size={18} />
      {#if chat.unread && !chat.open}<i class="count" aria-hidden="true">{unread}</i>{/if}
    </button>

    {#if onMedia}
      <a class="mg-btn secondary icon" href="/media/search" aria-label="Search the library" title="Search">
        <Icon name="search" size={18} />
      </a>
    {/if}

    <!-- Passkeys and signed-in devices. A permanent button rather than a dock
         section: it is where you go twice a year, not twice an hour. -->
    <a class="mg-btn secondary icon" class:on={path.startsWith('/account')}
       href="/account" aria-label="Account" title="Account">
      <Icon name="user" size={18} />
    </a>

    {#if path !== '/'}
      <a class="mg-btn secondary icon home" href="/" aria-label="Home" title="Home">
        <Icon name="home" size={18} />
      </a>
    {/if}
  </div>
</header>

<style>
  header {
    position: relative; z-index: 30;
    display: flex; align-items: flex-start; gap: 16px;
    padding: calc(var(--mg-sat) + 18px) clamp(16px, 3vw, 32px) 10px;
    max-width: 1400px; margin: 0 auto; width: 100%;
    animation: mg-fadeup 0.32s cubic-bezier(0.2, 0.8, 0.2, 1) both;
  }
  .when { min-width: 0; }
  .date { font: 500 13px/1.3 var(--mg-font); color: var(--mg-i2); }
  .clock { margin-top: 2px; font: 200 30px/1 var(--mg-font); letter-spacing: -0.02em; color: var(--mg-i); }

  .tools {
    margin-left: auto; flex: none; padding-top: 2px;
    display: flex; align-items: center; gap: 8px;
  }

  .chat { position: relative; }
  .chat.on, .mg-btn.on { background: var(--mg-glass-hover); border-color: var(--mg-line2); }
  .count {
    position: absolute; top: -3px; right: -3px;
    min-width: 18px; height: 18px; padding: 0 5px;
    display: inline-flex; align-items: center; justify-content: center;
    border-radius: 9999px; background: var(--mg-crit); color: #fff;
    border: 2px solid rgba(17, 17, 19, 0.9);
    font: 700 10px/1 var(--mg-font); font-style: normal; font-variant-numeric: tabular-nums;
  }

  @media (min-width: 720px) {
    .clock { font-size: 44px; }
    .date { font-size: 15px; }
  }
  /* A phone's top bar keeps the clock, the pill's dot and the two buttons a
     thumb actually reaches; Home is one tap away on the dock anyway. */
  @media (max-width: 560px) {
    .tools { gap: 6px; }
    .home { display: none; }
  }
  @media (prefers-reduced-motion: reduce) {
    header { animation: none; }
  }
</style>
