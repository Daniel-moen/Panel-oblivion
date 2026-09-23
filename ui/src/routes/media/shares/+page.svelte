<script>
  /* Share links: make one, watch what the client did with it.

     The interesting column is "picked" — a share the client has been through
     comes back with hearts and notes attached, and that is the whole point of
     sending it. The FCPXML export turns those picks into a timeline the
     editor can open, which is why it sits next to them rather than in a menu.

     The link a client opens is /media/s/<token>, rendered by share_page.py.
     Zerko mints its own "/s/<token>" in the payload, which is the React app's
     route, not ours — so the URL is rebuilt here from the token.

     Making a link is a dialog, not a panel that pushes the list down: it is a
     handful of decisions taken once, and on a phone it rises from the bottom
     where the thumb already is. */
  import { onMount } from 'svelte';
  import { fly, fade } from 'svelte/transition';
  import { flip } from 'svelte/animate';
  import { mstate, boot, say } from '$lib/media.svelte.js';
  import { media, thumbUrl } from '$lib/media.js';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';
  import Empty from '$lib/components/glass/Empty.svelte';

  let shares = $state([]);
  let loading = $state(true);
  let folders = $state([]);
  let open = $state(false);
  let picks = $state({});          // share id -> selects
  let form = $state({ title: '', message: '', folder_id: '', expires_days: '',
                      allow_download: true, allow_selects: true, allow_upload: false });
  let copied = $state(null);

  const linkFor = (s) => `${location.origin}/media/s/${s.token}`;

  onMount(async () => {
    await boot();
    if (!mstate.ready) { loading = false; return; }
    await Promise.all([load(), media.folderTree().then((f) => (folders = flat(f))).catch(() => {})]);
  });

  function flat(nodes, depth = 0, out = []) {
    for (const n of nodes || []) {
      out.push({ id: n.id, name: '— '.repeat(depth) + n.name });
      if (n.children?.length) flat(n.children, depth + 1, out);
    }
    return out;
  }

  async function load() {
    loading = true;
    try { shares = (await media.shares()) || []; }
    catch (e) { say(e.message, 'error'); }
    finally { loading = false; }
  }

  async function create(e) {
    e.preventDefault();
    if (!form.folder_id) { say('Pick a folder to share', 'error'); return; }
    try {
      const body = {
        title: form.title || null,
        message: form.message || null,
        folder_id: Number(form.folder_id),
        include_subfolders: true,
        allow_download: form.allow_download,
        allow_selects: form.allow_selects,
        allow_upload: form.allow_upload
      };
      if (form.expires_days) body.expires_days = Number(form.expires_days);
      const made = await media.createShare(body);
      say('Link created');
      open = false;
      form = { title: '', message: '', folder_id: '', expires_days: '',
               allow_download: true, allow_selects: true, allow_upload: false };
      await load();
      if (made?.token) copy({ token: made.token });
    } catch (e) { say(e.message, 'error'); }
  }

  async function copy(s) {
    const url = linkFor(s);
    try { await navigator.clipboard.writeText(url); }
    catch {
      const ta = document.createElement('textarea');
      ta.value = url; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); } catch { /* give up quietly */ }
      ta.remove();
    }
    copied = s.token;
    say('Link copied');
    setTimeout(() => { if (copied === s.token) copied = null; }, 2200);
  }

  async function revoke(s) {
    if (!confirm('Turn this link off? Anyone holding it loses access immediately.')) return;
    try { await media.revokeShare(s.id); say('Link turned off'); load(); }
    catch (e) { say(e.message, 'error'); }
  }

  async function loadPicks(s) {
    if (picks[s.id]) { picks = { ...picks, [s.id]: null }; return; }
    try {
      /* The endpoint answers { share, selects, ... }, not a bare list, and a
         row with a note but no heart is included on purpose — "the lighting
         is off here" is feedback worth keeping. */
      const r = await media.shareSelects(s.id);
      picks = { ...picks, [s.id]: r?.selects || [] };
    } catch (e) { say(e.message, 'error'); }
  }

  const hearts = (rows) => (rows || []).filter((p) => p.picked).length;
  const notes = (rows) => (rows || []).filter((p) => p.comment).length;
  const day = (v) => (v ? String(v).slice(0, 10) : null);

  /* The dialog: Escape closes it, and the page behind it does not scroll. */
  function onKey(e) {
    if (e.key === 'Escape' && open) { e.stopPropagation(); open = false; }
  }
  $effect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  });
</script>

<svelte:head><title>Shares · Media</title></svelte:head>
<svelte:window onkeydown={onKey} />

