<script>
  /* How long a trashed file waits before it is deleted for good. Needs the
     hard-delete capability, because that is exactly what it schedules. */
  import { onMount } from 'svelte';
  import { say } from '$lib/media.svelte.js';
  import { fmtBytes } from '$lib/media.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import SettingsCard from './SettingsCard.svelte';
  import { settingsApi as api } from './api.js';

  let trash = $state(null);
  let days = $state('0');
  let busy = $state(false);

  onMount(async () => {
    try { trash = await api.trash(); days = String(trash.auto_days || 0); }
    catch (e) { say(e.message, 'error'); }
  });

  const OPTIONS = [0, 7, 14, 30, 60, 90];

  async function save() {
    busy = true;
    try {
      const r = await api.saveTrash(Number(days));
      trash = { ...trash, auto_days: r.auto_days };
      say(r.auto_days ? `Trash empties itself after ${r.auto_days} days` : 'Trash will only empty by hand');
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }
</script>

<SettingsCard label="Trash">
  <div class="set mg-panel">
    <div class="l">
      <b>Empty the trash automatically</b>
      <span class="hint">
        {#if trash}{trash.count} file{trash.count === 1 ? '' : 's'} in the trash now ({fmtBytes(trash.total_size)}).{/if}
        Files older than this are deleted from disk for good, once an hour.
      </span>
    </div>
    <div class="btnrow">
      <div class="mg-select">
        <select bind:value={days} aria-label="Auto-empty after">
          {#each OPTIONS as d (d)}<option value={String(d)}>{d ? `After ${d} days` : 'Never'}</option>{/each}
          {#if !OPTIONS.includes(Number(days))}<option value={days}>After {days} days</option>{/if}
        </select>
        <span class="ic"><Icon name="chevronDown" size={15} /></span>
      </div>
      <button class="mg-btn secondary sm" onclick={save}
              disabled={busy || !trash || Number(days) === (trash.auto_days || 0)}>Save</button>
    </div>
  </div>
</SettingsCard>
