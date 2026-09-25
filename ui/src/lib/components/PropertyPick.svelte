<script>
  /* A one-line property picker for a task: type an address, suburb or
     title, pick one of the eight matches the server offers, and the task
     links to that prospect group. Self-contained on purpose (team.py's
     /api/team/properties, no Finder state) so it can sit inside the task
     card on the home page without dragging the prospect list in.

     Props:
       value     {group_id, label, suburb?} | null — bound
       onchange  optional, called with the new value */
  import { api } from '$lib/api.js';
  import Icon from '$lib/components/glass/Icon.svelte';

  let { value = $bindable(null), onchange = null, placeholder = 'Link a property…' } = $props();

  let q = $state('');
  let results = $state([]);
  let open = $state(false);
  let timer = null;

  function search() {
    clearTimeout(timer);
    const want = q.trim();
    if (want.length < 2) { results = []; open = false; return; }
    timer = setTimeout(async () => {
      try {
        const r = await api.propertySearch(want);
        results = r.results || [];
        open = true;
      } catch { results = []; }
    }, 180);
  }

  function pick(p) {
    value = { group_id: p.group_id, label: p.label, suburb: p.suburb };
    q = '';
    results = [];
    open = false;
    onchange?.(value);
  }

  function clear() {
    value = null;
    onchange?.(null);
  }
</script>

<div class="pp">
  {#if value}
    <span class="mg-chip ok picked">
      <Icon name="property" size={13} />
      <span class="lb">{value.label}{#if value.suburb}<i>{' · ' + value.suburb}</i>{/if}</span>
      <button type="button" class="x" onclick={clear} aria-label="Remove property link">
        <Icon name="close" size={12} />
      </button>
    </span>
  {:else}
    <label class="mg-search">
      <span class="ic"><Icon name="search" size={14} /></span>
      <input class="mg-input" type="search" {placeholder} bind:value={q} oninput={search}
             onfocus={() => (open = results.length > 0)}
             onblur={() => setTimeout(() => (open = false), 150)}
             autocomplete="off" aria-label="Link a property" />
    </label>
    {#if open && results.length}
      <ul class="mg-popover menu" role="listbox">
        {#each results as p (p.group_id)}
          <li>
            <button type="button" role="option" aria-selected="false" onmousedown={(e) => e.preventDefault()} onclick={() => pick(p)}>
              <b>{p.label}</b>
              <i>{p.suburb || ''}{#if p.tracked} · tracked{/if}</i>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</div>

<style>
  .pp { position: relative; display: flex; align-items: center; min-width: 0; width: 100%; min-height: 40px; }
  .mg-search { width: 100%; }
  .mg-search .mg-input { padding-right: 12px; }
  .mg-input::-webkit-search-cancel-button { display: none; }

  .menu {
    position: absolute; left: 0; right: 0; top: calc(100% + 4px); z-index: 30;
    margin: 0; list-style: none; max-height: 260px; overflow-y: auto;
  }
  .menu li { display: block; }
  .menu button {
    width: 100%; min-height: 44px; padding: 8px 10px; border: 0; border-radius: 8px;
    background: none; text-align: left; display: flex; flex-direction: column; gap: 1px;
    cursor: pointer; color: var(--mc-ink); font: inherit;
    transition: background var(--mc-t-fast);
  }
  .menu button:hover, .menu button:focus-visible { background: rgba(255, 255, 255, 0.05); outline: none; }
  .menu b { font: 500 13.5px/1.3 var(--mc-font); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }
  .menu i { font: 400 12px/1.3 var(--mc-font); font-style: normal; color: var(--mc-ink3); }

  .picked { height: 40px; max-width: 100%; padding-right: 4px; gap: 8px; font-size: 13px; }
  .picked .lb { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .picked i { font-style: normal; color: var(--mc-ink2); font-weight: 400; }
  .x {
    flex: none; width: 30px; height: 30px; border: 0; border-radius: 9999px; padding: 0;
    display: grid; place-items: center; background: none; color: var(--mc-ink2); cursor: pointer;
    transition: background var(--mc-t-fast), color var(--mc-t-fast);
  }
  .x:hover { background: rgba(255, 255, 255, 0.08); color: var(--mc-ink); }
</style>
