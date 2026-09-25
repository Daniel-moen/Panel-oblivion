<script>
  /* The open channel's thread: day dividers, runs grouped by sender (5 min),
     the "New" line before the first unread message, older pages on reaching
     the top, and the rule that a reader who has scrolled up is never yanked
     down — a chip offers the trip instead. At the foot (and only there) the
     channel counts as read. */
  import { tick, untrack } from 'svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Message from './Message.svelte';
  import { chat, loadOlder, loadTail, markRead } from '$lib/chat.svelte.js';
  import { mentionMatcher, dayKey, dayLabel, when } from './text.js';

  let { channelId } = $props();

  const GROUP_MS = 5 * 60 * 1000;

  /* Rows are replaced whole on any change, so a row object is a fine cache
     key: a new message parses one date, not the whole thread's. */
  const timeCache = new WeakMap();
  function timeOf(m) {
    let t = timeCache.get(m);
    if (!t) {
      t = { ms: when(m.created_at)?.getTime() ?? 0, day: dayKey(m.created_at), label: null };
      timeCache.set(m, t);
    }
    return t;
  }
  function dayOf(m) {
    const t = timeOf(m);
    if (t.label == null) t.label = dayLabel(m.created_at);
    return t.label;
  }

  const b = $derived(chat.byChannel[String(channelId)] || null);
  const matcher = $derived(mentionMatcher(chat.people));

  const firstUnread = $derived.by(() => {
    const dv = chat.divider;
    if (!b || !dv || dv.channel !== channelId) return null;
    const m = b.messages.find((x) => x.id > dv.after && !x.mine && !x.deleted);
    return m ? m.id : null;
  });

  const items = $derived.by(() => {
    const out = [];
    if (!b) return out;
    let day = null;
    let prev = null;
    const who = (m) => (m.user?.id != null ? 'u' + m.user.id : 's' + (m.sender || ''));
    for (const m of b.messages) {
      const k = timeOf(m).day;
      let broke = false;
      if (k !== day) {
        out.push({ kind: 'day', key: 'd' + m.id, label: dayOf(m) });
        day = k;
        broke = true;
      }
      if (m.id === firstUnread) {
        out.push({ kind: 'new', key: 'new' });
        broke = true;
      }
      const head = broke || !prev || who(prev) !== who(m) || timeOf(m).ms - timeOf(prev).ms > GROUP_MS;
      out.push({ kind: 'msg', key: m.id, m, head });
      prev = m;
    }
    for (const p of b.pending) {
      const head = !prev || !(prev.mine || prev.client_id);
      out.push({ kind: 'pending', key: 'p' + p.client_id, p, head });
      prev = { mine: true, client_id: p.client_id, created_at: p.created_at };
    }
    return out;
  });

  let scroller = $state(null);
  let hasNew = $state(false);
  let newCount = $state(0);
  let placedFor = null;          // the channel we have done the first positioning for
  let lastTail = null;           // id/pending signature of the foot, to spot arrivals

  function foot(behavior = 'auto') {
    if (!scroller) return;
    scroller.scrollTo({ top: scroller.scrollHeight, behavior });
    hasNew = false;
    newCount = 0;
    setBottom(true);
  }

  function setBottom(v) {
    if (chat.atBottom !== v) chat.atBottom = v;
    if (v) markRead();
  }

  async function onScroll() {
    if (!scroller) return;
    const near = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 48;
    setBottom(near);
    if (near) { hasNew = false; newCount = 0; }
    if (scroller.scrollTop < 120 && b?.hasMore && !b.loadingOlder) {
      const h = scroller.scrollHeight;
      const top = scroller.scrollTop;
      const got = await loadOlder(channelId);
      if (got) {
        await tick();
        if (scroller) scroller.scrollTop = top + (scroller.scrollHeight - h);
      }
    }
  }

  /* First placement per channel, once its tail has loaded: on the "New"
     line if there is one (a little context above it), else at the foot. */
  $effect(() => {
    const id = channelId;
    const ready = !!b?.loaded;
    if (!ready) return;
    untrack(() => {
      if (placedFor === id) return;
      placedFor = id;
      lastTail = sig();
      tick().then(() => {
        if (!scroller) return;
        const jump = chat.jumpTo != null ? scroller.querySelector(`[data-testid="chat-msg"][data-id="${chat.jumpTo}"]`) : null;
        const line = scroller.querySelector('[data-testid="chat-unread-divider"]');
        const target = jump || line;
        if (target) {
          scroller.scrollTop = Math.max(0, target.offsetTop - 56);
          if (jump) {
            jump.classList.add('flash');
            setTimeout(() => jump.classList.remove('flash'), 1600);
          }
          requestAnimationFrame(onScroll);
        } else {
          foot();
        }
        chat.jumpTo = null;
      });
    });
  });

  function sig() {
    const m = b?.messages;
    return `${m?.length ? m[m.length - 1].id : 0}:${b?.pending.length || 0}`;
  }
  const sigParts = (s) => (s || '0:0').split(':').map(Number);

  /* Arrivals at the foot: follow them if the reader is at the foot or it is
     their own line; otherwise count them on the chip. */
  $effect(() => {
    const s = sig();
    untrack(() => {
      if (placedFor !== channelId || s === lastTail) return;
      const [prevLast, prevPending] = sigParts(lastTail);
      const [nowLast, nowPending] = sigParts(s);
      lastTail = s;
      const list = b?.messages || [];
      /* follow only a change that is yours: a new pending bubble, or a new
         last row of your own (not a failed bubble sitting there) */
      const yours = nowPending > prevPending || (nowLast > prevLast && list[list.length - 1]?.mine);
      const fresh = nowLast > prevLast ? list.filter((m) => m.id > prevLast && !m.mine).length : 0;
      if (chat.atBottom || yours) tick().then(() => foot(chat.atBottom ? 'smooth' : 'auto'));
      else if (fresh) { hasNew = true; newCount += fresh; }
    });
  });

  /* a new channel → a fresh first placement */
  $effect(() => {
    channelId;
    untrack(() => { hasNew = false; newCount = 0; });
  });
