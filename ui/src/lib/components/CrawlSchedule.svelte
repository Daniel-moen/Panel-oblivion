<script>
  /* Auto-crawl schedule: one quiet line on /prospects ("Auto-crawl · next
     sweep 13:00") that opens a sheet with when it last ran, how long it
     took, when it runs next, and — for the owner and admins — the settings
     (GET/PATCH /api/crawl/schedule; saved in the database, the env vars are
     only defaults). Everyone else sees the same sheet read-only. */
  import { onMount } from 'svelte';
  import Sheet from './glass/Sheet.svelte';
  import Icon from './glass/Icon.svelte';
  import { get, patch } from '$lib/api.js';
  import { app, toast } from '$lib/state.svelte.js';

  let sched = $state(null);
  let open = $state(false);
  let saving = $state(false);
  let draft = $state(null);

  async function load() {
    try { sched = await get('/api/crawl/schedule'); } catch { /* the line just stays hidden */ }
  }
  onMount(() => {
    load();
    const t = setInterval(load, 5 * 60 * 1000);
    return () => clearInterval(t);
  });
  /* a crawl starting or finishing moves last/next */
  let wasRunning = null;
  $effect(() => {
    const r = !!app.status.running;
    if (wasRunning !== null && r !== wasRunning) load();
    wasRunning = r;
  });

  function edit() {
    draft = { ...sched.settings };
    open = true;
  }

  const WINDOWS = [
    { v: '0-0', label: 'Any time' },
    { v: '18-7', label: 'Outside office hours (18:00–07:00)' },
    { v: '7-18', label: 'Office hours only (07:00–18:00)' },
    { v: '20-6', label: 'Nights only (20:00–06:00)' }
  ];
  const windowKey = $derived(draft ? `${draft.sweep_from}-${draft.sweep_to}` : '');
  function setWindow(v) {
    const [a, b] = v.split('-').map(Number);
    draft.sweep_from = a; draft.sweep_to = b;
  }

  async function save() {
    saving = true;
    try {
      const body = {};
      for (const [k, v] of Object.entries(draft)) if (v !== sched.settings[k]) body[k] = v;
      sched = await patch('/api/crawl/schedule', body);
      draft = { ...sched.settings };
      toast('Crawl schedule saved', 'ok');
    } catch (e) {
      toast('Could not save: ' + e.message, 'error');
    } finally {
      saving = false;
    }
  }
  async function reset() {
    saving = true;
    try {
      sched = await patch('/api/crawl/schedule', { reset: true });
      draft = { ...sched.settings };
      toast('Back to the default schedule');
    } catch (e) {
      toast('Could not reset: ' + e.message, 'error');
    } finally { saving = false; }
  }

  const hm = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—');
  function when(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    const today = new Date();
    const tmr = new Date(); tmr.setDate(today.getDate() + 1);
    const yst = new Date(); yst.setDate(today.getDate() - 1);
    const day = d.toDateString() === today.toDateString() ? 'today'
      : d.toDateString() === tmr.toDateString() ? 'tomorrow'
      : d.toDateString() === yst.toDateString() ? 'yesterday'
      : d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' });
    return `${day} ${hm(iso)}`;
  }
  function dur(s) {
    if (s == null) return '';
    const m = Math.round(s / 60);
    return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}`;
  }
  const hour = (h) => String(h).padStart(2, '0') + ':00';

  const s = $derived(sched?.settings);
  const nextKind = $derived(!sched?.next_run ? null
    : sched.next_run === sched.next_full ? 'full pass' : 'sweep');
  const line = $derived.by(() => {
    if (!sched) return '';
    if (sched.running && ['full', 'sweep'].includes(sched.running.kind))
      return `Auto-crawl · ${sched.running.kind === 'full' ? 'nightly pass' : 'sweep'} running`;
    if (!s.enabled) return 'Auto-crawl off';
    if (!sched.next_run) return 'Auto-crawl on';
    return `Auto-crawl · next ${nextKind} ${when(sched.next_run)}`;
  });
</script>

{#if sched}
  <button type="button" class="mg-chip line" onclick={edit} title="Crawl schedule">
    <span class="mg-dot" class:ok={s.enabled} class:warn={!!sched.running}></span>
    <Icon name="clock" size={13} /> {line}
  </button>
{/if}

<Sheet {open} title="Crawl schedule" size="md" onclose={() => (open = false)}>
  {#if sched && draft}
    <dl class="mg-kv">
      <div><dt>Last nightly pass</dt><dd>{when(sched.last_full.started)}{#if sched.last_full.duration_s != null} · took {dur(sched.last_full.duration_s)}{:else if sched.last_full.started} · did not finish{/if}</dd></div>
      <div><dt>Last sweep</dt><dd>{when(sched.last_sweep.started)}{#if sched.last_sweep.duration_s != null} · took {dur(sched.last_sweep.duration_s)}{:else if sched.last_sweep.started} · did not finish{/if}</dd></div>
      <div><dt>Next nightly pass</dt><dd>{s.enabled && s.full_enabled ? when(sched.next_full) : 'off'}</dd></div>
      <div><dt>Next sweep</dt><dd>{s.enabled && s.sweep_hours > 0 ? when(sched.next_sweep) : 'off'}</dd></div>
      {#if sched.skipping_next}
        <div><dt>Idle pairs skipped</dt><dd>{sched.skipping_next} of {sched.sweep_pairs} suburb × portal pairs next sweep</dd></div>
      {/if}
    </dl>

    {#if sched.can_edit}
      <div class="form">
        <label class="sw">
          <input type="checkbox" bind:checked={draft.enabled} />
          <span><b>Crawl automatically</b><small>Off: only the New crawl button starts a crawl.</small></span>
        </label>

        <fieldset disabled={!draft.enabled}>
          <label class="sw">
            <input type="checkbox" bind:checked={draft.full_enabled} />
            <span><b>Nightly full pass</b><small>Every suburb and portal, Property24 included.</small></span>
          </label>
          <div class="field">
            <span class="lbl">Starts at</span>
            <span class="mg-select">
              <select bind:value={draft.full_hour} disabled={!draft.full_enabled} aria-label="Nightly pass hour">
                {#each Array(24) as _, h (h)}<option value={h}>{hour(h)}</option>{/each}
              </select>
              <span class="ic"><Icon name="chevronDown" size={14} /></span>
            </span>
            <label class="inline"><input type="checkbox" bind:checked={draft.rentals} disabled={!draft.full_enabled} /> include the rent book</label>
          </div>

          <div class="field">
            <span class="lbl">Freshness sweep</span>
            <span class="mg-select">
              <select bind:value={draft.sweep_hours} aria-label="Sweep interval">
                <option value={0}>Off</option>
                {#each [4, 6, 8, 12, 24] as h (h)}<option value={h}>Every {h} h</option>{/each}
                {#if ![0, 4, 6, 8, 12, 24].includes(draft.sweep_hours)}<option value={draft.sweep_hours}>Every {draft.sweep_hours} h</option>{/if}
              </select>
              <span class="ic"><Icon name="chevronDown" size={14} /></span>
            </span>
          </div>
          <p class="mg-hint">Page 1 of the fast portals. Counted from when the last one started, so it can never run back to back.</p>

          <div class="field">
            <span class="lbl">Sweep only</span>
            <span class="mg-select wide">
              <select value={windowKey} onchange={(e) => setWindow(e.currentTarget.value)} disabled={!draft.sweep_hours} aria-label="Sweep window">
                {#each WINDOWS as w (w.v)}<option value={w.v}>{w.label}</option>{/each}
                {#if !WINDOWS.some((w) => w.v === windowKey)}<option value={windowKey}>{hour(draft.sweep_from)}–{hour(draft.sweep_to)}</option>{/if}
              </select>
              <span class="ic"><Icon name="chevronDown" size={14} /></span>
            </span>
          </div>

          <div class="field">
            <span class="lbl">Skip idle areas</span>
            <span class="mg-select">
              <select bind:value={draft.skip_idle_after} disabled={!draft.sweep_hours} aria-label="Skip idle after">
                <option value={0}>Never</option>
                {#each [2, 3, 5] as n (n)}<option value={n}>After {n} quiet sweeps</option>{/each}
              </select>
              <span class="ic"><Icon name="chevronDown" size={14} /></span>
            </span>
          </div>
          <p class="mg-hint">A suburb on a portal whose page 1 had nothing new {draft.skip_idle_after || 'N'} sweeps running is left out, and re-checked every {draft.reprobe_every}th sweep. The nightly pass always covers everything.</p>
        </fieldset>
      </div>
    {:else}
      <p class="mg-hint ro">Only the owner or an admin can change the schedule.</p>
    {/if}
  {/if}

  {#snippet footer()}
    {#if sched?.can_edit}
      <div class="foot">
        {#if sched.customised.length}
          <button type="button" class="mg-btn ghost" onclick={reset} disabled={saving}>Reset to defaults</button>
        {/if}
        <button type="button" class="mg-btn primary" onclick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
      </div>
    {/if}
  {/snippet}
</Sheet>

<style>
  .line { height: 30px; gap: 7px; color: var(--mc-ink3); }
  .line .mg-dot { width: 7px; height: 7px; }
  .form { margin-top: 16px; display: flex; flex-direction: column; gap: 12px; }
  fieldset { border: 0; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 12px; }
  fieldset:disabled { opacity: 0.5; }
  .sw { display: flex; gap: 10px; align-items: flex-start; cursor: pointer; }
  .sw input { width: 18px; height: 18px; margin: 2px 0 0; flex: none; }
  .sw b { display: block; font: 600 13.5px/1.3 var(--mc-font); color: var(--mc-ink); }
  .sw small { display: block; font: 400 12.5px/1.4 var(--mc-font); color: var(--mc-ink3); margin-top: 2px; }
  .field { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .lbl { flex: 0 0 120px; font: 500 12.5px/1.3 var(--mc-font); color: var(--mc-ink3); }
  .mg-select select { height: 36px; }
  .wide { flex: 1 1 220px; }
  .wide select { width: 100%; }
  .inline { display: inline-flex; align-items: center; gap: 6px; font: 500 12.5px/1 var(--mc-font); color: var(--mc-ink2); }
  .mg-hint { margin-top: -4px; }
  .ro { margin-top: 14px; }
  .foot { display: flex; justify-content: flex-end; gap: 8px; width: 100%; }
</style>
