<script>
  /* One clip in the browse grid.

     Hover scrubbing is done by playing the proxy, not by a sprite strip:
     Zerko's previews.py only ever makes a single still (make_video_thumb /
     make_image_jpeg — there is no sprite generator to read), and the proxies
     are small H.264 files that already exist for exactly this reason. The
     video element is only created while the pointer is actually over the
     card, so a grid of 500 clips holds one video at a time, not 500.

     Touch devices never get it: `hover: hover` gates the whole thing, so a
     phone is not asked to autoplay anything. */
  import { thumbUrl, streamUrl, fmtDuration } from '$lib/media.js';
  import { labelColor } from '$lib/media.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';

  let { clip, selected = false, selecting = false, onopen, ontoggle } = $props();

  let hovering = $state(false);
  let loaded = $state(false);
  let el = $state(null);
  let visible = $state(false);

  /* Thumbnails only load once the card is near the viewport. With a few
     thousand clips the difference is the page painting at all. */
  $effect(() => {
    if (!el || visible) return;
    if (!('IntersectionObserver' in window)) { visible = true; return; }
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { visible = true; io.disconnect(); }
    }, { rootMargin: '400px' });
    io.observe(el);
    return () => io.disconnect();
  });

  const canScrub = $derived(clip.has_proxy && clip.media_type === 'video');
  const thumb = $derived(thumbUrl(clip));

  function activate(e) {
    if (selecting || e.metaKey || e.ctrlKey || e.shiftKey) { ontoggle?.(clip); return; }
    onopen?.(clip);
  }
</script>

<!-- role="group": the card holds two controls (open, select) and carries the
     hover handlers that swap the still for the moving preview. -->