</script>

<div class="wrap">
  <div class="thread" bind:this={scroller} onscroll={onScroll} data-testid="chat-thread"
       role="log" aria-label="Messages" tabindex="-1">
    {#if b?.loadingOlder}
      <div class="older"><span class="mg-spin"></span></div>
    {:else if b?.loaded && !b.hasMore && b.messages.length}
      <div class="start">The start of this channel</div>
    {/if}

    {#if b?.error && !b.loaded}
      <div class="mg-empty empty" role="alert">
        <span class="ic"><Icon name="alert" size={20} /></span>
        <h3>Couldn't load this channel</h3>
        <p>{b.error}</p>
        <div class="act"><button type="button" class="mg-btn secondary sm" data-testid="chat-thread-retry" onclick={() => loadTail(channelId)}><Icon name="refresh" size={14} /> Retry</button></div>
      </div>
    {:else if !b || (!b.loaded && !b.messages.length)}
      <div class="loading" aria-label="Loading messages">
        {#each [0, 1, 2] as i (i)}
          <div class="skrow" class:mine={i === 1}>
            <span class="mg-skel" style:width="{[62, 44, 70][i]}%" style:height="34px" style:border-radius="14px"></span>
          </div>
        {/each}
      </div>
    {:else if !b.messages.length && !b.pending.length}
      <div class="mg-empty empty">
        <span class="ic"><Icon name="chat" size={20} /></span>
        <h3>Nothing said yet</h3>
        <p>Start it off — mention someone with @, or attach a property, a photo or a link with +.</p>
      </div>
    {/if}

    {#each items as it (it.key)}
      {#if it.kind === 'day'}
        <div class="day"><span>{it.label}</span></div>
      {:else if it.kind === 'new'}
        <div class="newline" data-testid="chat-unread-divider" role="separator" aria-label="New messages"><span>New</span></div>
      {:else if it.kind === 'msg'}
        <Message m={it.m} head={it.head} {matcher} />
      {:else}
        <Message m={it.p} pending={it.p} head={it.head} {matcher} />
      {/if}
    {/each}
  </div>

  {#if hasNew}
    <button type="button" class="jump mg-btn sm primary" onclick={() => foot('smooth')}>
      {newCount > 1 ? `${newCount} new messages` : 'New message'} <Icon name="chevronDown" size={14} />
    </button>
  {/if}
  <span class="sr" aria-live="polite">{hasNew ? `${newCount} new message${newCount === 1 ? '' : 's'}` : ''}</span>
</div>

<style>
  .wrap { position: relative; flex: 1; min-height: 0; display: flex; flex-direction: column; }
  .thread {
    flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; outline: none;
    display: flex; flex-direction: column; gap: 2px;
    padding: 10px 14px 12px;
    -webkit-overflow-scrolling: touch;
  }
  .older, .start { display: flex; justify-content: center; padding: 6px 0 10px; color: var(--mc-ink3); font: 400 11.5px/1.3 var(--mc-font); }
  .loading { display: flex; flex-direction: column; gap: 10px; padding-top: 8px; }
  .skrow { display: flex; }
  .skrow.mine { justify-content: flex-end; }
  .empty { margin: auto 0; padding: 24px 8px; }

  .day { display: flex; align-items: center; gap: 10px; margin: 12px 0 4px; }
  .day::before, .day::after { content: ''; flex: 1; height: 1px; background: var(--mc-line); }
  .day span { font: 600 10.5px/1.3 var(--mc-font); letter-spacing: 0.05em; text-transform: uppercase; color: var(--mc-ink3); }

  .newline { display: flex; align-items: center; gap: 8px; margin: 10px 0 2px; }
  .newline::before { content: ''; flex: 1; height: 1px; background: var(--mc-accent); opacity: 0.6; }
  .newline span {
    font: 700 10.5px/1 var(--mc-font); letter-spacing: 0.06em; text-transform: uppercase;
    color: var(--mc-accent-ink); background: var(--mc-accent); padding: 3px 7px; border-radius: 9999px;
  }

  .thread :global(.flash .bubble) { outline: 2px solid var(--mc-accent); outline-offset: 2px; transition: outline-color 1.2s; }

  .jump {
    position: absolute; left: 50%; bottom: 12px; z-index: 3;
    transform: translateX(-50%); box-shadow: var(--mc-sh-2);
  }
  .jump:active { transform: translateX(-50%) scale(0.97); }
  .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  @media (pointer: coarse) { .jump { height: 44px; } }
</style>
