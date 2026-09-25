<script>
  /* Team chat, everywhere: the floating launcher (bottom-right, clear of the
     dock on a phone / upright iPad and of the rail on a desktop) and the
     sheet it opens. The strip's chat button toggles the same sheet.

     The sheet is ONE blurred rectangle — nothing inside it carries a
     backdrop-filter of its own. From 720px it is a panel: channels on the
     left (240px), the conversation on the right. Below that it is a
     near-full-screen sheet: a scrolling row of channel pills on top, the
     thread, the composer pinned at the foot — and kept above the iOS
     keyboard by following window.visualViewport.

     It steps aside while something else owns the screen's edge (the prospect
     drawer, the crawl slide-over); "Discuss" in the drawer closes the drawer
     on its way here. Escape closes a picker or menu first, then the sheet.

     State and polling live in chat.svelte.js; docs/CHAT.md is the contract
     (including every data-testid used here). */
  import { tick } from 'svelte';
  import { slide } from '$lib/motion.js';
  import { app } from '$lib/state.svelte.js';
  import { chat, openChat, closeChat, channelById, resumeChat } from '$lib/chat.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import ChannelList from './chat/ChannelList.svelte';
  import Thread from './chat/Thread.svelte';
  import Composer from './chat/Composer.svelte';
  import MentionsList from './chat/MentionsList.svelte';

  const blocked = $derived(!!app.selectedKey || app.runOpen);
  const show = $derived(!blocked);

  const badgeKind = $derived(chat.mentions > 0 ? 'mention' : 'plain');
  const badgeN = $derived(chat.mentions > 0 ? chat.mentions : chat.unread);
  const badgeTxt = $derived(badgeN > 99 ? '99+' : String(badgeN));

  const active = $derived(chat.active != null ? channelById(chat.active) : null);
  const title = $derived(chat.view === 'mentions' ? 'Mentions'
    : active ? (active.kind === 'property' ? active.property?.label || active.name : '#' + active.name) : 'Team chat');
  const subtitle = $derived(chat.view === 'mentions' ? 'Where you were @-mentioned'
    : active?.kind === 'property' ? [active.property?.suburb, 'property channel'].filter(Boolean).join(' · ')
    : active?.kind === 'general' ? 'Everyone on the team' : active ? 'Topic' : '');

  /* back on screen after the drawer / crawl panel: fast cadence again */
  let wasShown = true;
  $effect(() => {
    const on = show;
    if (on && !wasShown && chat.open) resumeChat();
    wasShown = on;
  });

  /* ——— the two shapes ——— */
  let wide = $state(true);
  $effect(() => {
    const mq = matchMedia('(min-width: 720px)');
    const sync = () => (wide = mq.matches);
    sync();
    mq.addEventListener('change', sync);
    return () => mq.removeEventListener('change', sync);
  });

  /* ——— the iOS keyboard: follow the visual viewport ——— */
  let kb = $state(0);      // px the keyboard (or anything) covers at the bottom
  let vvt = $state(0);     // the visual viewport's offset from the top
  let vvh = $state(0);
  $effect(() => {
    if (!(show && chat.open)) return;
    const vv = window.visualViewport;
    if (!vv) return;
    const measure = () => {
      const cover = Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop));
      kb = cover > 60 ? cover : 0;     // ignore toolbar wobble; a keyboard is tall
      vvt = Math.max(0, Math.round(vv.offsetTop));
      vvh = Math.round(vv.height);
    };
    measure();
    vv.addEventListener('resize', measure);
    vv.addEventListener('scroll', measure);
    return () => {
      vv.removeEventListener('resize', measure);
      vv.removeEventListener('scroll', measure);
      kb = 0;
      vvt = 0;
    };
  });

  /* A phone sheet covers the page, so the page behind must not scroll
     under a thumb that misses the thread. */
  $effect(() => {
    if (!(show && chat.open) || wide) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  });

  /* Opening lands with the composer focused on a keyboard device (a phone
     would throw its keyboard up over the thread you came to read). */
  let composer = $state(null);
  $effect(() => {
    if (!(show && chat.open)) return;
    const fine = matchMedia('(pointer: fine)').matches;
    tick().then(() => { if (fine) composer?.focus?.(); });
  });

  function onWindowKey(e) {
    if (e.key !== 'Escape' || !show || !chat.open) return;
    if (chat.overlay) {
      chat.overlay = '';
      e.preventDefault();
      return;
    }
    closeChat();
  }

  /* A tap outside an open menu closes it (not a picker or form, which close
     on Escape, Cancel or a pick). */
  function onWindowClick(e) {
    const o = chat.overlay;
    if (!o || !(o === 'attach' || o.startsWith('msg:'))) return;
    const t = e.target;
    if (t?.closest?.('[role="menu"], [data-testid="chat-attach"], [data-testid="chat-msg-actions"]')) return;
    chat.overlay = '';
  }
