<script>
  /* The clip lightbox: player on the left, everything known about the clip on
     the right, transcript running underneath in time with the playhead.

     The transcript is the reason this screen exists. Zerko stores segments
     with a start and an end but no per-word timings, so the word highlight is
     interpolated across the segment's own duration — an honest estimate that
     reads as karaoke and, more importantly, makes every line clickable: click
     a line, the player seeks there. Finding the ten seconds where someone
     said "sea view" is the whole job. */
  import { tick } from 'svelte';
  import { fade, pop, slide } from '$lib/motion.js';
  import { media, posterUrl, streamUrl, photoUrl, thumbUrl, fmtDuration, fmtBytes } from '$lib/media.js';
  import { say, can, CAP, setLabel, dropClips } from '$lib/media.svelte.js';
  import LabelDots from '$lib/components/media/library/LabelDots.svelte';
  import VirtualCopies from '$lib/components/media/library/VirtualCopies.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';

  let { clip, loading = false, onclose, onstep } = $props();

  let video = $state(null);
  let t = $state(0);
  let paused = $state(true);
  let notes = $state([]);
  let newNote = $state('');
  let follow = $state(true);       // keep the active line in view
  let listEl = $state(null);

  const segments = $derived(clip?.segments || []);
  const isPhoto = $derived(clip?.media_type === 'photo');

  const activeIdx = $derived.by(() => {
    if (!segments.length) return -1;
    for (let i = 0; i < segments.length; i++)
      if (t >= segments[i].start && t < segments[i].end) return i;
    return -1;
  });

  /* Split the active line into words and work out how far through it the
     playhead is, so the highlight moves along the sentence. */
  const activeWords = $derived.by(() => {
    const s = segments[activeIdx];
    if (!s) return null;
    const words = String(s.text || '').trim().split(/\s+/);
    const span = Math.max(0.001, s.end - s.start);
    const p = Math.min(1, Math.max(0, (t - s.start) / span));
    return { words, upto: Math.floor(p * words.length) };
  });

  $effect(() => {
    // Load notes whenever the clip changes.
    const id = clip?.id;
    if (!id) { notes = []; return; }
    media.notes(id).then((n) => (notes = n || [])).catch(() => (notes = []));
  });

  $effect(() => {
    // Scroll the active line into view, unless the reader took over.
    if (!follow || activeIdx < 0 || !listEl) return;
    const el = listEl.querySelector(`[data-seg="${activeIdx}"]`);
    if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  });

  function seek(seconds) {
    if (!video) return;
    video.currentTime = Math.max(0, seconds);
    video.play?.().catch(() => {});
    follow = true;
  }

  async function addNote() {
    const body = newNote.trim();
    if (!body || !clip) return;
    try {
      await media.addNote(clip.id, body);
      notes = [...notes, { id: Date.now(), content: body, created_at: new Date().toISOString() }];
      newNote = '';
      say('Note added');
    } catch (e) { say(e.message, 'error'); }
  }

  let trashing = $state(false);
  async function trashIt() {
    if (!clip) return;
    trashing = true;
    try {
      await media.trashOne(clip.id);
      say(`Moved ${clip.filename} to the trash`);
      dropClips([clip.id]);
    } catch (e) { say(e.message, 'error'); }
    finally { trashing = false; }
  }

  function onKey(e) {
    if (e.target.closest?.('input, textarea')) return;
    if (e.key === 'Escape') { e.preventDefault(); onclose?.(); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); onstep?.(1); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); onstep?.(-1); }
    else if (e.key === ' ' && video) {
      e.preventDefault();
      video.paused ? video.play() : video.pause();
    }
  }

  const facts = $derived(clip ? [
    ['Resolution', clip.resolution],
    ['Codec', [clip.video_codec, clip.audio_codec].filter(Boolean).join(' / ')],
    ['Frame rate', clip.frame_rate ? clip.frame_rate + ' fps' : null],
    ['Duration', clip.duration ? fmtDuration(clip.duration) : null],
    ['Size', clip.file_size ? fmtBytes(clip.file_size) : null],
    ['Camera', [clip.camera_make, clip.camera_model].filter(Boolean).join(' ')],
    ['Shot', clip.shoot_date ? clip.shoot_date.slice(0, 10) : null],
    ['Folder', clip.folder_name]
  ].filter(([, v]) => v) : []);

  /* ——— shape: a centred dialog from 720px, a bottom sheet below ——— */
  let wide = $state(true);
  $effect(() => {
    if (typeof matchMedia === 'undefined') return;
    const mq = matchMedia('(min-width: 720px)');
    const sync = () => (wide = mq.matches);
    sync();
    mq.addEventListener('change', sync);
    return () => mq.removeEventListener('change', sync);
  });

  /* Lock the page behind while open and take focus so Esc and Tab land here. */
  let box = $state(null);
  $effect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    tick().then(() => box?.focus?.({ preventScroll: true }));
    return () => { document.body.style.overflow = prev; };
  });

  /* ——— the phone throw: only the grab handle starts it ——— */
  let drag = $state(0);
  let from = 0;
  let held = $state(null);
  function grabStart(e) { if (wide) return; from = e.clientY; held = e.currentTarget; held.setPointerCapture?.(e.pointerId); }
  function grabMove(e) { if (held == null) return; drag = Math.max(0, e.clientY - from); }
  function grabEnd() { if (held == null) return; held = null; if (drag > 120) onclose?.(); drag = 0; }

  /* Rendered at the end of <body> so no ancestor's stacking context (the
     page's, the strip's) can sit on top of it or clip it. */
  const enter = (node) => (wide ? pop(node, { duration: 260 }) : slide(node, { y: 640, duration: 340, opacity: 1 }));

  function portal(node) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }
