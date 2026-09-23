<script>
  /* Team chat, everywhere. The launcher is a round glass button in the
     TopBar's right cluster (see components/glass/TopBar.svelte) — this file
     is the panel it opens: on a desktop a sheet of strong glass anchored
     under the chrome on the right, on a phone a bottom sheet. Agents talking
     to each other — a "who's taking the Blouberg valuation?" line, not a
     question for the AI. Agent Z is its own page and its own thread.

     It stays out of the way only when something else already owns the right
     edge: the prospect drawer or the crawl slide-over. It does NOT hide on
     /agent — a chat you can't reach from one page is a chat nobody trusts.

     No accounts exist on this dashboard, so the first thing the panel asks
     for is a name; after that it's remembered in this browser and editable
     from the header. */
  import { tick, untrack } from 'svelte';
  import { fly } from 'svelte/transition';
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
  <section class="panel mg-glass-strong" aria-label="Team chat"
           transition:fly={{ y: 12, duration: 200 }}>
    <header class="phead">
      <span class="mark" aria-hidden="true"><Icon name="message" size={16} /></span>
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
                    title="Change your name" aria-label="Change your name">
              <Icon name="edit" size={12} />
            </button>
          </span>
        {:else}
          <span class="me">say hello to the team</span>
        {/if}
      </div>
      <button class="mg-btn secondary icon sm" onclick={closeChat}
              title="Close" aria-label="Close team chat">
        <Icon name="close" size={15} />
      </button>
    </header>

    <div class="thread mg-noscroll" bind:this={scroller} onscroll={onScroll}>
      {#if !chat.messages.length}
        <div class="empty">
          {#if !chat.ready}
            <span class="mg-spin"></span>
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
      <button class="jump mg-btn sm primary" onclick={() => jump()}>New messages ↓</button>
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
          <button class="send mg-btn primary icon sm" onclick={saveName}
                  disabled={!draftName.trim()} aria-label="Save name">
            <Icon name="check" size={15} stroke={2} />
          </button>
        </div>
      {:else}
        <div class="field">
          <textarea bind:this={box} bind:value={text} rows="1"
                    placeholder="Message the team…" aria-label="Message the team"
                    oninput={grow} onkeydown={onKey}></textarea>
          <button class="send mg-btn primary icon sm" onclick={send}
                  disabled={!text.trim() || chat.sending} aria-label="Send">
            {#if chat.sending}<span class="mg-spin"></span>{:else}<Icon name="send" size={15} stroke={2} />{/if}
          </button>
        </div>
      {/if}
    </div>
  </section>
{/if}

<style>
  /* Anchored under the chrome on the right: the launcher is up there, so the
     panel drops from it rather than climbing out of a corner. */
  .panel {
    position: fixed; z-index: 70;
    top: calc(var(--mg-sat, 0px) + 92px);
    right: clamp(16px, 3vw, 32px);
    width: 380px; max-width: calc(100vw - 32px);
    height: min(62vh, 620px);
    display: flex; flex-direction: column; overflow: hidden;
  }

  .phead {
    flex: none; display: flex; align-items: center; gap: 10px;
    padding: 12px 12px 11px 14px;
    border-bottom: 1px solid var(--mg-line);
  }
  .mark {
    flex: none; display: grid; place-items: center;
    width: 28px; height: 28px; border-radius: 10px;
    background: var(--mg-glass-soft); border: 1px solid var(--mg-line);
    color: var(--mg-i2);
  }
  .who { flex: 1; min-width: 0; display: flex; flex-direction: column; line-height: 1.3; }
  .who > b { font: 600 13.5px/1.3 var(--mg-font); letter-spacing: -0.01em; color: var(--mg-i); }
  .me { display: inline-flex; align-items: center; gap: 4px;
        font: 400 11.5px/1.4 var(--mg-font); color: var(--mg-i3); min-width: 0; }
  .me b { font-weight: 500; color: var(--mg-i2);
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pencil { display: inline-flex; border: 0; background: none; padding: 0 2px;
            color: var(--mg-i3); transition: color 0.15s; }
  .pencil:hover { color: var(--mg-i); }
  .rename {
    margin-top: 3px; width: 100%; height: 26px; padding: 0 8px;
    background: var(--mg-glass-soft); color: var(--mg-i);
    border: 1px solid rgba(62, 207, 142, 0.5); border-radius: 8px;
    font: 500 12px/1 var(--mg-font); outline: none;
  }

  /* ——— the thread ——— */
  .thread {
    flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain;
    display: flex; flex-direction: column; gap: 4px;
    padding: 14px 14px 8px;
  }

  .day { display: flex; align-items: center; gap: 10px; margin: 10px 0 7px; }
  .day::before, .day::after { content: ''; flex: 1; height: 1px; background: var(--mg-line); }
  .day span { font: 500 11px/1.3 var(--mg-font); color: var(--mg-i3); }

  .row { display: flex; gap: 8px; align-items: flex-end;
         animation: line-in 0.26s cubic-bezier(0.2, 0.8, 0.2, 1) both; }
  .row.head { margin-top: 9px; }
  .row.mine { justify-content: flex-end; }
  @keyframes line-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

  .avatar {
    flex: none; width: 24px; height: 24px; border-radius: 50%;
    display: inline-flex; align-items: center; justify-content: center;
    background: var(--mg-glass-soft); border: 1px solid var(--mg-line);
    color: var(--mg-i2); font: 600 10px/1 var(--mg-font);
  }
  .avatar.ghost { background: none; border-color: transparent; }

  .said { min-width: 0; max-width: 78%; display: flex; flex-direction: column; align-items: flex-start; }
  .mine .said { align-items: flex-end; }
  .from { font: 500 11px/1.3 var(--mg-font); color: var(--mg-i3); margin: 0 0 3px 3px; }

  .bubble {
    margin: 0; padding: 7px 12px;
    font: 400 13.5px/1.5 var(--mg-font); color: var(--mg-i);
    white-space: pre-wrap; overflow-wrap: anywhere;
    background: var(--mg-glass-soft); border: 1px solid var(--mg-line);
    border-radius: 14px 14px 14px 4px;
  }
  /* your own lines are the green ones — the section's one accent, used once */
  .mine .bubble {
    background: rgba(62, 207, 142, 0.12); border-color: rgba(62, 207, 142, 0.3);
    border-radius: 14px 14px 4px 14px;
  }

  time { font: 400 10.5px/1.3 var(--mg-font); color: var(--mg-i3);
         margin: 3px 4px 0; font-variant-numeric: tabular-nums; }

  .empty { margin: auto 0; padding: 12px 4px; text-align: left; }
  .lead { margin: 0; font: 600 15px/1.3 var(--mg-font); letter-spacing: -0.015em; color: var(--mg-i); }
  .sub { margin: 6px 0 0; font: 400 12.5px/1.6 var(--mg-font); color: var(--mg-i3); }

  /* they've scrolled up — offer the trip down rather than taking it for them */
  .jump {
    position: absolute; left: 50%; bottom: 82px; transform: translateX(-50%);
    box-shadow: var(--mg-sh-2);
    animation: line-in 0.24s ease both;
  }

  .err { flex: none; margin: 0; padding: 4px 14px;
         font: 500 12px/1.4 var(--mg-font); color: var(--mg-crit); }

  /* ——— composer ——— */
  .composer { flex: none; padding: 10px 12px 12px; border-top: 1px solid var(--mg-line); }
  .ask { display: block; margin: 0 2px 7px; font: 500 12.5px/1.4 var(--mg-font); color: var(--mg-i2); }
  .field {
    display: flex; align-items: flex-end; gap: 8px;
    background: var(--mg-glass-soft); border: 1px solid var(--mg-line);
    border-radius: var(--mg-r-in); padding: 5px 5px 5px 12px;
    transition: border-color 0.18s, box-shadow 0.18s;
  }
  .field:focus-within { border-color: rgba(62, 207, 142, 0.6); box-shadow: 0 0 0 1px rgba(62, 207, 142, 0.4); }
  textarea, .field input {
    flex: 1; min-width: 0; resize: none; border: 0; outline: none; background: none;
    color: var(--mg-i); font: 400 13.5px/1.5 var(--mg-font);
    padding: 4px 0; max-height: 110px;
  }
  textarea::placeholder, .field input::placeholder { color: var(--mg-i3); }
  .send { flex: none; }

  /* a bottom sheet on a phone — thumb reach, and it clears nothing because
     it covers the dock outright while it is open */
  @media (max-width: 640px) {
    .panel {
      top: auto; right: 0; left: 0; bottom: 0;
      width: auto; max-width: none; height: 82dvh;
      border-radius: var(--mg-r) var(--mg-r) 0 0; border-bottom: 0;
      padding-bottom: var(--mg-sab, 0px);
    }
    .said { max-width: 86%; }
    .jump { bottom: 96px; }
  }

  @media (prefers-reduced-motion: reduce) {
    .row, .jump { animation: none; }
  }
</style>
