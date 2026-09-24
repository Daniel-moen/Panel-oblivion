<script>
  /* The edit, played in the browser: one <video> walking the timeline clip by
     clip on the proxy streams, at each clip's speed and volume, framed to
     the project's shape. It is a guide, not the render — transitions play as
     cuts and the grade is a CSS approximation; the render is exact.

     `time` is bindable: the timeline's playhead and this player share it. */
  import { streamUrl } from '$lib/media.js';
  import { layout, tc, ASPECT_WH } from '$lib/media/video.js';
  import Icon from '$lib/components/glass/Icon.svelte';

  let { project, time = $bindable(0) } = $props();

  let el = $state(null);
  let playing = $state(false);
  let cur = -1;                // index of the clip loaded in the element
  let pendingSeek = null;

  const lay = $derived(layout(project));
  const [aw, ah] = $derived(ASPECT_WH[project.aspect] || [9, 16]);

  function indexAt(t) {
    const it = lay.items;
    if (!it.length) return -1;
    let idx = 0;
    for (let i = 0; i < it.length; i++) if (t >= it[i].start - 1e-6) idx = i;
    return idx;
  }

  const idxNow = $derived(indexAt(time));
  const clipNow = $derived(project.clips[idxNow]);

  const filter = $derived.by(() => {
    const g = clipNow?.grade || project.grade || {};
    const b = Math.pow(2, (g.exposure || 0) * 0.6);
    const c = 1 + (g.contrast || 0) * 0.5;
    const s = 1 + (g.saturation || 0);
    const hue = (g.temp || 0) * -8;
    return `brightness(${b.toFixed(3)}) contrast(${c.toFixed(3)}) saturate(${Math.max(0, s).toFixed(3)}) sepia(${Math.max(0, (g.temp || 0) * 0.25).toFixed(3)}) hue-rotate(${hue.toFixed(1)}deg)`;
  });

  function applyClip(i, localT) {
    const c = project.clips[i];
    if (!el || !c) return;
    el.playbackRate = Math.max(0.0625, Math.min(16, c.speed || 1));
    el.muted = !!c.mute;
    el.volume = Math.max(0, Math.min(1, c.volume ?? 1));
    if (cur !== i || !el.currentSrc) {
      const same = cur >= 0 && project.clips[cur]?.video_id === c.video_id && el.currentSrc;
      cur = i;
      if (!same) {
        pendingSeek = localT;
        el.src = streamUrl({ id: c.video_id });
        el.load();
        return;
      }
    }
    el.currentTime = localT;
    if (playing) el.play().catch(() => {});
  }

  function onMeta() {
    if (pendingSeek != null && el) {
      el.currentTime = pendingSeek;
      pendingSeek = null;
      if (playing) el.play().catch(() => {});
    }
  }

  /** Put the element at timeline time t. */
  export function seek(t) {
    t = Math.max(0, Math.min(lay.total, t));
    time = t;
    const i = indexAt(t);
    if (i < 0) return;
    const c = project.clips[i];
    const local = c.src_in + (t - lay.items[i].start) * (c.speed || 1);
    applyClip(i, Math.min(local, c.src_out - 0.01));
  }

  function onTime() {
    if (!el || cur < 0 || pendingSeek != null) return;
    const c = project.clips[cur];
    if (!c) return;
    const t = lay.items[cur].start + (el.currentTime - c.src_in) / (c.speed || 1);
    if (playing) time = Math.max(lay.items[cur].start, t);
    if (playing && (el.currentTime >= c.src_out - 0.02)) next();
  }

  function next() {
    const n = cur + 1;
    if (n >= project.clips.length) {
      playing = false;
      el?.pause();
      time = lay.total;
      return;
    }
    time = lay.items[n].start;
    applyClip(n, project.clips[n].src_in);
  }

  function toggle() {
    if (!project.clips.length) return;
    if (playing) { playing = false; el?.pause(); return; }
    playing = true;
    if (time >= lay.total - 0.05) time = 0;
    seek(time);
  }

  /* an outside seek (ruler click, trim change) while paused: follow it */
  let lastSeen = -1;
  $effect(() => {
    const t = time;
    project.clips.length;
    if (playing) return;
    if (Math.abs(t - lastSeen) < 1e-4 && cur >= 0) return;
    lastSeen = t;
    queueMicrotask(() => seek(t));
  });

  /* the clip under the playhead was edited (trim, speed) — re-sync when paused */
  $effect(() => {
    const c = clipNow;
    if (!c) return;
    c.src_in; c.src_out; c.speed; c.video_id; c.volume; c.mute;
    if (!playing) queueMicrotask(() => seek(time));
  });
</script>

<div class="pv">
  <div class="stage" style:aspect-ratio="{aw} / {ah}" style:width="min(100%, calc(56vh * {aw} / {ah}))">
    {#if project.clips.length}
      <!-- svelte-ignore a11y_media_has_caption -->
      <video bind:this={el} playsinline preload="auto"
             class:fit={clipNow?.frame?.mode === 'fit'}
             style:filter={filter}
             style:object-position="{(clipNow?.frame?.x ?? 0.5) * 100}% {(clipNow?.frame?.y ?? 0.5) * 100}%"
             style:transform="scale({clipNow?.frame?.zoom ?? 1})"
             onloadedmetadata={onMeta} ontimeupdate={onTime}
             onended={() => { if (playing) next(); }}
             onclick={toggle}></video>
    {:else}
      <div class="none">Add clips to see the edit</div>
    {/if}
  </div>
  <div class="ctl">
    <button type="button" class="mg-btn secondary icon" onclick={toggle} disabled={!project.clips.length}
            aria-label={playing ? 'Pause' : 'Play'}>
      <Icon name={playing ? 'stop' : 'play'} size={16} />
    </button>
    <button type="button" class="mg-btn ghost icon" onclick={() => { playing = false; el?.pause(); seek(0); }} aria-label="To start">
      <Icon name="undo" size={15} />
    </button>
    <span class="t mg-tnum">{tc(time)} <i>/ {tc(lay.total)}</i></span>
  </div>
  <p class="note">Preview plays transitions as cuts and the look approximately — the render is exact.</p>
</div>

<style>
  .pv { display: flex; flex-direction: column; gap: 8px; align-items: center; min-width: 0; }
  .stage {
    position: relative; max-width: 100%;
    background: #000; border-radius: var(--mg-r-in); overflow: hidden; display: grid; place-items: center;
    margin: 0 auto;
  }
  video { width: 100%; height: 100%; object-fit: cover; display: block; transform-origin: center; }
  video.fit { object-fit: contain; }
  .none { color: var(--mg-i3); font-size: 13px; padding: 20px; text-align: center; }
  .ctl { display: flex; align-items: center; gap: 6px; }
  .t { font: 500 13px/1 var(--mg-mono); color: var(--mg-i); }
  .t i { font-style: normal; color: var(--mg-i3); }
  .note { margin: 0; font-size: 11.5px; color: var(--mg-i3); text-align: center; }
</style>
