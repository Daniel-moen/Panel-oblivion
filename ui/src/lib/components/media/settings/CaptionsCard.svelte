<script>
  /* The bits every listing caption ends with: the agency's hashtags and a
     sign-off line. Written once here, added to every caption drafted for a
     shoot. Needs shoots.manage (captions belong to shoots). */
  import { onMount } from 'svelte';
  import { say } from '$lib/media.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import SettingsCard from './SettingsCard.svelte';
  import { settingsApi as api } from './api.js';

  let s = $state(null);
  let busy = $state(false);
  let err = $state('');

  onMount(async () => {
    try { const r = await api.captions(); s = { hashtags: r.hashtags || '', signoff: r.signoff || '' }; }
    catch (e) { err = e.message; }
  });

  async function save() {
    busy = true;
    try {
      const r = await api.saveCaptions({ hashtags: s.hashtags, signoff: s.signoff });
      s = { hashtags: r.hashtags || '', signoff: r.signoff || '' };
      say('Caption defaults saved');
    } catch (e) { say(e.message, 'error'); }
    finally { busy = false; }
  }
</script>

<SettingsCard label="Caption defaults" sub="Added to every social caption drafted for a shoot.">
  {#if err}
    <div class="mg-strip crit"><span class="ic"><Icon name="alert" size={15} /></span><span>{err}</span></div>
  {:else if !s}
    <Skeleton h="7rem" r="12px" />
  {:else}
    <div class="pane mg-panel">
      <div class="fields">
        <div class="field">
          <label class="mg-label" for="cap-h">Hashtags</label>
          <textarea id="cap-h" class="mg-input" rows="2" maxlength="600" bind:value={s.hashtags}
                    placeholder="#oblivionestates #capetownproperty #forsale"></textarea>
        </div>
        <div class="field">
          <label class="mg-label" for="cap-s">Sign-off</label>
          <textarea id="cap-s" class="mg-input" rows="2" maxlength="300" bind:value={s.signoff}
                    placeholder="Call Oblivion Estates on 021 000 0000 to view."></textarea>
        </div>
      </div>
      <div class="btnrow" style="margin-top:12px">
        <button class="mg-btn primary sm" onclick={save} disabled={busy}><Icon name="check" size={13} />Save</button>
      </div>
    </div>
  {/if}
</SettingsCard>

<style>
  textarea.mg-input { min-height: 64px; resize: vertical; padding: 10px 14px; line-height: 1.5; }
</style>
