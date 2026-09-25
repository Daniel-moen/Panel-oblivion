<script>
  /* Create or edit one of the studio's Looks: a name, the instruction the
     image model follows, and up to two example photos that show the finish
     (the newest upload replaces the oldest). A new look is saved first; the
     examples are added once it exists. */
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import { say } from '$lib/media.svelte.js';
  import { looks } from '$lib/media/hdr.js';

  let { open = false, look = null, editable = true, onclose, onsaved } = $props();

  let form = $state({ name: '', prompt: '', tailor: true, real: true, seed: '' });
  let current = $state(null);          // the saved look (has id + examples)
  let busy = $state(false);
  let upPct = $state(null);
  let fileEl = $state(null);

  $effect(() => {
    if (!open) return;
    current = look ? { ...look } : null;
    form = {
      name: look?.name || '', prompt: look?.prompt || '',
      tailor: look?.tailor ?? true, real: look?.real ?? true,
      seed: look?.seed == null ? '' : String(look.seed)
    };
    upPct = null;
  });

  const valid = $derived(form.name.trim().length >= 1 && form.prompt.trim().length >= 3);

  async function save() {
    if (!valid || busy) return;
    busy = true;
    const body = {
      name: form.name.trim().slice(0, 60), prompt: form.prompt.trim().slice(0, 2000),
      tailor: !!form.tailor, real: !!form.real,
      seed: form.seed === '' || form.seed == null ? null : Math.max(0, Math.floor(Number(form.seed)) || 0)
    };
    try {
      const saved = current?.id ? await looks.update(current.id, body) : await looks.create(body);
      const wasNew = !current?.id;
      current = saved;
      onsaved?.(saved);
      say(wasNew ? 'Look created — add an example photo or two if you like' : 'Look saved');
      if (!wasNew) onclose?.();
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }

  async function addExample(e) {
    const f = e.currentTarget.files?.[0];
    e.currentTarget.value = '';
    if (!f || !current?.id) return;
    upPct = 0;
    try {
      const saved = await looks.addExample(current.id, f, (p) => (upPct = p)).promise;
      current = saved;
      onsaved?.(saved);
      say('Example added');
    } catch (err) { say(err.message, 'error'); }
    finally { upPct = null; }
  }

  async function removeExample(name) {
    try {
      const saved = await looks.removeExample(current.id, name);
      current = saved;
      onsaved?.(saved);
    } catch (e) { say(e.message, 'error'); }
  }
</script>

<Sheet {open} title={current?.id ? 'Edit look' : 'New look'} size="md" {onclose}>
  <div class="f">
    <label class="fld">
      <span class="mg-label">Name</span>
      <input class="mg-input" maxlength="60" bind:value={form.name} placeholder="e.g. Twilight" disabled={!editable} />
    </label>
    <label class="fld">
      <span class="mg-label">Instruction for the image model</span>
      <textarea class="mg-input ta" rows="6" maxlength="2000" bind:value={form.prompt} disabled={!editable}
                placeholder="Describe the finished photo: sky, light, colour, what glows…"></textarea>
    </label>
    <label class="sw"><input type="checkbox" bind:checked={form.tailor} disabled={!editable} />
      <span>Tailor to each photo <i>— Claude rewrites the instruction for what is actually in the photo</i></span></label>
    <label class="sw"><input type="checkbox" bind:checked={form.real} disabled={!editable} />
      <span>Keep it real <i>— only light, sky and window views change; the photo's own detail stays</i></span></label>
    <label class="fld seed">
      <span class="mg-label">Seed (optional — same seed, same result)</span>
      <input class="mg-input" type="number" min="0" bind:value={form.seed} disabled={!editable} />
    </label>

    <div class="ex">
      <span class="mg-label">Example photos {current?.id ? `· ${current.examples?.length || 0}/2` : ''}</span>
      {#if !current?.id}
        <p class="hint">Save the look first, then add up to two photos that show the finish you want.</p>
      {:else}
        <div class="exs">
          {#each current.examples || [] as n (n)}
            <figure>
              <img src={looks.exampleUrl(current.id, n)} alt="Example for {current.name}" loading="lazy" />
              {#if editable}
                <button type="button" class="x" aria-label="Remove this example" onclick={() => removeExample(n)}>
                  <Icon name="x" size={12} />
                </button>
              {/if}
            </figure>
          {/each}
          {#if editable}
            <button type="button" class="add" onclick={() => fileEl?.click()} disabled={upPct != null}>
              {#if upPct != null}<span class="mg-tnum">{Math.round(upPct * 100)}%</span>
              {:else}<Icon name="upload" size={18} /><span>{(current.examples?.length || 0) >= 2 ? 'Replace oldest' : 'Add photo'}</span>{/if}
            </button>
          {/if}
        </div>
        <input bind:this={fileEl} type="file" accept="image/jpeg,image/png,image/webp" hidden onchange={addExample} />
        <p class="hint">JPEG, PNG or WebP. The model matches their brightness, white balance and colour — nothing is copied in.</p>
      {/if}
    </div>
  </div>

  {#snippet footer()}
    <button class="mg-btn ghost" onclick={onclose}>{current?.id && !look ? 'Done' : 'Cancel'}</button>
    {#if editable}
      <button class="mg-btn accent" onclick={save} disabled={!valid || busy}>
        {#if busy}<span class="mg-spin"></span>{/if}{current?.id ? 'Save' : 'Create look'}
      </button>
    {/if}
  {/snippet}
</Sheet>

<style>
  .f { display: flex; flex-direction: column; gap: 12px; }
  .fld { display: flex; flex-direction: column; gap: 5px; }
  .fld .mg-input { width: 100%; }
  .ta { height: auto; min-height: 120px; padding: 10px 12px; resize: vertical; line-height: 1.5; font: 400 13px/1.5 var(--mc-font); }
  .seed { max-width: 260px; }
  .sw { display: flex; gap: 9px; align-items: flex-start; font: 500 12.5px/1.45 var(--mc-font); color: var(--mc-ink2); cursor: pointer; min-height: 28px; }
  .sw input { margin-top: 2px; accent-color: var(--mc-accent); width: 16px; height: 16px; flex: none; }
  .sw i { font-style: normal; color: var(--mc-ink3); font-weight: 400; }
  .hint { margin: 0; font: 400 12px/1.5 var(--mc-font); color: var(--mc-ink3); }
  .ex { display: flex; flex-direction: column; gap: 8px; }
  .exs { display: flex; gap: 8px; flex-wrap: wrap; }
  figure { position: relative; margin: 0; width: 132px; aspect-ratio: 3 / 2; border-radius: 10px; overflow: hidden; background: var(--mc-inset); }
  figure img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .x { position: absolute; top: 4px; right: 4px; width: 28px; height: 28px; border-radius: 50%;
       border: 1px solid var(--mc-line2); background: var(--mc-raised); color: var(--mc-ink); box-shadow: var(--mc-sh-1); display: grid; place-items: center; cursor: pointer; }
  .add { width: 132px; aspect-ratio: 3 / 2; border-radius: 10px; border: 1px dashed var(--mc-line2); background: var(--mc-raised);
         color: var(--mc-ink2); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px;
         font: 500 12px/1 var(--mc-font); cursor: pointer; }
  .add:hover { border-color: var(--mc-line3); color: var(--mc-ink); }
  @media (pointer: coarse) { .sw { min-height: 44px; align-items: center; } .sw input { margin-top: 0; } .x { width: 36px; height: 36px; } }
</style>
