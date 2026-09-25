<script>
  /* Who you are in the media library, and what that lets you do.

     Media roles are not managed here: they follow the dashboard's People
     page (media + admin → Admin, media → Editor), and Zerko's own sign-in,
     sign-up and user admin are switched off at the mount. */
  import SettingsCard from './SettingsCard.svelte';

  let { who = null, error = '' } = $props();

  const CAP_TEXT = {
    'media.read': 'Browse and play the library',
    'media.download': 'Download originals',
    'media.upload': 'Upload and export new files',
    'media.organise': 'Move, rename and make folders',
    'media.annotate': 'Tag, rate, note and edit photos',
    'media.trash': 'Move files to the trash',
    'media.harddelete': 'Empty the trash for good',
    'jobs.transcribe': 'Start transcriptions',
    'jobs.proxy': 'Build and cancel proxies',
    'shares.manage': 'Make and manage client portals',
    'shoots.manage': 'Run shoots, deliveries and captions',
    'users.create_clients': 'Invite clients (off here — accounts come from People)',
    admin: 'Server settings, AI keys, library checks and tag rules'
  };
  const ORDER = Object.keys(CAP_TEXT);
  const caps = $derived([...(who?.capabilities || [])].sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b)));
  const missing = $derived(ORDER.filter((c) => !caps.includes(c) && c !== 'users.create_clients'));
</script>

<SettingsCard label="Access">
  <div class="set mg-panel">
    <div class="l">
      <b>{who?.username || 'Signed in'}</b>
      <span class="hint">
        {#if error}Could not read your role: {error}
        {:else}Your media role comes from the dashboard's <a href="/account">People</a> page (Account):
          <b>media + admin</b> is an Admin here, <b>media</b> alone is an Editor. Zerko's own logins are disabled.{/if}
      </span>
    </div>
    <span class="mg-chip {who?.role === 'admin' ? 'ok' : ''}"><span class="dot"></span>{who?.role_label || who?.role || '—'}</span>
  </div>

  {#if caps.length}
    <div class="pane mg-panel">
      <ul class="caps">
        {#each caps as c (c)}
          <li class="yes"><span class="tick" aria-hidden="true">✓</span>{CAP_TEXT[c] || c}</li>
        {/each}
        {#each missing as c (c)}
          <li class="no"><span class="tick" aria-hidden="true">–</span>{CAP_TEXT[c]}</li>
        {/each}
      </ul>
    </div>
  {/if}
</SettingsCard>

<style>
  .caps { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px 16px;
          grid-template-columns: repeat(auto-fill, minmax(min(100%, 250px), 1fr)); }
  li { display: flex; gap: 8px; align-items: baseline; font: 400 12.5px/1.45 var(--mc-font); color: var(--mc-ink); }
  li.no { color: var(--mc-ink3); }
  .tick { flex: none; width: 14px; color: var(--mc-accent); font-weight: 700; }
  li.no .tick { color: var(--mc-ink3); }
  a { color: var(--mc-accent); text-decoration: underline; text-underline-offset: 2px; }
  .hint b { color: var(--mc-ink2); font-weight: 500; }
</style>
