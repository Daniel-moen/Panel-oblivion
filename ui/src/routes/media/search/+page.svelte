<script>
  /* Search across filenames and transcripts.

     The backend's /api/videos?search= already scores both — a filename hit is
     worth 10, a spoken-word hit 5 — and returns the matching transcript
     snippets on each row as `search_matches`. That is the interesting half:
     what someone actually wants is not "this clip matches" but "at 4:12
     somebody said the thing you are looking for", with a button that starts
     playing there. So each result card is a thumbnail, a name, and the
     sentences themselves as ghost rows, every one of them a seek. */
  import { onMount } from 'svelte';
  import { flip } from 'svelte/animate';
  import { fly } from 'svelte/transition';
  import { mstate, boot, openClip, closeClip, stepClip, labelColor } from '$lib/media.svelte.js';
  import { media, thumbUrl, fmtDuration } from '$lib/media.js';
  import ClipDrawer from '$lib/components/ClipDrawer.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';

  let q = $state('');
  let results = $state([]);
  let busy = $state(false);
  let ran = $state(false);
  let opening = $state(false);
  let debounce;
  let seq = 0;

  onMount(boot);

  $effect(() => {
    const term = q.trim();
    clearTimeout(debounce);
    if (term.length < 2) { results = []; ran = false; busy = false; return; }
    busy = true;
    debounce = setTimeout(async () => {
      const mine = ++seq;
      try {
        const r = await media.videos({ search: term });
        if (mine === seq) { results = r || []; ran = true; }
      } catch { if (mine === seq) results = []; }
      finally { if (mine === seq) busy = false; }
    }, 240);
  });

  /* Wrap every matched term in a mark, case-insensitively, without letting a
     stray regex character from the query break the pattern. The parts are
     rendered as text, never as markup, so nothing here reaches {@html}. */
  function highlight(text, term) {
    const words = term.trim().split(/\s+/).filter((w) => w.length > 1)
      .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    if (!words.length) return [{ t: text, hit: false }];
    const re = new RegExp(`(${words.join('|')})`, 'ig');
    // A global regex carries lastIndex between calls, so the hit test uses a
    // fresh anchored one per word rather than re.test(part).
    const exact = words.map((w) => new RegExp(`^${w}$`, 'i'));
    return String(text).split(re).filter(Boolean)
      .map((part, i) => ({ k: i, t: part, hit: exact.some((r) => r.test(part)) }));
  }

  async function playFrom(clip, seconds) {
    opening = true;
    await openClip(clip.id);
    opening = false;
    // Give the lightbox a frame to mount its <video> before seeking.
    requestAnimationFrame(() => {
      const v = document.querySelector('[role="dialog"] video');
      if (v) { v.currentTime = Math.max(0, seconds); v.play?.().catch(() => {}); }
    });
  }

  const totalHits = $derived(results.reduce((a, r) => a + (r.search_matches?.length || 0), 0));
</script>

<svelte:head><title>Search · Media</title></svelte:head>

