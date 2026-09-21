<script>
  /* Team chat, everywhere. A small floating button in the bottom-right corner
     of every page; click it and the team's conversation opens in a compact
     panel above it. Agents talking to each other — a "who's taking the
     Blouberg valuation?" line, not a question for the AI. Agent Z is its own
     page and its own thread.

     It stays out of the way only when something else already owns the right
     edge: the prospect drawer or the crawl slide-over. Unlike Z's old
     launcher it does NOT hide on /agent — a chat you can't reach from one
     page is a chat nobody trusts.

     No accounts exist on this dashboard, so the first thing the panel asks
     for is a name; after that it's remembered in this browser and editable
     from the header. */
  import { tick, untrack } from 'svelte';
  import { app } from '$lib/state.svelte.js';
  import { chat, say, setName, closeChat, toggleChat } from '$lib/chat.svelte.js';

  const blocked = $derived(!!app.selectedKey || app.runOpen);
  const show = $derived(!blocked);
  const named = $derived(!!chat.me);

  let text = $state('');
  let draftName = $state('');
  let editing = $state(false);
  let box = $state(null);        // composer textarea
  let nameBox = $state(null);    // the name input, whichever one is showing
  let scroller = $state(null);
  let atBottom = $state(true);
  let hasNew = $state(false);
  let seen = 0;                  // messages length we have already reacted to

  /* ——— the list, with its day dividers and sender grouping worked out
         once rather than inside the markup ——— */
  const DAY = { weekday: 'short', day: 'numeric', month: 'short' };

  function when(at) {
    const d = new Date(at);
    return isNaN(d) ? null : d;
  }
  function hhmm(at) {
    const d = when(at);
    return d ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : '';
  }
  function dayKey(at) {
    const d = when(at);
    return d ? d.toDateString() : '';
  }
  function dayLabel(at) {
    const d = when(at);
    if (!d) return '';
    const today = new Date();
    const yest = new Date(today);
    yest.setDate(today.getDate() - 1);
    if (d.toDateString() === today.toDateString()) return 'Today';
    if (d.toDateString() === yest.toDateString()) return 'Yesterday';
    return d.toLocaleDateString([], DAY);
  }
  function initials(name) {
    const parts = (name || '?').trim().split(/\s+/).slice(0, 2);
    return parts.map((p) => p[0]).join('').toUpperCase() || '?';
  }

  const items = $derived.by(() => {
    const out = [];
    let day = null;
    let last = null;
    for (const m of chat.messages) {
      const k = dayKey(m.at);
      if (k !== day) {
        out.push({ divider: true, key: 'd' + m.id, label: dayLabel(m.at) });
        day = k;
        last = null;
      }
      const mine = m.sender === chat.me;
      out.push({ divider: false, key: m.id, m, mine, head: !mine && m.sender !== last });
      last = m.sender;
    }
    return out;
  });

  /* ——— scrolling ———
     Newest in view, unless they have scrolled up to read something — then a
     chip offers the trip down instead of yanking the list out from under
     them. */
  function jump(behavior = 'smooth') {
    if (!scroller) return;
    scroller.scrollTo({ top: scroller.scrollHeight, behavior });
    hasNew = false;
    atBottom = true;
  }

  function onScroll() {
    if (!scroller) return;
    atBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 60;
    if (atBottom) hasNew = false;
  }

  $effect(() => {
    const n = chat.messages.length;
    if (n === seen) return;
    const grew = n > seen;
    seen = n;
    if (!grew || !chat.open) return;
    tick().then(() => {
      if (atBottom) jump();
      else hasNew = true;
    });
  });

  /* Opening lands at the newest message, with no animation to sit through.
     Only the open/shut flag is a dependency here — untracked, or a message
     arriving would re-run this and yank a reader back down, which is exactly
     what the chip above exists to avoid. */
  $effect(() => {
    if (!chat.open) return;
    untrack(() => {
      seen = chat.messages.length;
      tick().then(() => {
        jump('auto');
        if (chat.me) box?.focus?.();
        else nameBox?.focus?.();
      });
    });
  });

  /* ——— composing ——— */
  async function send() {
    const q = text.trim();
    if (!q || chat.sending || !named) return;
    text = '';
    grow();
    atBottom = true;
    const ok = await say(q);
    if (!ok) text = q;          // put it back rather than lose it
    await tick();
    jump();
  }

  function onKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  function grow() {
    if (!box) return;
    box.style.height = 'auto';
    box.style.height = Math.min(box.scrollHeight, 110) + 'px';
  }

  function saveName() {
    if (!setName(draftName)) return;
    draftName = '';
    editing = false;
    tick().then(() => box?.focus?.());
  }

  /* Clicking away from the rename box keeps a real name and quietly drops an
     empty one — nobody meant to erase themselves. */
  function commitName() {
    if (draftName.trim()) saveName();
    else if (chat.me) editing = false;
  }

  function startEdit() {
    draftName = chat.me;
    editing = true;
    tick().then(() => nameBox?.select?.());
  }

  function onNameKey(e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      saveName();
    } else if (e.key === 'Escape' && editing) {
      e.stopPropagation();
      editing = false;
    }
  }

  function onWindowKey(e) {
    if (e.key === 'Escape' && chat.open && show) closeChat();
  }

  const badge = $derived(chat.unread > 9 ? '9+' : String(chat.unread));
