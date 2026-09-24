<script>
  /* The clip lightbox: player on the left, everything known about the clip on
     the right, transcript running underneath in time with the playhead.

     The transcript is the reason this screen exists. Zerko stores segments
     with a start and an end but no per-word timings, so the word highlight is
     interpolated across the segment's own duration — an honest estimate that
     reads as karaoke and, more importantly, makes every line clickable: click
     a line, the player seeks there. Finding the ten seconds where someone
     said "sea view" is the whole job. */
  import { fade, fly } from 'svelte/transition';
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
</script>



<svelte:window onkeydown={onKey} />

<div class="scrim" onclick={onclose} transition:fade={{ duration: 180 }} aria-hidden="true"></div>

<div class="box mg-glass-strong" role="dialog" aria-modal="true" aria-label={clip?.filename || 'Clip'}
     transition:fly={{ y: 18, duration: 280, opacity: 0 }}>

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
          <p class="path">{clip.filepath}</p>
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

<style>
  .scrim {
    position: fixed; inset: 0; z-index: 90; background: rgba(6, 6, 8, 0.6);
    -webkit-backdrop-filter: blur(6px); backdrop-filter: blur(6px);
  }
  .box {
    position: fixed; inset: clamp(8px, 2.5vh, 22px) clamp(8px, 2.5vw, 22px);
    z-index: 91; overflow: hidden; will-change: transform, opacity;
  }

  /* Round glass buttons, the same vocabulary as the top bar. */
  .x { position: absolute; right: 12px; top: 12px; z-index: 6; }
  .nav {
    position: absolute; top: 50%; margin-top: -20px; z-index: 6;
    opacity: 0; transition: opacity 0.2s, background 0.18s, border-color 0.18s;
  }
  .box:hover .nav { opacity: 0.8; }
  .nav:hover, .nav:focus-visible { opacity: 1; }
  .prev { left: 12px; }
  .next { right: 12px; }

  .grid { display: grid; grid-template-columns: minmax(0, 1fr) 320px; height: 100%; }
  .stagecol { display: flex; flex-direction: column; min-width: 0; overflow-y: auto; }

  /* Readability beats glass: the video sits on near-opaque black. */
  .screen { background: #000; aspect-ratio: 16 / 9; flex: none; position: relative; }
  .screen video, .screen img { width: 100%; height: 100%; object-fit: contain; display: block; }

  .head { padding: 16px 20px 6px; }
  .head h2 { font-size: 17px; overflow-wrap: anywhere; }
  .sub { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 4px;
         font: 400 12.5px/1.5 var(--mg-font); color: var(--mg-i3); }
  .sub span + span::before { content: '·'; margin-right: 8px; }

  .tr { padding: 10px 20px 22px; min-height: 0; }
  .trh { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
  .follow { font: 400 12px/1 var(--mg-font); color: var(--mg-i3);
            display: flex; align-items: center; gap: 6px; cursor: pointer; }
  .follow input { accent-color: var(--mg-ok); }

  /* Transcript lines are ghost rows: nothing but type until one is live. */
  .lines { max-height: 40vh; overflow-y: auto; display: flex; flex-direction: column; gap: 1px; }
  .line {
    display: grid; grid-template-columns: 52px minmax(0, 1fr); gap: 10px;
    text-align: left; padding: 7px 9px; border-radius: 10px; border: 0; cursor: pointer;
    background: none; color: var(--mg-i2); font: 400 13.5px/1.6 var(--mg-font);
    transition: background 0.2s, color 0.2s;
  }
  .line:hover { background: rgba(255, 255, 255, 0.05); color: var(--mg-i); }
  .line.on { background: rgba(255, 255, 255, 0.08); color: var(--mg-i); }
  .line:focus-visible { outline: 2px solid var(--mg-ok); outline-offset: -2px; }
  .tc { font: 500 11.5px/1.9 var(--mg-mono); color: var(--mg-i3); }
  .line.on .tc { color: var(--mg-ok); }
  .tx { overflow-wrap: anywhere; }
  .w { transition: color 0.18s; }
  .w.said { color: #3ecf8e; font-weight: 500; }

  .none { padding: 10px 20px 24px; color: var(--mg-i3); font-size: 13px; }
  .link { color: var(--mg-ok); border: 0; background: none; padding: 0; cursor: pointer;
          font: inherit; text-decoration: underline; }

  .side {
    border-left: 1px solid var(--mg-line); padding: 18px; overflow-y: auto;
    background: rgba(0, 0, 0, 0.18);
  }
  .side section { margin-bottom: 22px; }
  .side section .mg-label { margin-bottom: 8px; }

  .tags { display: flex; gap: 5px; flex-wrap: wrap; }
  .tags .mg-chip { animation: chip 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) both; }
  @keyframes chip { from { opacity: 0; transform: scale(0.85); } to { opacity: 1; transform: none; } }

  .note {
    margin: 0 0 6px; padding: 8px 11px; border-radius: 12px;
    font: 400 12.5px/1.55 var(--mg-font); color: var(--mg-i2); overflow-wrap: anywhere;
  }
  .path { margin: 0; padding: 8px 11px; border-radius: 12px; background: var(--mg-term);
          font: 11.5px/1.55 var(--mg-mono); color: var(--mg-i3); overflow-wrap: anywhere; }
  .open { display: flex; gap: 6px; flex-wrap: wrap; }
  .dim { display: block; font: 400 12.5px/1.5 var(--mg-font); color: var(--mg-i3); }
  form { margin-top: 8px; }

  @media (max-width: 900px) {
    .grid { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto auto; overflow-y: auto; }
    .side { border-left: 0; border-top: 1px solid var(--mg-line); }
    .nav { display: none; }
    .lines { max-height: none; }
    .side { padding: 16px 14px calc(16px + var(--mg-sab, 0px)); }
  }
  @media (pointer: coarse) {
    .x { width: 40px; height: 40px; }
    .open .mg-btn, section > .mg-btn { height: 40px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .tags .mg-chip { animation: none; }
    .line, .w { transition: none; }
  }
</style>
