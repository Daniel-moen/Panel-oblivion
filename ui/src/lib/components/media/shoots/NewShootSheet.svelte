<script>
  /* Book a shoot: POST /api/shoots. Used by the list and by the calendar
     (which passes the day that was tapped). A library folder can be linked
     at the same time — the suggestions are top-level folders that are not on
     a shoot yet (/api/shoots/suggest/folders). */
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import ShootForm from './ShootForm.svelte';
  import { shoots, folderName } from '$lib/media/shoots.js';

  let { open = false, date = '', near = null, onclose, oncreated } = $props();

  const blank = () => ({ address: '', suburb: '', agent: '', shoot_date: date || '', shoot_time: '',
                         note: '', lat: null, lng: null });
  let form = $state(blank());
  let agents = $state([]);
  let suggestions = $state([]);
  let folder = $state('');
  let busy = $state(false);
  let err = $state('');

  /* Fresh form every time it opens (with the calendar's day). */
  $effect(() => {
    if (!open) return;
    form = blank();
    folder = ''; err = '';
    shoots.agents().then((r) => (agents = r?.agents || [])).catch(() => {});
    shoots.suggestFolders().then((r) => (suggestions = r?.suggestions || [])).catch(() => {});
  });

  function useSuggestion(path) {
    folder = path;
    const s = suggestions.find((x) => x.path === path);
    if (s && !form.address.trim()) form.address = s.suggested_address;
  }

  async function submit(e) {
    e?.preventDefault();
    if ((form.address || '').trim().length < 3) { err = 'The address needs at least three characters.'; return; }
    busy = true; err = '';
    try {
      const body = {
        address: form.address.trim(),
        suburb: form.suburb || null,
        agent: form.agent || null,
        shoot_date: form.shoot_date || null,
        shoot_time: form.shoot_time || null,
        note: form.note || null,
        folders: folder ? [folder] : []
      };
      if (form.lat != null && form.lng != null) { body.lat = form.lat; body.lng = form.lng; }
      const made = await shoots.create(body);
      oncreated?.(made);
    } catch (e2) { err = e2.message; }
    finally { busy = false; }
  }
</script>

<Sheet {open} title="Book a shoot" {onclose}>
  <form id="new-shoot" onsubmit={submit}>
    <ShootForm bind:value={form} {agents} {near} idp="ns" />

    <div class="f">
      <label class="mg-label" for="ns-folder">Library folder (optional)</label>
      <div class="mg-select">
        <select id="ns-folder" value={folder} onchange={(e) => useSuggestion(e.currentTarget.value)}>
          <option value="">None yet — link one later</option>
          {#each suggestions as s (s.path)}<option value={s.path}>{folderName(s.path)}</option>{/each}
        </select>
        <span class="ic"><Icon name="chevronDown" size={15} /></span>
      </div>
    </div>

    {#if err}<p class="err">{err}</p>{/if}
  </form>

  {#snippet footer()}
    <div class="right">
      <button type="button" class="mg-btn ghost" onclick={() => onclose?.()}>Cancel</button>
      <button type="submit" form="new-shoot" class="mg-btn primary" disabled={busy}>
        {#if busy}<span class="mg-spin"></span>{:else}<Icon name="plus" size={15} />{/if}Book it
      </button>
    </div>
  {/snippet}
</Sheet>

<style>
  .f { display: flex; flex-direction: column; gap: 5px; margin-top: 12px; }
  .mg-select { display: block; }
  .err { margin: 12px 0 0; font: 400 12.5px/1.45 var(--mc-font); color: var(--mc-crit); }
</style>
