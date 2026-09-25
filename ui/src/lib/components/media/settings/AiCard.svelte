<script>
  /* The AI switches, admin only. Two separate things:
       Claude — the text brain (captions, tagging, the finder): either the
                Anthropic API with a key, or the Claude Code CLI on this host.
       Image AI — a hosted image model for staging / sky / removal edits.
     Keys are write-only. The backend answers with a hint ("...abcd"), which
     is all this card ever shows; an empty key field means "leave it as is". */
  import { onMount } from 'svelte';
  import { say } from '$lib/media.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import SettingsCard from './SettingsCard.svelte';
  import { settingsApi as api } from './api.js';

  let { onchanged } = $props();

  let ai = $state(null);
  let models = $state([]);
  let aiForm = $state({ backend: 'api', key: '', model: 'auto' });
  let aiBusy = $state(false);

  let img = $state(null);
  let imgForm = $state({ backend: 'off', key: '', model: '' });
  let imgBusy = $state(false);
  let err = $state('');

  const HOSTED = ['fal', 'gemini', 'openai'];

  onMount(async () => {
    try {
      const [a, i] = await Promise.all([api.ai(), api.image()]);
      setAi(a); setImg(i);
      loadModels();
    } catch (e) { err = e.message; }
  });

  function setAi(a) {
    ai = a;
    aiForm = { backend: a.backend || 'api', key: '', model: a.model || 'auto' };
  }
  function setImg(i) {
    img = i;
    const b = i.backend === 'comfyui' ? 'off' : i.backend || 'off';
    imgForm = { backend: b, key: '', model: HOSTED.includes(b) ? i.models?.[b] || '' : '' };
  }

  async function loadModels() {
    try { models = (await api.aiModels())?.models || []; }
    catch { models = []; }
  }

  async function saveAi() {
    aiBusy = true;
    try {
      const body = { model: aiForm.model };
      if (aiForm.backend !== ai.backend) body.backend = aiForm.backend;
      if (aiForm.key.trim()) body.key = aiForm.key.trim();
      if (body.backend) delete body.model;           // the two take different model names
      setAi(await api.saveAi(body));
      await loadModels();
      say('Claude settings saved');
      onchanged?.();
    } catch (e) { say(e.message, 'error'); }
    finally { aiBusy = false; }
  }
  async function clearKey() {
    if (!confirm('Remove the saved Claude key from this server?')) return;
    aiBusy = true;
    try { setAi(await api.saveAi({ key: '' })); say('Key removed'); onchanged?.(); }
    catch (e) { say(e.message, 'error'); }
    finally { aiBusy = false; }
  }
  async function testAi() {
    aiBusy = true;
    try { const r = await api.testAi(); say(`Claude answered “${r.reply}” (${r.model})`); }
    catch (e) { say(e.message, 'error'); }
    finally { aiBusy = false; }
  }

  async function saveImg() {
    imgBusy = true;
    try {
      const b = imgForm.backend;
      const body = { backend: b };
      if (HOSTED.includes(b)) {
        if (imgForm.key.trim()) body[`${b}_key`] = imgForm.key.trim();
        if (imgForm.model.trim()) body[`${b}_model`] = imgForm.model.trim();
      }
      setImg(await api.saveImage(body));
      say('Image AI settings saved');
      onchanged?.();
    } catch (e) { say(e.message, 'error'); }
    finally { imgBusy = false; }
  }
  async function testImg() {
    imgBusy = true;
    try { const r = await api.testImage(); say(`Image model answered in ${r.seconds}s`); }
    catch (e) { say(e.message, 'error'); }
    finally { imgBusy = false; }
  }

  const imgHint = $derived(HOSTED.includes(imgForm.backend) ? img?.keys?.[imgForm.backend] || '' : '');
</script>