<!-- ————————————————————————————————————————————————————— header row ——— -->
<div class="mg-row">
  <h2 class="mg-h2">Search</h2>
  {#if ran && !busy}
    <span class="mg-count">
      {results.length} clip{results.length === 1 ? '' : 's'}{#if totalHits} · {totalHits} spoken match{totalHits === 1 ? '' : 'es'}{/if}
    </span>
  {/if}
</div>

<!-- —————————————————————————————————————————————————— the search pill ——— -->
<div class="find">
  <label class="mg-search big">
    <span class="ic"><Icon name="search" size={18} /></span>
    <!-- svelte-ignore a11y_autofocus -->
    <input class="mg-input" type="search" bind:value={q} autofocus
           aria-label="Search the library"
           placeholder="sea view, drone, &ldquo;the kitchen&rdquo;…" />
    {#if q}
      <button class="clear" type="button" onclick={() => (q = '')} aria-label="Clear search">
        <Icon name="close" size={15} />
      </button>
    {/if}
  </label>
  <p class="hint">Filenames and everything spoken on camera, searched as you type.</p>
</div>

{#if busy && !results.length}
  <div class="rows">
    {#each Array(5) as _, i (i)}
      <div class="mg-card row ghost">
        <Skeleton h="54px" w="96px" r="12px" delay={i * 70} />
        <div class="body">
          <Skeleton h="13px" w="42%" delay={i * 70} />
          <div style="height:8px"></div>
          <Skeleton h="12px" w="80%" delay={i * 70} />
        </div>
      </div>
    {/each}
  </div>
{:else if !q.trim()}
  <Empty icon="search" title="Search transcripts"
         hint="Every transcript in the library is searched as you type — no button, no waiting." />
{:else if ran && !results.length}
  <Empty icon="search" title="Nothing for &ldquo;{q.trim()}&rdquo;"
         hint="Only transcribed clips can be searched by what was said. Queue transcription from a clip's detail view." />
{:else}
  <div class="rows">
    {#each results as r, i (r.id)}
      <article class="mg-card row" animate:flip={{ duration: 300 }}
               in:fly={{ y: 12, duration: 320, delay: Math.min(i * 35, 350) }}>
        <button class="th mg-glass-soft" onclick={() => playFrom(r, 0)}
                aria-label="Open {r.filename}">
          {#if thumbUrl(r)}
            <img src={thumbUrl(r)} alt="" loading="lazy" />
          {:else}
            <span class="noimg"><Icon name="film" size={15} /></span>
          {/if}
          {#if r.duration}<span class="dur mg-tnum">{fmtDuration(r.duration)}</span>{/if}
        </button>

        <div class="body">
          <h3>
            {#if r.label}<i class="lbl" style:background={labelColor(r.label)} role="img"
                            aria-label="{r.label} label" title="{r.label} label"></i>{/if}
            <button class="name" onclick={() => playFrom(r, 0)}>
              {#each highlight(r.filename, q) as part (part.k)}
                {#if part.hit}<mark>{part.t}</mark>{:else}{part.t}{/if}
              {/each}
            </button>
          </h3>
          <p class="where">{[r.folder_name, r.resolution, r.file_size_formatted]
            .filter(Boolean).join(' · ')}</p>

          {#if r.search_matches?.length}
            <ul class="quotes">
              {#each r.search_matches.slice(0, 4) as m (m.start)}
                <li>
                  <button class="tc mg-pill" onclick={() => playFrom(r, m.start)}
                          title="Play from {fmtDuration(m.start)}">
                    <Icon name="play" size={10} stroke={2} />
                    <span class="mg-tnum">{fmtDuration(m.start)}</span>
                  </button>
                  <q>
                    {#each highlight(m.text, q) as part (part.k)}
                      {#if part.hit}<mark>{part.t}</mark>{:else}{part.t}{/if}
                    {/each}
                  </q>
                </li>
              {/each}
              {#if r.search_matches.length > 4}
                <li class="more">+{r.search_matches.length - 4} more in this clip</li>
              {/if}
            </ul>
          {/if}
        </div>
      </article>
    {/each}
  </div>
{/if}

{#if mstate.openId != null}
  <ClipDrawer clip={mstate.openClip} loading={opening}
              onclose={closeClip} onstep={stepClip} />
{/if}

<style>
  /* Chrome draws its own × inside a search field; this one has a pill button. */
  input[type='search']::-webkit-search-cancel-button { -webkit-appearance: none; appearance: none; }

  /* ———————————————————————————————————————————————————— the big pill ——— */
  .find { max-width: 620px; margin: 0 auto 20px; }
  .big .mg-input { height: 48px; padding-left: 46px; padding-right: 50px; font-size: 15px; }
  .big > .ic { left: 17px; }
  .big > .clear { right: 6px; width: 36px; height: 36px; }
  .hint { margin: 9px 2px 0; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink3); text-align: center; }

  /* ———————————————————————————————————————————————————————— results ——— */
  .rows { display: flex; flex-direction: column; gap: 10px; max-width: 900px; margin: 0 auto; }
  .row { display: flex; gap: 14px; padding: 12px; }
  .row.ghost { align-items: center; }

  .th {
    position: relative; flex: none; width: 96px; height: 54px; padding: 0;
    border-radius: 12px; overflow: hidden; cursor: pointer;
    transition: border-color 0.18s;
  }
  .th:hover { border-color: var(--mc-line2); }
  .th img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .noimg { position: absolute; inset: 0; display: grid; place-items: center; color: var(--mc-ink3); }
  .dur {
    position: absolute; right: 4px; bottom: 4px; padding: 1px 4px; border-radius: 5px;
    background: rgba(0, 0, 0, 0.72); color: #fff; font: 600 10px/1.5 var(--mc-font);
  }

  .body { min-width: 0; flex: 1; }
  h3 { margin: 0; font: 600 13.5px/1.35 var(--mc-font); letter-spacing: -0.01em; }
  .name {
    border: 0; background: none; padding: 0; font: inherit; color: var(--mc-ink);
    text-align: left; overflow-wrap: anywhere; cursor: pointer;
  }
  .name:hover { text-decoration: underline; text-underline-offset: 3px; }
  .where { margin: 3px 0 8px; font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); }

  /* ——————————————————————————————————————————— the spoken-word hits ——— */
  .quotes { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 5px; }
  .quotes li {
    display: flex; gap: 9px; align-items: flex-start;
    padding: 7px 10px; border-radius: 11px; background: rgba(255, 255, 255, 0.04);
    font: 400 12.5px/1.55 var(--mc-font); color: var(--mc-ink2);
  }
  .quotes q { quotes: '“' '”'; overflow-wrap: anywhere; min-width: 0; }
  .more { color: var(--mc-ink3); font-size: 12px; background: none; padding: 2px 2px 0; }

  .tc {
    display: inline-flex; align-items: center; gap: 4px; flex: none; height: 32px;
    padding: 0 10px; border: 1px solid var(--mc-line); background: var(--mc-raised);
    color: var(--mc-ink2); font: 500 11.5px/1 var(--mc-font); cursor: pointer;
    transition: background 0.18s, border-color 0.18s, color 0.18s;
  }
  .tc:hover { background: rgba(62, 207, 142, 0.12); border-color: rgba(62, 207, 142, 0.4); color: var(--mc-accent); }
  .tc:active { transform: scale(0.97); }

  mark {
    background: rgba(62, 207, 142, 0.3); color: #5fe3a8;
    border-radius: 3px; padding: 0 0.12em; font-weight: 600;
  }

  .lbl { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px;
         vertical-align: 0.05em; }

  @media (max-width: 420px) {
    .th { width: 72px; height: 44px; }
    .big .mg-input { font-size: 16px; }   /* 16px stops iOS zooming the page on focus */
  }
  @media (max-width: 620px) {
    .row { padding: 11px; gap: 11px; }
    .tc { height: 40px; padding: 0 12px; }
    .quotes li { flex-direction: column; gap: 6px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .tc:active { transform: none; }
  }
</style>