</script>

<svelte:window onkeydown={onWindowKey} />

{#if show}
  <div class="dock" class:open={chat.open}>
    {#if chat.open}
      <section class="panel" aria-label="Team chat">
        <header class="phead">
          <span class="mark" aria-hidden="true">
            <svg viewBox="0 0 20 20" fill="none"><path
              d="M3.2 8.6c0-2.6 2.4-4.6 6.8-4.6s6.8 2 6.8 4.6-2.4 4.6-6.8 4.6c-.7 0-1.4-.05-2-.15L4.4 15.1l.5-2.3C3.8 12 3.2 10.4 3.2 8.6Z"
              stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
          </span>
          <div class="who">
            <b>Team chat</b>
            {#if editing}
              <input class="rename" bind:this={nameBox} bind:value={draftName}
                     maxlength="40" placeholder="Your name"
                     aria-label="Your display name"
                     onkeydown={onNameKey} onblur={commitName} />
            {:else if named}
              <span class="me">
                you're <b>{chat.me}</b>
                <button class="pencil" onclick={startEdit}
                        title="Change your name" aria-label="Change your name">✎</button>
              </span>
            {:else}
              <span class="me">say hello to the team</span>
            {/if}
          </div>
          <button class="ico" onclick={closeChat}
                  title="Close" aria-label="Close team chat">✕</button>
        </header>

        <div class="thread" bind:this={scroller} onscroll={onScroll}>
          {#if !chat.messages.length}
            <div class="empty">
              {#if !chat.ready}
                <span class="spin"></span>
              {:else}
                <p class="lead">Nothing said yet.</p>
                <p class="sub">This is the team's own line — who's taking a
                  valuation, who just got a mandate, who needs a photo before
                  five. Everyone on the dashboard sees it.</p>
              {/if}
            </div>
          {/if}

          {#each items as it (it.key)}
            {#if it.divider}
              <div class="day"><span>{it.label}</span></div>
            {:else}
              <div class="row" class:mine={it.mine} class:head={it.head}>
                {#if it.head}
                  <span class="avatar" aria-hidden="true">{initials(it.m.sender)}</span>
                {:else if !it.mine}
                  <span class="avatar ghost" aria-hidden="true"></span>
                {/if}
                <div class="said">
                  {#if it.head}<span class="from">{it.m.sender}</span>{/if}
                  <p class="bubble">{it.m.body}</p>
                  <time datetime={it.m.at}>{hhmm(it.m.at)}</time>
                </div>
              </div>
            {/if}
          {/each}
        </div>

        {#if hasNew}
          <button class="jump" onclick={() => jump()}>New messages ↓</button>
        {/if}

        {#if chat.error}
          <p class="err">{chat.error}</p>
        {/if}

        <div class="composer">
          {#if !named}
            <label class="ask" for="chat-name">What should the team call you?</label>
            <div class="field">
              <input id="chat-name" bind:this={nameBox} bind:value={draftName}
                     maxlength="40" placeholder="Duane" onkeydown={onNameKey} />
              <button class="btn primary send" onclick={saveName}
                      disabled={!draftName.trim()} aria-label="Save name">↑</button>
            </div>
          {:else}
            <div class="field">
              <textarea bind:this={box} bind:value={text} rows="1"
                        placeholder="Message the team…" aria-label="Message the team"
                        oninput={grow} onkeydown={onKey}></textarea>
              <button class="btn primary send" onclick={send}
                      disabled={!text.trim() || chat.sending} aria-label="Send">
                {#if chat.sending}<span class="spin light"></span>{:else}↑{/if}
              </button>
            </div>
          {/if}
        </div>
      </section>
    {/if}

    <button class="launch" class:on={chat.open}
            onclick={toggleChat}
            aria-expanded={chat.open}
            aria-label={chat.open ? 'Close team chat'
                                  : `Open team chat${chat.unread ? ` (${chat.unread} unread)` : ''}`}
            title={chat.open ? 'Close team chat' : 'Team chat'}>
      {#if chat.open}
        <span class="glyph" aria-hidden="true">✕</span>
      {:else}
        <svg class="bubble-ico" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M4 10.4C4 7.2 7.1 5 12 5s8 2.2 8 5.4-3.1 5.4-8 5.4c-.9 0-1.8-.08-2.6-.22L5.4 17.6l.7-3C4.8 13.6 4 12.1 4 10.4Z"
                stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
          <circle cx="9" cy="10.4" r="1.05" fill="currentColor"/>
          <circle cx="12" cy="10.4" r="1.05" fill="currentColor"/>
          <circle cx="15" cy="10.4" r="1.05" fill="currentColor"/>
        </svg>
      {/if}
      {#if chat.unread && !chat.open}
        <i class="count" aria-hidden="true">{badge}</i>
      {/if}
    </button>
  </div>
{/if}

<style>
  .dock {
    position: fixed; right: 1.25rem; bottom: 1.25rem; z-index: 1200;
    display: flex; flex-direction: column; align-items: flex-end; gap: 0.7rem;
  }

  /* ——— the launcher ——— */
  .launch {
    position: relative; width: 54px; height: 54px; border-radius: 50%;
    border: 0; padding: 0; color: #fff;
    display: inline-flex; align-items: center; justify-content: center;
    background: linear-gradient(140deg, var(--accent) 0%, var(--accent-2) 55%, var(--accent) 100%);
    background-size: 200% 200%;
    box-shadow: 0 6px 20px rgba(37, 99, 235, 0.38), 0 1px 3px rgba(16, 24, 40, 0.24);
    transition: transform 0.18s cubic-bezier(0.22, 0.68, 0.3, 1), box-shadow 0.18s;
    animation: drift 10s ease-in-out infinite;
  }
  .launch:hover { transform: translateY(-2px) scale(1.04);
                  box-shadow: 0 10px 28px rgba(37, 99, 235, 0.46), 0 1px 3px rgba(16, 24, 40, 0.26); }
  .launch:active { transform: translateY(0) scale(0.97); }
  .launch:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
  .bubble-ico { width: 26px; height: 26px; display: block; }
  .glyph { display: block; font-size: 1.05rem; font-weight: 600; line-height: 1; }
  @keyframes drift { 50% { background-position: 100% 50%; } }

  /* how many landed while the panel was shut */
  .count {
    position: absolute; top: -2px; right: -2px;
    min-width: 20px; height: 20px; padding: 0 5px;
    display: inline-flex; align-items: center; justify-content: center;
    border-radius: 999px; background: var(--hot); color: #fff;
    border: 2px solid var(--bg);
    font: 700 0.68rem/1 var(--font-ui); font-style: normal;
    font-variant-numeric: tabular-nums;
    animation: pop-in 0.26s cubic-bezier(0.22, 0.68, 0.3, 1) both;
  }
  @keyframes pop-in { from { transform: scale(0.4); opacity: 0; } to { transform: none; opacity: 1; } }

  /* ——— the panel ——— */
  .panel {
    position: relative;
    display: flex; flex-direction: column; overflow: hidden;
    width: 380px; max-width: calc(100vw - 2.5rem);
    height: min(60vh, 620px);
    background: color-mix(in srgb, var(--bg-2) 92%, transparent);
    backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
    border: 1px solid var(--line);
    border-radius: 18px; box-shadow: var(--shadow-2);
    transform-origin: bottom right;
    animation: pop 0.24s cubic-bezier(0.22, 0.68, 0.3, 1) both;
  }
  @keyframes pop { from { opacity: 0; transform: translateY(10px) scale(0.96); }
                   to { opacity: 1; transform: none; } }

  .phead {
    display: flex; align-items: center; gap: 0.6rem; flex: none;
    padding: 0.7rem 0.75rem 0.7rem 0.85rem;
    border-bottom: 1px solid var(--line);
    background: linear-gradient(180deg, var(--accent-soft), transparent);
  }
  .mark { flex: none; display: inline-flex; align-items: center; justify-content: center;
          width: 28px; height: 28px; border-radius: 9px; color: #fff;
          background: linear-gradient(140deg, var(--accent) 0%, var(--accent-2) 100%);
          box-shadow: 0 1px 6px rgba(37, 99, 235, 0.28); }
  .mark svg { width: 17px; height: 17px; }
  .who { flex: 1; min-width: 0; display: flex; flex-direction: column; line-height: 1.25; }
  .who > b { font-size: 0.86rem; font-weight: 700; letter-spacing: -0.01em; color: var(--ink); }
  .me { display: inline-flex; align-items: center; gap: 0.25rem;
        font-size: 0.72rem; color: var(--ink-3); min-width: 0; }
  .me b { font-weight: 600; color: var(--ink-2);
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pencil { border: 0; background: none; padding: 0 0.15rem; line-height: 1;
            color: var(--ink-3); font-size: 0.72rem;
            transition: color 0.15s; }
  .pencil:hover { color: var(--accent); }
  .rename { margin-top: 0.15rem; width: 100%;
            background: var(--bg-2); color: var(--ink);
            border: 1px solid var(--accent-line); border-radius: 6px;
            padding: 0.15rem 0.4rem; font: 500 0.75rem/1.3 var(--font-ui);
            outline: none; }

  .ico { flex: none; display: inline-flex; align-items: center; justify-content: center;
         width: 28px; height: 28px; border-radius: 8px;
         border: 1px solid transparent; background: none;
         color: var(--ink-3); font-size: 0.85rem; line-height: 1;
         transition: color 0.15s, background 0.15s, border-color 0.15s; }
  .ico:hover { color: var(--ink); background: var(--bg-3); border-color: var(--line-2); }

  /* ——— the thread ——— */
  .thread { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain;
            display: flex; flex-direction: column; gap: 0.3rem;
            padding: 0.9rem 0.85rem 0.5rem; }

  .day { display: flex; align-items: center; gap: 0.6rem; margin: 0.6rem 0 0.45rem; }
  .day::before, .day::after { content: ''; flex: 1; height: 1px; background: var(--line); }
  .day span { font: 600 0.68rem/1.3 var(--font-ui); color: var(--ink-3);
              letter-spacing: 0.02em; }

  .row { display: flex; gap: 0.5rem; align-items: flex-end;
         animation: line-in 0.26s cubic-bezier(0.22, 0.68, 0.3, 1) both; }
  .row.head { margin-top: 0.55rem; }
  .row.mine { justify-content: flex-end; }
  @keyframes line-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

  .avatar { flex: none; width: 24px; height: 24px; border-radius: 50%;
            display: inline-flex; align-items: center; justify-content: center;
            background: var(--bg-3); color: var(--ink-2);
            border: 1px solid var(--line-2);
            font: 700 0.62rem/1 var(--font-ui); letter-spacing: 0.01em; }
  .avatar.ghost { background: none; border-color: transparent; }

  .said { min-width: 0; max-width: 78%; display: flex; flex-direction: column;
          align-items: flex-start; }
  .mine .said { align-items: flex-end; }
  .from { font: 600 0.7rem/1.3 var(--font-ui); color: var(--ink-3);
          margin: 0 0 0.15rem 0.2rem; }

  .bubble { margin: 0; padding: 0.42rem 0.7rem;
            font: 400 0.86rem/1.5 var(--font-ui); color: var(--ink);
            white-space: pre-wrap; overflow-wrap: anywhere;
            background: var(--bg-3); border: 1px solid var(--line-2);
            border-radius: 14px 14px 14px 4px; }
  .mine .bubble { background: var(--accent-soft); color: var(--accent-ink);
                  border-color: var(--accent-line);
                  border-radius: 14px 14px 4px 14px; }

  time { font: 500 0.64rem/1.3 var(--font-ui); color: var(--ink-3);
         margin: 0.12rem 0.3rem 0; font-variant-numeric: tabular-nums; }

  .empty { margin: auto 0; padding: 1rem 0.3rem; text-align: left; }
  .lead { margin: 0; font-size: 0.95rem; font-weight: 700; letter-spacing: -0.01em; }
  .sub { margin: 0.35rem 0 0; font-size: 0.8rem; line-height: 1.55; color: var(--ink-3); }

  /* they've scrolled up — offer the trip down rather than taking it for them */
  .jump {
    position: absolute; left: 50%; bottom: 4.6rem; transform: translateX(-50%);
    border: 1px solid var(--accent-line); border-radius: 999px;
    background: var(--accent); color: #fff;
    padding: 0.28rem 0.8rem; font: 600 0.74rem/1.3 var(--font-ui);
    box-shadow: var(--shadow-2);
    animation: line-in 0.24s ease both;
  }
  .jump:hover { background: var(--accent-2); }

  .err { flex: none; margin: 0; padding: 0.3rem 0.85rem;
         font: 500 0.72rem/1.4 var(--font-ui); color: var(--bad); }

  /* ——— composer ——— */
  .composer { flex: none; padding: 0.55rem 0.7rem 0.7rem;
              border-top: 1px solid var(--line); }
  .ask { display: block; margin: 0 0.2rem 0.4rem;
         font: 600 0.76rem/1.4 var(--font-ui); color: var(--ink-2); }
  .field { display: flex; align-items: flex-end; gap: 0.5rem;
           background: var(--bg-2);
           border: 1px solid var(--line-2); border-radius: var(--r-lg);
           padding: 0.35rem 0.35rem 0.35rem 0.75rem;
           transition: border-color 0.18s, box-shadow 0.18s; }
  .field:focus-within { border-color: var(--accent);
                        box-shadow: 0 0 0 4px var(--accent-soft); }
  textarea, .field input {
    flex: 1; min-width: 0; resize: none; border: 0; outline: none; background: none;
    color: var(--ink); font: 400 0.87rem/1.5 var(--font-ui);
    padding: 0.3rem 0; max-height: 110px;
  }
  textarea::placeholder, .field input::placeholder { color: var(--ink-3); }
  .btn.send { width: 32px; height: 32px; padding: 0; flex: none; border-radius: 9px;
              font-size: 0.95rem;
              background: linear-gradient(140deg, var(--accent) 0%, var(--accent-2) 100%);
              border-color: transparent;
              transition: transform 0.15s, box-shadow 0.15s, opacity 0.15s; }
  .btn.send:not(:disabled):hover { transform: translateY(-1px);
                                   box-shadow: 0 4px 14px rgba(37, 99, 235, 0.38); }
  .spin.light { border-color: rgba(255, 255, 255, 0.35); border-top-color: #fff; }

  /* full-screen sheet on a phone */
  @media (max-width: 640px) {
    .dock { right: 0.9rem; bottom: 0.9rem; gap: 0; }
    .panel { position: fixed; inset: 0; width: auto; max-width: none; height: auto;
             border-radius: 0; border: 0; }
    .dock.open .launch { display: none; }
    .said { max-width: 86%; }
  }

  @media (prefers-reduced-motion: reduce) {
    .launch, .panel, .row, .jump, .count { animation: none; }
    .launch:hover, .launch:active, .btn.send:not(:disabled):hover { transform: none; }
  }
</style>