</script>

<svelte:window onkeydown={onWindowKey} onclick={onWindowClick} />

{#if show && !chat.open}
  <button type="button" class="launcher" data-testid="chat-launcher" onclick={openChat}
          aria-label={`Open team chat${chat.mentions ? `, ${chat.mentions} mention${chat.mentions === 1 ? '' : 's'}` : chat.unread ? `, ${chat.unread} unread` : ''}`}
          title="Team chat">
    <Icon name="chat" size={22} stroke={1.9} />
    {#if badgeN > 0}
      <i class="badge" class:mention={badgeKind === 'mention'} data-testid="chat-badge" data-kind={badgeKind}
         aria-hidden="true">{badgeTxt}</i>
    {/if}
  </button>
{/if}

{#if show && chat.open}
  <div class="sheet" class:wide class:kb={kb > 0} data-testid="chat-sheet" role="dialog" aria-label="Team chat"
           style:--kb="{kb}px" style:--vvt="{vvt}px" style:--vvh="{vvh}px"
           transition:slide={wide ? { y: 24, duration: 260 } : { y: 520, duration: 300, opacity: 1 }}>
    <header class="phead">
      <span class="mark" aria-hidden="true"><Icon name={chat.view === 'mentions' ? 'bell' : 'chat'} size={16} /></span>
      <div class="who">
        <b>{title}</b>
        {#if subtitle}<span class="sub">{subtitle}</span>{/if}
      </div>
      <button type="button" class="mg-btn secondary icon sm close" data-testid="chat-close" onclick={closeChat}
              title="Close (Esc)" aria-label="Close team chat">
        <Icon name="close" size={15} />
      </button>
    </header>

    {#if chat.syncError}
      <div class="mg-strip warn err" role="status">
        <span class="ic"><Icon name="refresh" size={14} /></span><span>Reconnecting — {chat.syncError}</span>
      </div>
    {/if}

    <div class="body">
      {#if wide}
        <aside class="side"><ChannelList /></aside>
      {:else}
        <ChannelList compact />
      {/if}

      <div class="conv">
        {#if chat.view === 'mentions'}
          <MentionsList />
        {:else if active}
          {#key active.id}
            <Thread channelId={active.id} />
            {#if chat.error}
              <div class="mg-strip crit err" role="alert">
                <span class="ic"><Icon name="alert" size={14} /></span><span>{chat.error}</span>
                <button type="button" class="x" onclick={() => (chat.error = '')} aria-label="Dismiss"><Icon name="close" size={12} /></button>
              </div>
            {/if}
            <Composer channelId={active.id} bind:this={composer} />
          {/key}
        {:else}
          <div class="mg-empty idle">
            {#if !chat.ready}
              <span class="mg-spin"></span>
            {:else}
              <span class="ic"><Icon name={chat.error ? 'alert' : 'chat'} size={20} /></span>
              <h3>{chat.error ? 'Chat is unavailable' : 'Pick a channel'}</h3>
              {#if chat.error}<p>{chat.error}</p>{/if}
            {/if}
          </div>
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  /* ——— the launcher ——— */
  .launcher {
    position: fixed; z-index: 55;
    right: calc(16px + var(--sar)); bottom: calc(var(--mc-dock-h) + var(--sab) + 16px);
    width: 56px; height: 56px; border-radius: 50%;
    display: grid; place-items: center; cursor: pointer;
    background: var(--mc-glass-strong); color: var(--mc-ink);
    border: 1px solid var(--mc-glass-line2);
    box-shadow: var(--mc-sh-3), var(--mc-lit);
    -webkit-backdrop-filter: blur(var(--mc-blur)) saturate(150%); backdrop-filter: blur(var(--mc-blur)) saturate(150%);
    transition: transform 120ms var(--mc-ease), background var(--mc-t-fast), border-color var(--mc-t-fast);
  }
  .launcher:hover { background: rgba(30, 30, 36, 0.86); border-color: var(--mc-line3); }
  .launcher:active { transform: scale(0.95); }
  @media (min-width: 1024px) {
    .launcher { right: calc(24px + var(--sar)); bottom: calc(24px + var(--sab)); }
  }
  .badge {
    position: absolute; top: -3px; right: -3px; min-width: 22px; height: 22px; padding: 0 6px;
    border-radius: 9999px; display: grid; place-items: center;
    font: 700 11.5px/1 var(--mc-font); font-style: normal; font-variant-numeric: tabular-nums;
    background: #3a3a42; color: var(--mc-ink); border: 2px solid var(--mc-bg);
  }
  .badge.mention { background: var(--mc-accent); color: var(--mc-accent-ink); }

  /* ——— the sheet: a phone first ——— */
  .sheet {
    position: fixed; z-index: 75;
    left: 0; right: 0; top: calc(var(--sat) + 8px); bottom: 0;
    display: flex; flex-direction: column; overflow: hidden;
    padding-bottom: var(--sab);
    /* denser than the shared glass: a thread is text you read, and the page
       (or the dock on a phone) must never ghost through it */
    background: rgba(16, 16, 20, 0.985);
    border: 1px solid var(--mc-glass-line); border-bottom: 0;
    border-radius: var(--mc-r-lg) var(--mc-r-lg) 0 0;
    box-shadow: var(--mc-sh-3), var(--mc-lit);
    -webkit-backdrop-filter: blur(var(--mc-blur)) saturate(150%); backdrop-filter: blur(var(--mc-blur)) saturate(150%);
  }
  /* the keyboard is up: sit between the top of the visible area and it */
  .sheet.kb:not(.wide) {
    top: calc(var(--vvt) + 6px); bottom: var(--kb); padding-bottom: 0;
    border-radius: var(--mc-r-lg);
  }

  /* from 720px: a panel, bottom-right, clear of the dock */
  .sheet.wide {
    left: auto; top: auto; right: 16px;
    bottom: calc(var(--mc-dock-h) + var(--sab) + 12px);
    width: min(760px, calc(100vw - 32px));
    height: min(660px, calc(100dvh - var(--sat) - var(--mc-strip-h) - var(--mc-dock-h) - var(--sab) - 28px));
    padding-bottom: 0;
    border-bottom: 1px solid var(--mc-glass-line); border-radius: var(--mc-r-lg);
  }
  .sheet.wide.kb { bottom: calc(var(--kb) + 12px); max-height: calc(var(--vvh) - 24px); }
  /* from 1024px the dock is gone and the rail is on the left */
  @media (min-width: 1024px) {
    .sheet.wide {
      right: 20px; bottom: calc(var(--sab) + 20px);
      width: min(780px, calc(100vw - var(--mc-rail-w) - 40px));
      height: min(680px, calc(100dvh - var(--sat) - var(--mc-strip-h) - 40px));
    }
  }

  /* ——— header ——— */
  .phead {
    flex: none; display: flex; align-items: center; gap: 10px;
    padding: 8px 10px 8px 14px; min-height: 54px;
    border-bottom: 1px solid var(--mc-line);
  }
  .mark {
    flex: none; display: grid; place-items: center; width: 32px; height: 32px;
    border-radius: 10px; background: var(--mc-surface); border: 1px solid var(--mc-line); color: var(--mc-ink2);
  }
  .who { flex: 1; min-width: 0; display: flex; flex-direction: column; line-height: 1.3; }
  .who b { font: 600 14.5px/1.3 var(--mc-font); letter-spacing: -0.01em; color: var(--mc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sub { font: 400 12px/1.35 var(--mc-font); color: var(--mc-ink3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  /* ——— body ——— */
  .body { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  .wide .body { flex-direction: row; }
  .side {
    flex: none; width: 240px; min-height: 0; display: flex; flex-direction: column;
    border-right: 1px solid var(--mc-line);
  }
  .conv { position: relative; flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; }
  .idle { margin: auto; padding: 24px; }

  .err { flex: none; margin: 6px 10px 0; padding: 8px 10px; align-items: center; }
  .err .x {
    margin-left: auto; flex: none; width: 24px; height: 24px; border: 0; border-radius: 50%;
    display: grid; place-items: center; background: none; color: inherit; cursor: pointer;
  }

  @media (pointer: coarse) {
    .close { width: 44px; height: 44px; }
    .err .x { width: 36px; height: 36px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .launcher, .launcher:active { transition: none; transform: none; }
  }
</style>
