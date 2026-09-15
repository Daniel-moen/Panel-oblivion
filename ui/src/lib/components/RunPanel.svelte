<script>
  import { app, actions } from '$lib/state.svelte.js';

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

{#if app.runOpen}
  <div class="scrim" onclick={() => (app.runOpen = false)} aria-hidden="true"></div>
  <aside class="sheet" aria-label="Crawl setup">
    <header>
      <div class="head">
        <h2>New crawl</h2>
        <p class="hint">Pick portals and areas, then let the engine run. Property24 is
          heavily throttled — the fast portals finish in minutes.</p>
      </div>
      <button class="close" onclick={() => (app.runOpen = false)} title="close (Esc)">✕</button>
    </header>

    <div class="body">
      <section>
        <div class="sechead">
          <span class="sectitle">Portals</span>
          <span class="presets">
            <button onclick={() => presetSources('all')}>all</button>
            <button onclick={() => presetSources('fast')} title="skip the slow, easily-blocked Property24 crawl">fast</button>
            <button onclick={() => presetSources('none')}>none</button>
          </span>
        </div>
        <div class="srcgrid">
          {#each sources as [name, label, ok, why] (name)}
            <button
              class="srccard" class:on={pickedSources.includes(name)}
              disabled={!ok} title={why || ''} onclick={() => toggleSource(name)}>
              <span class="box"></span>
              <span class="srcname">{label}</span>
              <span class="srcmeta">
                {#if !ok}<span class="blocked">blocked</span>{:else if storedBySource[name] != null}{storedBySource[name]} stored{:else}&nbsp;{/if}
              </span>
            </button>
          {/each}
        </div>
      </section>

      <section>
        <div class="sechead">
          <span class="sectitle">Areas <b class="cnt">{sel.suburbs.length}</b></span>
          <span class="presets">
            <button onclick={() => presetAreas('prime')} title="Oblivion's core Atlantic Seaboard + Constantia patch">prime</button>
            <button onclick={() => presetAreas('all')}>all</button>
            <button onclick={() => presetAreas('none')}>none</button>
          </span>
        </div>
        {#each regions as [region, items] (region)}
          <div class="region">
            <div class="reghead">
              <span class="regname">{region}</span>
              <span class="presets">
                <button onclick={() => presetRegion(items, true)}>all</button>
                <button onclick={() => presetRegion(items, false)}>none</button>
              </span>
            </div>
            <div class="pills">
              {#each items as [slug, name, scope] (slug)}
                <button class="pill" class:on={sel.suburbs.includes(slug)}
                        class:town={scope === 'town'}
                        title={scope === 'town' ? 'crawl the whole town' : ''}
                        onclick={() => toggleSuburb(slug)}>{name}</button>
              {/each}
            </div>
          </div>
        {/each}
      </section>

      <section>
        <div class="sechead"><span class="sectitle">Options</span></div>
        <div class="opts">
          <label class="opt">
            <span>Pages per area</span>
            <select bind:value={sel.pages}>
              {#each [1, 2, 3, 4, 5] as n}<option value={n}>{n}</option>{/each}
            </select>
          </label>
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
      </section>
    </div>

    <footer>
      <button class="btn primary big" disabled={running || !sel.suburbs.length || !pickedSources.length}
              onclick={start}>
        {running ? 'A job is running…' : 'Start crawl'}
      </button>
      <div class="secondary">
        <button class="act" disabled={running} onclick={() => actions.rescore(sel.useAi)}
                title="Re-match and re-score everything already in the database">Re-score data</button>
        <button class="act" onclick={() => actions.erfResolve()}
                title="Match every property against the public cadastres to get its erf number and official address">Resolve erfs</button>
        {#if running}
          <button class="act stop" onclick={() => actions.stop()}>Stop job</button>
        {/if}
      </div>
    </footer>
  </aside>
{/if}

<style>
  .scrim { position: fixed; inset: 0; z-index: 40; background: var(--scrim); }

  .sheet {
    position: fixed; top: 0; right: 0; bottom: 0; z-index: 41;
    width: min(480px, 96vw); display: flex; flex-direction: column;
    background: var(--bg-2);
    border-left: 1px solid var(--line);
    box-shadow: var(--shadow-2);
    animation: slidein 0.22s ease-out;
  }
  @keyframes slidein { from { transform: translateX(40px); opacity: 0; } to { transform: none; opacity: 1; } }

  /* ————————————————————————————————————————————————— header ——— */
  header { position: relative; padding: 1.35rem clamp(1rem, 4vw, 1.5rem) 1.1rem; }
  .head { padding-right: 2.6rem; }
  h2 {
    margin: 0; font-family: var(--font-display);
    font-weight: 700; font-size: 1.25rem; line-height: 1.25;
    letter-spacing: -0.01em; color: var(--ink);
  }
  .hint {
    margin: 0.4rem 0 0; font-family: var(--font-ui);
    font-size: 0.82rem; line-height: 1.5; color: var(--ink-2);
  }
  .close {
    position: absolute; top: 1.2rem; right: clamp(1rem, 4vw, 1.5rem);
    width: 32px; height: 32px; flex: none; padding: 0;
    display: inline-flex; align-items: center; justify-content: center;
    border: 1px solid var(--line-2); border-radius: var(--r-sm);
    background: var(--bg-2); color: var(--ink-2);
    font: 500 0.8rem/1 var(--font-ui);
    transition: background 0.15s, color 0.15s, border-color 0.15s;
  }
  .close:hover { background: var(--bg-3); border-color: var(--line-3); color: var(--ink); }

  .body { flex: 1; overflow-y: auto; padding: 0 clamp(1rem, 4vw, 1.5rem) 1.5rem; }
  section { padding-top: 1.15rem; margin-bottom: 1.15rem; border-top: 1px solid var(--line); }
  section:last-child { margin-bottom: 0; }

  .sechead {
    display: flex; align-items: center; justify-content: space-between; gap: 1rem;
    margin-bottom: 0.7rem;
  }
  .sectitle {
    display: inline-flex; align-items: center; gap: 0.45rem;
    font: 700 0.82rem/1.3 var(--font-ui); color: var(--ink);
  }
  .cnt {
    font: 600 0.7rem/1.3 var(--font-ui);
    color: var(--accent-2); background: var(--accent-soft);
    padding: 0.1rem 0.5rem; border-radius: 999px;
  }
  .presets { display: inline-flex; gap: 0.65rem; }
  .presets button {
    background: none; border: none; padding: 0;
    font: 600 0.76rem/1.3 var(--font-ui); color: var(--accent);
    transition: color 0.12s;
  }
  .presets button:hover { color: var(--accent-2); text-decoration: underline; }

  /* ——————————————————————————————————————————— portal checklist ——— */
  .srcgrid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
             gap: 0.5rem; }
  .srccard {
    display: flex; align-items: center; gap: 0.55rem; text-align: left; min-width: 0;
    background: var(--bg-2); border: 1px solid var(--line-2); border-radius: var(--r-sm);
    padding: 0.55rem 0.65rem;
    transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
  }
  .srccard:hover:not(:disabled) { border-color: var(--line-3); background: #fdfdfe; }
  .srccard .box {
    position: relative; flex: none; width: 16px; height: 16px;
    border: 1px solid var(--line-3); border-radius: 4px; background: var(--bg-2);
    transition: background 0.15s, border-color 0.15s;
  }
  .srccard.on { border-color: var(--accent-line); background: var(--accent-soft); }
  .srccard.on .box { border-color: var(--accent); background: var(--accent); }
  .srccard.on .box::after {
    content: '✓'; position: absolute; inset: 0;
    display: flex; align-items: center; justify-content: center;
    font: 700 0.68rem/1 var(--font-ui); color: #fff;
  }
  .srccard:disabled { opacity: 0.55; cursor: default; }
  .srcname {
    flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    font: 500 0.84rem/1.3 var(--font-ui); color: var(--ink);
  }
  .srccard.on .srcname { font-weight: 600; }
  .srcmeta {
    flex: none; font: 400 0.72rem/1.3 var(--font-ui); color: var(--ink-3);
    font-variant-numeric: tabular-nums;
  }
  .blocked {
    display: inline-flex; align-items: center;
    font: 600 0.68rem/1.3 var(--font-ui);
    padding: 0.12rem 0.5rem; border-radius: 999px;
    background: var(--red-soft); color: #b91c1c; white-space: nowrap;
  }

  /* ————————————————————————————————————————————————— areas ——— */
  .region { margin-bottom: 0.9rem; }
  .region:last-child { margin-bottom: 0; }
  .reghead {
    display: flex; align-items: center; justify-content: space-between; gap: 0.75rem;
    margin-bottom: 0.45rem;
  }
  .regname {
    font: 600 0.76rem/1.3 var(--font-ui); color: var(--ink-3);
  }
  .pills { display: flex; flex-wrap: wrap; gap: 0.35rem; }
  .pill {
    border-radius: 999px; border: 1px solid var(--line-2); background: var(--bg-2);
    color: var(--ink-2); padding: 0.28rem 0.8rem;
    font: 500 0.78rem/1.3 var(--font-ui);
    transition: border-color 0.12s, color 0.12s, background 0.12s;
  }
  .pill:hover { border-color: var(--line-3); color: var(--ink); background: var(--bg-3); }
  .pill.on { background: var(--accent); border-color: var(--accent); color: #fff; }
  .pill.on:hover { background: var(--accent-2); border-color: var(--accent-2); color: #fff; }
  .pill.town { border-style: dashed; }
  .pill.town.on { border-style: dashed; border-color: var(--accent); }

  /* ——————————————————————————————————————————————— options ——— */
  .opts { display: flex; gap: 1.8rem; align-items: center; flex-wrap: wrap; }
  .opt {
    display: flex; align-items: center; gap: 0.65rem; cursor: pointer;
    font: 500 0.84rem/1.3 var(--font-ui); color: var(--ink-2);
  }
  .opt select { padding: 0.34rem 1.7rem 0.34rem 0.6rem; }

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
  footer {
    padding: 0.9rem clamp(1rem, 4vw, 1.5rem) 1.1rem;
    border-top: 1px solid var(--line); background: var(--bg-2);
  }
  .big { width: 100%; padding: 0.65rem; font-size: 0.9rem; border-radius: var(--r-sm); }
  .secondary { display: flex; gap: 0.4rem; margin-top: 0.6rem; justify-content: center;
               flex-wrap: wrap; }
  .stop:hover { background: var(--red-soft); border-color: var(--red-line); color: var(--red); }
</style>
