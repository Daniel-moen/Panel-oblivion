<script>
  /* One portal: what it is, whether it is live, whether the client has said
     they are done — and, one tap down, what they did with it.

     The detail panel mounts one section at a time, so opening a card costs a
     single request, not five. */
  import { play, fadeIn, staggerIn } from '$lib/motion.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import { say } from '$lib/media.svelte.js';
  import { portals, portalLink, kindOf, KINDS, when, day } from '$lib/media/portals.js';
  import PortalPicks from './PortalPicks.svelte';
  import PortalPins from './PortalPins.svelte';
  import PortalActivity from './PortalActivity.svelte';
  import PortalInbox from './PortalInbox.svelte';
  import PortalEdit from './PortalEdit.svelte';

  let { share: s, shootName = null, folders = [], watermarks = [], canOrganise = false,
        onchanged, delay = 0 } = $props();

  let tab = $state(null);
  let copied = $state(false);

  const kind = $derived(kindOf(s));
  const kindMeta = $derived(KINDS.find((k) => k.value === kind));
  const link = $derived(portalLink(s.token));
  const life = $derived(s.revoked ? { t: '', l: 'off' } : s.expired ? { t: 'warn', l: 'expired' } : { t: 'ok', l: 'live' });

  const tabs = $derived([
    ...(kind !== 'receive' ? [{ value: 'picks', label: 'Picks', icon: 'star', count: s.selects || null },
                              { value: 'pins', label: 'Pins', icon: 'pin' }] : []),
    ...(s.intake_folder_id ? [{ value: 'inbox', label: 'Inbox', icon: 'inbox', count: s.intake_waiting || null }] : []),
    { value: 'activity', label: 'Activity', icon: 'eye' },
    ...(!s.revoked ? [{ value: 'settings', label: 'Settings', icon: 'sliders' }] : [])
  ]);

  async function copy() {
    try { await navigator.clipboard.writeText(link); }
    catch {
      const ta = document.createElement('textarea');
      ta.value = link; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); } catch { /* give up quietly */ }
      ta.remove();
    }
    copied = true;
    say('Link copied');
    setTimeout(() => (copied = false), 2200);
  }

  async function revoke() {
    if (!confirm('Turn this link off? Anyone holding it loses access immediately.')) return;
    try { await portals.revoke(s.id); say('Link turned off'); onchanged?.(); }
    catch (e) { say(e.message, 'error'); }
  }
</script>