<div class="card" bind:this={el}
     role="group" aria-label={clip.filename}
     class:sel={selected}
     onmouseenter={() => (hovering = true)}
     onmouseleave={() => (hovering = false)}>

  <button class="hit" onclick={activate}
          aria-label="Open {clip.filename}">
    <span class="frame">
      {#if visible && thumb}
        <img src={thumb} alt="" loading="lazy" class:in={loaded}
             onload={() => (loaded = true)} />
      {:else if visible}
        <span class="noimg">no preview</span>
      {/if}

      {#if hovering && canScrub}
        <!-- svelte-ignore a11y_media_has_caption -->
        <video src={streamUrl(clip)} muted loop autoplay playsinline preload="none"></video>
      {/if}

      <span class="shade" aria-hidden="true"></span>

      {#if clip.duration}
        <span class="dur">{fmtDuration(clip.duration)}</span>
      {/if}

      <span class="chips">
        {#if clip.resolution}<span class="chip">{clip.resolution}</span>{/if}
        {#if clip.video_codec}<span class="chip">{clip.video_codec}</span>{/if}
        {#if clip.media_type === 'photo'}<span class="chip">photo</span>{/if}
      </span>

      {#if clip.rating}
        <span class="stars" aria-label="{clip.rating} stars">{'★'.repeat(clip.rating)}</span>
      {/if}

      {#if !clip.has_proxy && clip.media_type === 'video'}
        <span class="flag" title="No proxy yet — playback uses the master">no proxy</span>
      {/if}
    </span>

    <span class="meta">
      <b>{#if clip.label}<i class="lbl" style:background={labelColor(clip.label)}
             role="img" title="{clip.label} label" aria-label="{clip.label} label"></i>{/if}{clip.filename}</b>
      <span>{[clip.folder_name, clip.file_size_formatted].filter(Boolean).join(' · ')}</span>
    </span>
  </button>

  <button class="tick" class:on={selected} aria-pressed={selected}
          aria-label={selected ? 'Deselect' : 'Select'}
          onclick={(e) => { e.stopPropagation(); ontoggle?.(clip); }}>
    <Icon name="check" size={13} stroke={3} />
  </button>
</div>

<style>
  /* A panel card holding a 12px-radius frame. The frame is the clip; the
     two lines under it are the only chrome. */
  .card {
    position: relative; border-radius: var(--mc-r); padding: 5px;
    background: var(--mc-surface); border: 1px solid var(--mc-line); box-shadow: var(--mc-sh-1);
    transition: border-color var(--mc-t-fast), transform var(--mc-t) var(--mc-ease);
  }
  .card:hover { transform: translateY(-2px); border-color: var(--mc-line2); z-index: 2; }
  .card.sel { border-color: var(--mc-ok-line); box-shadow: 0 0 0 1px var(--mc-ok-line); }

  .hit { display: block; width: 100%; text-align: left; padding: 0; border: 0;
         background: none; border-radius: var(--mc-r-md); cursor: pointer; }
  .hit:focus-visible { outline: 2px solid var(--mc-accent); outline-offset: 2px; }

  .frame {
    position: relative; display: block; aspect-ratio: 16 / 9; border-radius: var(--mc-r-md);
    background: var(--mc-inset); overflow: hidden;
  }
  .frame img, .frame video {
    position: absolute; inset: 0; width: 100%; height: 100%;
    object-fit: cover; display: block;
  }
  .frame img { opacity: 0; transition: opacity var(--mc-t-slow), transform var(--mc-t-slow) var(--mc-ease); }
  .frame img.in { opacity: 1; }
  .card:hover .frame img { transform: scale(1.04); }
  .frame video { z-index: 1; animation: fadein var(--mc-t-slow) var(--mc-ease) both; }
  @keyframes fadein { from { opacity: 0; } to { opacity: 1; } }

  .noimg { position: absolute; inset: 0; display: grid; place-items: center;
           font-size: 11px; color: var(--mc-ink3); }

  .shade {
    position: absolute; inset: 0; z-index: 2; pointer-events: none;
    background: linear-gradient(180deg, rgba(0, 0, 0, 0.3) 0%, transparent 34%,
                                transparent 60%, rgba(0, 0, 0, 0.62) 100%);
    opacity: 0.75; transition: opacity 0.25s;
  }
  .card:hover .shade { opacity: 1; }

  /* The duration sits on the inset colour so it survives a white frame. */
  .dur {
    position: absolute; right: 6px; bottom: 6px; z-index: 3;
    font: 500 11px/1 var(--mc-mono); font-variant-numeric: tabular-nums;
    background: var(--mc-inset); color: var(--mc-ink); padding: 4px 7px; border-radius: var(--mc-r-sm);
  }

  /* Clear of the duration badge: on a narrow card the chips clip, never overlap. */
  .chips { position: absolute; left: 6px; bottom: 6px; right: 60px; z-index: 3; display: flex; gap: 4px; overflow: hidden;
           opacity: 0; transform: translateY(4px); transition: opacity 0.22s, transform 0.22s; }
  .card:hover .chips { opacity: 1; transform: none; }
  .chip {
    font: 500 10.5px/1 var(--mc-font); letter-spacing: 0.01em;
    background: var(--mc-inset); color: var(--mc-ink2);
    border: 1px solid var(--mc-line);
    padding: 4px 7px; border-radius: var(--mc-r-sm); white-space: nowrap;
  }

  .stars { position: absolute; left: 36px; top: 6px; z-index: 3; font-size: 10.5px; line-height: 1;
           color: var(--mc-warn); letter-spacing: 0.04em;
           background: var(--mc-inset); padding: 4px 6px; border-radius: var(--mc-r-sm); }
  .flag {
    position: absolute; right: 6px; top: 6px; z-index: 3;
    font: 500 10px/1 var(--mc-font); padding: 4px 7px; border-radius: var(--mc-r-sm);
    background: var(--mc-inset); border: 1px solid var(--mc-warn-line);
    color: var(--mc-warn);
  }

  .meta { display: block; padding: 8px 7px 5px; min-width: 0; }
  .meta b { display: block; font: 500 13px/1.35 var(--mc-font); color: var(--mc-ink);
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .lbl { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px;
         vertical-align: 0.05em; }
  .meta span { display: block; font: 400 11.5px/1.45 var(--mc-font); color: var(--mc-ink3);
               white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  /* The select tick: a 24px round control that fills green once it is on. */
  .tick {
    position: absolute; left: 12px; top: 12px; z-index: 4;
    width: 24px; height: 24px; border-radius: 50%; padding: 0; cursor: pointer;
    display: grid; place-items: center;
    border: 1px solid var(--mc-line3); background: var(--mc-inset);
    color: var(--mc-ink2);
    opacity: 0; transform: scale(0.85);
    transition: opacity var(--mc-t-fast), transform var(--mc-t) var(--mc-ease),
                background var(--mc-t-fast), border-color var(--mc-t-fast), color var(--mc-t-fast);
  }
  .card:hover .tick, .tick.on, .tick:focus-visible { opacity: 1; transform: scale(1); }
  .tick.on {
    background: var(--mc-accent); border-color: var(--mc-accent); color: var(--mc-accent-ink);
  }
  /* 24px to look at, 44px to hit: a thumb needs the bigger target. */
  .tick::before { content: ''; position: absolute; inset: -10px; border-radius: 50%; }
  .tick:focus-visible { outline: 2px solid var(--mc-accent); outline-offset: 2px; }

  @media (hover: none) {
    .frame video { display: none; }
    .tick { opacity: 1; transform: scale(1); }
    .chips { opacity: 1; transform: none; }
  }
  @media (prefers-reduced-motion: reduce) {
    .card, .card:hover, .frame img, .tick { transition: none; transform: none; }
    .frame video { animation: none; }
  }
</style>
