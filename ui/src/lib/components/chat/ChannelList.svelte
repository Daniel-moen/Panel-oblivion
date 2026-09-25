<script>
  /* The channels: #general, the topics by name, then property channels (by
     address, with a small photo) by last activity — each with its unread
     badge and the last line said. Plus the Mentions tab and, for admins, "+"
     to make a topic.

     `compact` is the phone shape: one horizontally scrolling segmented row
     above the conversation. The data-testids are the same in both shapes. */
  import { tick } from 'svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import { chat, openChannel, showMentions, createTopic } from '$lib/chat.svelte.js';
  import { shortAgo } from './text.js';

  let { compact = false } = $props();

  const sorted = $derived.by(() => {
    const live = chat.channels.filter((c) => !c.archived_at);
    const g = live.filter((c) => c.kind === 'general');
    const t = live.filter((c) => c.kind === 'topic').sort((a, b) => (a.name || '').localeCompare(b.name || ''));
    const p = live.filter((c) => c.kind === 'property')
      .sort((a, b) => (b.last?.id || 0) - (a.last?.id || 0) || b.id - a.id);
    const rest = live.filter((c) => !['general', 'topic', 'property'].includes(c.kind));
    return [...g, ...t, ...rest, ...p];
  });

  const admin = $derived(!!chat.me?.is_admin);
  const label = (c) => (c.kind === 'property' ? c.property?.label || c.name : c.name);

  let adding = $state(false);
  let name = $state('');
  let busy = $state(false);
  let err = $state('');
  let input = $state(null);
  let broken = $state({});

  async function startAdd() {
    adding = true;
    name = '';
    err = '';
    await tick();
    input?.focus();
  }

  async function add() {
    const n = name.trim();
    if (!n || busy) return;
    busy = true;
    err = '';
    try {
      await createTopic(n);
      adding = false;
      name = '';
    } catch (e) {
      err = e?.status === 409 ? 'A channel with that name exists.' : e?.status === 403 ? 'Only admins can make channels.' : (e?.message || 'Could not create');
    } finally {
      busy = false;
    }
  }

  function onKey(e) {
    if (e.key === 'Enter') { e.preventDefault(); add(); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); adding = false; }
  }

  const isOn = (c) => chat.view === 'channel' && chat.active === c.id;
</script>

