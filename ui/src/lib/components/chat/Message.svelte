<script>
  /* One line in the thread. The body is TEXT: it is split into text, link and
     @mention segments and each is rendered as a Svelte text node or an <a> —
     never {@html}. Own lines sit on the right in the accent tint; others get
     an avatar (initials) on the first line of a run from one sender.

     A pending line (an optimistic send) carries `pending` — the entry from
     the store's outbox: {client_id, status 'sending'|'failed', error}. */
  import { tick } from 'svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Attachment from './Attachment.svelte';
  import { chat, editMessage, deleteMessage, retry, discard } from '$lib/chat.svelte.js';
  import { segments, initials, hhmm, when } from './text.js';
  import { play, fadeUp } from '$lib/motion.js';

  /* enter: Thread says this line arrived after the thread's first render —
     it rises in with fadeUp; history just appears. */
  let { m, pending = null, head = false, matcher = null, enter = false } = $props();

  const EDIT_MS = 15 * 60 * 1000;

  const mine = $derived(!!pending || !!m.mine);
  const admin = $derived(!!chat.me?.is_admin);
  const name = $derived(m.sender || m.user?.display_name || (mine ? chat.me?.display_name : '') || 'Someone');
  const mid = $derived(pending ? 'p-' + pending.client_id : m.id);
  const menuOpen = $derived(!pending && chat.overlay === 'msg:' + m.id);
  const editing = $derived(!pending && chat.overlay === 'edit:' + m.id);
  /* admins may edit any message at any time (legacy rows included); others
     their own, within 15 minutes — the server's rule */
  const canEdit = $derived(!pending && !m.deleted
    && (admin || (mine && Date.now() - (when(m.created_at)?.getTime() ?? 0) < EDIT_MS)));
  const canDelete = $derived(!pending && !m.deleted && (mine || admin));
  const segs = $derived(m.deleted ? [] : segments(m.body || '', matcher, {
    mentionIds: m.mentions || [], meId: chat.me?.id ?? null, mine
  }));

  let draft = $state('');
  let editBox = $state(null);
  let saving = $state(false);
  let err = $state('');

  function toggleMenu(e) {
    e.stopPropagation();
    chat.overlay = menuOpen ? '' : 'msg:' + m.id;
  }

  async function startEdit() {
    draft = m.body || '';
    err = '';
    chat.overlay = 'edit:' + m.id;
    await tick();
    if (editBox) {
      editBox.focus();
      editBox.setSelectionRange(draft.length, draft.length);
      grow();
    }
  }

  function grow() {
    if (!editBox) return;
    editBox.style.height = 'auto';
    editBox.style.height = Math.min(editBox.scrollHeight, 180) + 'px';
  }

  async function save() {
    const body = draft.trim();
    if (!body && !(m.attachments || []).length) return;
    if (body === (m.body || '').trim()) { chat.overlay = ''; return; }
    saving = true;
    err = '';
    try {
      await editMessage(m.id, body);
      chat.overlay = '';
    } catch (e) {
      err = e?.code === 'edit_window' ? 'Too late to edit — the 15-minute window has passed.' : (e?.message || 'Could not save');
    } finally {
      saving = false;
    }
  }

  async function remove() {
    chat.overlay = '';
    if (!confirm('Delete this message for everyone?')) return;
    try { await deleteMessage(m.id); } catch (e) { chat.error = e?.message || 'Could not delete'; }
  }

  function onEditKey(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      chat.overlay = '';
    } else if (e.key === 'Enter' && !e.shiftKey && !matchMedia('(pointer: coarse)').matches) {
      e.preventDefault();
      save();
    }
  }
</script>

