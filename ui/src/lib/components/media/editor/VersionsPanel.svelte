<script>
  /* Versions of an edit: virtual copies (other edits of the same file, Zerko
     1.3), snapshots (named states of the edit to come back to), and presets
     (looks shared across the studio).

     Snapshots live with the photo — one list whichever copy you are on, and
     restoring one puts it on the version you are looking at. A preset can be
     laid on as written, or "fitted": the server measures this frame first and
     lands the look on top of it (/api/photo-presets/{id}/for/{photo}). */
  import { onMount, untrack } from 'svelte';
  import Section from './Section.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import { pe, applyLook, cleanRecipe } from '$lib/media/photoedit.js';
  import { say } from '$lib/media.svelte.js';

  let { api, ed, copies = [], onswitch, onreloadcopies, disabled = false } = $props();

  let snaps = $state([]);
  let presets = $state([]);
  let snapName = $state('');
  let presetName = $state('');
  let copyName = $state('');
  let renaming = $state(null);
  let renameTo = $state('');
  let busy = $state(null);

  const current = () => cleanRecipe($state.snapshot(ed.recipe));

  async function loadSnaps() {
    try { snaps = (await pe.snapshots(ed.id)).snapshots || []; } catch { snaps = []; }
  }
  async function loadPresets() {
    try { presets = (await pe.presets()).presets || []; } catch { presets = []; }
  }
  onMount(loadPresets);
  $effect(() => { ed.id; untrack(loadSnaps); });

  /* ------------------------------------------------------------ copies */
  async function newCopy(blank = false) {
    busy = 'copy';
    try {
      await api.settle();
      const c = await pe.newCopy(ed.id, copyName.trim(), blank ? null : current());
      copyName = '';
      await onreloadcopies?.();
      say(`Made “${c.name}”`);
      onswitch?.(c.id);
    } catch (e) { say(e.message, 'error'); }
    finally { busy = null; }
  }
  async function rename(c) {
    const name = renameTo.trim();
    if (!name) { renaming = null; return; }
    try { await pe.renameCopy(ed.id, c.id, name); renaming = null; await onreloadcopies?.(); }
    catch (e) { say(e.message, 'error'); }
  }
  async function removeCopy(c) {
    if (!confirm(`Delete the virtual copy “${c.name}”? The photo file is not touched.`)) return;
    try {
      await pe.deleteCopy(ed.id, c.id);
      if (ed.copy === c.id) onswitch?.(null);
      await onreloadcopies?.();
      say('Virtual copy deleted');
    } catch (e) { say(e.message, 'error'); }
  }

  /* --------------------------------------------------------- snapshots */
  async function snap() {
    const name = snapName.trim() || `Snapshot ${snaps.length + 1}`;
    try { snaps = (await pe.addSnapshot(ed.id, name, current())).snapshots || []; snapName = ''; say(`Saved “${name}”`); }
    catch (e) { say(e.message, 'error'); }
  }
  function restore(s) { api.replace(s.recipe); say(`Restored “${s.name}”`); }
  async function dropSnap(i) {
    try { snaps = (await pe.deleteSnapshot(ed.id, i)).snapshots || []; }
    catch (e) { say(e.message, 'error'); }
  }

  /* ----------------------------------------------------------- presets */
  function applyPreset(p) { api.replace(applyLook(ed.recipe, p.recipe)); say(`Applied “${p.name}”`); }
  async function fitPreset(p) {
    busy = 'fit' + p.id;
    try {
      const r = await pe.presetFor(p.id, ed.id);
      api.replace(applyLook(ed.recipe, r.recipe));
      say(`Fitted “${p.name}” to this photo`);
    } catch (e) { say(e.message, 'error'); }
    finally { busy = null; }
  }
  async function savePreset() {
    const name = presetName.trim();
    if (!name) return;
    const r = current();
    // a preset is a look: what was painted on this photo stays with it
    r.spots = []; r.removes = []; r.masks = r.masks.filter((m) => m.kind !== 'brush');
    r.gen_ref = ''; r.gen_look = ''; r.gen_geo = '';
    try { await pe.savePreset(name, r); presetName = ''; await loadPresets(); say(`Preset “${name}” saved`); }
    catch (e) { say(e.message, 'error'); }
  }
  async function dropPreset(p) {
    if (!confirm(`Delete the preset “${p.name}” for everyone?`)) return;
    try { await pe.deletePreset(p.id); await loadPresets(); }
    catch (e) { say(e.message, 'error'); }
  }

  const when = (s) => { try { return new Date(s).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }); } catch { return s; } };
</script>

