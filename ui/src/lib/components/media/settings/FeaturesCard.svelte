<script>
  /* What this server can actually do, from /api/media/status. Anything that
     is off says why in plain words, so a greyed-out button elsewhere has an
     explanation somebody can find. */
  import SettingsCard from './SettingsCard.svelte';

  let { status = null } = $props();

  const F = [
    { k: 'ffmpeg', name: 'Video processing', on: 'Thumbnails, proxies, trims and exports',
      off: 'ffmpeg is not installed on this server, so video can be stored but not processed.' },
    { k: 'raw', name: 'Camera RAW photos', on: 'RAW files decode for previews, HDR and the editor',
      off: 'The RAW decoder (rawpy) is not installed; RAW files show without a preview.' },
    { k: 'heic', name: 'iPhone HEIC photos', on: 'HEIC stills preview and edit like JPEGs',
      off: 'HEIC support (pillow-heif) is not installed; iPhone photos show without a preview.' },
    { k: 'onnx', name: 'On-device photo models', on: 'Sky masks, room detection and similar run locally',
      off: 'onnxruntime is not installed, so the local photo models are off.' },
    { k: 'ai', name: 'Claude (captions, tagging, finder)', on: 'Claude answers for captions, tags and search',
      off: 'No Claude backend is configured — an admin can set one in the AI card below.' },
    { k: 'image_ai', name: 'Image AI (virtual staging, sky swap, object removal)', on: 'A hosted image model is set',
      off: 'Not configured — add a fal, Gemini or OpenAI key in the AI card below. Local image AI (ComfyUI) needs an NVIDIA GPU, which this server does not have.' },
    { k: 'transcription', name: 'Transcription', on: 'Spoken words become searchable text',
      off: 'Needs openai-whisper, which pulls in torch — not installed on this deployment, as it does not fit the build image.' },
    { k: 'splat', name: '3D fly-throughs', on: 'Gaussian-splat walkthroughs',
      off: 'Not included in this build.' }
  ];

  const feats = $derived(status?.features || {});
  const onCount = $derived(F.filter((f) => feats[f.k]).length);
</script>

<SettingsCard label="Features on this server"
              sub={status ? `Zerko ${status.version || ''} · ${onCount} of ${F.length} available` : ''}>
  {#if !status}
    <p class="note">Checking…</p>
  {:else}
    <ul class="fl">
      {#each F as f (f.k)}
        {@const on = !!feats[f.k]}
        <li class="mg-glass-soft" class:off={!on}>
          <span class="mg-dot {on ? 'ok' : ''}"></span>
          <span class="tx">
            <b>{f.name}</b>
            <span class="hint">{on ? f.on : f.off}</span>
          </span>
          <span class="st">{on ? 'On' : 'Off'}</span>
        </li>
      {/each}
    </ul>
  {/if}
</SettingsCard>

<style>
  .fl { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px;
        grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr)); }
  li { display: flex; align-items: flex-start; gap: 10px; padding: 11px 14px; border-radius: var(--mg-r-in); min-width: 0; }
  li .mg-dot { margin-top: 5px; flex: none; }
  .tx { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .tx b { font: 500 13px/1.3 var(--mg-font); color: var(--mg-i); }
  li.off .tx b { color: var(--mg-i2); }
  .st { flex: none; font: 500 11.5px/1.6 var(--mg-font); color: var(--mg-ok); }
  li.off .st { color: var(--mg-i3); }
</style>
