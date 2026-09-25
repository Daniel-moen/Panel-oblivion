<script>
  /* The crawl setup — the app's one signature action, so it opens as a Sheet:
     the raised plane, scrim, Esc, focus trap and the phone's bottom-sheet
     shape all come from components/glass/Sheet.svelte.

     Inside: portal tiles (check toggles), the area finder with regions that
     fold, the options (pages per area as a Seg, two switches) and a footer
     whose one primary action is "Start crawl". Selection persists in
     localStorage under `obv2.crawl`. */
  import { app, actions } from '$lib/state.svelte.js';
  import Sheet from '$lib/components/glass/Sheet.svelte';
  import Seg from '$lib/components/glass/Seg.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';

  const PAGE_OPTS = [1, 2, 3, 4, 5].map((n) => ({ value: n, label: String(n) }));

  const PRIME = ['clifton', 'camps-bay', 'bantry-bay', 'fresnaye', 'bishopscourt',
                 'constantia', 'llandudno', 'bakoven'];
  const SLOW = ['property24'];

  const sources = $derived(app.config.sources || []);
  const regions = $derived(Object.entries(app.config.suburbs || {}));
  const running = $derived(app.status.running);
  const storedBySource = $derived(app.stats?.by_source || {});

  /* selection — persisted so tomorrow's crawl starts where today's left off */
  let sel = $state({ suburbs: PRIME, sources: null, pages: 2, useAi: true,
                     rentals: false });
  let restored = false;

  $effect(() => {
    if (restored) return;
    try {
      const raw = localStorage.getItem('obv2.crawl');
      if (raw) sel = { ...sel, ...JSON.parse(raw) };
    } catch { /* first run */ }
    restored = true;
  });
  $effect(() => {
    if (restored) localStorage.setItem('obv2.crawl', JSON.stringify(sel));
  });

  const enabledSources = $derived(sources.filter(([, , ok]) => ok).map(([n]) => n));
  const pickedSources = $derived(
    (sel.sources ?? enabledSources).filter((n) => enabledSources.includes(n)));

  function toggleSource(name) {
    const cur = new Set(pickedSources);
    cur.has(name) ? cur.delete(name) : cur.add(name);
    sel.sources = [...cur];
  }
  function presetSources(p) {
    sel.sources = p === 'all' ? [...enabledSources]
      : p === 'none' ? []
      : enabledSources.filter((n) => !SLOW.includes(n));
  }

  function toggleSuburb(slug) {
    const cur = new Set(sel.suburbs);
    cur.has(slug) ? cur.delete(slug) : cur.add(slug);
    sel.suburbs = [...cur];
  }
  function presetAreas(p) {
    if (p === 'all')
      sel.suburbs = regions.flatMap(([, items]) => items.map((t) => t[0]));
    else if (p === 'none') sel.suburbs = [];
    else sel.suburbs = [...PRIME];
  }
  function presetRegion(items, on) {
    const slugs = items.map((t) => t[0]);
    const cur = new Set(sel.suburbs);
    for (const s of slugs) on ? cur.add(s) : cur.delete(s);
    sel.suburbs = [...cur];
  }

  /* ——— areas: a search across every region, and regions that fold away ——— */
  let q = $state('');
  let folded = $state({});          // region -> explicit open/closed, else auto

  const shownRegions = $derived.by(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return regions;
    return regions
      .map(([r, items]) => [r, items.filter(([slug, name]) =>
        name.toLowerCase().includes(needle) || slug.includes(needle))])
      .filter(([, items]) => items.length);
  });

  /* open where the work is: a search hit, an explicit click, or a region the
     crawl already covers */
  function isOpen(region, items) {
    if (region in folded) return folded[region];
    if (q.trim()) return true;
    return items.some(([slug]) => sel.suburbs.includes(slug));
  }
  const picked = (items) => items.filter(([slug]) => sel.suburbs.includes(slug)).length;

  const estimate = $derived(pickedSources.length * sel.suburbs.length * (+sel.pages || 0));
  const summary = $derived(
    `${pickedSources.length} portal${pickedSources.length === 1 ? '' : 's'} · ` +
    `${sel.suburbs.length} area${sel.suburbs.length === 1 ? '' : 's'} · ` +
    `${sel.pages} page${+sel.pages === 1 ? '' : 's'} each ≈ ${estimate} pages` +
    (sel.rentals ? ' · rentals too' : ''));

  async function start() {
    const ok = await actions.scrape({
      suburbs: sel.suburbs, sources: pickedSources,
      pages: +sel.pages, use_ai: sel.useAi,
      /* 'both' crawls each portal's to-rent book in the same pass; rentals
         are only stored, never deduped or scored. */
      type: sel.rentals ? 'both' : 'sale'
    });
    if (ok) { app.runOpen = false; app.logOpen = true; }
  }