<article class="mg-card sh" in:staggerIn|global={{ i: Math.round(delay / 60) }}>
  <div class="ch">
    <span class="kind" title={kindMeta?.hint}><Icon name={kindMeta?.icon || 'share'} size={14} /></span>
    <h3>{s.title || 'Untitled portal'}</h3>
    <span class="mg-chip {life.t}"><span class="dot"></span>{life.l}</span>
    <span class="mg-chip">{kindMeta?.label || kind}</span>
    {#if s.has_password}<span class="mg-chip" title="Password protected"><Icon name="lock" size={12} /></span>{/if}
  </div>

  <p class="meta">
    {#if shootName}<span class="w"><Icon name="camera" size={13} />{shootName}</span>{/if}
    {#if s.folder && kind !== 'receive'}<span class="w"><Icon name="folder" size={13} />{s.folder}</span>{/if}
    {#if s.created_at}<span class="w mg-tnum">made {day(s.created_at)}{s.created_by ? ` by ${s.created_by}` : ''}</span>{/if}
    <span class="w mg-tnum">{s.expires_at ? `expires ${day(s.expires_at)}` : 'no expiry'}</span>
    {#if s.last_viewed_at}<span class="w mg-tnum">last opened {when(s.last_viewed_at)}</span>{/if}
  </p>

  {#if s.confirmed_at}
    <div class="done">
      <Icon name="check" size={14} />
      <span><b>Client said done</b> {when(s.confirmed_at)}{s.confirmed_by ? ` · ${s.confirmed_by}` : ''}</span>
    </div>
  {/if}

  <div class="urlrow">
    <code title={link}>{link}</code>
    <button class="mg-btn secondary sm" onclick={copy}>
      {#if copied}<Icon name="check" size={14} />Copied{:else}<Icon name="copy" size={14} />Copy{/if}
    </button>
    <a class="mg-btn secondary sm" href={link} target="_blank" rel="noopener">
      <Icon name="external" size={13} />Open
    </a>
  </div>

  <div class="chips">
    {#if kind !== 'receive'}<span class="mg-chip"><b class="mg-tnum">{s.count ?? '—'}</b> files</span>{/if}
    <span class="mg-chip"><b class="mg-tnum">{s.views ?? 0}</b> views</span>
    {#if kind !== 'receive'}<span class="mg-chip {s.selects ? 'ok' : ''}"><b class="mg-tnum">{s.selects ?? 0}</b> picked</span>{/if}
    {#if s.intake_folder_id}<span class="mg-chip {s.intake_waiting ? 'warn' : ''}"><b class="mg-tnum">{s.uploads ?? 0}</b> received{#if s.intake_waiting}{' · '}{s.intake_waiting} to file{/if}</span>{/if}
    {#if kind !== 'receive'}
      {#if s.allow_download}<span class="mg-chip">downloads{s.allow_zip ? ' + zip' : ', one by one'}</span>{/if}
      {#if s.watermark_previews}<span class="mg-chip">watermarked{s.watermark_name ? ` · ${s.watermark_name}` : ''}</span>{/if}
    {/if}
  </div>

  <div class="acts">
    <div class="tabs mg-noscroll">
      <Seg label="Portal details" value={tab} options={tabs}
           onchange={(v) => (tab = tab === v ? null : v)} />
    </div>
    {#if !s.revoked}
      <button class="mg-btn sm danger drop" onclick={revoke}><Icon name="x" size={13} />Turn off</button>
    {/if}
  </div>

  {#if tab}
    <div class="panel" transition:play={fadeIn}>
      {#key tab}
        {#if tab === 'picks'}<PortalPicks share={s} />
        {:else if tab === 'pins'}<PortalPins share={s} />
        {:else if tab === 'inbox'}<PortalInbox share={s} {folders} {canOrganise} onfiled={onchanged} />
        {:else if tab === 'activity'}<PortalActivity share={s} />
        {:else if tab === 'settings'}<PortalEdit share={s} {watermarks} {onchanged} />{/if}
      {/key}
    </div>
  {/if}
</article>

<style>
  .sh { padding: 15px 16px; min-width: 0; }
  .ch { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 4px; }
  .ch h3 { margin: 0; min-width: 0; font: 600 15px/1.25 var(--mc-font); letter-spacing: -0.01em;
           color: var(--mc-ink); overflow-wrap: anywhere; }
  .kind { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 8px; flex: none;
          background: var(--mc-raised); border: 1px solid var(--mc-line); color: var(--mc-ink2); }

  .meta { margin: 0 0 10px; display: flex; flex-wrap: wrap; gap: 4px 12px;
          font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); }
  .meta .w { display: inline-flex; align-items: center; gap: 5px; min-width: 0; overflow-wrap: anywhere; }

  .done { display: flex; align-items: center; gap: 8px; margin: 0 0 10px; padding: 8px 12px;
          border-radius: var(--mc-r-md); background: var(--mc-ok-soft);
          border: 1px solid var(--mc-ok-line); color: var(--mc-accent);
          font: 400 12.5px/1.4 var(--mc-font); }
  .done span { color: var(--mc-ink2); }
  .done b { color: var(--mc-accent); font-weight: 600; }

  .urlrow { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
  code { flex: 1 1 200px; min-width: 0; height: 40px; display: flex; align-items: center;
         padding: 0 12px; border-radius: var(--mc-r-md); background: var(--mc-inset); border: 1px solid var(--mc-line);
         font: 11.5px/1 var(--mc-mono); color: var(--mc-ink2);
         overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .urlrow .mg-btn { min-height: 40px; }
  @media (max-width: 560px) { .urlrow code { flex-basis: 100%; } .urlrow .mg-btn { flex: 1; } }

  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
  .chips b { color: var(--mc-ink); font-weight: 600; }

  .acts { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .tabs { overflow-x: auto; max-width: 100%; }
  .drop { margin-left: auto; min-height: 40px; }
  @media (pointer: coarse) { .urlrow .mg-btn, .drop { min-height: 44px; } }

  .panel { margin-top: 13px; padding-top: 13px; border-top: 1px solid var(--mc-line); min-width: 0; }
</style>
