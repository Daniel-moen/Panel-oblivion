<script>
  /* Change a live portal without sending a new link. The usual sequence: a
     delivery goes out watermarked with downloads off, and once the invoice is
     paid the marks come off and downloads go on. Each switch saves at once. */
  import { say } from '$lib/media.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import { portals, kindOf, day } from '$lib/media/portals.js';

  let { share, watermarks = [], onchanged } = $props();
  let busy = $state(false);
  const receiving = $derived(kindOf(share) === 'receive');

  async function patch(body, msg) {
    if (busy) return;
    busy = true;
    try {
      await portals.edit(share.id, body);
      say(msg || 'Saved');
      await onchanged?.();
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }
</script>

<div class="ed">
  {#if !receiving}
    <div class="togs">
      <button class="mg-chip tog" class:on={share.allow_download} aria-pressed={share.allow_download} disabled={busy}
              onclick={() => patch({ allow_download: !share.allow_download }, share.allow_download ? 'Downloads off' : 'Downloads on')}>
        {#if share.allow_download}<Icon name="check" size={13} />{/if}Downloads
      </button>
      <button class="mg-chip tog" class:on={share.allow_zip} aria-pressed={share.allow_zip} disabled={busy}
              onclick={() => patch({ allow_zip: !share.allow_zip })}>
        {#if share.allow_zip}<Icon name="check" size={13} />{/if}Zip of everything
      </button>
      <button class="mg-chip tog" class:on={share.allow_selects} aria-pressed={share.allow_selects} disabled={busy}
              onclick={() => patch({ allow_selects: !share.allow_selects })}>
        {#if share.allow_selects}<Icon name="check" size={13} />{/if}Picks, notes &amp; pins
      </button>
      <button class="mg-chip tog" class:on={share.watermark_previews} aria-pressed={share.watermark_previews} disabled={busy}
              onclick={() => patch({ watermark_previews: !share.watermark_previews })}>
        {#if share.watermark_previews}<Icon name="check" size={13} />{/if}Watermarked previews
      </button>
    </div>

    {#if share.watermark_previews}
      <div class="row">
        <span class="lbl">Watermark</span>
        {#if watermarks.length}
          <div class="mg-select grow">
            <select value={share.watermark_name || ''} disabled={busy} aria-label="Watermark"
                    onchange={(e) => patch({ watermark_name: e.currentTarget.value })}>
              <option value="">The first one ({watermarks[0].name})</option>
              {#each watermarks as w (w.name)}<option value={w.name}>{w.name}</option>{/each}
            </select>
            <span class="ic"><Icon name="chevronDown" size={15} /></span>
          </div>
        {:else}
          <span class="hint">No watermark PNGs yet — add one when making a portal.</span>
        {/if}
      </div>
    {/if}
  {:else}
    <p class="hint">A receiving portal shows nothing of the library, so there are no download or
      watermark settings. Only its expiry can change.</p>
  {/if}

  <div class="row">
    <span class="lbl">Expiry</span>
    <span class="val mg-tnum">{share.expires_at ? day(share.expires_at) : 'never'}</span>
    {#if share.expires_at}
      <button class="mg-btn secondary sm" disabled={busy}
              onclick={() => patch({ extend_days: 30 }, 'Extended by 30 days')}>
        <Icon name="clock" size={13} />+30 days
      </button>
    {/if}
  </div>
</div>

<style>
  .ed { display: flex; flex-direction: column; gap: 12px; }
  .togs { display: flex; flex-wrap: wrap; gap: 8px; }
  .tog { min-height: 40px; padding: 0 14px; font-size: 12.5px; cursor: pointer; }
  .row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .lbl { font: 500 11px/1.4 var(--mc-font); color: var(--mc-ink3); min-width: 70px; }
  .val { font: 500 13px/1 var(--mc-font); color: var(--mc-ink); }
  .grow { flex: 1 1 180px; min-width: 0; display: block; }
  .hint { margin: 0; font: 400 12px/1.5 var(--mc-font); color: var(--mc-ink3); }
</style>
