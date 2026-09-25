<script>
  /* Captions for posting the property (captions.py).

     Each "Write" comes out worded differently from the ones before it for
     this property. With AI configured (features.ai, or a caption key) Claude
     writes them from the listing facts; without it the backend's built-in
     writer still works offline — so the button stays live and says which
     writer it will use rather than going dead.

     Only captions that were copied are kept as history (GET …/captions
     returns copied ones); a fresh draft lives here until it is copied. */
  import Icon from '$lib/components/glass/Icon.svelte';
  import { say } from '$lib/media.svelte.js';
  import { shoots, CAPTION_PLATFORMS, CAPTION_TONES, CAPTION_CLIPS, copyText } from '$lib/media/shoots.js';

  let { shoot, items = [], aiFeature = false } = $props();

  let history = $state([]);
  let settings = $state(null);
  let draft = $state(null);      // the caption object just written
  let text = $state('');
  let busy = $state(false);
  let opts = $state({ platform: 'instagram', tone: 'warm', clip: '', video_id: '',
                      price: true, agent: true, address: false, hashtags: true, emoji: false });

  /* the backend's own answer (a caption key, or Manage › AI) wins over the boot flag */
  const ai = $derived(settings ? !!settings.ai : !!aiFeature);
  const facts = $derived(shoot.facts || {});
  const thin = $derived(!facts.beds && !facts.price && !facts.features?.length && !facts.kind);

  const sid = $derived(shoot.id);

  async function load(id = sid) {
    try {
      const r = await shoots.captions(id);
      history = r?.captions || [];
      settings = r?.settings || null;
    } catch (e) { say(e.message, 'error'); }
  }
  $effect(() => { load(sid); });   // not on every edit of the shoot, only a new one

  /* Picking a file guesses what kind of post it makes. */
  async function onVideo(id) {
    opts.video_id = id;
    if (!id) return;
    try {
      const r = await shoots.guessClip(shoot.id, Number(id));
      if (r?.clip) opts.clip = r.clip;
    } catch { /* keep the manual choice */ }
  }

  async function write() {
    busy = true;
    try {
      const c = await shoots.writeCaption(shoot.id, { ...opts, video_id: opts.video_id ? Number(opts.video_id) : null });
      draft = c; text = c.text;
      if (c.note) say(c.note, 'error', 6000);
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }

  async function copyDraft() {
    if (!draft) return;
    const ok = await copyText(text);
    say(ok ? 'Copied — paste it into your post' : 'Could not copy. Select the text and copy it yourself.', ok ? 'ok' : 'error');
    try {
      if (text !== draft.text) await shoots.editCaption(shoot.id, draft.id, text);
      await shoots.copiedCaption(shoot.id, draft.id);
      draft = null; text = '';
      load();
    } catch (e) { say(e.message, 'error'); }
  }

  async function copyOld(c) {
    const ok = await copyText(c.text);
    say(ok ? 'Copied' : 'Could not copy', ok ? 'ok' : 'error');
    shoots.copiedCaption(shoot.id, c.id).then(() => load()).catch(() => {});
  }

  async function remove(c) {
    try {
      await shoots.deleteCaption(shoot.id, c.id);
      if (draft?.id === c.id) { draft = null; text = ''; }
      history = history.filter((x) => x.id !== c.id);
    } catch (e) { say(e.message, 'error'); }
  }

  const label = (p) => CAPTION_PLATFORMS.find((x) => x.value === p)?.label || p;
  const day = (v) => (v ? new Date(v + 'Z').toLocaleDateString('en-ZA', { day: 'numeric', month: 'short' }) : '');
  const TOGGLES = [['price', 'Price'], ['agent', 'Agent'], ['address', 'Address'], ['hashtags', 'Hashtags'], ['emoji', 'Emoji']];
</script>

<section class="mg-card">
  <div class="hd">
    <h3><Icon name="text" size={15} />Captions</h3>
    {#if settings}
      <span class="mg-chip {ai ? 'mgr' : ''}">{ai ? 'Claude writes these' : 'Built-in writer'}</span>
    {/if}
  </div>

  {#if settings && !ai}
    <p class="note">AI isn't configured, so the built-in writer words these from the listing facts. Add an Anthropic key in Media › Settings to have Claude write them.</p>
  {/if}
  {#if thin}
    <p class="note warn"><Icon name="alert" size={12} />Fill in the listing facts (beds, price, features) — nothing is made up, so an empty listing gives a thin caption.</p>
  {/if}

  <div class="grid">
    <div class="mg-select">
      <select bind:value={opts.platform} aria-label="Where it will be posted">
        {#each CAPTION_PLATFORMS as p (p.value)}<option value={p.value}>{p.label}</option>{/each}
      </select>
      <span class="ic"><Icon name="chevronDown" size={15} /></span>
    </div>
    <div class="mg-select">
      <select bind:value={opts.tone} aria-label="Tone">
        {#each CAPTION_TONES as t (t)}<option value={t}>{t[0].toUpperCase() + t.slice(1)} tone</option>{/each}
      </select>
      <span class="ic"><Icon name="chevronDown" size={15} /></span>
    </div>
    <div class="mg-select">
      <select value={opts.video_id} onchange={(e) => onVideo(e.currentTarget.value)} aria-label="For which file">
        <option value="">Any file</option>
        {#each items as v (v.id)}<option value={v.id}>{v.filename}</option>{/each}
      </select>
      <span class="ic"><Icon name="chevronDown" size={15} /></span>
    </div>
    <div class="mg-select">
      <select bind:value={opts.clip} aria-label="Kind of post">
        {#each CAPTION_CLIPS as c (c.value)}<option value={c.value}>{c.value ? c.label : 'Any kind of post'}</option>{/each}
      </select>
      <span class="ic"><Icon name="chevronDown" size={15} /></span>
    </div>
  </div>

  <div class="togs">
    {#each TOGGLES as [k, l] (k)}
      <button type="button" class="mg-chip tog" class:on={opts[k]} aria-pressed={opts[k]} onclick={() => (opts[k] = !opts[k])}>
        {#if opts[k]}<Icon name="check" size={12} />{/if}{l}
      </button>
    {/each}
  </div>

  <button class="mg-btn accent wide" onclick={write} disabled={busy}>
    {#if busy}<span class="mg-spin"></span>Writing…{:else}<Icon name="wand" size={15} />{draft ? 'Write another' : 'Write a caption'}{/if}
  </button>

  {#if draft}
    <div class="draft">
      <textarea class="mg-input" rows="7" bind:value={text} aria-label="Caption draft"></textarea>
      {#if draft.missing?.length}<p class="note">Not mentioned (not filled in): {draft.missing.join(', ')}.</p>{/if}
      <div class="acts">
        <button class="mg-btn primary sm" onclick={copyDraft}><Icon name="copy" size={13} />Copy</button>
        <button class="mg-btn ghost sm" onclick={() => remove(draft)}><Icon name="trash" size={13} />Discard</button>
        <span class="src">{draft.source === 'ai' ? 'by Claude' : 'built-in writer'}</span>
      </div>
    </div>
  {/if}

  {#if history.length}
    <h4 class="mg-label">Copied before</h4>
    <ul class="hist">
      {#each history as c (c.id)}
        <li>
          <div class="meta">
            <span class="mg-chip">{label(c.platform)}</span>
            {#if c.tone}<span class="t">{c.tone}</span>{/if}
            <span class="t mg-tnum">{day(c.copied_at)}</span>
            <span class="sp"></span>
            <button class="mg-btn ghost icon sm" onclick={() => copyOld(c)} aria-label="Copy again" title="Copy again"><Icon name="copy" size={13} /></button>
            <button class="mg-btn ghost icon sm" onclick={() => remove(c)} aria-label="Delete" title="Delete"><Icon name="trash" size={13} /></button>
          </div>
          <p>{c.text}</p>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .hd { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
  h3 { margin: 0; flex: 1; display: flex; align-items: center; gap: 7px; font: 600 14px/1.3 var(--mc-font); color: var(--mc-ink); }
  .note { margin: 0 0 10px; display: flex; gap: 6px; align-items: baseline; font: 400 12px/1.5 var(--mc-font); color: var(--mc-ink3); }
  .note.warn { color: var(--mc-warn); }
  .grid { display: grid; gap: 8px; grid-template-columns: 1fr 1fr; margin-bottom: 10px; }
  .grid .mg-select { display: block; }
  @media (max-width: 420px) { .grid { grid-template-columns: 1fr; } }
  .togs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
  .tog { min-height: 36px; padding: 0 12px; }
  .wide { width: 100%; }
  .draft { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }
  .draft textarea { min-height: 150px; }
  .acts { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .src { margin-left: auto; font: 400 11.5px/1 var(--mc-font); color: var(--mc-ink3); }
  h4.mg-label { margin: 16px 0 6px; }
  .hist { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
  .hist li { padding: 8px 10px; border-radius: var(--mc-r-md); background: var(--mc-raised); border: 1px solid var(--mc-line); }
  .meta { display: flex; align-items: center; gap: 8px; }
  .t { font: 400 11.5px/1 var(--mc-font); color: var(--mc-ink3); }
  .sp { flex: 1; }
  .hist p { margin: 6px 0 0; white-space: pre-wrap; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink2);
            display: -webkit-box; -webkit-line-clamp: 4; line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
</style>