</script>



<svelte:window onkeydown={onKey} />

<div class="mg-portal" use:portal>
<div class="scrim" onclick={onclose} transition:fade={{ duration: 200 }} aria-hidden="true"></div>

{#key wide}
<div class="box" class:phone={!wide} role="dialog" aria-modal="true" aria-label={clip?.filename || 'Clip'}
     tabindex="-1" bind:this={box}
     style:transform={drag ? `translate3d(0,${drag}px,0)` : null}
     style:transition={held == null ? 'transform 0.28s var(--mc-ease-out)' : 'none'}
     transition:enter>

  {#if !wide}
    <div class="grab" onpointerdown={grabStart} onpointermove={grabMove}
         onpointerup={grabEnd} onpointercancel={grabEnd} role="presentation"><i></i></div>
  {/if}


  <button class="mg-btn secondary icon sm x" onclick={onclose} aria-label="Close (Esc)">
    <Icon name="close" size={15} />
  </button>
  <button class="mg-btn secondary icon nav prev" onclick={() => onstep?.(-1)} aria-label="Previous clip">
    <Icon name="chevronLeft" size={18} />
  </button>
  <button class="mg-btn secondary icon nav next" onclick={() => onstep?.(1)} aria-label="Next clip">
    <Icon name="chevronRight" size={18} />
  </button>

  <div class="grid">
    <div class="stagecol mg-noscroll">
      <div class="screen">
        {#if loading || !clip}
          <Skeleton h="100%" r="0" />
        {:else if isPhoto}
          <img src={photoUrl(clip)} alt={clip.filename} />
        {:else}
          <!-- svelte-ignore a11y_media_has_caption -->
          <video bind:this={video} bind:currentTime={t} bind:paused
                 src={streamUrl(clip)} poster={thumbUrl(clip)}
                 controls playsinline preload="metadata"></video>
        {/if}
      </div>

      {#if clip}
        <div class="head">
          <h2 class="mg-h2">{clip.filename}</h2>
          <div class="sub">
            {#each facts.slice(0, 4) as [k, v] (k)}<span>{v}</span>{/each}
          </div>
        </div>
      {/if}

      {#if segments.length}
        <div class="tr">
          <div class="trh">
            <span class="mg-label">Transcript</span>
            <label class="follow">
              <input type="checkbox" bind:checked={follow} /> follow playback
            </label>
          </div>
          <div class="lines mg-noscroll" bind:this={listEl} onwheel={() => (follow = false)}>
            {#each segments as s, i (i)}
              <button class="line" data-seg={i} class:on={i === activeIdx}
                      onclick={() => seek(s.start)}>
                <span class="tc mg-tnum">{fmtDuration(s.start)}</span>
                <span class="tx">
                  {#if i === activeIdx && activeWords}
                    {#each activeWords.words as w, wi (wi)}<span
                      class="w" class:said={wi <= activeWords.upto}>{w}</span>{' '}{/each}
                  {:else}{s.text}{/if}
                </span>
              </button>
            {/each}
          </div>
        </div>
      {:else if clip && !loading}
        <p class="none">
          {clip.transcription_status === 'processing'
            ? 'Transcribing this clip now…'
            : 'No transcript yet.'}
          {#if clip.media_type === 'video' && clip.transcription_status !== 'processing'}
            <button class="link" onclick={async () => {
              try { await media.transcribe(clip.id); say('Queued for transcription'); }
              catch (e) { say(e.message, 'error'); } }}>Transcribe it</button>
          {/if}
        </p>
      {/if}
    </div>

    <aside class="side mg-noscroll">
      {#if loading || !clip}
        {#each Array(6) as _, i (i)}
          <div style="margin-bottom:0.6rem"><Skeleton h="0.9rem" delay={i * 60} /></div>
        {/each}
      {:else}
        {#if can(CAP.ANNOTATE)}
          <section>
            <span class="mg-label">Label</span>
            <LabelDots value={clip.label ?? null} noneLabel="Clear label"
                       onchange={(v) => setLabel([clip.id], v)} />
          </section>
        {:else if clip.label}
          <section>
            <span class="mg-label">Label</span>
            <span class="mg-chip">{clip.label}</span>
          </section>
        {/if}

        <section>
          <span class="mg-label">Open in</span>
          <div class="open">
            {#if isPhoto}
              <a class="mg-btn secondary sm" href="/media/edit?id={clip.id}">
                <Icon name="sliders" size={14} />Edit photo
              </a>
              <a class="mg-btn secondary sm" href="/media/hdr?id={clip.id}">
                <Icon name="sun" size={14} />HDR / Looks
              </a>
            {:else if clip.media_type === 'video'}
              <a class="mg-btn secondary sm" href="/media/video?clip={clip.id}">
                <Icon name="film" size={14} />Open in video editor
              </a>
            {/if}
            {#if can(CAP.DOWNLOAD)}
              <a class="mg-btn ghost sm" href={media.fileUrl(clip.id)} download={clip.filename}>
                <Icon name="download" size={14} />Download
              </a>
            {/if}
          </div>
        </section>

        {#if isPhoto}
          <VirtualCopies {clip} />
        {/if}

        <section>
          <span class="mg-label">Details</span>
          <dl class="mg-kv">
            {#each facts as [k, v] (k)}
              <div><dt>{k}</dt><dd>{v}</dd></div>
            {/each}
          </dl>
        </section>

        <section>
          <span class="mg-label">Tags</span>
          <div class="tags">
            {#each clip.tags || [] as tag (tag.id)}
              <span class="mg-chip">{tag.name}</span>
            {:else}
              <span class="dim">None yet.</span>
            {/each}
          </div>
        </section>

        <section>
          <span class="mg-label">Notes</span>
          {#each notes as n (n.id)}
            <p class="note mg-glass-soft">{n.content}</p>
          {:else}
            <p class="dim">Nothing noted.</p>
          {/each}
          <form onsubmit={(e) => { e.preventDefault(); addNote(); }}>
            <input class="mg-input" type="text" bind:value={newNote} placeholder="Add a note…" />
          </form>
        </section>

        <section>
          <span class="mg-label">File</span>
          <p class="path mg-code">{clip.filepath}</p>
        </section>

        {#if can(CAP.TRASH)}
          <section>
            <button class="mg-btn danger sm" disabled={trashing} onclick={trashIt}>
              <Icon name="trash" size={14} />Move to trash
            </button>
          </section>
        {/if}
      {/if}
    </aside>
  </div>
</div>
{/key}
</div>

<style>
  .scrim { position: fixed; inset: 0; z-index: 90; background: var(--mc-scrim); }

  /* The lightbox: a raised plane, not glass. Centred from 720px up. */
  .box {
    position: fixed; inset: clamp(8px, 2.5vh, 22px) clamp(8px, 2.5vw, 22px);
    z-index: 91; overflow: hidden; outline: none; will-change: transform;
    display: flex; flex-direction: column;
    background: var(--mc-raised); border: 1px solid var(--mc-line2);
    border-radius: var(--mc-r-lg); box-shadow: var(--mc-sh-2);
  }
  /* Below 720px: a near-full-height sheet that rises from the bottom edge. */
  .box.phone {
    inset: auto 0 0 0; height: 94dvh;
    border-left: 0; border-right: 0; border-bottom: 0;
    border-radius: var(--mc-r-lg) var(--mc-r-lg) 0 0;
  }
  .grab { flex: none; display: grid; place-items: center; padding: 10px 0 6px; cursor: grab; touch-action: none; }
  .grab > i { display: block; width: 36px; height: 4px; border-radius: 9999px; background: var(--mc-line3); }

  .x { position: absolute; right: 12px; top: 12px; z-index: 6; }
  .phone .x { top: 8px; right: 10px; }
  .nav {
    position: absolute; top: 50%; margin-top: -20px; z-index: 6;
    opacity: 0; transition: opacity var(--mc-t-fast), background var(--mc-t-fast), border-color var(--mc-t-fast);
  }
  .box:hover .nav { opacity: 0.85; }
  .nav:hover, .nav:focus-visible { opacity: 1; }
  .prev { left: 12px; }
  .next { right: 12px; }

  .grid { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) 320px; }
  .stagecol { display: flex; flex-direction: column; min-width: 0; overflow-y: auto; }

  .screen { background: var(--mc-inset); aspect-ratio: 16 / 9; flex: none; position: relative; }
  .screen video, .screen img { width: 100%; height: 100%; object-fit: contain; display: block; }

  .head { padding: 16px 20px 6px; }
  .head h2 { font-size: 17px; overflow-wrap: anywhere; }
  .sub { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 4px;
         font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink3); }
  .sub span + span::before { content: '·'; margin-right: 8px; }

  .tr { padding: 10px 20px 22px; min-height: 0; }
  .trh { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
  .follow { font: 400 12px/1 var(--mc-font); color: var(--mc-ink3);
            display: flex; align-items: center; gap: 6px; cursor: pointer; }
  .follow input { accent-color: var(--mc-accent); }

  /* Transcript lines are ghost rows: nothing but type until one is live. */
  .lines { max-height: 40vh; overflow-y: auto; display: flex; flex-direction: column; gap: 1px; }
  .line {
    display: grid; grid-template-columns: 52px minmax(0, 1fr); gap: 10px;
    text-align: left; padding: 7px 9px; border-radius: var(--mc-r-sm); border: 0; cursor: pointer;
    background: none; color: var(--mc-ink2); font: 400 13.5px/1.6 var(--mc-font);
    transition: background var(--mc-t-fast), color var(--mc-t-fast);
  }
  .line:hover { background: var(--mc-line); color: var(--mc-ink); }
  .line.on { background: var(--mc-ok-soft); color: var(--mc-ink); }
  .line:focus-visible { outline: 2px solid var(--mc-accent); outline-offset: -2px; }
  .tc { font: 500 11.5px/1.9 var(--mc-mono); color: var(--mc-ink3); }
  .line.on .tc { color: var(--mc-accent); }
  .tx { overflow-wrap: anywhere; }
  .w { transition: color var(--mc-t-fast); }
  .w.said { color: var(--mc-accent); font-weight: 500; }

  .none { padding: 10px 20px 24px; color: var(--mc-ink3); font-size: 13px; }
  .link { color: var(--mc-accent); border: 0; background: none; padding: 0; cursor: pointer;
          font: inherit; text-decoration: underline; }

  .side {
    border-left: 1px solid var(--mc-line); padding: 18px; overflow-y: auto; overscroll-behavior: contain;
    background: var(--mc-surface);
  }
  .side section { margin-bottom: 22px; }
  .side section .mg-label { margin-bottom: 8px; }

  .tags { display: flex; gap: 5px; flex-wrap: wrap; }

  .note {
    margin: 0 0 6px; padding: 8px 11px; border-radius: var(--mc-r-md);
    font: 400 12.5px/1.55 var(--mc-font); color: var(--mc-ink2); overflow-wrap: anywhere;
  }
  .path { margin: 0; overflow-wrap: anywhere; color: var(--mc-ink3); font-size: 11.5px; }
  .open { display: flex; gap: 6px; flex-wrap: wrap; }
  .dim { display: block; font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink3); }
  form { margin-top: 8px; }

  @media (max-width: 900px) {
    .grid { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto auto; overflow-y: auto; overscroll-behavior: contain; }
    .stagecol { overflow: visible; }
    .side { overflow: visible; }
    .side { border-left: 0; border-top: 1px solid var(--mc-line); }
    .nav { display: none; }
    .lines { max-height: none; }
    .side { padding: 16px 16px calc(24px + var(--sab)); }
  }
  @media (pointer: coarse) {
    .x { width: 44px; height: 44px; }
    .open .mg-btn, section > .mg-btn { height: 44px; }
    .line { min-height: 44px; }
    .follow { min-height: 44px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .line, .w { transition: none; }
  }
</style>
