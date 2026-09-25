<script>
  /* The composer: a textarea that grows to six lines, the @ people picker,
     the "+" attach menu (property · media · link) and the chips of what is
     waiting to go. Text, attachments and picked mentions are kept per
     channel in the store's drafts, so switching channels loses nothing.

     Keys: on a keyboard, Enter sends and Shift+Enter is a new line; on a
     touch screen (pointer: coarse) Enter is a new line and the button sends.
     With the picker open, ↑/↓ move, Enter/Tab pick, Escape closes. */
  import { tick } from 'svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import PropertyPick from '$lib/components/PropertyPick.svelte';
  import MediaPicker from './MediaPicker.svelte';
  import { chat, send, addAttachment, removeAttachment, mentionText, loadPeople } from '$lib/chat.svelte.js';
  import { me } from '$lib/me.svelte.js';
  import { isHttp, domainOf, initials } from './text.js';

  let { channelId, disabled = false } = $props();

  const d = $derived(chat.drafts[String(channelId)] || null);
  const ch = $derived(chat.channels.find((c) => c.id === channelId) || null);
  const archived = $derived(!!ch?.archived_at);

  let box = $state(null);
  let query = $state('');        // what follows the @ being typed
  let atFrom = -1;               // index of that @ in the text
  let sel = $state(0);
  let linkUrl = $state('');
  let linkTitle = $state('');
  let linkErr = $state('');
  let propPick = $state(null);

  const overlay = $derived(chat.overlay);
  /* the server refuses media attachments (403 media_forbidden) from anyone
     without the media privilege — don't offer what will bounce */
  const canMedia = $derived(me.loaded && (me.privileges || []).includes('media'));
  const peopleOpen = $derived(overlay === 'people');

  const coarse = () => typeof matchMedia !== 'undefined' && matchMedia('(pointer: coarse)').matches;

  const matches = $derived.by(() => {
    if (!peopleOpen) return [];
    const q = query.toLowerCase();
    return chat.people
      .filter((p) => !p.is_me && p.id !== chat.me?.id)
      .filter((p) => !q
        || (p.display_name || '').toLowerCase().includes(q)
        || (p.username || '').toLowerCase().includes(q))
      .sort((a, b) => {
        const as = (a.display_name || '').toLowerCase().startsWith(q) || (a.username || '').toLowerCase().startsWith(q);
        const bs = (b.display_name || '').toLowerCase().startsWith(q) || (b.username || '').toLowerCase().startsWith(q);
        return (bs ? 1 : 0) - (as ? 1 : 0) || (b.online ? 1 : 0) - (a.online ? 1 : 0);
      })
      .slice(0, 8);
  });

  const canSend = $derived(!!d && !disabled && !archived && (!!(d.text || '').trim() || d.attachments.length > 0));

  /* ——— growing ——— */
  function grow() {
    if (!box) return;
    box.style.height = 'auto';
    box.style.height = Math.min(box.scrollHeight + 2, 6 * 21 + 22) + 'px';
  }
  $effect(() => {
    d?.text;
    channelId;
    tick().then(grow);
  });

  /* ——— the @ picker ——— */
  const AT = /(^|[^\p{L}\p{N}_])@([^\s@]{0,30}(?: [^\s@]{0,30})?)$/u;

  function scanAt() {
    if (!box || !d) return;
    const upto = d.text.slice(0, box.selectionStart ?? d.text.length);
    const m = upto.match(AT);
    if (m) {
      atFrom = upto.length - m[2].length - 1;
      if (query !== m[2]) sel = 0;
      query = m[2];
      if (!chat.people.length) loadPeople();
      if (chat.overlay !== 'people' && (chat.overlay === '' || chat.overlay.startsWith('msg:'))) chat.overlay = 'people';
      /* "@dan x" with nobody matching is just text */
      if (m[2].includes(' ') && !matches.length) closePeople();
    } else {
      closePeople();
    }
  }

  function closePeople() {
    atFrom = -1;
    query = '';
    if (chat.overlay === 'people') chat.overlay = '';
  }

  async function pickPerson(p) {
    if (!d || atFrom < 0 || !box) return;
    const name = mentionText(p);
    const caret = box.selectionStart ?? d.text.length;
    const before = d.text.slice(0, atFrom);
    const after = d.text.slice(caret);
    const ins = '@' + name + ' ';
    d.text = before + ins + after.replace(/^ /, '');
    if (!d.mentions.some((x) => x.id === p.id)) d.mentions.push({ id: p.id, name });
    closePeople();
    await tick();
    const at = before.length + ins.length;
    box.focus();
    box.setSelectionRange(at, at);
    grow();
  }

  function onInput(e) {
    if (d) d.text = e.currentTarget.value;
    grow();
    scanAt();
  }

  function onKey(e) {
    if (peopleOpen && matches.length) {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = (sel + 1) % matches.length; return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); sel = (sel - 1 + matches.length) % matches.length; return; }
      if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pickPerson(matches[sel] || matches[0]); return; }
    }
    if (e.key === 'Escape' && chat.overlay) {
      e.preventDefault();
      e.stopPropagation();
      if (peopleOpen) closePeople();
      else chat.overlay = '';
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !coarse()) {
      e.preventDefault();
      submit();
    }
  }

  function submit() {
    if (!canSend) return;
    closePeople();
    if (send(channelId)) tick().then(() => { grow(); if (!coarse()) box?.focus(); });
  }

  /* ——— attaching ——— */
  function toggleAttach(e) {
    e.stopPropagation();
    chat.overlay = overlay === 'attach' ? '' : 'attach';
  }

  async function choose(kind) {
    chat.overlay = kind;
    if (kind === 'link') {
      linkUrl = '';
      linkTitle = '';
      linkErr = '';
    }
    if (kind === 'property') propPick = null;
    await tick();
    const el = document.querySelector(kind === 'link' ? '[data-testid="chat-link-url"]' : '.propick input');
    el?.focus?.();
  }

  function addLink() {
    let u = linkUrl.trim();
    if (u && !/^[a-z][a-z0-9+.-]*:/i.test(u)) u = 'https://' + u;
    if (!isHttp(u)) { linkErr = 'Enter a web address starting with http:// or https://'; return; }
    if (u.length > 2048) { linkErr = 'That address is too long (2048 characters at most).'; return; }
    const title = linkTitle.trim().slice(0, 200);
    if (addAttachment(channelId, { type: 'link', url: u, title: title || null, domain: domainOf(u) })) {
      chat.overlay = '';
      box?.focus();
    }
  }

  function onLinkKey(e) {
    if (e.key === 'Enter') { e.preventDefault(); addLink(); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); chat.overlay = ''; box?.focus(); }
  }

  function pickedProperty(v) {
    if (!v) return;
    addAttachment(channelId, { type: 'property', gid: String(v.group_id), label: v.label, suburb: v.suburb || null });
    chat.overlay = '';
    propPick = null;
    box?.focus();
  }

  function pickedMedia(a) {
    addAttachment(channelId, a);
    chat.overlay = '';
  }

  const chipIcon = (a) => (a.type === 'property' ? 'property' : a.type === 'media' ? (a.kind === 'video' ? 'film' : 'image') : 'link');
  const chipLabel = (a) => (a.type === 'property' ? a.label || 'Property'
    : a.type === 'media' ? a.name || 'Media' : a.title || a.domain || a.url);

  export function focus() { box?.focus(); }
