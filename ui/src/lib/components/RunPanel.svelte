<script>
  /* The crawl setup — the app's one signature action, so it opens as a Sheet:
     strong glass, blurred scrim, Esc, focus trap and the phone's bottom-sheet
     shape all come from components/glass/Sheet.svelte.

     TODO(prospects agent): only the container was re-homed in the foundation
     pass. Everything inside — the portal cards, the region list, the pills,
     the switches and the footer actions — is still on the old vocabulary and
     wants `.mg-card` / `.mg-chip` / `.mg-btn` / `.mg-label`. */
  import { app, actions } from '$lib/state.svelte.js';
  import Sheet from '$lib/components/glass/Sheet.svelte';

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
  <p class="hint">Pick portals and areas, then let the engine run.</p>

  <div class="body">
        <section class="panel">
          <div class="sechead">
            <span class="sectitle">Portals <b class="cnt">{pickedSources.length}</b></span>
            <span class="seg" role="group" aria-label="portal presets">
              <button onclick={() => presetSources('all')}>All</button>
              <button onclick={() => presetSources('fast')}
                      title="skip the slow, easily-blocked Property24 crawl">Fast</button>
              <button onclick={() => presetSources('none')}>None</button>
            </span>
          </div>
          <div class="srcgrid">
            {#each sources as [name, label, ok, why] (name)}
              <button
                class="srccard" class:on={pickedSources.includes(name)}
                disabled={!ok} title={why || ''} onclick={() => toggleSource(name)}>
                <span class="box"></span>
                <span class="srctxt">
                  <span class="srcname">{label}</span>
                  <span class="srcmeta">
                    {#if !ok}<span class="blocked">blocked here</span>
                    {:else if storedBySource[name] != null}{storedBySource[name]} stored
                    {:else}ready{/if}
                  </span>
                </span>
              </button>
            {/each}
          </div>
        </section>

        <section class="panel areas">
          <div class="sechead">
            <span class="sectitle">Areas <b class="cnt">{sel.suburbs.length}</b></span>
            <span class="seg" role="group" aria-label="area presets">
              <button onclick={() => presetAreas('prime')}
                      title="Oblivion's core Atlantic Seaboard + Constantia patch">Prime</button>
              <button onclick={() => presetAreas('all')}>All</button>
              <button onclick={() => presetAreas('none')}>None</button>
            </span>
          </div>

          <input type="search" class="find" placeholder="Find a suburb…" bind:value={q} />

          <div class="arealist">
            {#each shownRegions as [region, items] (region)}
              <div class="region">
                <div class="reghead">
                  <button class="regtoggle" onclick={() => (folded[region] = !isOpen(region, items))}>
                    <span class="chev" class:open={isOpen(region, items)}>›</span>
                    <span class="regname">{region}</span>
                    <span class="regcount">{picked(items)}/{items.length}</span>
                  </button>
                  <span class="regacts">
                    <button class="act" onclick={() => presetRegion(items, true)}>all</button>
                    <button class="act" onclick={() => presetRegion(items, false)}>none</button>
                  </span>
                </div>
                {#if isOpen(region, items)}
                  <div class="pills">
                    {#each items as [slug, name, scope] (slug)}
                      <button class="pill" class:on={sel.suburbs.includes(slug)}
                              class:town={scope === 'town'}
                              title={scope === 'town' ? 'crawl the whole town' : ''}
                              onclick={() => toggleSuburb(slug)}>{name}</button>
                    {/each}
                  </div>
                {/if}
              </div>
            {:else}
              <p class="nohit">No suburb matches “{q}”.</p>
            {/each}
          </div>
        </section>

        <section class="panel">
          <div class="sechead"><span class="sectitle">Options</span></div>
          <div class="opts">
            <div class="opt">
              <span>Pages per area</span>
              <span class="seg" role="group" aria-label="pages per area">
                {#each [1, 2, 3, 4, 5] as n (n)}
                  <button class:on={+sel.pages === n} onclick={() => (sel.pages = n)}>{n}</button>
                {/each}
              </span>
            </div>
            <label class="opt sw">
              <span>AI scoring</span>
              <input type="checkbox" bind:checked={sel.useAi} />
              <i></i>
            </label>
            <label class="opt sw" title="Also crawl each portal's to-rent book. Rentals are stored for the To rent view — never scored.">
              <span>Include rentals</span>
              <input type="checkbox" bind:checked={sel.rentals} />
              <i></i>
            </label>
          </div>
          <p class="note">Property24 is heavily throttled — the fast portals finish in minutes.</p>
        </section>
  </div>

  {#snippet footer()}
    <div class="sum">{summary}</div>
    <div class="right">
      <button class="mg-btn sm secondary" disabled={running} onclick={() => actions.rescore(sel.useAi)}
              title="Re-match and re-score everything already in the database">Re-score data</button>
      <button class="mg-btn sm secondary" onclick={() => actions.erfResolve()}
              title="Match every property against the public cadastres to get its erf number and official address">Resolve erfs</button>
      {#if running}
        <button class="mg-btn sm danger" onclick={() => actions.stop()}>Stop job</button>
      {/if}
      <button class="mg-btn primary go" disabled={running || !sel.suburbs.length || !pickedSources.length}
              onclick={start}>
        {running ? 'A job is running…' : 'Start crawl'}
      </button>
    </div>
  {/snippet}
</Sheet>

<style>
  /* The Sheet owns the scrim, the card, the header and the footer shell. */
  .hint { margin: 0 0 14px; font: 400 12.5px/1.5 var(--mg-font); color: var(--mg-i2); }

  /* ——— body: portals over options on the left, areas tall on the right ——— */
  .body { display: grid; gap: 0.8rem; align-items: start; }
  @media (min-width: 760px) {
    .body { grid-template-columns: minmax(0, 1fr) minmax(0, 1.05fr); }
    .areas { grid-column: 2; grid-row: span 2; }
  }
  section { padding: 0.9rem 1rem 1rem; }

  .sechead {
    display: flex; align-items: center; justify-content: space-between; gap: 0.75rem;
    margin-bottom: 0.7rem;
  }
  .sectitle {
    display: inline-flex; align-items: center; gap: 0.45rem;
    font: 700 0.86rem/1.3 var(--font-ui); color: var(--ink);
  }
  .cnt {
    font: 600 0.7rem/1.3 var(--font-ui);
    color: var(--accent-2); background: var(--accent-soft);
    padding: 0.1rem 0.5rem; border-radius: 999px;
  }

  /* segmented presets — the same control the filter bar uses */
  .seg { display: inline-flex; background: var(--bg-2);
         border: 1px solid var(--line-2); border-radius: var(--r-sm);
         overflow: hidden; box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04); }
  .seg button { background: none; border: none; color: var(--ink-2);
                font: 600 0.74rem/1.3 var(--font-ui); padding: 0.3rem 0.65rem;
                border-right: 1px solid var(--line); }
  .seg button:last-child { border-right: none; }
  .seg button:hover { color: var(--ink); background: var(--bg-3); }
  .seg button.on { background: var(--accent-soft); color: var(--accent-2); }

  /* ——————————————————————————————————————————— portal checklist ——— */
  .srcgrid { display: grid; gap: 0.5rem;
             grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }
  .srccard {
    display: flex; align-items: center; gap: 0.6rem; text-align: left;
    min-width: 0; min-height: 56px;
    background: var(--bg-2); border: 1px solid var(--line-2); border-radius: var(--r);
    padding: 0.55rem 0.7rem;
    transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
  }
  .srccard:hover:not(:disabled) { border-color: var(--line-3); background: var(--hover); }
  .srccard .box {
    position: relative; flex: none; width: 18px; height: 18px;
    border: 1px solid var(--line-3); border-radius: 5px; background: var(--bg-2);
    transition: background 0.15s, border-color 0.15s;
  }
  .srccard.on { border-color: var(--accent-line); background: var(--accent-soft); }
  .srccard.on .box { border-color: var(--accent); background: var(--accent); }
  .srccard.on .box::after {
    content: '✓'; position: absolute; inset: 0;
    display: flex; align-items: center; justify-content: center;
    font: 700 0.72rem/1 var(--font-ui); color: #fff;
  }
  .srccard:disabled { opacity: 0.5; cursor: default; }
  .srctxt { display: flex; flex-direction: column; gap: 0.15rem; min-width: 0; }
  .srcname {
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    font: 500 0.86rem/1.3 var(--font-ui); color: var(--ink);
  }
  .srccard.on .srcname { font-weight: 600; }
  .srcmeta {
    font: 400 0.72rem/1.3 var(--font-ui); color: var(--ink-3);
    font-variant-numeric: tabular-nums;
  }
  .blocked {
    display: inline-flex; align-items: center;
    font: 600 0.68rem/1.3 var(--font-ui);
    padding: 0.1rem 0.45rem; border-radius: 999px;
    background: var(--red-soft); color: var(--bad-ink); white-space: nowrap;
  }

  /* ————————————————————————————————————————————————— areas ——— */
  .find { width: 100%; margin-bottom: 0.6rem; }
  .arealist { max-height: min(46vh, 400px); overflow-y: auto; padding-right: 0.2rem; }
  .region { padding: 0.35rem 0; border-top: 1px solid var(--line); }
  .region:first-child { border-top: none; padding-top: 0; }
  .reghead { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
  .regtoggle {
    display: flex; align-items: center; gap: 0.45rem; flex: 1; min-width: 0;
    background: none; border: none; padding: 0.25rem 0; text-align: left;
  }
  .chev { display: inline-block; flex: none; width: 12px; color: var(--ink-3);
          font-size: 0.9rem; line-height: 1; transition: transform 0.15s; }
  .chev.open { transform: rotate(90deg); }
  .regname {
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    font: 600 0.8rem/1.3 var(--font-ui); color: var(--ink-2);
  }
  .regtoggle:hover .regname { color: var(--ink); }
  .regcount { font: 500 0.72rem/1.3 var(--font-ui); color: var(--ink-3);
              font-variant-numeric: tabular-nums; }
  .regacts { display: inline-flex; gap: 0.3rem; flex: none; }
  .regacts .act { padding: 0.18rem 0.5rem; font-size: 0.72rem; }

  .pills { display: flex; flex-wrap: wrap; gap: 0.35rem; padding: 0.4rem 0 0.5rem 1.05rem; }
  .pill {
    border-radius: 999px; border: 1px solid var(--line-2); background: var(--bg-2);
    color: var(--ink-2); padding: 0.32rem 0.85rem;
    font: 500 0.78rem/1.3 var(--font-ui);
    transition: border-color 0.12s, color 0.12s, background 0.12s;
  }
  .pill:hover { border-color: var(--line-3); color: var(--ink); background: var(--bg-3); }
  .pill.on { background: var(--accent); border-color: var(--accent); color: #fff; }
  .pill.on:hover { background: var(--accent-2); border-color: var(--accent-2); color: #fff; }
  .pill.town { border-style: dashed; }
  .pill.town.on { border-style: dashed; border-color: var(--accent); }
  .nohit { margin: 0.4rem 0; font-size: 0.82rem; color: var(--ink-3); }

  /* ——————————————————————————————————————————————— options ——— */
  .opts { display: flex; flex-direction: column; gap: 0.15rem; }
  .opt {
    display: flex; align-items: center; justify-content: space-between; gap: 1rem;
    padding: 0.45rem 0; cursor: pointer;
    font: 500 0.86rem/1.3 var(--font-ui); color: var(--ink-2);
  }
  .opt + .opt { border-top: 1px solid var(--line); }
  .note { margin: 0.7rem 0 0; font: 400 0.76rem/1.5 var(--font-ui); color: var(--ink-3); }

  /* modern switch */
  .sw input { position: absolute; opacity: 0; pointer-events: none; }
  .sw i {
    width: 38px; height: 22px; border-radius: 999px; background: var(--line-2);
    position: relative; flex: none; transition: background 0.18s;
  }
  .sw i::after {
    content: ''; position: absolute; top: 2px; left: 2px;
    width: 18px; height: 18px; border-radius: 50%; background: #fff;
    box-shadow: 0 1px 2px rgba(16, 24, 40, 0.18);
    transition: transform 0.18s;
  }
  .sw input:checked + i { background: var(--accent); }
  .sw input:checked + i::after { transform: translateX(16px); }
  .sw input:focus-visible + i { outline: 2px solid var(--accent); outline-offset: 2px; }

  /* ———————————————————————————————————————————————— footer ——— */
  .sum { font: 500 12px/1.4 var(--mg-font); color: var(--mg-i3); font-variant-numeric: tabular-nums; }

  @media (max-width: 640px) {
    .go { flex: 1; }
  }
</style>
