<script>
  /* Library check (admin): does every catalogue row still have its file, and
     is there anything on the drive the catalogue doesn't know about?

     A missing file with exactly one same-named, same-sized candidate
     elsewhere is almost certainly the same file somebody moved, so it can be
     relinked in one tap. A row whose file is truly gone can be cleared (the
     backend refuses to clear a row whose file is actually present). */
  import { onMount } from 'svelte';
  import { say } from '$lib/media.svelte.js';
  import { fmtBytes } from '$lib/media.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import SettingsCard from './SettingsCard.svelte';
  import { settingsApi as api } from './api.js';

  let st = $state(null);
  let busy = $state(false);
  let timer = null;

  async function poll() {
    try { st = await api.libraryStatus(); } catch (e) { say(e.message, 'error'); return; }
    clearTimeout(timer);
    if (st.running) timer = setTimeout(poll, 1500);
  }

  onMount(() => { poll(); return () => clearTimeout(timer); });

  async function run() {
    try { await api.libraryCheck(); say('Checking the library…'); poll(); }
    catch (e) { say(e.message, 'error'); }
  }

  async function apply(body, what) {
    busy = true;
    try {
      const r = await api.libraryApply(body);
      say(`${what}: ${r.relinked} relinked, ${r.cleared} cleared` + (r.errors?.length ? ` — ${r.errors[0]}` : ''),
          r.errors?.length ? 'error' : 'ok');
      await poll();
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }

  const relinkable = $derived((st?.missing || []).filter((m) => m.suggestion));
  const pct = $derived(st?.running && st.total ? Math.round((st.checked / st.total) * 100) : null);
  const short = (p) => String(p || '').split('/').slice(-3).join('/');
</script>

<SettingsCard label="Library check">
  <div class="set mg-glass-soft">
    <div class="l">
      <b>Check files against the catalogue</b>
      <span class="hint">{st?.message || 'Not run yet'}{st?.finished_at && !st.running ? ' · last run ' + st.finished_at.slice(0, 16).replace('T', ' ') + ' UTC' : ''}</span>
    </div>
    <button class="mg-btn secondary sm" onclick={run} disabled={!st || st.running}>
      <Icon name="refresh" size={14} />{st?.running ? 'Checking…' : 'Run'}
    </button>
  </div>

  {#if st?.running}
    <div class="mg-bar" class:indeterminate={pct == null}><i style:width={pct != null ? pct + '%' : null}></i></div>
  {/if}

  {#if st && !st.running && st.missing?.length}
    <div class="pane mg-glass-soft">
      <div class="hd">
        <b>{st.missing.length} missing</b>
        {#if relinkable.length}
          <button class="mg-btn primary sm" disabled={busy}
                  onclick={() => apply({ relink: relinkable.map((m) => ({ id: m.id, path: m.suggestion })) }, 'Relinked')}>
            <Icon name="link" size={13} />Relink all {relinkable.length}
          </button>
        {/if}
      </div>
      <ul class="rows">
        {#each st.missing as m (m.id)}
          <li>
            <span class="nm">
              <b title={m.filepath}>{m.filename}</b>
              <small>{m.suggestion ? `Found at …/${short(m.suggestion)}` : `Was at …/${short(m.filepath)}`}{m.size ? ' · ' + fmtBytes(m.size) : ''}</small>
            </span>
            {#if m.suggestion}
              <button class="mg-btn secondary sm" disabled={busy}
                      onclick={() => apply({ relink: [{ id: m.id, path: m.suggestion }] }, 'Relinked')}>Relink</button>
            {:else}
              <button class="mg-btn ghost sm" disabled={busy}
                      onclick={() => confirm(`Forget ${m.filename}? Its tags, notes and transcript go with it.`) && apply({ clear: [m.id] }, 'Cleared')}>Forget</button>
            {/if}
          </li>
        {/each}
      </ul>
    </div>
  {/if}

  {#if st && !st.running && st.unindexed_count}
    <div class="pane mg-glass-soft">
      <div class="hd"><b>{st.unindexed_count} on disk but not in the library</b></div>
      <ul class="rows">
        {#each st.unindexed.slice(0, 12) as p (p)}<li><span class="nm"><small title={p}>…/{short(p)}</small></span></li>{/each}
      </ul>
      <p class="note">Re-index the drive (Maintenance, below) to pick these up.</p>
    </div>
  {/if}
</SettingsCard>

<style>
  .mg-bar { margin: 4px 2px 8px; }
  .hd { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
  .hd b { flex: 1; font: 600 13.5px/1.2 var(--mg-font); color: var(--mg-i); }
  .rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px;
          max-height: 300px; overflow-y: auto; }
  .rows li { display: flex; align-items: center; gap: 10px; min-height: 40px; }
  .nm { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .nm b { font: 500 12.5px/1.3 var(--mg-font); color: var(--mg-i); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .nm small { font: 11.5px/1.4 var(--mg-mono); color: var(--mg-i3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .rows .mg-btn { flex: none; min-height: 36px; }
</style>
