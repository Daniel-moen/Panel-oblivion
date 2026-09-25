<script>
  import { api } from '$lib/api.js';
  import { actions, toast } from '$lib/state.svelte.js';
  import { fmtInt, fmtArea, satUrl } from '$lib/format.js';
  import Icon from './glass/Icon.svelte';

  let { r } = $props();

  const resolved = $derived(['ok', 'confirmed', 'check'].includes(r.erf_status));
  const erfLabel = $derived(`${r.erf_number}${r.erf_portion ? '/' + r.erf_portion : ''}`);

  /* ------------------------------------------------------------- deed ---- */
  let deed = $state(null);
  let deedErr = $state(null);
  let deedBusy = $state(false);
  let deedGid = null;

  /* The status poll replaces the prospect objects every few seconds, so `r`
     changes identity even when it is still the same property — keying the
     reset on the object used to wipe a fetched deed off the screen moments
     later. Key on the group_id VALUE instead, and since /api/deed persists
     into owner_details, load whatever the server already holds. */
  $effect(() => {
    const gid = r.group_id;
    if (gid === deedGid) return;
    deedGid = gid;
    deed = null; deedErr = null;
    if (gid != null) loadStored(gid);
  });

  async function loadStored(gid) {
    try {
      const d = await api.owner(String(gid));
      if (deedGid === gid && d && Object.keys(d).length && !deed) deed = d;
    } catch { /* nothing stored yet — the fetch button covers it */ }
  }

  async function fetchDeed() {
    deedBusy = true; deedErr = null;
    try {
      deed = await api.deed(String(r.group_id));
    } catch (e) {
      deedErr = e.code === 'loom_auth'
        ? 'LOOM session expired — refresh the token (run loom_login.py on the Mac).'
        : e.code === 'no_erf'
          ? 'Resolve this property’s erf number first.'
          : e.message || String(e);
    } finally { deedBusy = false; }
  }

  const deedRows = $derived.by(() => {
    if (!deed) return [];
    return [
      ['Registered owner', deed.owner_name],
      ['Owner type', deed.owner_type],
      ['Title deed', deed.deed_number],
      ['Registered', deed.purchase_date],
      ['Purchase price', deed.purchase_price ? 'R' + fmtInt(deed.purchase_price) : null],
      ['Bond holder', deed.bond_holder],
      ['Phone', deed.phone],
      ['Email', deed.email]
    ].filter(([, v]) => v != null && v !== '');
  });

  function copyCma() {
    navigator.clipboard.writeText(
      `${r.official_address}, ${r.official_suburb} — Erf ${erfLabel}`);
    toast('Copied for CMA search');
  }

  /* AI locate pick, when present */
  const ai = $derived(r.erf_ai);
  const aiCand = $derived.by(() => {
    if (!ai?.best) return null;
    return (r.erf_cands || []).find((c) => String(c.erf) === String(ai.best.erf)) || null;
  });
  const aiVerdict = $derived(ai?.verify?.verdict);
  const aiConf = $derived(Math.max(0, Math.min(100, Number(ai?.best?.confidence) || 0)));
  const confTone = $derived(aiConf >= 75 ? '' : aiConf >= 50 ? 'warn' : 'crit');

  /* The candidate parcels the cadastre matched, a few at most on screen. */
  const cands = $derived((r.erf_cands || []).slice(0, 6));
</script>