<SettingsCard label="AI" sub="Administrators only. Keys are stored on the server and never shown again — only their last four characters.">
  {#if err}
    <div class="mg-strip crit"><span class="ic"><Icon name="alert" size={15} /></span><span>{err}</span></div>
  {:else if !ai || !img}
    <Skeleton h="7rem" r="12px" />
  {:else}
    <!-- ——————————————————————————————————————————————————— Claude ——— -->
    <div class="pane mg-panel">
      <div class="hd">
        <b>Claude</b>
        <span class="mg-chip {ai.ai ? 'ok' : ''}"><span class="dot"></span>{ai.ai ? 'On' : 'Off'}</span>
      </div>
      <div class="fields">
        <div class="field">
          <label class="mg-label" for="ai-b">Runs through</label>
          <div class="mg-select">
            <select id="ai-b" bind:value={aiForm.backend}>
              <option value="api">Anthropic API key</option>
              <option value="claude_code">Claude Code on this server{ai.cli ? '' : ' (not found)'}</option>
            </select>
            <span class="ic"><Icon name="chevronDown" size={15} /></span>
          </div>
        </div>
        {#if aiForm.backend === 'api'}
          <div class="field">
            <label class="mg-label" for="ai-k">API key {#if ai.key_hint}<span class="dim">saved: {ai.key_hint}{ai.source && ai.source !== 'settings' ? ` (from ${ai.source})` : ''}</span>{/if}</label>
            <input id="ai-k" class="mg-input" type="password" autocomplete="off" bind:value={aiForm.key}
                   placeholder={ai.has_key ? 'Leave empty to keep the saved key' : 'sk-ant-…'} />
          </div>
        {/if}
        {#if aiForm.backend === ai.backend}
          <div class="field">
            <label class="mg-label" for="ai-m">Model</label>
            <div class="mg-select">
              <select id="ai-m" bind:value={aiForm.model}>
                {#if !models.some((m) => m.id === aiForm.model)}<option value={aiForm.model}>{aiForm.model}</option>{/if}
                {#each models as m (m.id)}<option value={m.id}>{m.name}</option>{/each}
              </select>
              <span class="ic"><Icon name="chevronDown" size={15} /></span>
            </div>
          </div>
        {/if}
      </div>
      {#if aiForm.backend === 'claude_code'}
        <p class="hint">Uses the <code>claude</code> command-line tool{ai.cli ? ` at ${ai.cli}` : ''} and its own sign-in — no key here.</p>
      {/if}
      <div class="btnrow">
        <button class="mg-btn primary sm" onclick={saveAi} disabled={aiBusy}><Icon name="check" size={13} />Save</button>
        <button class="mg-btn secondary sm" onclick={testAi} disabled={aiBusy || !ai.ai}><Icon name="bolt" size={13} />Test</button>
        {#if ai.source === 'settings' && ai.has_key}
          <button class="mg-btn ghost sm" onclick={clearKey} disabled={aiBusy}><Icon name="trash" size={13} />Remove key</button>
        {/if}
      </div>
    </div>

    <!-- ————————————————————————————————————————————————— Image AI ——— -->
    <div class="pane mg-panel">
      <div class="hd">
        <b>Image AI</b>
        <span class="mg-chip {img.on ? 'ok' : ''}"><span class="dot"></span>{img.on ? 'On' : 'Off'}</span>
      </div>
      <div class="fields">
        <div class="field">
          <label class="mg-label" for="im-b">Provider</label>
          <div class="mg-select">
            <select id="im-b" bind:value={imgForm.backend}
                    onchange={() => { imgForm.key = ''; imgForm.model = img.models?.[imgForm.backend] || ''; }}>
              {#each img.backends as b (b.id)}
                <option value={b.id} disabled={b.id === 'comfyui'}>
                  {b.name}{b.id === 'comfyui' ? ' — needs an NVIDIA GPU, not on this server' : ''}
                </option>
              {/each}
            </select>
            <span class="ic"><Icon name="chevronDown" size={15} /></span>
          </div>
        </div>
        {#if HOSTED.includes(imgForm.backend)}
          <div class="field">
            <label class="mg-label" for="im-k">Key {#if imgHint}<span class="dim">saved: {imgHint}</span>{/if}</label>
            <input id="im-k" class="mg-input" type="password" autocomplete="off" bind:value={imgForm.key}
                   placeholder={imgHint ? 'Leave empty to keep the saved key' : 'Paste the key'} />
          </div>
          <div class="field">
            <label class="mg-label" for="im-m">Model</label>
            <input id="im-m" class="mg-input" type="text" bind:value={imgForm.model}
                   placeholder={img.default_models?.[imgForm.backend] || ''} />
          </div>
        {/if}
      </div>
      <p class="hint">Local image AI (ComfyUI) needs an NVIDIA GPU and a 23 GB install, so it is not offered here — use a hosted key.</p>
      <div class="btnrow">
        <button class="mg-btn primary sm" onclick={saveImg} disabled={imgBusy}><Icon name="check" size={13} />Save</button>
        <button class="mg-btn secondary sm" onclick={testImg} disabled={imgBusy || !img.on}
                title="Paints one small picture — billed by the provider"><Icon name="image" size={13} />Test</button>
      </div>
    </div>
  {/if}
</SettingsCard>

<style>
  .hd { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
  .hd b { font: 600 14px/1.2 var(--mc-font); color: var(--mc-ink); }
  .dim { color: var(--mc-ink3); font-weight: 400; }
  .pane .hint { display: block; margin: 10px 0 0; }
  .btnrow { margin-top: 12px; }
</style>
