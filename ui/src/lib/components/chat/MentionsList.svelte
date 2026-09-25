<script>
  /* Where you were @-mentioned, newest first, across every channel. Tap one
     to jump to its channel with that message brought into view. */
  import Icon from '$lib/components/glass/Icon.svelte';
  import { chat, openChannel } from '$lib/chat.svelte.js';
  import { initials, hhmm, dayLabel } from './text.js';

  function go(m) {
    const id = m.channel?.id ?? m.channel_id;
    if (id == null) return;
    chat.jumpTo = m.id;
    openChannel(id);
  }
  const where = (m) => (m.channel?.kind === 'property' ? m.channel?.name : '#' + (m.channel?.name || 'channel'));
</script>

<div class="list" aria-label="Your mentions">
  {#if chat.mentionsLoading && !chat.mentionList.length}
    <div class="pad"><span class="mg-spin"></span></div>
  {:else if !chat.mentionList.length}
    <div class="mg-empty empty">
      <span class="ic"><Icon name="bell" size={20} /></span>
      <h3>No mentions yet</h3>
      <p>When someone writes @ and your name, it lands here.</p>
    </div>
  {:else}
    {#each chat.mentionList as m (m.id)}
      <button type="button" class="row" onclick={() => go(m)}>
        <span class="av" aria-hidden="true">{m.user?.initials || initials(m.sender)}</span>
        <span class="tx">
          <span class="top"><b>{m.sender || 'Someone'}</b> <span class="in">in {where(m)}</span>
            <span class="at">{dayLabel(m.created_at)} {hhmm(m.created_at)}</span></span>
          <span class="body">{m.deleted ? 'Message deleted' : m.body || '(attachment)'}</span>
        </span>
      </button>
    {/each}
  {/if}
</div>

<style>
  .list { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 8px; display: flex; flex-direction: column; gap: 2px; }
  .pad { display: flex; justify-content: center; padding: 24px; color: var(--mc-ink3); }
  .empty { margin: auto 0; }
  .row {
    display: flex; gap: 10px; align-items: flex-start; width: 100%; padding: 10px; min-height: 56px;
    border: 0; border-radius: 12px; background: none; text-align: left; font: inherit; cursor: pointer; color: var(--mc-ink2);
  }
  .row:hover { background: rgba(255, 255, 255, 0.06); }
  .av {
    flex: none; width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center;
    background: var(--mc-raised); border: 1px solid var(--mc-line2); font: 600 10.5px/1 var(--mc-font); color: var(--mc-ink2);
  }
  .tx { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 3px; }
  .top { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; font: 400 12px/1.3 var(--mc-font); color: var(--mc-ink3); }
  .top b { font: 600 13px/1.3 var(--mc-font); color: var(--mc-ink); }
  .at { margin-left: auto; }
  .body {
    font: 400 13.5px/1.45 var(--mc-font); color: var(--mc-ink2); overflow-wrap: anywhere;
    display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
  }
</style>