<div class="erf">
  {#if resolved}
    <div class="head">
      <b>Erf <span class="mg-mono">{erfLabel}</span></b>
      {#if r.erf_status === 'check'}<span class="mg-chip warn" title={r.erf_note || 'size mismatch'}>Verify</span>{:else}<span class="mg-chip ok">Resolved</span>{/if}
      {#if r.parcel_area_m2}<span class="area mg-mono">{fmtArea(r.parcel_area_m2)}</span>{/if}
    </div>
    <p class="addr">{r.official_address}{r.official_suburb ? `, ${r.official_suburb}` : ''}</p>
    {#if r.erf_status === 'check' && r.erf_note}
      <div class="mg-strip warn"><span class="ic"><Icon name="alert" size={14} /></span><span>Verify: {r.erf_note}</span></div>
    {/if}
    <div class="acts">
      {#if r.erf_lat}
        <a class="mg-btn sm secondary" href={satUrl(r.erf_lat, r.erf_lng)} target="_blank" rel="noopener"><Icon name="mapPin" size={14} /> Satellite</a>
      {/if}
      <button type="button" class="mg-btn sm secondary" onclick={copyCma}><Icon name="copy" size={14} /> Copy for CMA</button>
      {#if r.group_id != null}
        <button type="button" class="mg-btn sm secondary" disabled={deedBusy} onclick={fetchDeed}>
          {#if deedBusy}<span class="mg-spin"></span> Fetching deed…{:else}<Icon name="key" size={14} /> {deed ? 'Refresh deed' : 'Get deed info'}{/if}
        </button>
      {/if}
    </div>

    {#if deedErr}<div class="mg-strip crit"><span class="ic"><Icon name="alert" size={14} /></span><span>{deedErr}</span></div>{/if}
    {#if deed}
      {#if deedRows.length}
        <div class="deed">
          <span class="hud">Title deed</span>
          <dl class="mg-kv">
            {#each deedRows as [k, v] (k)}
              <div><dt>{k}</dt><dd>{v}</dd></div>
            {/each}
          </dl>
          <p class="mg-hint">{deed.notes || 'Via LOOM deeds registry'}{deed.updated_at ? ` · saved ${String(deed.updated_at).slice(0, 16)}` : ''} · POPIA: mandate pitch only</p>
        </div>
      {:else}
        <p class="mg-hint gap">LOOM returned no owner/deed detail.</p>
      {/if}
    {/if}
  {:else}
    {#if r.erf_status === 'candidates'}
      <p class="cand"><b class="mg-tnum">{r.erf_cand_count}</b> candidate erven
        <span class="dim">· {r.erf_note || 'same suburb, matching erf size'}</span></p>
    {:else}
      <p class="cand dim">{r.erf_note || 'Not resolved yet — run “Resolve erfs” from the crawl panel, or locate from photos.'}</p>
    {/if}

    {#if cands.length}
      <div class="mg-list cands">
        {#each cands as c (c.erf + '/' + (c.portion ?? ''))}
          <div class="mg-listrow" class:sel={ai?.best && String(ai.best.erf) === String(c.erf)}>
            <div class="t">
              <b>Erf <span class="mg-mono">{c.erf}{c.portion ? '/' + c.portion : ''}</span>{#if ai?.best && String(ai.best.erf) === String(c.erf)}<span class="mg-chip mgr pick">AI pick</span>{/if}</b>
              <span>{[c.address, c.suburb].filter(Boolean).join(' · ') || '—'}</span>
            </div>
            {#if c.area_m2}<span class="carea mg-mono">{fmtArea(c.area_m2)}</span>{/if}
            {#if c.lat}
              <a class="mg-btn ghost icon sm" href={satUrl(c.lat, c.lng)} target="_blank" rel="noopener"
                 aria-label="Satellite view of erf {c.erf}" title="Satellite view"><Icon name="mapPin" size={14} /></a>
            {/if}
          </div>
        {/each}
      </div>
      {#if (r.erf_cands || []).length > cands.length}
        <p class="mg-hint gap">Showing {cands.length} of {r.erf_cands.length} parcels.</p>
      {/if}
    {/if}

    <div class="acts">
      {#if r.erf_ai_running}
        <span class="mg-btn sm ghost busy"><span class="mg-spin"></span> AI locating…</span>
      {:else}
        <button type="button" class="mg-btn sm secondary" onclick={() => actions.erfLocate(r.listing_key)}
          title="Download the listing photos and satellite crops of candidate parcels, then ask a vision model which stand this is">
          <Icon name="sparkles" size={14} /> {ai ? 'Re-run AI locate' : 'AI locate from photos'}
        </button>
      {/if}
    </div>

    {#if ai?.best}
      <div class="aipick">
        <div class="aihead">
          <span class="hud mgr">AI pick</span>
          <b>Erf <span class="mg-mono">{ai.best.erf}</span></b>
          {#if aiVerdict === 'confirm'}<span class="mg-chip ok">Verified</span>
          {:else if aiVerdict === 'reject'}<span class="mg-chip crit">Verifier rejected</span>
          {:else if aiVerdict === 'uncertain'}<span class="mg-chip warn">Verifier unsure</span>{/if}
        </div>
        {#if aiCand}<p class="addr">{aiCand.address}</p>{/if}
        <div class="conf">
          <div class="mg-bar {confTone}"><i style:width="{aiConf}%"></i></div>
          <span class="mg-mono">{ai.best.confidence ?? '?'}%</span>
        </div>
        {#if ai.best.verdict}<p class="vtext">{ai.best.verdict}</p>{/if}
        {#if ai.street_clues}<p class="vtext">Text clues: {ai.street_clues}</p>{/if}
        {#if aiCand}
          <div class="acts">
            {#if aiCand.lat}
              <a class="mg-btn sm secondary" href={satUrl(aiCand.lat, aiCand.lng)} target="_blank" rel="noopener"><Icon name="mapPin" size={14} /> Satellite</a>
            {/if}
            <button type="button" class="mg-btn sm accent" onclick={() => actions.erfConfirm(r.listing_key, String(ai.best.erf))}>
              <Icon name="check" size={14} /> Accept
            </button>
          </div>
        {/if}
      </div>
    {/if}
    {#if r.erf_ai_error}<div class="mg-strip crit"><span class="ic"><Icon name="alert" size={14} /></span><span>AI locate failed — {r.erf_ai_error}</span></div>{/if}
  {/if}
</div>

<style>
  .erf { background: var(--mc-surface); border: 1px solid var(--mc-line); border-radius: var(--mc-r-md); padding: 14px; }

  .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .head b { font: 600 14px/1.3 var(--mc-font); color: var(--mc-ink); }
  .head .mg-chip { height: 22px; padding: 0 8px; font-size: 11px; }
  .area { margin-left: auto; font-size: 12.5px; color: var(--mc-ink2); }

  .addr { margin: 4px 0 0; font: 500 13px/1.45 var(--mc-font); color: var(--mc-ink); }
  .erf .mg-strip { margin: 10px 0 0; }

  .cand { margin: 0; font: 400 13px/1.5 var(--mc-font); color: var(--mc-ink2); }
  .cand b { color: var(--mc-ink); }
  .dim { color: var(--mc-ink3); }

  .cands { margin: 10px -14px 0; border-top: 1px solid var(--mc-line); border-bottom: 1px solid var(--mc-line); }
  .cands .mg-listrow { padding: 8px 14px; min-height: 48px; }
  .cands .t > b { display: flex; align-items: center; gap: 6px; }
  .pick { height: 20px; padding: 0 7px; font-size: 10.5px; }
  .carea { flex: none; font-size: 12px; color: var(--mc-ink2); }

  .acts { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 12px; }
  .busy { color: var(--mc-mgr); }

  .aipick { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--mc-line); }
  .aihead { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .aihead .hud.mgr { color: var(--mc-mgr); }
  .aihead b { font: 600 13.5px/1.3 var(--mc-font); color: var(--mc-ink); }
  .aihead .mg-chip { height: 22px; padding: 0 8px; font-size: 11px; }
  .conf { display: grid; grid-template-columns: 1fr auto; gap: 10px; align-items: center; margin-top: 10px; }
  .conf .mg-mono { font-size: 12px; color: var(--mc-ink); }
  .vtext { margin: 8px 0 0; font: 400 12.5px/1.55 var(--mc-font); color: var(--mc-ink2); }

  .deed { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--mc-line); }
  .deed .hud { margin-bottom: 2px; }
  .deed .mg-hint { margin-top: 8px; font-size: 11.5px; }
  .gap { margin-top: 10px; }

  @media (pointer: coarse) {
    .acts :global(.mg-btn.sm) { height: 40px; }
    .cands .mg-btn.icon.sm { width: 40px; height: 40px; }
  }
</style>
