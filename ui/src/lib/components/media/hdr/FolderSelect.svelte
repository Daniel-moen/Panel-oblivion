<script>
  /* A library folder, as a glass select. The flat /api/folders list already
     carries each folder's path relative to the drive, which reads better than
     an indented tree in a native select. */
  import { onMount } from 'svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import { media } from '$lib/media.js';

  let { value = null, onchange, allowAll = false, label = 'Folder', placeholder = 'Choose a folder…' } = $props();

  let folders = $state([]);

  onMount(async () => {
    try {
      const all = (await media.folders()) || [];
      folders = all
        .filter((f) => !String(f.relative_path || f.name).split('/').some((p) => p.startsWith('_') || p.startsWith('.')))
        .sort((a, b) => String(a.relative_path || a.name).localeCompare(String(b.relative_path || b.name)));
    } catch { folders = []; }
  });
</script>

<span class="mg-select fs">
  <select aria-label={label} value={value == null ? '' : String(value)}
          onchange={(e) => onchange?.(e.currentTarget.value === '' ? null : Number(e.currentTarget.value))}>
    <option value="">{allowAll ? 'All folders' : placeholder}</option>
    {#each folders as f (f.id)}
      <option value={String(f.id)}>{f.relative_path || f.name}{f.video_count ? ` (${f.video_count})` : ''}</option>
    {/each}
  </select>
  <span class="ic"><Icon name="chevronDown" size={15} /></span>
</span>

<style>
  .fs { flex: 1 1 220px; max-width: 100%; }
  .fs > select { width: 100%; }
</style>