</script>

<Sheet open={app.runOpen} title="New crawl" size="full" onclose={() => (app.runOpen = false)}>
  <p class="mg-hint lede">Pick portals and areas, then let the engine run.</p>

  <div class="grid">
    <section class="mg-section portals">
      <div class="head">
        <h3>Portals</h3>
        <span class="mg-chip on cnt mg-tnum">{pickedSources.length}</span>
        <div class="mg-actions presets" role="group" aria-label="Portal presets">
          <button type="button" class="mg-btn ghost sm" onclick={() => presetSources('all')}>All</button>
          <button type="button" class="mg-btn ghost sm" onclick={() => presetSources('fast')}
                  title="Skip the slow, easily-blocked Property24 crawl">Fast</button>
          <button type="button" class="mg-btn ghost sm" onclick={() => presetSources('none')}>None</button>
        </div>
      </div>
      <div class="body">
        {#if !sources.length}
          <p class="mg-hint">No portals reported by the engine yet.</p>
        {/if}
        <div class="srcgrid">
          {#each sources as [name, label, ok, why] (name)}
            {@const on = pickedSources.includes(name)}
            <button type="button" class="src mg-tile" class:on disabled={!ok}
                    aria-pressed={on} title={why || ''} onclick={() => toggleSource(name)}>
              <span class="box" aria-hidden="true">{#if on}<Icon name="check" size={12} stroke={2.5} />{/if}</span>
              <span class="srctxt">
                <span class="srcname">{label}</span>
                <span class="srcmeta mg-tnum">
                  {#if !ok}<span class="blocked">Blocked here</span>
                  {:else if storedBySource[name] != null}{storedBySource[name]} stored
                  {:else}Ready{/if}
                </span>
              </span>
            </button>
          {/each}
        </div>
      </div>
    </section>

    <section class="mg-section areas">
      <div class="head">
        <h3>Areas</h3>
        <span class="mg-chip on cnt mg-tnum">{sel.suburbs.length}</span>
        <div class="mg-actions presets" role="group" aria-label="Area presets">
          <button type="button" class="mg-btn ghost sm" onclick={() => presetAreas('prime')}
                  title="Oblivion's core Atlantic Seaboard + Constantia patch">Prime</button>
          <button type="button" class="mg-btn ghost sm" onclick={() => presetAreas('all')}>All</button>
          <button type="button" class="mg-btn ghost sm" onclick={() => presetAreas('none')}>None</button>
        </div>
      </div>
      <div class="body">
        <label class="mg-search find">
          <span class="ic"><Icon name="search" size={15} /></span>
          <input class="mg-input" type="search" placeholder="Find a suburb…"
                 aria-label="Find a suburb" bind:value={q} />
          {#if q}
            <button type="button" class="clear" aria-label="Clear" onclick={() => (q = '')}>
              <Icon name="close" size={14} />
            </button>
          {/if}
        </label>

        <div class="arealist">
          {#each shownRegions as [region, items] (region)}
            {@const open = isOpen(region, items)}
            <div class="region">
              <div class="reghead">
                <button type="button" class="regtoggle" aria-expanded={open}
                        onclick={() => (folded[region] = !open)}>
                  <span class="chev" class:open><Icon name="chevronRight" size={14} /></span>
                  <span class="regname">{region}</span>
                  <span class="regcount mg-tnum" class:some={picked(items) > 0}>{picked(items)}/{items.length}</span>
                </button>
                <span class="regacts">
                  <button type="button" class="mg-btn ghost sm" onclick={() => presetRegion(items, true)}
                          aria-label="Select all of {region}">All</button>
                  <button type="button" class="mg-btn ghost sm" onclick={() => presetRegion(items, false)}
                          aria-label="Clear {region}">None</button>
                </span>
              </div>
              {#if open}
                <div class="pills">
                  {#each items as [slug, name, scope] (slug)}
                    <button type="button" class="mg-chip pill" class:on={sel.suburbs.includes(slug)}
                            class:town={scope === 'town'} aria-pressed={sel.suburbs.includes(slug)}
                            title={scope === 'town' ? 'Crawl the whole town' : ''}
                            onclick={() => toggleSuburb(slug)}>{name}</button>
                  {/each}
                </div>
              {/if}
            </div>
          {:else}
            <p class="mg-hint nohit">No suburb matches “{q}”.</p>
          {/each}
        </div>
      </div>
    </section>

    <section class="mg-section opts">
      <div class="head"><h3>Options</h3></div>
      <div class="body">
        <div class="opt">
          <span class="optl">Pages per area</span>
          <Seg label="Pages per area" options={PAGE_OPTS} value={+sel.pages}
               onchange={(v) => (sel.pages = v)} />
        </div>
        <label class="opt sw">
          <span class="optl">AI scoring</span>
          <input type="checkbox" bind:checked={sel.useAi} />
          <i aria-hidden="true"></i>
        </label>
        <label class="opt sw" title="Also crawl each portal's to-rent book. Rentals are stored for the To rent view — never scored.">
          <span class="optl">Include rentals <small>stored for the To rent view, never scored</small></span>
          <input type="checkbox" bind:checked={sel.rentals} />
          <i aria-hidden="true"></i>
        </label>
        <p class="mg-hint note">Property24 is heavily throttled — the fast portals finish in minutes.</p>
      </div>
    </section>
  </div>

  {#snippet footer()}
    <div class="sum mg-tnum">{summary}</div>
    <div class="right">
      <button type="button" class="mg-btn secondary" disabled={running} onclick={() => actions.rescore(sel.useAi)}
              title="Re-match and re-score everything already in the database">Re-score data</button>
      <button type="button" class="mg-btn secondary" onclick={() => actions.erfResolve()}
              title="Match every property against the public cadastres to get its erf number and official address">Resolve erfs</button>
      {#if running}
        <button type="button" class="mg-btn danger" onclick={() => actions.stop()}>
          <Icon name="stop" size={14} /> Stop job
        </button>
      {/if}
      <button type="button" class="mg-btn primary go" disabled={running || !sel.suburbs.length || !pickedSources.length}
              onclick={start}>
        {#if running}<span class="mg-spin"></span> A job is running…{:else}<Icon name="play" size={14} /> Start crawl{/if}
      </button>
    </div>
  {/snippet}
</Sheet>

<style>
  /* The Sheet owns the scrim, the plane, the header and the footer shell. */
  .lede { margin: 0 0 14px; }

  /* ——— portals over options on the left, areas tall on the right ——— */
  .grid { display: grid; gap: 12px; align-items: start; }
  @media (min-width: 760px) {
    .grid { grid-template-columns: minmax(0, 1fr) minmax(0, 1.05fr); }
    .areas { grid-column: 2; grid-row: span 2; }
  }
  /* sections sit on the raised sheet: one step down, to the surface */
  .mg-section > .head { align-items: center; padding: 8px 8px 8px 16px; min-height: 52px; }
  .mg-section > .head > h3 { color: var(--mc-ink); }
  .cnt { height: 22px; padding: 0 8px; font-size: 11.5px; font-weight: 600; }
  .presets { gap: 2px; }
  .mg-section > .body { padding: 12px; }

  /* ——————————————————————————————————————————— portal tiles ——— */
  .srcgrid { display: grid; gap: 8px; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }
  .src {
    display: flex; align-items: center; gap: 10px; min-width: 0; min-height: 56px;
    padding: 8px 12px; border-radius: var(--mc-r-md);
    color: inherit; font: inherit; text-align: left; cursor: pointer;
    transition: border-color var(--mc-t-fast), background var(--mc-t-fast), transform 120ms var(--mc-ease);
  }
  .src:hover:not(:disabled) { border-color: var(--mc-line2); }
  .src:active:not(:disabled) { transform: scale(0.98); }
  .src.on { background: var(--mc-ok-soft); border-color: var(--mc-ok-line); }
  .src:disabled { opacity: 0.55; cursor: not-allowed; }
  .box {
    flex: none; width: 20px; height: 20px; display: grid; place-items: center;
    border: 1.5px solid var(--mc-line3); border-radius: 6px; background: var(--mc-inset);
    color: var(--mc-accent-ink);
    transition: background var(--mc-t-fast), border-color var(--mc-t-fast);
  }
  .src.on .box { background: var(--mc-accent); border-color: var(--mc-accent); }
  .srctxt { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .srcname {
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    font: 500 13.5px/1.3 var(--mc-font); color: var(--mc-ink);
  }
  .src.on .srcname { font-weight: 600; }
  .srcmeta { font: 400 11.5px/1.3 var(--mc-font); color: var(--mc-ink3); }
  .src.on .srcmeta { color: var(--mc-ink2); }
  .blocked { color: var(--mc-crit); font-weight: 600; }

  /* ————————————————————————————————————————————————— areas ——— */
  .find { margin-bottom: 8px; }
  .find :global(input[type='search']::-webkit-search-cancel-button) { display: none; }
  .arealist { max-height: min(46vh, 420px); overflow-y: auto; overscroll-behavior: contain; margin: 0 -4px; padding: 0 4px; }
  .region { border-top: 1px solid var(--mc-line); }
  .region:first-child { border-top: 0; }
  .reghead { display: flex; align-items: center; gap: 4px; min-height: 44px; }
  .regtoggle {
    display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; min-height: 44px;
    background: none; border: 0; padding: 0 4px; text-align: left; color: inherit; font: inherit; cursor: pointer;
    border-radius: 8px;
  }
  .chev { flex: none; display: flex; color: var(--mc-ink3); transition: transform var(--mc-t) var(--mc-ease); }
  .chev.open { transform: rotate(90deg); }
  .regname {
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    font: 600 13px/1.3 var(--mc-font); color: var(--mc-ink2);
  }
  .regtoggle:hover .regname { color: var(--mc-ink); }
  .regcount { font: 500 11.5px/1.3 var(--mc-font); color: var(--mc-ink3); }
  .regcount.some { color: var(--mc-accent); }
  .regacts { display: inline-flex; gap: 2px; flex: none; }

  .pills { display: flex; flex-wrap: wrap; gap: 6px; padding: 2px 0 12px 26px; }
  .pill { height: 32px; padding: 0 12px; font-size: 12.5px; }
  .pill.town { border-style: dashed; }
  .nohit { margin: 8px 0; }

  /* ——————————————————————————————————————————————— options ——— */
  .opt {
    display: flex; align-items: center; justify-content: space-between; gap: 16px;
    min-height: 52px; padding: 6px 0; cursor: pointer;
  }
  .opt + .opt { border-top: 1px solid var(--mc-line); }
  .optl { display: flex; flex-direction: column; gap: 2px; font: 500 13.5px/1.3 var(--mc-font); color: var(--mc-ink); }
  .optl small { font: 400 11.5px/1.35 var(--mc-font); color: var(--mc-ink3); }
  .note { margin-top: 8px; }

  /* switch */
  /* the input lives inside its row: absolutely placed against nothing, a
     tap's focus-scroll would scroll the sheet's clipped box itself */
  .sw { position: relative; }
  .sw input { position: absolute; left: 0; top: 50%; margin: 0; opacity: 0; width: 1px; height: 1px; pointer-events: none; }
  .sw i {
    position: relative; flex: none; width: 40px; height: 24px; border-radius: 9999px;
    background: var(--mc-line2); transition: background var(--mc-t-fast);
  }
  .sw i::after {
    content: ''; position: absolute; top: 3px; left: 3px; width: 18px; height: 18px; border-radius: 50%;
    background: var(--mc-ink); box-shadow: var(--mc-sh-1);
    transition: transform var(--mc-t) var(--mc-ease), background var(--mc-t-fast);
  }
  .sw input:checked + i { background: var(--mc-accent); }
  .sw input:checked + i::after { transform: translateX(16px); background: var(--mc-accent-ink); }
  .sw input:focus-visible + i { outline: 2px solid rgba(62, 207, 142, 0.7); outline-offset: 2px; }

  /* ———————————————————————————————————————————————— footer ——— */
  .sum { flex: 1 1 220px; min-width: 0; font: 500 12px/1.4 var(--mc-font); color: var(--mc-ink3); }
  .right { flex-wrap: wrap; justify-content: flex-end; }

  @media (pointer: coarse) {
    .src { min-height: 56px; }
    .pill { height: 44px; padding: 0 14px; font-size: 13px; }
    .mg-section > .head .mg-btn.sm, .regacts .mg-btn.sm { height: 44px; min-width: 44px; }
  }
  @media (max-width: 639px) {
    .right { width: 100%; margin-left: 0; }
    .right > .mg-btn { flex: 1 1 auto; }
    .go { flex-basis: 100%; order: 9; height: 48px; }
  }
</style>
