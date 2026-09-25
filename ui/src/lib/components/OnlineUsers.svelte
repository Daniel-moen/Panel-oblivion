<script>
  /* Who is here, and what they are busy with.

     One line per person: avatar with a status dot (accent = online, warn =
     away, muted = offline), name and role, then the honest sentence — the
     page they are on and the device for someone online, "last seen 3 h ago"
     for someone who is not — and, when they have pressed "I'm on it" on a
     task, "Busy with: …" under it.

     Admins also get each person's signed-in browsers (device, since, last
     beat, page) and a Sign out on each; team.py refuses to touch the
     owner's, and another admin's unless you are the owner. Members are
     handed a roster with no sessions in it at all, so nothing here has to
     hide anything.

     Reads `roster` from presence.svelte.js and subscribes to its 30 s poll
     while mounted. */
  import { onMount } from 'svelte';
  import { roster, watchRoster, loadRoster, agoShort, STATUS_LABEL } from '$lib/presence.svelte.js';
  import { toast } from '$lib/state.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';

  let open = $state(new Set());     // user ids with the sessions list unfolded
  let busy = $state(null);          // session id being revoked

  onMount(() => watchRoster(30));

  function toggle(uid) {
    if (open.has(uid)) open.delete(uid); else open.add(uid);
    open = new Set(open);
  }

  async function revoke(s, u) {
    if (busy) return;
    if (!confirm(`Sign ${u.display_name}'s ${s.label} out now?`)) return;
    busy = s.id;
    try {
      const r = await import('$lib/api.js').then((m) => m.api.revokeAnySession(s.id));
      if (r.self) { location.href = '/login'; return; }
      toast('Signed out.');
      await loadRoster();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      busy = null;
    }
  }

  function line(u) {
    if (u.status === 'online') {
      const bits = [u.page_title || 'Home'];
      if (u.device) bits.push(u.device);
      return `Online · ${bits.join(' · ')}`;
    }
    if (u.status === 'away') return `Away · last active ${agoShort(u.seconds_ago)}`;
    if (u.disabled) return 'Account disabled';
    return u.seconds_ago == null ? 'Never signed in' : `Last seen ${agoShort(u.seconds_ago)}`;
  }

  const day = (iso) => (iso ? String(iso).slice(0, 10) : '');
  const ROLE = { owner: 'Owner', admin: 'Admin', member: 'Member' };
</script>

