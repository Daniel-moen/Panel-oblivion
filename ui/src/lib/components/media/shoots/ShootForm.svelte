<script>
  /* The fields a shoot takes (shoots.py NewShoot / EditShoot):
     address · suburb · agent · shoot_date · shoot_time · note · lat/lng.

     The address search asks the backend (/api/shoots/geocode/search, which
     asks OpenStreetMap on our behalf — the browser never talks to a third
     party). Picking a result sets the pin and the suburb; the typed address
     stays the one on the invoice unless the field is still empty. */
  import { play, fadeIn } from '$lib/motion.js';
  import Icon from '$lib/components/glass/Icon.svelte';
  import { shoots } from '$lib/media/shoots.js';

  let { value = $bindable(), agents = [], near = null, idp = 'sf' } = $props();

  let finding = $state(false);
  let results = $state(null);
  let findMsg = $state('');

  async function find() {
    const s = (value.address || '').trim();
    if (s.length < 3) { findMsg = 'Type at least three characters of the address first.'; return; }
    finding = true; findMsg = ''; results = null;
    try {
      const r = (await shoots.geocode(s, near))?.results || [];
      results = r;
      if (!r.length) findMsg = 'Nothing found — add the suburb or town and try again.';
      else if (!r.some((x) => x.exact)) findMsg = "The exact house number wasn't found — pick the street.";
    } catch (e) { findMsg = e.message; }
    finally { finding = false; }
  }

  function pick(r) {
    value.lat = r.lat;
    value.lng = r.lng;
    if (r.suburb && !value.suburb) value.suburb = r.suburb;
    if (!value.address?.trim()) value.address = String(r.label || '').split(',')[0];
    results = null;
    findMsg = '';
  }

  function onAddrKey(e) {
    if (e.key === 'Enter') { e.preventDefault(); find(); }
  }
</script>

<div class="form">
  <div class="f">
    <label class="mg-label" for="{idp}-addr">Address</label>
    <div class="addr">
      <input id="{idp}-addr" class="mg-input" type="text" bind:value={value.address}
             onkeydown={onAddrKey} placeholder="12 Ocean View Drive" autocomplete="off" required minlength="3" />
      <button type="button" class="mg-btn secondary icon" onclick={find} disabled={finding}
              aria-label="Find this address on the map" title="Find on the map">
        {#if finding}<span class="mg-spin"></span>{:else}<Icon name="mapPin" size={16} />{/if}
      </button>
    </div>
    {#if results?.length}
      <ul class="results mg-popover" transition:play={fadeIn}>
        {#each results as r, i (i)}
          <li>
            <button type="button" onclick={() => pick(r)}>
              <b>{r.label}</b>
              <span>{r.exact ? 'house' : 'street'} · {r.km} km</span>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
    {#if findMsg}<p class="hint">{findMsg}</p>{/if}
    {#if value.lat != null && value.lng != null}
      <p class="hint pin">
        <Icon name="pin" size={12} />
        <span class="mg-tnum">{Number(value.lat).toFixed(5)}, {Number(value.lng).toFixed(5)}</span>
        <button type="button" class="lnk" onclick={() => { value.lat = null; value.lng = null; value.clear_location = true; }}>clear</button>
      </p>
    {/if}
  </div>

  <div class="two">
    <div class="f">
      <label class="mg-label" for="{idp}-sub">Suburb</label>
      <input id="{idp}-sub" class="mg-input" type="text" bind:value={value.suburb} placeholder="Camps Bay" />
    </div>
    <div class="f">
      <label class="mg-label" for="{idp}-agent">Agent</label>
      <input id="{idp}-agent" class="mg-input" type="text" bind:value={value.agent}
             list="{idp}-agents" placeholder="Pick or type a name" autocomplete="off" />
      <datalist id="{idp}-agents">
        {#each agents as a (a.id)}<option value={a.name}>{a.agency || ''}</option>{/each}
      </datalist>
    </div>
  </div>

  <div class="two">
    <div class="f">
      <label class="mg-label" for="{idp}-date">Booked for</label>
      <input id="{idp}-date" class="mg-input" type="date" bind:value={value.shoot_date} />
    </div>
    <div class="f">
      <label class="mg-label" for="{idp}-time">Time</label>
      <input id="{idp}-time" class="mg-input" type="time" step="300" bind:value={value.shoot_time} />
    </div>
  </div>

  <div class="f">
    <label class="mg-label" for="{idp}-note">Notes</label>
    <textarea id="{idp}-note" class="mg-input" rows="3" maxlength="2000" bind:value={value.note}
              placeholder="Gate code, keys with the neighbour, twilight wanted…"></textarea>
  </div>
</div>

<style>
  .form { display: flex; flex-direction: column; gap: 12px; }
  .f { display: flex; flex-direction: column; gap: 5px; min-width: 0; position: relative; }
  .two { display: grid; gap: 12px; grid-template-columns: 1fr 1fr; }
  @media (max-width: 420px) { .two { grid-template-columns: 1fr; } }
  .addr { display: flex; gap: 8px; }
  .addr .mg-input { flex: 1; min-width: 0; }

  .results { list-style: none; margin: 4px 0 0; max-height: 240px; overflow-y: auto; }
  .results button {
    width: 100%; min-height: 40px; display: flex; flex-direction: column; align-items: flex-start; gap: 2px;
    padding: 7px 10px; border: 0; border-radius: var(--mc-r-sm); background: none; color: var(--mc-ink);
    text-align: left; cursor: pointer; font: inherit;
  }
  .results button:hover { background: var(--mc-line); }
  .results b { font: 500 13px/1.3 var(--mc-font); }
  .results span { font: 400 11.5px/1.3 var(--mc-font); color: var(--mc-ink3); }

  .hint { margin: 2px 0 0; font: 400 11.5px/1.45 var(--mc-font); color: var(--mc-ink3); }
  .pin { display: flex; align-items: center; gap: 6px; color: var(--mc-accent); }
  @media (pointer: coarse) { .results button { min-height: 44px; } .lnk { min-height: 36px; } }
  .lnk { border: 0; background: none; padding: 4px; color: var(--mc-ink3); text-decoration: underline; cursor: pointer; font: inherit; }

</style>
