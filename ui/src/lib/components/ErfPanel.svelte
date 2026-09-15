<script>
  import { api } from '$lib/api.js';
  import { actions, toast } from '$lib/state.svelte.js';
  import { fmtInt, fmtArea, satUrl } from '$lib/format.js';

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
</script>

<div class="erf" class:soft={!resolved}>
  {#if resolved}
    <div class="head">
      <b>Erf {erfLabel}</b>
      {#if r.erf_status === 'check'}<span class="chk" title={r.erf_note || 'size mismatch'}>verify</span>{/if}
      {#if r.parcel_area_m2}<span class="area">{fmtArea(r.parcel_area_m2)}</span>{/if}
    </div>
    <p class="addr">{r.official_address}{r.official_suburb ? `, ${r.official_suburb}` : ''}</p>
    {#if r.erf_status === 'check' && r.erf_note}
      <p class="note">Verify: {r.erf_note}</p>
    {/if}
    <div class="acts">
      {#if r.erf_lat}
        <a class="act" href={satUrl(r.erf_lat, r.erf_lng)} target="_blank" rel="noopener">Satellite ↗</a>
      {/if}
      <button class="act" onclick={copyCma}>Copy for CMA</button>
      {#if r.group_id != null}
        <button class="act" disabled={deedBusy} onclick={fetchDeed}>
          {deedBusy ? 'Fetching deed…' : deed ? 'Refresh deed' : 'Get deed info'}
        </button>
      {/if}
    </div>

    {#if deedErr}<p class="note bad">{deedErr}</p>{/if}
    {#if deed}
      {#if deedRows.length}
        <div class="deed">
          {#each deedRows as [k, v] (k)}
            <div class="drow"><span>{k}</span><b>{v}</b></div>
          {/each}
          <p class="pop">{deed.notes || 'Via LOOM deeds registry'}
            {deed.updated_at ? ` · saved ${String(deed.updated_at).slice(0, 16)}` : ''}
            · POPIA: mandate pitch only</p>
        </div>
      {:else}
        <p class="note">LOOM returned no owner/deed detail.</p>
      {/if}
    {/if}
  {:else}
    {#if r.erf_status === 'candidates'}
      <p class="cand"><b>{r.erf_cand_count}</b> candidate erven
        <span class="dim">({r.erf_note || 'same suburb, matching erf size'})</span></p>
    {:else}
      <p class="cand dim">{r.erf_note || 'Not resolved yet — run “Resolve erfs” from the crawl panel, or locate from photos.'}</p>
    {/if}

    <div class="acts">
      {#if r.erf_ai_running}
        <span class="act busy"><span class="spin"></span>&nbsp;AI locating…</span>
      {:else}
        <button class="act" onclick={() => actions.erfLocate(r.listing_key)}
          title="Download the listing photos and satellite crops of candidate parcels, then ask a vision model which stand this is">
          {ai ? 'Re-run AI locate' : 'AI locate from photos'}
        </button>
      {/if}
    </div>

    {#if ai?.best}
      <div class="aipick">
        <p>AI pick: <b>erf {ai.best.erf}</b>{aiCand ? ` · ${aiCand.address}` : ''}
          · {ai.best.confidence ?? '?'}% confident
          {#if aiVerdict === 'confirm'}<span class="v ok">verified ✓</span>
          {:else if aiVerdict === 'reject'}<span class="v no">verifier rejected ✗</span>
          {:else if aiVerdict === 'uncertain'}<span class="v un">verifier unsure</span>{/if}
        </p>
        {#if ai.best.verdict}<p class="dim vtext">{ai.best.verdict}</p>{/if}
        {#if ai.street_clues}<p class="dim vtext">Text clues: {ai.street_clues}</p>{/if}
        <div class="acts">
          {#if aiCand?.lat}
            <a class="act" href={satUrl(aiCand.lat, aiCand.lng)} target="_blank" rel="noopener">Satellite ↗</a>
          {/if}
          {#if aiCand}
            <button class="act ok" onclick={() => actions.erfConfirm(r.listing_key, String(ai.best.erf))}>
              Accept ✓
            </button>
          {/if}
        </div>
      </div>
    {/if}
    {#if r.erf_ai_error}<p class="note bad">AI locate failed — {r.erf_ai_error}</p>{/if}
  {/if}
</div>

<style>
  .erf { background: var(--bg-3); border: 1px solid var(--line);
         border-radius: var(--r); padding: 0.85rem 1rem; font-size: 0.82rem; }
  .erf.soft { background: var(--bg-2); border-style: dashed; border-color: var(--line-2); }

  .head { display: flex; align-items: baseline; gap: 0.6rem; }
  .head b { font-size: 0.86rem; font-weight: 700; color: var(--ink); }
  .area { color: var(--ink-3); font-size: 0.76rem; }
  .chk { color: var(--warm-ink); background: var(--warm-soft); font-size: 0.68rem; font-weight: 600;
         border-radius: 999px; padding: 0.08rem 0.5rem; }

  .addr { margin: 0.25rem 0 0; color: var(--ink); font-weight: 500; }
  .note { margin: 0.5rem 0 0; font-size: 0.78rem; font-weight: 500; color: var(--psole); }
  .note.bad { color: var(--bad); }
  .dim { color: var(--ink-3); }
  .cand { margin: 0; color: var(--ink-2); }
  .cand b { color: var(--ink); }

  .acts { display: flex; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.6rem; }
  .act.busy { color: var(--accent-2); border-color: transparent; background: none; }
  .act.ok { color: var(--open); border-color: var(--open); }
  .act.ok:hover { background: var(--open-soft); }

  .aipick { margin-top: 0.7rem; padding-top: 0.6rem; border-top: 1px solid var(--line-2); }
  .aipick p { margin: 0; }
  .aipick b { color: var(--accent-2); }
  .vtext { margin-top: 0.3rem; font-size: 0.76rem; line-height: 1.5; }
  .v { margin-left: 0.4rem; font-size: 0.74rem; font-weight: 600; }
  .v.ok { color: var(--good); } .v.no { color: var(--bad); } .v.un { color: var(--psole); }

  .deed { margin-top: 0.7rem; border-top: 1px solid var(--line-2); padding-top: 0.5rem; }
  .drow { display: flex; justify-content: space-between; gap: 1rem;
          align-items: baseline; padding: 0.22rem 0; }
  .drow span { font-size: 0.74rem; color: var(--ink-3); }
  .drow b { font-weight: 600; font-size: 0.82rem; text-align: right; word-break: break-word; }
  .pop { margin: 0.55rem 0 0; font-size: 0.7rem; color: var(--ink-3); }
</style>