<div class="row" class:mine class:head class:pend={!!pending} class:failed={pending?.status === 'failed'}
     class:me-hit={!mine && m.mentions_me}
     data-testid="chat-msg" data-id={mid} data-mine={mine ? 'true' : 'false'}
     data-status={pending ? pending.status : null}
     in:play|global={{ v: fadeUp, skip: !enter }}>
  {#if !mine}
    {#if head}
      <span class="avatar" aria-hidden="true">{m.user?.initials || initials(name)}</span>
    {:else}
      <span class="avatar ghost" aria-hidden="true"></span>
    {/if}
  {/if}

  <div class="said">
    {#if head && !mine}<span class="from">{name}</span>{/if}

    {#if editing}
      <div class="editbox">
        <textarea class="mg-input edit" bind:this={editBox} bind:value={draft} rows="2"
                  data-testid="chat-edit-input" aria-label="Edit message"
                  oninput={grow} onkeydown={onEditKey}></textarea>
        {#if err}<span class="err">{err}</span>{/if}
        <div class="editacts">
          <button type="button" class="mg-btn ghost sm" onclick={() => (chat.overlay = '')}>Cancel</button>
          <button type="button" class="mg-btn accent sm" data-testid="chat-edit-save" onclick={save}
                  disabled={saving || (!draft.trim() && !(m.attachments || []).length)}>
            {#if saving}<span class="mg-spin"></span>{/if} Save
          </button>
        </div>
      </div>
    {:else}
      <div class="bubblewrap">
        {#if m.deleted}
          <p class="bubble deleted" data-testid="chat-msg-body">Message deleted</p>
        {:else}
          {#if m.body}
            <p class="bubble" data-testid="chat-msg-body">{#each segs as s, i (i)}{#if s.t === 'link'}<a href={s.href} target="_blank" rel="noopener noreferrer">{s.v}</a>{:else if s.t === 'mention'}<span class="mention" class:me={s.me} data-testid="chat-mention" data-me={s.me ? 'true' : 'false'}>{s.v}</span>{:else}{s.v}{/if}{/each}</p>
          {/if}
          {#if (m.attachments || []).length}
            <div class="atts">
              {#each m.attachments as a, i (i)}<Attachment {a} />{/each}
            </div>
          {/if}
        {/if}

        {#if canEdit || canDelete}
          <div class="actwrap">
            <button type="button" class="acts" data-testid="chat-msg-actions" onclick={toggleMenu}
                    aria-label="Message actions" aria-haspopup="menu" aria-expanded={menuOpen}>
              <Icon name="more" size={16} />
            </button>
            {#if menuOpen}
              <div class="menu" role="menu">
                {#if canEdit}
                  <button type="button" role="menuitem" data-testid="chat-msg-edit" onclick={startEdit}>
                    <Icon name="edit" size={14} /> Edit
                  </button>
                {/if}
                {#if canDelete}
                  <button type="button" role="menuitem" class="danger" data-testid="chat-msg-delete" onclick={remove}>
                    <Icon name="trash" size={14} /> Delete
                  </button>
                {/if}
              </div>
            {/if}
          </div>
        {/if}
      </div>
    {/if}

    {#if pending?.status === 'failed'}
      <div class="failbar" data-testid="chat-failed" role="alert">
        <Icon name="alert" size={13} />
        <span class="why">Not sent{pending.error ? ' — ' + pending.error : ''}</span>
        <button type="button" class="lnk" data-testid="chat-retry" onclick={() => retry(pending.channel_id, pending.client_id)}>Retry</button>
        <button type="button" class="lnk dim" onclick={() => discard(pending.channel_id, pending.client_id)}>Discard</button>
      </div>
    {:else}
      <span class="meta mg-tnum">
        {#if pending}<span class="mg-spin tiny" aria-label="Sending"></span> Sending…{:else}{hhmm(m.created_at)}{#if m.edited_at && !m.deleted}<span class="edited"> (edited)</span>{/if}{/if}
      </span>
    {/if}
  </div>
</div>

<style>
  .row { display: flex; gap: 8px; align-items: flex-end; padding: 1px 0; }
  .row.head { margin-top: 10px; }
  .row.mine { justify-content: flex-end; }

  .avatar {
    flex: none; width: 28px; height: 28px; border-radius: 50%; margin-bottom: 18px;
    display: inline-grid; place-items: center;
    background: var(--mc-raised); border: 1px solid var(--mc-line2);
    color: var(--mc-ink2); font: 600 10.5px/1 var(--mc-font);
  }
  .avatar.ghost { background: none; border-color: transparent; }

  .said { min-width: 0; max-width: min(78%, 520px); display: flex; flex-direction: column; align-items: flex-start; }
  .mine .said { align-items: flex-end; }
  .from { font: 500 11.5px/1.3 var(--mc-font); color: var(--mc-ink3); margin: 0 0 3px 4px; }

  .bubblewrap { position: relative; display: flex; flex-direction: column; gap: 6px; min-width: 0; max-width: 100%; }
  .mine .bubblewrap { align-items: flex-end; }

  .bubble {
    margin: 0; padding: 8px 12px; min-width: 0; max-width: 100%;
    font: 400 14px/1.5 var(--mc-font); color: var(--mc-ink);
    white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word;
    background: var(--mc-raised); border: 1px solid var(--mc-line);
    border-radius: 16px 16px 16px 6px;
  }
  .mine .bubble {
    background: var(--mc-ok-soft); border-color: var(--mc-ok-line);
    border-radius: 16px 16px 6px 16px;
  }
  .me-hit .bubble { border-color: var(--mc-ok-line); box-shadow: inset 3px 0 0 var(--mc-accent); }
  .pend .bubble { opacity: 0.72; }
  .failed .bubble { opacity: 1; background: var(--mc-crit-soft); border-color: var(--mc-crit-line); }
  .bubble.deleted { font-style: italic; color: var(--mc-ink3); background: transparent; border-style: dashed; }
  .bubble a { color: var(--mc-accent-bright); text-decoration: underline; text-underline-offset: 2px; overflow-wrap: anywhere; }
  .mention {
    padding: 0 3px; border-radius: 5px; font-weight: 600;
    background: rgba(255, 255, 255, 0.1); color: var(--mc-ink);
  }
  .mention.me { background: var(--mc-accent); color: var(--mc-accent-ink); }

  .atts { display: flex; flex-direction: column; gap: 6px; width: 100%; min-width: min(240px, 60vw); }
  .mine .atts { align-items: flex-end; }

  .meta { font: 400 10.5px/1.3 var(--mc-font); color: var(--mc-ink3); margin: 3px 6px 0; display: inline-flex; align-items: center; gap: 4px; }
  .edited { color: var(--mc-ink3); }
  .tiny { width: 9px; height: 9px; border-width: 1.5px; }

  /* the ⋯ sits beside the bubble; quiet until the row is hovered or focused */
  .actwrap { position: absolute; top: 2px; right: calc(100% + 2px); }
  .row:not(.mine) .actwrap { right: auto; left: calc(100% + 2px); }
  .acts {
    width: 28px; height: 28px; border: 0; border-radius: 9999px; padding: 0;
    display: grid; place-items: center; background: none; color: var(--mc-ink3); cursor: pointer;
    opacity: 0; transition: opacity var(--mc-t-fast), background var(--mc-t-fast), color var(--mc-t-fast);
  }
  .row:hover .acts, .acts:focus-visible, .acts[aria-expanded='true'] { opacity: 1; }
  .acts:hover { background: rgba(255, 255, 255, 0.08); color: var(--mc-ink); }
  @media (hover: none) { .acts { opacity: 0.7; } }

  .menu {
    position: absolute; top: 30px; right: 0; z-index: 5; min-width: 132px; padding: 4px;
    background: #1c1c21; border: 1px solid var(--mc-glass-line2); border-radius: 12px;
    box-shadow: var(--mc-sh-2);
  }
  .row:not(.mine) .menu { right: auto; left: 0; }
  .menu button {
    display: flex; align-items: center; gap: 8px; width: 100%; min-height: 36px; padding: 6px 10px;
    border: 0; border-radius: 8px; background: none; color: var(--mc-ink2);
    font: 500 13px/1.2 var(--mc-font); text-align: left; cursor: pointer;
  }
  .menu button:hover { background: rgba(255, 255, 255, 0.08); color: var(--mc-ink); }
  .menu button.danger { color: var(--mc-crit); }

  .editbox { display: flex; flex-direction: column; gap: 6px; width: min(420px, 70vw); }
  .edit { min-height: 60px; max-height: 180px; resize: none; font-size: 14px; }
  .editacts { display: flex; justify-content: flex-end; gap: 6px; }
  .err { font: 400 12px/1.4 var(--mc-font); color: var(--mc-crit); }

  .failbar {
    display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin: 4px 4px 0;
    font: 500 12px/1.3 var(--mc-font); color: var(--mc-crit);
  }
  .why { min-width: 0; overflow-wrap: anywhere; }
  .lnk {
    border: 0; background: none; padding: 4px 6px; border-radius: 6px; cursor: pointer;
    font: 600 12px/1 var(--mc-font); color: var(--mc-ink);
  }
  .lnk:hover { background: rgba(255, 255, 255, 0.08); }
  .lnk.dim { color: var(--mc-ink2); font-weight: 500; }

  @media (pointer: coarse) {
    .acts { width: 44px; height: 44px; }
    .menu button { min-height: 44px; }
    .lnk { min-height: 44px; padding: 0 12px; }
    .actwrap { top: -6px; }
  }
  @media (max-width: 719px) { .said { max-width: 84%; } }
</style>