<section class="mg-section ou" aria-label="People">
  {#if !roster.loaded}
    <p class="mg-hint pad">{roster.error ? roster.error : 'Loading…'}</p>
  {:else}
    <ul class="mg-list people">
      {#each roster.users as u (u.id)}
        <li class="person {u.status}" class:off={u.disabled}>
          <div class="main">
            <span class="av" aria-hidden="true">
              <span class="ini">{u.initials}</span>
              <span class="mg-dot dot" class:ok={u.status === 'online'} class:warn={u.status === 'away'}>
                {#if u.status === 'online'}<i class="mg-ping"></i>{/if}
              </span>
            </span>
            <div class="who">
              <div class="nm">
                <b>{u.display_name}</b>
                {#if u.is_me}<span class="tag you">you</span>{/if}
                <span class="tag">{ROLE[u.role] || u.role}</span>
              </div>
              <div class="ln"><span class="st">{STATUS_LABEL[u.status]}</span>{line(u).slice(STATUS_LABEL[u.status].length)}</div>
              {#if u.busy.length}
                {#each u.busy as b (b.id)}
                  <div class="busy">
                    <Icon name="bolt" size={12} />
                    <span>Busy with: <b>{b.title}</b>{#if b.property}<i> · {b.property.label}</i>{/if}</span>
                  </div>
                {/each}
              {:else if u.open_tasks && u.status !== 'offline'}
                <div class="busy quiet">{u.open_tasks} open task{u.open_tasks === 1 ? '' : 's'}, none started</div>
              {/if}
            </div>
            {#if roster.is_admin && u.sessions}
              <button type="button" class="mg-btn sm ghost ses" onclick={() => toggle(u.id)} aria-expanded={open.has(u.id)}
                      disabled={!u.sessions.length} title="Signed-in browsers">
                <Icon name="key" size={14} />
                <span class="mg-mono">{u.sessions.length}</span>
                <Icon name={open.has(u.id) ? 'chevronUp' : 'chevronDown'} size={13} />
              </button>
            {/if}
          </div>

          {#if roster.is_admin && open.has(u.id) && u.sessions?.length}
            <ul class="sessions">
              {#each u.sessions as s (s.id)}
                <li class="sess">
                  <span class="mg-dot sm" class:ok={s.status === 'online'} class:warn={s.status === 'away'}></span>
                  <div class="sw">
                    <b>{s.label}{#if s.current}<span class="tag you">this browser</span>{/if}</b>
                    <i>signed in {day(s.created_at)} · {s.status === 'offline' ? 'last seen ' + agoShort((new Date(roster.now) - new Date(s.last_seen_at)) / 1000) : (s.page || '/')}</i>
                  </div>
                  <button type="button" class="mg-btn sm danger" onclick={() => revoke(s, u)} disabled={busy === s.id}>Sign out</button>
                </li>
              {/each}
            </ul>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  /* One .mg-section, one hairline-divided row per person. State is carried
     by .mg-dot (ok = online, warn = away, plain = offline) and the status
     word; everything else is ink on the surface. */
  .pad { padding: 14px 16px; }
  .people { list-style: none; margin: 0; padding: 0; }
  .person { padding: 10px 16px; }
  .person.off { opacity: 0.55; }
  .main { display: flex; align-items: center; gap: 12px; min-height: 44px; }

  .av { position: relative; flex: none; width: 40px; height: 40px; }
  .ini {
    width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center;
    background: var(--mc-raised); border: 1px solid var(--mc-line2);
    font: 600 13px/1 var(--mc-font); letter-spacing: 0.02em; color: var(--mc-ink2);
  }
  .online .ini { color: var(--mc-ink); border-color: var(--mc-ok-line); }
  .dot { position: absolute; right: -1px; bottom: -1px; width: 11px; height: 11px; box-shadow: 0 0 0 2px var(--mc-surface); }

  .who { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .nm { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .nm b { font: 600 13.5px/1.35 var(--mc-font); letter-spacing: -0.01em; color: var(--mc-ink); }
  .tag {
    display: inline-flex; align-items: center; height: 20px; padding: 0 7px; border-radius: 9999px;
    background: var(--mc-raised); border: 1px solid var(--mc-line);
    font: 500 10.5px/1 var(--mc-mono); color: var(--mc-ink3); text-transform: uppercase; letter-spacing: 0.04em;
  }
  .tag.you { color: var(--mc-accent); border-color: var(--mc-ok-line); background: var(--mc-ok-soft); text-transform: none; letter-spacing: 0; }
  .ln { font: 400 12.5px/1.4 var(--mc-font); color: var(--mc-ink3); }
  .st { font-weight: 500; color: var(--mc-ink3); }
  .online .st { color: var(--mc-accent); }
  .away .st { color: var(--mc-warn); }
  .busy { display: flex; align-items: center; gap: 6px; margin-top: 2px; font: 400 12.5px/1.4 var(--mc-font); color: var(--mc-ink2); }
  .busy :global(svg) { color: var(--mc-accent); flex: none; }
  .busy b { font-weight: 500; color: var(--mc-ink); }
  .busy i { font-style: normal; color: var(--mc-ink3); }
  .busy.quiet { color: var(--mc-ink3); }

  .ses { color: var(--mc-ink3); }
  .ses:hover:not(:disabled) { color: var(--mc-ink); }

  .sessions { list-style: none; margin: 8px 0 2px 52px; padding: 0; display: flex; flex-direction: column; gap: 4px; }
  .sess {
    display: flex; align-items: center; gap: 10px; min-height: 44px; padding: 4px 4px 4px 10px;
    border-radius: var(--mc-r-sm); background: var(--mc-raised); border: 1px solid var(--mc-line);
  }
  .sw { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .sw b { font: 500 13px/1.35 var(--mc-font); color: var(--mc-ink); display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .sw i { font: 400 11.5px/1.35 var(--mc-font); font-style: normal; color: var(--mc-ink3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  @media (max-width: 480px) {
    .sessions { margin-left: 0; }
    .sw i { white-space: normal; }
  }
</style>