{#if compact}
  <div class="seg mg-noscroll" role="tablist" aria-label="Channels">
    <button type="button" class="tab ment" role="tab" aria-selected={chat.view === 'mentions'}
            class:on={chat.view === 'mentions'} data-testid="chat-mentions-tab" onclick={showMentions}>
      <span class="at">@</span> Mentions
      {#if chat.mentions}<i class="n hot">{chat.mentions}</i>{/if}
    </button>
    {#each sorted as c (c.id)}
      <button type="button" class="tab" role="tab" aria-selected={isOn(c)} class:on={isOn(c)}
              data-testid="chat-channel" data-slug={c.slug} data-id={c.id}
              title={label(c)} onclick={() => openChannel(c.id)}>
        {#if c.kind === 'property'}
          {#if c.property?.photo_url && !broken[c.id]}
            <img src={c.property.photo_url} alt="" onerror={() => (broken[c.id] = true)} />
          {:else}<Icon name="property" size={13} />{/if}
        {:else}<span class="hash">#</span>{/if}
        <span class="nm">{label(c)}</span>
        {#if c.unread}<i class="n" class:hot={c.mentions} data-testid="chat-channel-unread">{c.unread > 99 ? '99+' : c.unread}</i>{/if}
      </button>
    {/each}
    {#if admin}
      <button type="button" class="tab add" data-testid="chat-new-channel" onclick={startAdd} aria-label="New channel">
        <Icon name="plus" size={14} />
      </button>
    {/if}
  </div>
  {#if adding}
    <div class="newform compactform">
      <input class="mg-input" bind:this={input} bind:value={name} maxlength="40" placeholder="Channel name"
             aria-label="New channel name" onkeydown={onKey} />
      <button type="button" class="mg-btn accent sm" onclick={add} disabled={!name.trim() || busy}>Create</button>
      <button type="button" class="mg-btn ghost icon sm" onclick={() => (adding = false)} aria-label="Cancel"><Icon name="close" size={14} /></button>
      {#if err}<span class="err">{err}</span>{/if}
    </div>
  {/if}
{:else}
  <nav class="list" aria-label="Channels">
    <button type="button" class="row ment" class:on={chat.view === 'mentions'}
            data-testid="chat-mentions-tab" onclick={showMentions} aria-pressed={chat.view === 'mentions'}>
      <span class="ic at">@</span>
      <span class="tx"><b>Mentions</b><span class="pv">Where you were @-mentioned</span></span>
      {#if chat.mentions}<i class="n hot">{chat.mentions}</i>{/if}
    </button>

    <div class="hd">
      <span>Channels</span>
      {#if admin}
        <button type="button" class="addbtn" data-testid="chat-new-channel" onclick={startAdd}
                aria-label="New channel" title="New channel"><Icon name="plus" size={14} /></button>
      {/if}
    </div>
    {#if adding}
      <div class="newform">
        <input class="mg-input" bind:this={input} bind:value={name} maxlength="40" placeholder="Channel name"
               aria-label="New channel name" onkeydown={onKey} />
        <div class="nfacts">
          <button type="button" class="mg-btn ghost sm" onclick={() => (adding = false)}>Cancel</button>
          <button type="button" class="mg-btn accent sm" onclick={add} disabled={!name.trim() || busy}>Create</button>
        </div>
        {#if err}<span class="err">{err}</span>{/if}
      </div>
    {/if}

    {#each sorted as c, i (c.id)}
      {#if c.kind === 'property' && (i === 0 || sorted[i - 1].kind !== 'property')}
        <div class="hd"><span>Properties</span></div>
      {/if}
      <button type="button" class="row" class:on={isOn(c)} class:unread={c.unread}
              data-testid="chat-channel" data-slug={c.slug} data-id={c.id}
              aria-current={isOn(c) ? 'true' : undefined} onclick={() => openChannel(c.id)}>
        {#if c.kind === 'property'}
          <span class="ic ph">
            {#if c.property?.photo_url && !broken[c.id]}
              <img src={c.property.photo_url} alt="" loading="lazy" onerror={() => (broken[c.id] = true)} />
            {:else}<Icon name="property" size={14} />{/if}
          </span>
        {:else}
          <span class="ic">#</span>
        {/if}
        <span class="tx">
          <b>{label(c)}</b>
          <span class="pv">{#if c.last}{c.last.sender ? c.last.sender + ': ' : ''}{c.last.preview}{:else}{c.kind === 'property' ? c.property?.suburb || 'Property' : 'No messages yet'}{/if}</span>
        </span>
        <span class="side">
          {#if c.last}<span class="ago">{shortAgo(c.last.at)}</span>{/if}
          {#if c.unread}<i class="n" class:hot={c.mentions} data-testid="chat-channel-unread">{c.unread > 99 ? '99+' : c.unread}</i>{/if}
        </span>
      </button>
    {/each}
  </nav>
{/if}

<style>
  /* ——— the phone row ——— */
  .seg {
    flex: none; display: flex; gap: 6px; overflow-x: auto; padding: 8px 10px;
    border-bottom: 1px solid var(--mc-line); scroll-snap-type: x proximity;
    -webkit-overflow-scrolling: touch;
  }
  .tab {
    flex: none; display: inline-flex; align-items: center; gap: 6px; max-width: 200px;
    height: 36px; padding: 0 12px; border-radius: 9999px; scroll-snap-align: start;
    background: var(--mc-glass-soft); border: 1px solid var(--mc-glass-line);
    color: var(--mc-ink2); font: 500 13px/1 var(--mc-font); cursor: pointer; white-space: nowrap;
  }
  .tab.on { background: var(--mc-glass-on); border-color: var(--mc-glass-line2); color: var(--mc-ink); }
  .tab img { width: 20px; height: 20px; border-radius: 6px; object-fit: cover; margin-left: -4px; }
  .tab .nm { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .tab .hash, .tab .at, .row .at { color: var(--mc-ink3); font-weight: 600; }
  .tab.add { width: 36px; padding: 0; justify-content: center; }
  .compactform { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 8px 10px; border-bottom: 1px solid var(--mc-line); }
  .compactform .mg-input { flex: 1; min-width: 140px; height: 36px; }

  /* ——— the side list ——— */
  .list { display: flex; flex-direction: column; gap: 2px; padding: 8px; overflow-y: auto; min-height: 0; flex: 1; overscroll-behavior: contain; }
  .hd {
    display: flex; align-items: center; justify-content: space-between; gap: 6px;
    padding: 12px 8px 4px; font: 600 10.5px/1.3 var(--mc-font); letter-spacing: 0.05em;
    text-transform: uppercase; color: var(--mc-ink3);
  }
  .addbtn {
    width: 26px; height: 26px; border-radius: 8px; border: 1px solid var(--mc-glass-line);
    background: var(--mc-glass-soft); color: var(--mc-ink2); display: grid; place-items: center; cursor: pointer;
  }
  .addbtn:hover { color: var(--mc-ink); border-color: var(--mc-glass-line2); }
  .row {
    display: flex; align-items: center; gap: 10px; width: 100%; min-height: 48px; padding: 6px 8px;
    border: 0; border-radius: 12px; background: none; color: var(--mc-ink2);
    font: inherit; text-align: left; cursor: pointer;
    transition: background var(--mc-t-fast), color var(--mc-t-fast);
  }
  .row:hover { background: rgba(255, 255, 255, 0.06); }
  .row.on { background: var(--mc-glass-on); color: var(--mc-ink); }
  .ic {
    flex: none; width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center;
    background: var(--mc-glass-soft); border: 1px solid var(--mc-glass-line);
    font: 600 14px/1 var(--mc-font); color: var(--mc-ink3); overflow: hidden;
  }
  .ic.ph img { width: 100%; height: 100%; object-fit: cover; }
  .tx { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 1px; }
  .tx b { font: 500 13px/1.3 var(--mc-font); color: var(--mc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .row.unread .tx b { font-weight: 700; }
  .pv { font: 400 11.5px/1.3 var(--mc-font); color: var(--mc-ink3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .side { flex: none; display: flex; flex-direction: column; align-items: flex-end; gap: 3px; }
  .ago { font: 400 10.5px/1 var(--mc-font); color: var(--mc-ink3); }

  .n {
    flex: none; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 9999px;
    display: inline-grid; place-items: center; font: 700 10.5px/1 var(--mc-font); font-style: normal;
    background: rgba(255, 255, 255, 0.16); color: var(--mc-ink);
  }
  .n.hot { background: var(--mc-accent); color: var(--mc-accent-ink); }

  .newform { display: flex; flex-direction: column; gap: 6px; padding: 4px 6px 8px; }
  .newform .mg-input { height: 36px; }
  .nfacts { display: flex; justify-content: flex-end; gap: 6px; }
  .err { font: 400 12px/1.4 var(--mc-font); color: var(--mc-crit); }

  @media (pointer: coarse) {
    .tab { height: 44px; }
    .tab.add { width: 44px; }
    .row { min-height: 52px; }
    .addbtn { width: 36px; height: 36px; }
  }
</style>
