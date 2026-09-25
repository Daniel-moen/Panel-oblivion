<script>
  /* The bell: notes, client picks and comments, uploads and portal visits,
     newest first (zerko/activity.py). The feed is assembled server-side from
     rows that already exist, so there is nothing to keep in sync here — poll
     the unread count once a minute while the page is open, fetch the full
     list when the sheet opens, and mark it seen once it has been shown.

     `compact` draws just the round icon button (Browse); otherwise a pill
     with the word (Overview). */
  import { onMount } from 'svelte';
  import { media } from '$lib/media.js';
  import { say } from '$lib/media.svelte.js';
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';

  let { compact = false } = $props();

  let open = $state(false);
  let feed = $state(null);          // { events, unread, seen_at }
  let loading = $state(false);
  let unread = $state(0);
  let timer;

  async function poll() {
    try {
      const f = await media.activity();
      unread = f?.unread || 0;
      if (!open) feed = f;
    } catch { /* a bell that cannot ring just stays quiet */ }
  }

  onMount(() => {
    poll();
    timer = setInterval(() => { if (!document.hidden) poll(); }, 60000);
    return () => clearInterval(timer);
  });

  async function show() {
    open = true;
    loading = !feed;
    try { feed = await media.activity(); }
    catch (e) { say(e.message, 'error'); }
    finally { loading = false; }
    // Seen once it has been on screen, not before: the unread dots stay on
    // the lines for this viewing, the badge goes.
    if (unread) {
      try { await media.activitySeen(); unread = 0; } catch { /* next poll retries */ }
    }
  }

  /* The backend stores naive UTC; without a zone JS would read it as local. */
  const when = (s) => {
    if (!s) return '';
    const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + 'Z');
    const mins = Math.round((Date.now() - d.getTime()) / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const h = Math.round(mins / 60);
    if (h < 24) return `${h}h ago`;
    const days = Math.round(h / 24);
    if (days < 7) return `${days}d ago`;
    return d.toLocaleDateString('en-ZA', { day: 'numeric', month: 'short' });
  };

  const ICON = { note: 'message', pick: 'star', comment: 'chat', upload: 'upload',
                 share_view: 'eye', download: 'download', done: 'check' };

  function line(e) {
    const who = e.who || 'Someone';
    const f = e.filename || 'a file';
    const on = e.share_title ? ` on ${e.share_title}` : '';
    switch (e.kind) {
      case 'note': return `${who} noted on ${f}`;
      case 'pick': return `${who} picked ${f}${on}`;
      case 'comment': return `${who} commented on ${f}${on}`;
      case 'upload': return e.count > 1 ? `${who} uploaded ${e.count} files` : `${who} uploaded ${f}`;
      case 'share_view': return `${who} opened ${e.share_title || 'a share link'}`;
      case 'download':
        return e.text ? `${who} downloaded ${e.text}${on}`
          : `${who} downloaded ${e.count > 1 ? e.count + ' files' : f}${on}`;
      case 'done': return `${who} marked ${e.share_title || 'a share link'} done`;
      default: return `${who} · ${e.kind}`;
    }
  }

  const quote = (e) => (['note', 'comment', 'done'].includes(e.kind) && e.text ? e.text : null);

  function href(e) {
    if (e.media_id && ['note', 'pick', 'comment', 'upload'].includes(e.kind)) return `/media/browse?open=${e.media_id}`;
    if (e.share_id) return '/media/shares';
    if (e.media_id) return `/media/browse?open=${e.media_id}`;
    return null;
  }
</script>

<button type="button" class="bell mg-btn secondary {compact ? 'icon' : ''} sm"
        onclick={show} aria-label={unread ? `Activity, ${unread} unread` : 'Activity'} title="Activity">
  <Icon name="bell" size={15} />
  {#if !compact}<span>Activity</span>{/if}
  {#if unread}<span class="badge mg-tnum">{unread > 99 ? '99+' : unread}</span>{/if}
</button>

<Sheet open={open} title="Activity" size="sm" onclose={() => (open = false)}>
  {#if loading}
    {#each Array(5) as _, i (i)}
      <div class="sk"><Skeleton h="14px" w="80%" delay={i * 60} /><Skeleton h="11px" w="40%" delay={i * 60} /></div>
    {/each}
  {:else if !feed?.events?.length}
    <Empty icon="bell" title="No activity yet" hint="Notes, client picks, comments and uploads show up here." />
  {:else}
    <ul class="list">
      {#each feed.events as e (e.id)}
        {@const to = href(e)}
        <li class:unread={e.unread}>
          <span class="ic"><Icon name={ICON[e.kind] || 'bell'} size={14} /></span>
          <svelte:element this={to ? 'a' : 'div'} class="body" href={to}
                          onclick={() => { if (to) open = false; }} role={to ? undefined : 'presentation'}>
            <b>{line(e)}</b>
            {#if quote(e)}<q>{quote(e)}</q>{/if}
            <time>{when(e.at)}</time>
          </svelte:element>
        </li>
      {/each}
    </ul>
  {/if}
</Sheet>

<style>
  .bell { position: relative; }
  .badge {
    position: absolute; top: -5px; right: -5px; min-width: 18px; height: 18px;
    padding: 0 5px; border-radius: 9999px; display: grid; place-items: center;
    background: var(--mc-crit); color: var(--mc-ink); font: 700 10.5px/1 var(--mc-font);
    box-shadow: 0 0 0 2px var(--mc-bg);
  }
  @media (pointer: coarse) {
    .bell { height: 44px; }
    .bell.icon { width: 44px; }
  }

  .sk { display: grid; gap: 6px; padding: 10px 2px; }

  .list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
  li { display: grid; grid-template-columns: 30px minmax(0, 1fr); gap: 10px; align-items: start;
       padding: 8px 6px; border-radius: var(--mc-r-md); position: relative; }
  li.unread { background: var(--mc-ok-soft); }
  li.unread::after { content: ''; position: absolute; right: 10px; top: 14px; width: 7px; height: 7px;
                     border-radius: 50%; background: var(--mc-accent); }
  .ic { width: 30px; height: 30px; border-radius: var(--mc-r-sm); display: grid; place-items: center;
        background: var(--mc-surface); border: 1px solid var(--mc-line); color: var(--mc-ink2); }
  .body { display: flex; flex-direction: column; gap: 2px; min-width: 0; padding-right: 14px;
          color: inherit; text-decoration: none; }
  a.body:hover b { color: var(--mc-accent); }
  .body b { font: 500 13px/1.4 var(--mc-font); color: var(--mc-ink); overflow-wrap: anywhere; }
  .body q { font: 400 12.5px/1.45 var(--mc-font); color: var(--mc-ink2); overflow-wrap: anywhere; }
  .body time { font: 400 11.5px/1.3 var(--mc-font); color: var(--mc-ink3); }
</style>
