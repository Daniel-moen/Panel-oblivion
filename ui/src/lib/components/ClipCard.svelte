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
<div class="card mg-glass-soft" bind:this={el}
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
  /* A glass-soft card holding a 12px-radius frame. The frame is the clip; the
     two lines under it are the only chrome. */
  .card {
    position: relative; border-radius: 16px; padding: 5px;
    transition: background 0.2s, border-color 0.2s,
                transform 0.26s cubic-bezier(0.2, 0.8, 0.2, 1), box-shadow 0.26s;
  }
  .card:hover {
    transform: translateY(-3px); background: var(--mg-glass-hover);
    border-color: var(--mg-line2); box-shadow: var(--mg-sh-2); z-index: 2;
  }
  .card.sel { border-color: rgba(62, 207, 142, 0.55); box-shadow: 0 0 0 1px rgba(62, 207, 142, 0.35); }

  .hit { display: block; width: 100%; text-align: left; padding: 0; border: 0;
         background: none; border-radius: 12px; cursor: pointer; }
  .hit:focus-visible { outline: 2px solid var(--mg-ok); outline-offset: 2px; }

  .frame {
    position: relative; display: block; aspect-ratio: 16 / 9; border-radius: 12px;
    background: var(--mg-term); overflow: hidden;
  }
  .frame img, .frame video {
    position: absolute; inset: 0; width: 100%; height: 100%;
    object-fit: cover; display: block;
  }
  .frame img { opacity: 0; transition: opacity 0.4s, transform 0.5s cubic-bezier(0.2, 0.8, 0.2, 1); }
  .frame img.in { opacity: 1; }
  .card:hover .frame img { transform: scale(1.04); }
  .frame video { z-index: 1; animation: fadein 0.45s ease both; }
  @keyframes fadein { from { opacity: 0; } to { opacity: 1; } }

  .noimg { position: absolute; inset: 0; display: grid; place-items: center;
           font-size: 11px; color: var(--mg-i3); }

  .shade {
    position: absolute; inset: 0; z-index: 2; pointer-events: none;
    background: linear-gradient(180deg, rgba(0, 0, 0, 0.3) 0%, transparent 34%,
                                transparent 60%, rgba(0, 0, 0, 0.62) 100%);
    opacity: 0.75; transition: opacity 0.25s;
  }
  .card:hover .shade { opacity: 1; }

  /* Readability beats glass on a moving image: the duration sits on near-opaque
     dark so it survives a white frame. */
  .dur {
    position: absolute; right: 6px; bottom: 6px; z-index: 3;
    font: 600 11px/1 var(--mg-font); font-variant-numeric: tabular-nums;
    background: var(--mg-term); color: #fff; padding: 4px 7px; border-radius: 9999px;
  }

  .chips { position: absolute; left: 6px; bottom: 6px; z-index: 3; display: flex; gap: 4px;
           opacity: 0; transform: translateY(4px); transition: opacity 0.22s, transform 0.22s; }
  .card:hover .chips { opacity: 1; transform: none; }
  .chip {
    font: 500 10.5px/1 var(--mg-font); letter-spacing: 0.01em;
    background: rgba(8, 8, 10, 0.72); color: rgba(255, 255, 255, 0.86);
    border: 1px solid rgba(255, 255, 255, 0.14);
    padding: 4px 7px; border-radius: 9999px; white-space: nowrap;
  }

  .stars { position: absolute; left: 8px; top: 7px; z-index: 3; font-size: 11px;
           color: var(--mg-warn); text-shadow: 0 1px 3px rgba(0, 0, 0, 0.6); letter-spacing: 0.04em; }
  .flag {
    position: absolute; right: 6px; top: 6px; z-index: 3;
    font: 500 10px/1 var(--mg-font); padding: 4px 7px; border-radius: 9999px;
    background: rgba(240, 180, 41, 0.16); border: 1px solid rgba(240, 180, 41, 0.35);
    color: var(--mg-warn);
  }

  .meta { display: block; padding: 8px 7px 5px; min-width: 0; }
  .meta b { display: block; font: 500 13px/1.35 var(--mg-font); color: var(--mg-i);
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .lbl { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px;
         vertical-align: 0.05em; box-shadow: 0 0 0 2px rgba(0, 0, 0, 0.25); }
  .meta span { display: block; font: 400 11.5px/1.45 var(--mg-font); color: var(--mg-i3);
               white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  /* The select tick: a 24px round piece of glass that fills green once it is on. */
  .tick {
    position: absolute; left: 12px; top: 12px; z-index: 4;
    width: 24px; height: 24px; border-radius: 50%; padding: 0; cursor: pointer;
    display: grid; place-items: center;
    border: 1px solid rgba(255, 255, 255, 0.35); background: rgba(8, 8, 10, 0.55);
    color: rgba(255, 255, 255, 0.9);
    -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px);
    opacity: 0; transform: scale(0.7);
    transition: opacity 0.2s, transform 0.34s cubic-bezier(0.34, 1.56, 0.64, 1),
                background 0.2s, border-color 0.2s, color 0.2s;
  }
  .card:hover .tick, .tick.on, .tick:focus-visible { opacity: 1; transform: scale(1); }
  .tick.on {
    background: var(--mg-ok); border-color: var(--mg-ok); color: var(--mg-ok-ink);
    transform: scale(1.06);
  }
  /* 24px to look at, 40px to hit: a thumb needs the bigger target. */
  .tick::before { content: ''; position: absolute; inset: -8px; border-radius: 50%; }
  .tick:focus-visible { outline: 2px solid var(--mg-ok); outline-offset: 2px; }

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
