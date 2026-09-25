<script>
  /* Tag rules (admin): the words in a transcript that earn a tag.

     Built-in rules ship with the app (bedroom, pool, sea view …) and can only
     be switched off or on. Custom rules are a tag plus plain phrases — the
     backend turns phrases into a safe pattern, so a stray bracket can't break
     a tagging run — and "Try it" counts matching transcripts before anything
     is tagged. Rules apply on the next auto-tag pass. */
  import { onMount } from 'svelte';
  import { say } from '$lib/media.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import SettingsCard from './SettingsCard.svelte';
  import { settingsApi as api } from './api.js';

  let { transcription = false } = $props();

  let rules = $state(null);
  let showBuiltin = $state(false);
  let form = $state({ tag: '', phrases: '', min_hits: 1 });
  let preview = $state(null);
  let busy = $state(false);

  const phrasesOf = (s) => s.split(/[,\n;]/).map((x) => x.trim()).filter(Boolean);

  async function load() {
    try { rules = await api.tagRules(); } catch (e) { say(e.message, 'error'); }
  }
  onMount(load);

  async function tryIt() {
    const p = phrasesOf(form.phrases);
    if (!p.length) { say('Type a phrase or two first', 'error'); return; }
    try { preview = await api.previewRule(p, Number(form.min_hits) || 1); }
    catch (e) { say(e.message, 'error'); }
  }

  async function add() {
    const p = phrasesOf(form.phrases);
    if (!form.tag.trim() || !p.length) { say('A rule needs a tag and at least one phrase', 'error'); return; }
    busy = true;
    try {
      await api.addRule({ tag: form.tag.trim(), phrases: p, min_hits: Number(form.min_hits) || 1 });
      form = { tag: '', phrases: '', min_hits: 1 };
      preview = null;
      say('Rule added — it applies on the next auto-tag pass');
      await load();
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }

  async function toggleCustom(r) {
    try { await api.editRule(r.id, { enabled: !r.enabled }); await load(); }
    catch (e) { say(e.message, 'error'); }
  }
  async function remove(r) {
    if (!confirm(`Delete the rule for “${r.tag}”? Tags it already added stay.`)) return;
    try { await api.delRule(r.id); await load(); }
    catch (e) { say(e.message, 'error'); }
  }
  async function toggleBuiltin(r) {
    try { await api.toggleBuiltin(r.tag, !r.enabled); await load(); }
    catch (e) { say(e.message, 'error'); }
  }
</script>

<SettingsCard label="Tag rules"
              sub={transcription ? 'Words in a transcript that earn a tag. Applied on the next auto-tag pass.'
                                 : 'Words in a transcript that earn a tag. Transcription is not installed here, so these only apply to transcripts made elsewhere.'}>
  {#if !rules}
    <p class="note">Loading…</p>
  {:else}
    <div class="pane mg-glass-soft">
      <div class="fields">
        <div class="field sm">
          <label class="mg-label" for="tr-tag">Tag</label>
          <input id="tr-tag" class="mg-input" type="text" maxlength="80" bind:value={form.tag} placeholder="wine cellar" />
        </div>
        <div class="field">
          <label class="mg-label" for="tr-ph">Phrases <span class="dim">comma-separated</span></label>
          <input id="tr-ph" class="mg-input" type="text" bind:value={form.phrases}
                 oninput={() => (preview = null)} placeholder="wine cellar, wine room, tasting room" />
        </div>
        <div class="field xs">
          <label class="mg-label" for="tr-min">Min. hits</label>
          <input id="tr-min" class="mg-input" type="number" min="1" max="20" bind:value={form.min_hits} />
        </div>
      </div>
      {#if preview}
        <p class="note">Would tag <b>{preview.matches}</b> of {preview.of} transcribed files.
          {#each preview.examples.slice(0, 3) as ex (ex.id)}
            <span class="ex">{ex.filename}: {ex.before}<mark>{ex.match}</mark>{ex.after}</span>
          {/each}
        </p>
      {/if}
      <div class="btnrow" style="margin-top:12px">
        <button class="mg-btn secondary sm" onclick={tryIt} disabled={busy}><Icon name="search" size={13} />Try it</button>
        <button class="mg-btn primary sm" onclick={add} disabled={busy}><Icon name="plus" size={13} />Add rule</button>
      </div>
    </div>

    {#if rules.custom.length}
      <ul class="rules">
        {#each rules.custom as r (r.id)}
          <li class="mg-glass-soft" class:off={!r.enabled}>
            <span class="nm"><b>{r.tag}</b><small>{r.phrases.join(', ')}{r.min_hits > 1 ? ` · ${r.min_hits}+ hits` : ''}</small></span>
            <button class="mg-chip tog" class:on={r.enabled} aria-pressed={r.enabled} onclick={() => toggleCustom(r)}>
              {r.enabled ? 'On' : 'Off'}
            </button>
            <button class="mg-btn ghost icon sm" aria-label="Delete rule {r.tag}" onclick={() => remove(r)}><Icon name="trash" size={14} /></button>
          </li>
        {/each}
      </ul>
    {/if}

    <button class="mg-btn ghost sm more" onclick={() => (showBuiltin = !showBuiltin)}>
      <Icon name={showBuiltin ? 'chevronUp' : 'chevronDown'} size={13} />
      {showBuiltin ? 'Hide' : 'Show'} the {rules.builtin.length} built-in rules
    </button>
    {#if showBuiltin}
      <ul class="rules">
        {#each rules.builtin as r (r.tag)}
          <li class="mg-glass-soft" class:off={!r.enabled}>
            <span class="nm"><b>{r.tag}</b><small class="mono">{r.matches}</small></span>
            <button class="mg-chip tog" class:on={r.enabled} aria-pressed={r.enabled} onclick={() => toggleBuiltin(r)}>
              {r.enabled ? 'On' : 'Off'}
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</SettingsCard>

<style>
  .dim { color: var(--mc-ink3); font-weight: 400; }
  .field.sm { flex: 1 1 140px; }
  .field.xs { flex: 0 1 100px; }
  .ex { display: block; font-size: 12px; color: var(--mc-ink3); overflow-wrap: anywhere; }
  mark { background: rgba(62, 207, 142, 0.22); color: var(--mc-ink); border-radius: 3px; padding: 0 2px; }
  .rules { list-style: none; margin: 6px 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
  .rules li { display: flex; align-items: center; gap: 10px; padding: 6px 8px 6px 14px; border-radius: var(--mc-r-md); min-height: 48px; }
  .rules li.off .nm b { color: var(--mc-ink3); }
  .nm { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .nm b { font: 500 13px/1.3 var(--mc-font); color: var(--mc-ink); }
  .nm small { font: 400 11.5px/1.4 var(--mc-font); color: var(--mc-ink3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .nm small.mono { font-family: var(--mc-mono); }
  .tog { min-height: 36px; min-width: 52px; justify-content: center; cursor: pointer; }
  .more { margin-top: 4px; min-height: 40px; }
</style>
