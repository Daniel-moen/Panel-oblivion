<script>
  /* Virtual copies of a photo (photo_edit.py): other edits of the same file
     — a twilight version, a black and white — with no second file on disk,
     as in Lightroom. A new copy starts "as shot"; the editor is where it
     gets its look, so every row links there with ?copy=. */
  import { media } from '$lib/media.js';
  import { say, can, CAP } from '$lib/media.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';

  let { clip } = $props();

  let copies = $state([]);
  let loaded = $state(false);
  let newName = $state('');
  let editing = $state(null);      // copy id being renamed
  let draft = $state('');
  let busy = $state(false);

  $effect(() => {
    const id = clip?.id;
    copies = []; loaded = false; editing = null;
    if (!id) return;
    media.copies(id).then((r) => { if (clip?.id === id) { copies = r?.copies || []; loaded = true; } })
      .catch(() => { loaded = true; });
  });

  const canEdit = $derived(can(CAP.ANNOTATE));

  async function add() {
    busy = true;
    try {
      const c = await media.newCopy(clip.id, newName.trim());
      copies = [...copies, c];
      newName = '';
      say(`Made virtual copy “${c.name}”`);
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }

  async function rename(c) {
    const name = draft.trim();
    editing = null;
    if (!name || name === c.name) return;
    try {
      const r = await media.renameCopy(clip.id, c.id, name);
      copies = copies.map((x) => (x.id === c.id ? { ...x, name: r.name } : x));
    } catch (e) { say(e.message, 'error'); }
  }

  async function remove(c) {
    if (!confirm(`Delete the virtual copy “${c.name}”? Its edit is lost; the photo is untouched.`)) return;
    try {
      await media.delCopy(clip.id, c.id);
      copies = copies.filter((x) => x.id !== c.id);
      say('Virtual copy deleted');
    } catch (e) { say(e.message, 'error'); }
  }
</script>

<section>
  <span class="mg-label">Virtual copies</span>
  {#if loaded && !copies.length}
    <p class="dim">None. A virtual copy is another edit of this photo without a second file.</p>
  {/if}
  <ul>
    {#each copies as c (c.id)}
      <li class="mg-tile">
        {#if editing === c.id}
          <input class="mg-input sm" type="text" bind:value={draft} maxlength="80"
                 aria-label="Copy name"
                 onkeydown={(e) => { if (e.key === 'Enter') rename(c); if (e.key === 'Escape') editing = null; }}
                 onblur={() => rename(c)} />
        {:else}
          <b title={c.name}>{c.name}</b>
        {/if}
        <a class="mg-btn ghost icon sm" href="/media/edit?id={clip.id}&copy={c.id}"
           title="Open in editor" aria-label="Open {c.name} in the photo editor">
          <Icon name="sliders" size={14} />
        </a>
        {#if canEdit}
          <button class="mg-btn ghost icon sm" title="Rename" aria-label="Rename {c.name}"
                  onclick={() => { editing = c.id; draft = c.name; }}>
            <Icon name="pencil" size={14} />
          </button>
          <button class="mg-btn ghost icon sm" title="Delete" aria-label="Delete {c.name}"
                  onclick={() => remove(c)}>
            <Icon name="trash" size={14} />
          </button>
        {/if}
      </li>
    {/each}
  </ul>
  {#if canEdit}
    <form onsubmit={(e) => { e.preventDefault(); add(); }}>
      <input class="mg-input" type="text" bind:value={newName} maxlength="80"
             placeholder="New copy name (optional)" aria-label="New virtual copy name" />
      <button class="mg-btn secondary sm" type="submit" disabled={busy}>
        <Icon name="plus" size={14} />Copy
      </button>
    </form>
  {/if}
</section>

<style>
  section { margin-bottom: 22px; }
  section .mg-label { margin-bottom: 8px; }
  ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
  li { display: flex; align-items: center; gap: 2px; padding: 3px 3px 3px 11px; border-radius: var(--mc-r-md); min-height: 44px; }
  li b { flex: 1; min-width: 0; font: 500 12.5px/1.3 var(--mc-font); color: var(--mc-ink);
         overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  li input { flex: 1; min-width: 0; height: 32px; }
  form { display: flex; gap: 6px; margin-top: 8px; align-items: center; }
  form input { flex: 1; min-width: 0; }
  .dim { margin: 0 0 6px; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink3); }
  @media (pointer: coarse) { li .mg-btn.icon { width: 44px; height: 44px; } form .mg-btn { height: 44px; } }
</style>
