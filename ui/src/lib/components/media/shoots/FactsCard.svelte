<script>
  /* What the listing says — fed to the caption writer and the listing text.
     PATCH /api/shoots/{id} { facts: {...} }; a key sent as null clears it. */
  import Icon from '$lib/components/glass/Icon.svelte';
  import { say } from '$lib/media.svelte.js';
  import { shoots, KINDS } from '$lib/media/shoots.js';

  let { shoot, onchange } = $props();

  let f = $state({});
  let dirty = $state(false);
  let saving = $state(false);

  $effect(() => {
    const x = shoot.facts || {};
    f = { kind: x.kind || '', listing: x.listing || '', price: x.price ?? '', beds: x.beds ?? '',
          baths: x.baths ?? '', parking: x.parking ?? '', floor_m2: x.floor_m2 ?? '', erf_m2: x.erf_m2 ?? '',
          features: (x.features || []).join('\n') };
    dirty = false;
  });

  const num = (v, int = true) => (v === '' || v == null ? null : int ? Math.round(Number(v)) : Number(v));

  async function save() {
    saving = true;
    try {
      const facts = {
        kind: f.kind || null, listing: f.listing || null,
        price: num(f.price), beds: num(f.beds, false), baths: num(f.baths, false),
        parking: num(f.parking), floor_m2: num(f.floor_m2), erf_m2: num(f.erf_m2),
        features: String(f.features || '').split('\n').map((s) => s.trim()).filter(Boolean)
      };
      const s = await shoots.update(shoot.id, { facts });
      say('Listing facts saved');
      onchange?.(s);
    } catch (e) { say(e.message, 'error'); }
    finally { saving = false; }
  }

  const touch = () => (dirty = true);
  const NUMS = [['price', 'Price (R)', 1000], ['beds', 'Beds', 0.5], ['baths', 'Baths', 0.5], ['parking', 'Parking', 1],
                ['floor_m2', 'Floor m²', 1], ['erf_m2', 'Erf m²', 1]];
</script>

<section class="mg-card">
  <div class="hd"><h3><Icon name="property" size={15} />Listing facts</h3></div>
  <div class="grid" oninput={touch} onchange={touch}>
    <div class="f">
      <label class="mg-label" for="fx-kind">Kind</label>
      <div class="mg-select">
        <select id="fx-kind" bind:value={f.kind}>
          <option value="">—</option>
          {#each KINDS as k (k)}<option value={k}>{k[0].toUpperCase() + k.slice(1)}</option>{/each}
        </select>
        <span class="ic"><Icon name="chevronDown" size={15} /></span>
      </div>
    </div>
    <div class="f">
      <label class="mg-label" for="fx-list">For</label>
      <div class="mg-select">
        <select id="fx-list" bind:value={f.listing}>
          <option value="">—</option><option value="sale">Sale</option><option value="rent">Rent</option>
        </select>
        <span class="ic"><Icon name="chevronDown" size={15} /></span>
      </div>
    </div>
    {#each NUMS as [k, l, step] (k)}
      <div class="f">
        <label class="mg-label" for="fx-{k}">{l}</label>
        <input id="fx-{k}" class="mg-input mg-tnum" type="number" min="0" {step} inputmode="decimal" bind:value={f[k]} />
      </div>
    {/each}
    <div class="f full">
      <label class="mg-label" for="fx-feat">Features (one per line)</label>
      <textarea id="fx-feat" class="mg-input" rows="3" bind:value={f.features} placeholder="Pool&#10;Sea views&#10;Solar"></textarea>
    </div>
  </div>
  {#if dirty}
    <button class="mg-btn accent wide" onclick={save} disabled={saving}><Icon name="check" size={14} />Save facts</button>
  {/if}
</section>

<style>
  .hd { margin-bottom: 10px; }
  h3 { margin: 0; display: flex; align-items: center; gap: 7px; font: 600 14px/1.3 var(--mc-font); color: var(--mc-ink); }
  .grid { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); }
  .f { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
  .full { grid-column: 1 / -1; }
  .mg-select { display: block; }
  .wide { width: 100%; margin-top: 12px; }
</style>