<Section title="Virtual copies" icon="copy" badge={copies.length || null}>
  <p class="hint">Other edits of the same file — a twilight, a black and white — with no second file on disk.</p>
  <div class="list">
    <div class="it" class:on={!ed.copy}>
      <button type="button" class="nm" onclick={() => onswitch?.(null)}>Original edit</button>
    </div>
    {#each copies as c (c.id)}
      <div class="it" class:on={ed.copy === c.id}>
        {#if renaming === c.id}
          <form class="rn" onsubmit={(e) => { e.preventDefault(); rename(c); }}>
            <input class="mg-input" bind:value={renameTo} maxlength="80" aria-label="New name" />
            <button type="submit" class="mg-btn accent icon sm" aria-label="Save name"><Icon name="check" size={13} /></button>
          </form>
        {:else}
          <button type="button" class="nm" onclick={() => onswitch?.(c.id)}>{c.name}</button>
          <button type="button" class="mg-btn ghost icon sm" aria-label="Rename" title="Rename" {disabled}
                  onclick={() => { renaming = c.id; renameTo = c.name; }}><Icon name="pencil" size={13} /></button>
          <button type="button" class="mg-btn ghost icon sm" aria-label="Delete copy" title="Delete" {disabled}
                  onclick={() => removeCopy(c)}><Icon name="trash" size={13} /></button>
        {/if}
      </div>
    {/each}
  </div>
  <form class="add" onsubmit={(e) => { e.preventDefault(); newCopy(false); }}>
    <input class="mg-input" placeholder="Name (e.g. Twilight)" bind:value={copyName} maxlength="80" {disabled} />
    <button type="submit" class="mg-btn secondary sm" disabled={disabled || busy === 'copy'}>
      {#if busy === 'copy'}<span class="mg-spin"></span>{:else}<Icon name="plus" size={13} />{/if} Copy this edit</button>
  </form>
  <button type="button" class="mg-btn ghost sm start" onclick={() => newCopy(true)} disabled={disabled || busy === 'copy'}>
    New copy from the original, as shot</button>
</Section>

<Section title="Snapshots" icon="camera" badge={snaps.length || null}>
  <form class="add" onsubmit={(e) => { e.preventDefault(); snap(); }}>
    <input class="mg-input" placeholder="Snapshot name" bind:value={snapName} maxlength="80" {disabled} />
    <button type="submit" class="mg-btn secondary sm" {disabled}><Icon name="plus" size={13} /> Save</button>
  </form>
  {#if snaps.length}
    <div class="list">
      {#each snaps as s, i (s.name + s.at)}
        <div class="it">
          <button type="button" class="nm two" onclick={() => restore(s)} {disabled} title="Restore">
            <span>{s.name}</span><small>{when(s.at)}{s.by ? ' · ' + s.by : ''}</small>
          </button>
          <button type="button" class="mg-btn ghost sm" onclick={() => restore(s)} {disabled}>Restore</button>
          <button type="button" class="mg-btn ghost icon sm" aria-label="Delete snapshot" title="Delete" {disabled}
                  onclick={() => dropSnap(i)}><Icon name="trash" size={13} /></button>
        </div>
      {/each}
    </div>
  {:else}
    <p class="hint">No snapshots yet.</p>
  {/if}
</Section>

<Section title="Presets" icon="sparkles" badge={presets.length || null}>
  {#if presets.length}
    <div class="list">
      {#each presets as p (p.id)}
        <div class="it">
          <span class="nm static">{p.name}{#if p.created_by}<small> · {p.created_by}</small>{/if}</span>
          <button type="button" class="mg-btn ghost sm" onclick={() => applyPreset(p)} {disabled} title="Apply the preset as written">Apply</button>
          <button type="button" class="mg-btn ghost sm" onclick={() => fitPreset(p)} disabled={disabled || !!busy}
                  title="Measure this photo and land the look on it">
            {#if busy === 'fit' + p.id}<span class="mg-spin"></span>{/if}Fit</button>
          <button type="button" class="mg-btn ghost icon sm" aria-label="Delete preset" title="Delete" {disabled}
                  onclick={() => dropPreset(p)}><Icon name="trash" size={13} /></button>
        </div>
      {/each}
    </div>
  {:else}
    <p class="hint">No presets yet — save this edit as the first.</p>
  {/if}
  <form class="add" onsubmit={(e) => { e.preventDefault(); savePreset(); }}>
    <input class="mg-input" placeholder="Preset name" bind:value={presetName} maxlength="80" {disabled} />
    <button type="submit" class="mg-btn secondary sm" disabled={disabled || !presetName.trim()}>Save as preset</button>
  </form>
</Section>

<style>
  .hint { margin: 0 0 6px; font-size: 11.5px; line-height: 1.45; color: var(--mc-ink3); }
  .list { display: flex; flex-direction: column; margin-bottom: 8px; }
  .it { display: flex; align-items: center; gap: 2px; border-bottom: 1px solid var(--mc-line); border-radius: 10px; }
  .it:last-child { border-bottom: 0; }
  .it.on { background: rgba(62, 207, 142, 0.1); }
  .it.on .nm { color: var(--mc-accent); }
  .nm {
    flex: 1; min-width: 0; min-height: 40px; padding: 0 8px; border: 0; background: none; text-align: left;
    color: var(--mc-ink); font: 500 13px/1.3 var(--mc-font); cursor: pointer;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: flex; align-items: center;
  }
  .nm.static { cursor: default; }
  .nm.two { flex-direction: column; align-items: flex-start; justify-content: center; }
  small { color: var(--mc-ink3); font-size: 11px; font-weight: 400; }
  .add { display: flex; gap: 6px; align-items: center; }
  .add .mg-input { height: 36px; flex: 1; min-width: 0; }
  .rn { flex: 1; display: flex; gap: 6px; align-items: center; padding: 4px 0; }
  .rn .mg-input { height: 34px; }
  .start { align-self: flex-start; margin-top: 4px; }
</style>