</script>

<div class="composer">
  {#if overlay === 'link'}
    <div class="panel" role="group" aria-label="Attach a link">
      <div class="prow">
        <input class="mg-input" type="url" inputmode="url" placeholder="https://…" bind:value={linkUrl}
               data-testid="chat-link-url" aria-label="Link address" onkeydown={onLinkKey} />
      </div>
      <div class="prow">
        <input class="mg-input" type="text" maxlength="200" placeholder="Title (optional)" bind:value={linkTitle}
               data-testid="chat-link-title" aria-label="Link title" onkeydown={onLinkKey} />
        <button type="button" class="mg-btn accent sm" data-testid="chat-link-add" onclick={addLink}>Add</button>
        <button type="button" class="mg-btn ghost icon sm" onclick={() => (chat.overlay = '')} aria-label="Cancel"><Icon name="close" size={14} /></button>
      </div>
      {#if linkErr}<span class="perr" role="alert">{linkErr}</span>{/if}
    </div>
  {:else if overlay === 'property'}
    <div class="panel" role="group" aria-label="Attach a property">
      <div class="prow propick">
        <PropertyPick bind:value={propPick} onchange={pickedProperty} placeholder="Find a property by address or suburb…" />
        <button type="button" class="mg-btn ghost icon sm" onclick={() => (chat.overlay = '')} aria-label="Cancel"><Icon name="close" size={14} /></button>
      </div>
    </div>
  {/if}

  {#if peopleOpen && matches.length}
    <ul class="people" role="listbox" data-testid="chat-people" aria-label="Mention someone">
      {#each matches as p, i (p.id)}
        <li role="option" aria-selected={i === sel} data-testid="chat-person" data-username={p.username}
            class:on={i === sel}
            onmousedown={(e) => e.preventDefault()}
            onclick={() => pickPerson(p)}
            onkeydown={(e) => { if (e.key === 'Enter') pickPerson(p); }}
            onmouseenter={() => (sel = i)}>
          <span class="av" aria-hidden="true">{p.initials || initials(p.display_name || p.username)}</span>
          <span class="pn"><b>{p.display_name || p.username}</b><i>@{p.username}</i></span>
          {#if p.online}<span class="mg-dot ok sm" aria-label="online"></span>{/if}
        </li>
      {/each}
    </ul>
  {/if}

  {#if overlay === 'attach'}
    <div class="attachmenu" role="menu" aria-label="Attach">
      <button type="button" role="menuitem" data-testid="chat-attach-opt-property" onclick={() => choose('property')}>
        <Icon name="property" size={16} /> Property
      </button>
      {#if canMedia}
        <button type="button" role="menuitem" data-testid="chat-attach-opt-media" onclick={() => choose('media')}>
          <Icon name="image" size={16} /> Media
        </button>
      {/if}
      <button type="button" role="menuitem" data-testid="chat-attach-opt-link" onclick={() => choose('link')}>
        <Icon name="link" size={16} /> Link
      </button>
    </div>
  {/if}

  {#if d?.attachments.length}
    <div class="chips" aria-label="Attachments waiting to send">
      {#each d.attachments as a, i (a.type + ':' + (a.gid ?? a.id ?? a.url))}
        <span class="chip" data-testid="chat-draft-chip" data-type={a.type}>
          <Icon name={chipIcon(a)} size={13} />
          <span class="cl">{chipLabel(a)}</span>
          <button type="button" class="cx" onclick={() => removeAttachment(channelId, i)}
                  aria-label={'Remove ' + chipLabel(a)}><Icon name="close" size={12} /></button>
        </span>
      {/each}
    </div>
  {/if}

  {#if archived}
    <p class="note">This channel is archived — read only.</p>
  {:else}
    <div class="field">
      <button type="button" class="mg-btn secondary icon plus" class:on={overlay === 'attach'}
              data-testid="chat-attach" onclick={toggleAttach} disabled={disabled || !d}
              aria-label="Attach" aria-haspopup="menu" aria-expanded={overlay === 'attach'} title="Attach a property, media or a link">
        <Icon name="plus" size={17} />
      </button>
      <textarea class="mg-input msg" bind:this={box} value={d?.text || ''} rows="1"
                data-testid="chat-input" placeholder={ch ? `Message ${ch.kind === 'property' ? '' : '#'}${ch.name}` : 'Message the team…'}
                aria-label="Message" disabled={disabled || !d} maxlength="4000"
                oninput={onInput} onkeydown={onKey} onclick={scanAt}
                onblur={() => setTimeout(() => { if (chat.overlay === 'people') closePeople(); }, 150)}></textarea>
      <button type="button" class="mg-btn accent icon send" data-testid="chat-send" onclick={submit}
              disabled={!canSend} aria-label="Send" title="Send">
        <Icon name="send" size={16} stroke={2} />
      </button>
    </div>
  {/if}
</div>

<MediaPicker open={overlay === 'media'} onclose={() => (chat.overlay = '')} onpick={pickedMedia} />

<style>
  .composer {
    position: relative; flex: none; padding: 8px 10px 10px;
    border-top: 1px solid var(--mc-line); background: #17171b;
  }
  .field { display: flex; align-items: flex-end; gap: 8px; }
  .msg {
    flex: 1; min-width: 0; min-height: 40px; height: 40px; max-height: 148px;
    padding: 9px 12px; resize: none; line-height: 21px; font-size: 14px;
    overflow-y: auto;
  }
  .plus.on { background: var(--mc-glass-on); }

  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 8px; }
  .chip {
    display: inline-flex; align-items: center; gap: 6px; max-width: 100%; height: 30px; padding: 0 2px 0 10px;
    border-radius: 9999px; background: var(--mc-glass-soft); border: 1px solid var(--mc-glass-line2);
    color: var(--mc-ink); font: 500 12px/1 var(--mc-font);
  }
  .cl { min-width: 0; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cx {
    flex: none; width: 26px; height: 26px; border: 0; border-radius: 50%; padding: 0;
    display: grid; place-items: center; background: none; color: var(--mc-ink2); cursor: pointer;
  }
  .cx:hover { background: rgba(255, 255, 255, 0.1); color: var(--mc-ink); }

  /* the pop-ups rise out of the composer; solid, not blurred — the sheet is
     the one frosted surface */
  .people, .attachmenu {
    position: absolute; left: 10px; bottom: calc(100% + 6px); z-index: 6;
    margin: 0; padding: 4px; list-style: none;
    background: #1c1c21; border: 1px solid var(--mc-glass-line2); border-radius: 14px;
    box-shadow: var(--mc-sh-2);
  }
  .people { right: 10px; max-height: 280px; overflow-y: auto; }
  .people li {
    display: flex; align-items: center; gap: 10px; min-height: 40px; padding: 6px 10px;
    border-radius: 10px; cursor: pointer; color: var(--mc-ink2);
  }
  .people li.on { background: rgba(255, 255, 255, 0.09); color: var(--mc-ink); }
  .av {
    flex: none; width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center;
    background: var(--mc-raised); border: 1px solid var(--mc-line2); font: 600 10px/1 var(--mc-font); color: var(--mc-ink2);
  }
  .pn { min-width: 0; flex: 1; display: flex; flex-direction: column; }
  .pn b { font: 500 13.5px/1.3 var(--mc-font); color: var(--mc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pn i { font: 400 11.5px/1.3 var(--mc-font); font-style: normal; color: var(--mc-ink3); }

  .attachmenu { min-width: 170px; }
  .attachmenu button {
    display: flex; align-items: center; gap: 10px; width: 100%; min-height: 40px; padding: 8px 12px;
    border: 0; border-radius: 10px; background: none; color: var(--mc-ink2);
    font: 500 13.5px/1.2 var(--mc-font); cursor: pointer; text-align: left;
  }
  .attachmenu button:hover, .attachmenu button:focus-visible { background: rgba(255, 255, 255, 0.08); color: var(--mc-ink); outline: none; }

  .panel { display: flex; flex-direction: column; gap: 6px; margin: 0 0 8px; }
  .prow { display: flex; align-items: center; gap: 6px; min-width: 0; }
  .prow .mg-input { flex: 1; min-width: 0; }
  .perr { font: 400 12px/1.4 var(--mc-font); color: var(--mc-crit); }
  /* PropertyPick's list drops down by default; at the foot of the sheet it
     has to rise instead, and without a second blur */
  .propick :global(.menu) {
    top: auto; bottom: calc(100% + 4px);
    background: #1c1c21; -webkit-backdrop-filter: none; backdrop-filter: none;
  }
  .propick :global(.pp) { flex: 1; min-width: 0; }

  .note { margin: 4px 2px; font: 400 12.5px/1.4 var(--mc-font); color: var(--mc-ink3); }

  @media (pointer: coarse) {
    .msg { min-height: 44px; height: 44px; font-size: 16px; padding: 10px 12px; }
    .send, .plus { width: 44px; height: 44px; }
    .cx { width: 36px; height: 36px; }
    .chip { height: 38px; }
    .people li, .attachmenu button { min-height: 44px; }
  }
</style>
