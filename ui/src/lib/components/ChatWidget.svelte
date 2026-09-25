<script>
  /* Team chat, everywhere. The launcher is the chat button in the status
     strip (components/glass/StatusStrip.svelte, with the unread count) —
     this file is the panel it opens: on a phone a full-width sheet that sits
     on top of the dock; from 720px a 380px raised panel anchored bottom-right,
     clear of the dock (and, from 1024px, of the rail). Solid raised plane,
     slides in and out on the settle curve. Agents talking
     to each other — a "who's taking the Blouberg valuation?" line, not a
     question for the AI. Agent Z is its own page and its own thread.

     It stays out of the way only when something else already owns the right
     edge: the prospect drawer or the crawl slide-over. It does NOT hide on
     /agent — a chat you can't reach from one page is a chat nobody trusts.

     No accounts exist on this dashboard, so the first thing the panel asks
     for is a name; after that it's remembered in this browser and editable
     from the header. */
  import { tick, untrack } from 'svelte';
  import { slide } from '$lib/motion.js';
  import { app } from '$lib/state.svelte.js';
  import { chat, say, setName, closeChat } from '$lib/chat.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';

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
</script>

<svelte:window onkeydown={onWindowKey} />

{#if show && chat.open}
  <section class="chat" aria-label="Team chat"
           transition:slide={{ y: 28, duration: 280 }}>
    <header class="phead">
      <span class="mark" aria-hidden="true"><Icon name="chat" size={16} /></span>
      <div class="who">
        <b>Team chat</b>
        {#if editing}
          <input class="mg-input rename" bind:this={nameBox} bind:value={draftName}
                 maxlength="40" placeholder="Your name"
                 aria-label="Your display name"
                 onkeydown={onNameKey} onblur={commitName} />
        {:else if named}
          <span class="me">
            you're <b>{chat.me}</b>
            <button type="button" class="pencil" onclick={startEdit}
                    title="Change your name" aria-label="Change your name">
              <Icon name="edit" size={13} />
            </button>
          </span>
        {:else}
          <span class="me">say hello to the team</span>
        {/if}
      </div>
      <button type="button" class="mg-btn secondary icon sm close" onclick={closeChat}
              title="Close (Esc)" aria-label="Close team chat">
        <Icon name="close" size={15} />
      </button>
    </header>

    <div class="thread" bind:this={scroller} onscroll={onScroll}>
      {#if !chat.messages.length}
        {#if !chat.ready}
          <div class="loading" aria-label="Loading messages">
            {#each [0, 1, 2] as i (i)}
              <div class="skrow" class:mine={i === 1}>
                <span class="mg-skel" style:width="{[62, 44, 70][i]}%" style:height="34px" style:border-radius="14px"></span>
              </div>
            {/each}
          </div>
        {:else}
          <div class="mg-empty empty">
            <span class="ic"><Icon name="chat" size={20} /></span>
            <h3>Nothing said yet</h3>
            <p>The team's own line — who's taking a valuation, who just got a
              mandate, who needs a photo before five. Everyone on the dashboard
              sees it.</p>
          </div>
        {/if}
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
              <time class="mg-tnum" datetime={it.m.at}>{hhmm(it.m.at)}</time>
            </div>
          </div>
        {/if}
      {/each}
    </div>

    {#if hasNew}
      <button type="button" class="jump mg-btn sm primary" onclick={() => jump()}>
        New messages <Icon name="chevronDown" size={14} />
      </button>
    {/if}

    {#if chat.error}
      <div class="mg-strip crit err" role="alert">
        <span class="ic"><Icon name="alert" size={14} /></span><span>{chat.error}</span>
      </div>
    {/if}

    <div class="composer">
      {#if !named}
        <label class="mg-label ask" for="chat-name">What should the team call you?</label>
        <div class="field">
          <input id="chat-name" class="mg-input" bind:this={nameBox} bind:value={draftName}
                 maxlength="40" placeholder="Your name" onkeydown={onNameKey} />
          <button type="button" class="send mg-btn accent icon" onclick={saveName}
                  disabled={!draftName.trim()} aria-label="Save name" title="Save name">
            <Icon name="check" size={16} stroke={2.25} />
          </button>
        </div>
      {:else}
        <div class="field">
          <textarea class="mg-input msg" bind:this={box} bind:value={text} rows="1"
                    placeholder="Message the team…" aria-label="Message the team"
                    oninput={grow} onkeydown={onKey}></textarea>
          <button type="button" class="send mg-btn accent icon" onclick={send}
                  disabled={!text.trim() || chat.sending} aria-label="Send" title="Send (Enter)">
            {#if chat.sending}<span class="mg-spin"></span>{:else}<Icon name="send" size={16} stroke={2} />{/if}
          </button>
        </div>
      {/if}
    </div>
  </section>
{/if}

<style>
  /* A phone: a full-width sheet resting on the dock, most of the screen tall.
     The launcher lives up in the strip; the thumb lives down here. */
  .chat {
    position: fixed; z-index: 70;
    left: 0; right: 0;
    bottom: calc(var(--mc-dock-h) + var(--sab));
    top: calc(var(--sat) + var(--mc-strip-h) + 8px);
    display: flex; flex-direction: column; overflow: hidden;
    background: var(--mc-raised);
    border: 1px solid var(--mc-line2); border-bottom: 0;
    border-radius: var(--mc-r-lg) var(--mc-r-lg) 0 0;
    box-shadow: var(--mc-sh-3);
    will-change: transform, opacity;
  }
  /* from 720px: a 380px panel, bottom-right, clear of the dock */
  @media (min-width: 720px) {
    .chat {
      left: auto; right: 16px; top: auto; width: 380px;
      bottom: calc(var(--mc-dock-h) + var(--sab) + 12px);
      height: min(600px, calc(100dvh - var(--sat) - var(--mc-strip-h) - var(--mc-dock-h) - var(--sab) - 28px));
      border-bottom: 1px solid var(--mc-line2);
      border-radius: var(--mc-r-lg);
      box-shadow: var(--mc-sh-2);
    }
  }
  /* from 1024px the dock is gone (the rail is on the left) */
  @media (min-width: 1024px) {
    .chat {
      right: 20px; bottom: calc(var(--sab) + 20px);
      height: min(620px, calc(100dvh - var(--sat) - var(--mc-strip-h) - 40px));
    }
  }

  /* ——— header ——— */
  .phead {
    flex: none; display: flex; align-items: center; gap: 10px;
    padding: 10px 10px 10px 14px; min-height: 56px;
    border-bottom: 1px solid var(--mc-line);
  }
  .mark {
    flex: none; display: grid; place-items: center; width: 32px; height: 32px;
    border-radius: 10px; background: var(--mc-surface); border: 1px solid var(--mc-line);
    color: var(--mc-ink2);
  }
  .who { flex: 1; min-width: 0; display: flex; flex-direction: column; line-height: 1.3; }
  .who > b { font: 600 14px/1.3 var(--mc-font); letter-spacing: -0.01em; color: var(--mc-ink); }
  .me {
    display: inline-flex; align-items: center; gap: 4px; min-width: 0;
    font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3);
  }
  .me b { font-weight: 500; color: var(--mc-ink2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pencil {
    display: inline-grid; place-items: center; width: 28px; height: 28px; margin: -6px 0;
    border: 0; border-radius: 8px; background: none; color: var(--mc-ink3); cursor: pointer;
    transition: color var(--mc-t-fast), background var(--mc-t-fast);
  }
  .pencil:hover { color: var(--mc-ink); background: rgba(255, 255, 255, 0.05); }
  .rename { margin-top: 4px; height: 32px; font-size: 13px; }

  /* ——— the thread ——— */
  .thread {
    flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain;
    display: flex; flex-direction: column; gap: 4px;
    padding: 12px 14px 10px;
    background: var(--mc-surface);
  }
  .loading { display: flex; flex-direction: column; gap: 10px; padding-top: 8px; }
  .skrow { display: flex; }
  .skrow.mine { justify-content: flex-end; }
  .empty { margin: auto 0; padding: 24px 8px; }

  .day { display: flex; align-items: center; gap: 10px; margin: 10px 0 6px; }
  .day::before, .day::after { content: ''; flex: 1; height: 1px; background: var(--mc-line); }
  .day span { font: 600 10.5px/1.3 var(--mc-font); letter-spacing: 0.05em; text-transform: uppercase; color: var(--mc-ink3); }

  .row { display: flex; gap: 8px; align-items: flex-end; animation: mg-rise var(--mc-t) var(--mc-ease) both; }
  .row.head { margin-top: 8px; }
  .row.mine { justify-content: flex-end; }

  .avatar {
    flex: none; width: 26px; height: 26px; border-radius: 50%; margin-bottom: 18px;
    display: inline-grid; place-items: center;
    background: var(--mc-raised); border: 1px solid var(--mc-line2);
    color: var(--mc-ink2); font: 600 10px/1 var(--mc-font);
  }
  .avatar.ghost { background: none; border-color: transparent; }

  .said { min-width: 0; max-width: 78%; display: flex; flex-direction: column; align-items: flex-start; }
  .mine .said { align-items: flex-end; }
  .from { font: 500 11.5px/1.3 var(--mc-font); color: var(--mc-ink3); margin: 0 0 3px 4px; }

  .bubble {
    margin: 0; padding: 8px 12px;
    font: 400 13.5px/1.5 var(--mc-font); color: var(--mc-ink);
    white-space: pre-wrap; overflow-wrap: anywhere;
    background: var(--mc-raised); border: 1px solid var(--mc-line2);
    border-radius: 16px 16px 16px 6px;
  }
  /* your own lines are the green ones — the one accent, tinted */
  .mine .bubble {
    background: var(--mc-ok-soft); border-color: var(--mc-ok-line);
    border-radius: 16px 16px 6px 16px;
  }
  time { font: 400 10.5px/1.3 var(--mc-font); color: var(--mc-ink3); margin: 3px 6px 0; }

  /* they've scrolled up — offer the trip down rather than taking it for them */
  .jump {
    position: absolute; left: 50%; bottom: 84px; z-index: 2;
    transform: translateX(-50%); box-shadow: var(--mc-sh-2);
  }
  .jump:active { transform: translateX(-50%) scale(0.97); }

  .err { flex: none; margin: 8px 12px 0; padding: 8px 12px; align-items: center; }

  /* ——— composer ——— */
  .composer { flex: none; padding: 10px 12px 12px; border-top: 1px solid var(--mc-line); background: var(--mc-raised); }
  .ask { margin: 0 2px 8px; }
  .field { display: flex; align-items: flex-end; gap: 8px; }
  .field .mg-input { flex: 1; min-width: 0; }
  .msg {
    min-height: 40px; height: 40px; max-height: 110px; padding: 9px 12px;
    resize: none; line-height: 1.5; font-size: 14px;
  }
  .send { flex: none; }

  @media (max-width: 719px) {
    .said { max-width: 86%; }
  }
  @media (pointer: coarse) {
    .close, .send { width: 44px; height: 44px; }
    .msg, .field input.mg-input { min-height: 44px; height: 44px; font-size: 16px; }
    .pencil { width: 36px; height: 36px; }
  }
</style>