<div class="mg-row">
  <h2 class="mg-h2">Shares</h2>
  {#if !loading}
    <span class="mg-count">{shares.length} link{shares.length === 1 ? '' : 's'}</span>
  {/if}
  <div class="mg-actions">
    <button class="mg-btn primary sm" onclick={() => (open = true)} disabled={!mstate.ready}>
      <Icon name="plus" size={14} />New share
    </button>
  </div>
</div>

<!-- ————————————————————————————————————————————————— the make dialog ——— -->
{#if open}
  <div class="veil" transition:fade={{ duration: 160 }}>
    <button type="button" class="scrim" aria-label="Close" onclick={() => (open = false)}></button>

    <div class="box mg-glass-strong" role="dialog" aria-modal="true"
         aria-label="New share link" transition:fly={{ y: 24, duration: 240 }}>
      <span class="grab" aria-hidden="true"></span>

      <form class="fm" onsubmit={create}>
        <div class="bh">
          <h3>New share link</h3>
          <button type="button" class="mg-btn secondary icon sm" aria-label="Close"
                  onclick={() => (open = false)}><Icon name="x" size={15} /></button>
        </div>

        <div class="body mg-noscroll">
          <div class="two">
            <div class="f">
              <span class="mg-label" id="sh-title">Title</span>
              <input class="mg-input" type="text" aria-labelledby="sh-title"
                     bind:value={form.title} placeholder="Camps Bay — first cut" />
            </div>
            <div class="f">
              <span class="mg-label" id="sh-folder">Folder</span>
              <div class="mg-select">
                <select bind:value={form.folder_id} aria-labelledby="sh-folder">
                  <option value="">Choose a folder…</option>
                  {#each folders as f (f.id)}<option value={f.id}>{f.name}</option>{/each}
                </select>
                <span class="ic"><Icon name="chevronDown" size={15} /></span>
              </div>
            </div>
          </div>

          <div class="f">
            <span class="mg-label" id="sh-msg">Message to the client</span>
            <input class="mg-input" type="text" aria-labelledby="sh-msg" bind:value={form.message}
                   placeholder="Here's the first pass — heart the ones you want." />
          </div>

          <div class="f">
            <span class="mg-label" id="sh-exp">Expires after</span>
            <div class="mg-select">
              <select bind:value={form.expires_days} aria-labelledby="sh-exp">
                <option value="">Never</option>
                <option value="7">7 days</option>
                <option value="30">30 days</option>
                <option value="90">90 days</option>
              </select>
              <span class="ic"><Icon name="chevronDown" size={15} /></span>
            </div>
          </div>

          <div class="f">
            <span class="mg-label">What the client may do</span>
            <div class="togs">
              <button type="button" class="mg-chip tog" class:on={form.allow_download}
                      aria-pressed={form.allow_download}
                      onclick={() => (form.allow_download = !form.allow_download)}>
                {#if form.allow_download}<Icon name="check" size={13} />{/if}Download
              </button>
              <button type="button" class="mg-chip tog" class:on={form.allow_selects}
                      aria-pressed={form.allow_selects}
                      onclick={() => (form.allow_selects = !form.allow_selects)}>
                {#if form.allow_selects}<Icon name="check" size={13} />{/if}Picks &amp; notes
              </button>
              <button type="button" class="mg-chip tog" class:on={form.allow_upload}
                      aria-pressed={form.allow_upload}
                      onclick={() => (form.allow_upload = !form.allow_upload)}>
                {#if form.allow_upload}<Icon name="check" size={13} />{/if}Upload back
              </button>
            </div>
          </div>
        </div>

        <div class="bf">
          <button type="button" class="mg-btn ghost" onclick={() => (open = false)}>Cancel</button>
          <button type="submit" class="mg-btn primary"><Icon name="link" size={15} />Create the link</button>
        </div>
      </form>
    </div>
  </div>
{/if}

<!-- —————————————————————————————————————————————————————— the links ——— -->
{#if loading}
  <div class="list">
    {#each Array(3) as _, i (i)}
      <div class="mg-card">
        <Skeleton h="1rem" w="35%" delay={i * 80} />
        <div style="height:0.6rem"></div>
        <Skeleton h="0.8rem" w="60%" delay={i * 80} />
      </div>
    {/each}
  </div>
{:else if !shares.length}
  <Empty icon="share" title="No links yet"
         hint="Make one and send it. The client sees a dark, full-width player, hearts the takes they want and leaves notes — all of which come back here.">
    {#snippet children()}
      <button class="mg-btn primary sm" onclick={() => (open = true)} disabled={!mstate.ready}>
        <Icon name="plus" size={14} />New share
      </button>
    {/snippet}
  </Empty>
{:else}
  <div class="list">
    {#each shares as s, i (s.id)}
      <article class="mg-card sh" animate:flip={{ duration: 250 }}
               in:fly={{ y: 12, duration: 320, delay: Math.min(i * 50, 300) }}>
        <div class="ch">
          <h3>{s.title || 'Untitled link'}</h3>
          <span class="mg-chip {s.revoked ? '' : 'ok'}"><span class="dot"></span>{s.revoked ? 'off' : 'live'}</span>
        </div>

        <p class="meta">
          {#if s.folder_name}<span class="w"><Icon name="folder" size={13} />{s.folder_name}</span>{/if}
          {#if day(s.created_at)}<span class="w mg-tnum">made {day(s.created_at)}</span>{/if}
          <span class="w mg-tnum">{s.expires_at ? `expires ${day(s.expires_at)}` : 'no expiry'}</span>
        </p>

        <div class="urlrow">
          <code>{linkFor(s)}</code>
          <button class="mg-btn secondary sm" onclick={() => copy(s)}>
            {#if copied === s.token}<Icon name="check" size={14} />Copied
            {:else}<Icon name="copy" size={14} />Copy{/if}
          </button>
          <a class="mg-btn secondary sm" href={linkFor(s)} target="_blank" rel="noopener">
            <Icon name="play" size={13} />Open
          </a>
        </div>

        <div class="chips">
          <span class="mg-chip"><b class="mg-tnum">{s.video_count ?? s.count ?? '—'}</b> clips</span>
          <span class="mg-chip"><b class="mg-tnum">{s.view_count ?? 0}</b> views</span>
          {#if s.allow_download}<span class="mg-chip">downloads on</span>{/if}
          {#if s.allow_selects}<span class="mg-chip">picks on</span>{/if}
          {#if s.allow_upload}<span class="mg-chip">uploads on</span>{/if}
        </div>

        <div class="acts">
          <button class="mg-btn secondary sm" onclick={() => loadPicks(s)}>
            <Icon name="star" size={13} />{picks[s.id] ? 'Hide picks' : 'Client picks'}
          </button>
          <a class="mg-btn secondary sm" href={media.fcpxmlUrl(s.id)}>
            <Icon name="download" size={13} />FCPXML
          </a>
          <a class="mg-btn secondary sm" href={media.csvUrl(s.id)}>
            <Icon name="download" size={13} />CSV
          </a>
          {#if !s.revoked}
            <button class="mg-btn sm danger drop" onclick={() => revoke(s)}>
              <Icon name="x" size={13} />Turn off
            </button>
          {/if}
        </div>

        {#if picks[s.id]}
          <div class="picks" in:fly={{ y: -6, duration: 200 }}>
            {#if picks[s.id].length}
              <div class="sum">
                <span class="mg-chip ok"><b class="mg-tnum">{hearts(picks[s.id])}</b> hearted</span>
                <span class="mg-chip"><b class="mg-tnum">{notes(picks[s.id])}</b> note{notes(picks[s.id]) === 1 ? '' : 's'}</span>
              </div>
              <div class="strip mg-noscroll">
                {#each picks[s.id] as p (p.video_id)}
                  <figure class="pick mg-glass-soft">
                    <span class="shot">
                      {#if p.thumbnail_path}
                        <img src={thumbUrl(p)} alt="" loading="lazy" />
                      {:else}
                        <span class="noimg">no thumbnail</span>
                      {/if}
                      {#if p.picked}<span class="heart" aria-label="picked">♥</span>{/if}
                    </span>
                    <figcaption>
                      <b title={p.filename || 'Clip ' + p.video_id}>{p.filename || 'Clip ' + p.video_id}</b>
                      {#if p.viewer_name}<span class="by">by {p.viewer_name}</span>{/if}
                      {#if p.comment}<p title={p.comment}>{p.comment}</p>{/if}
                    </figcaption>
                  </figure>
                {/each}
              </div>
            {:else}
              <p class="none">The client has not picked anything yet.</p>
            {/if}
          </div>
        {/if}
      </article>
    {/each}
  </div>
{/if}

<style>
  /* ———————————————————————————————————————————————————————— dialog ——— */
  .veil {
    position: fixed; inset: 0; z-index: 90; display: flex; justify-content: center;
    align-items: flex-end; background: var(--mg-scrim);
    -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
  }
  /* The scrim is a real button so closing by tapping outside costs no a11y. */
  .scrim { position: absolute; inset: 0; border: 0; padding: 0; background: none; cursor: default; }

  .box {
    position: relative; z-index: 1;
    display: flex; flex-direction: column; width: 100%; max-height: 92dvh; min-height: 0;
    border-radius: var(--mg-r) var(--mg-r) 0 0;
    padding-bottom: var(--mg-sab);
  }
  /* The form carries the column layout; the box carries the glass, so the
     dialog role sits on an element that is not itself a form. */
  .fm { display: flex; flex-direction: column; min-height: 0; flex: 1; }
  .grab {
    flex: none; width: 36px; height: 4px; border-radius: 9999px; margin: 10px auto 2px;
    background: rgba(255, 255, 255, 0.25);
  }

  .bh { flex: none; display: flex; align-items: center; gap: 10px; padding: 12px 16px 8px; }
  .bh h3 { margin: 0; flex: 1; min-width: 0; font: 600 16px/1.2 var(--mg-font);
           letter-spacing: -0.01em; color: var(--mg-i); }

  .body { flex: 1; min-height: 0; overflow-y: auto; padding: 4px 16px 16px;
          display: flex; flex-direction: column; gap: 12px; }
  .f { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
  .two { display: grid; gap: 12px; grid-template-columns: 1fr; }
  .mg-select { display: block; }

  .togs { display: flex; flex-wrap: wrap; gap: 8px; }
  .tog { min-height: 40px; padding: 0 14px; font-size: 12.5px; }

  .bf { flex: none; display: flex; justify-content: flex-end; gap: 8px;
        padding: 12px 16px; border-top: 1px solid var(--mg-line); }

  @media (min-width: 640px) {
    .veil { align-items: center; padding: 24px; }
    .box { max-width: 560px; border-radius: var(--mg-r); padding-bottom: 0; }
    .grab { display: none; }
    .bh { padding-top: 16px; }
    .two { grid-template-columns: 1fr 1fr; }
  }

  /* ————————————————————————————————————————————————————————— list ——— */
  .list { display: flex; flex-direction: column; gap: 12px; }
  .sh { padding: 15px 16px; }

  .ch { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; margin-bottom: 4px; }
  .ch h3 { margin: 0; font: 600 15px/1.25 var(--mg-font); letter-spacing: -0.01em; color: var(--mg-i); }

  .meta { margin: 0 0 11px; display: flex; flex-wrap: wrap; gap: 4px 12px;
          font: 400 12px/1.4 var(--mg-font); color: var(--mg-i3); }
  .meta .w { display: inline-flex; align-items: center; gap: 5px; min-width: 0; }

  .urlrow { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
  code {
    flex: 1 1 200px; min-width: 0; height: 32px; display: flex; align-items: center;
    padding: 0 12px; border-radius: 9999px; background: var(--mg-term);
    font: 11.5px/1 var(--mg-mono); color: var(--mg-i2);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }

  .chips, .sum { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
  .chips b, .sum b { color: var(--mg-i); font-weight: 600; }
  .sum { margin: 0 0 10px; }

  .acts { display: flex; flex-wrap: wrap; gap: 8px; }
  .drop { margin-left: auto; }

  /* —————————————————————————————————————————————————————— the picks ——— */
  .picks { margin-top: 13px; padding-top: 13px; border-top: 1px solid var(--mg-line); }
  .strip { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 4px; }

  .pick { flex: none; width: 168px; margin: 0; padding: 6px; border-radius: var(--mg-r-in); }
  .shot { position: relative; display: block; aspect-ratio: 16 / 9; overflow: hidden;
          border-radius: 10px; background: var(--mg-term); }
  .shot img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .noimg { position: absolute; inset: 0; display: grid; place-items: center;
           font: 400 10.5px/1 var(--mg-font); color: var(--mg-i3); }
  .heart {
    position: absolute; right: 5px; bottom: 5px; width: 22px; height: 22px; border-radius: 50%;
    display: grid; place-items: center; font-size: 11px; color: var(--mg-crit);
    background: rgba(8, 8, 10, 0.72); border: 1px solid rgba(242, 109, 100, 0.35);
  }

  figcaption { display: flex; flex-direction: column; gap: 2px; padding: 8px 4px 3px; min-width: 0; }
  figcaption b { font: 500 12px/1.3 var(--mg-font); color: var(--mg-i);
                 overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .by { font: 400 11px/1.3 var(--mg-font); color: var(--mg-i3); }
  figcaption p {
    margin: 3px 0 0; font: 400 11.5px/1.45 var(--mg-font); color: var(--mg-i2);
    display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3;
    -webkit-box-orient: vertical; overflow: hidden;
  }
  .none { margin: 0; font: 400 12.5px/1.5 var(--mg-font); color: var(--mg-i3); }

  @media (prefers-reduced-motion: reduce) {
    .veil { -webkit-backdrop-filter: none; backdrop-filter: none; }
  }
</style>
