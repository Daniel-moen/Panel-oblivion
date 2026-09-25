<script>
  /* What the engine has been doing — Mission Control's ActivityFeed. One
     timestamped line per event, newest first: new listings landing, price
     cuts, likely sales, relists, scoring passes, lead moves and crawl runs
     (all assembled server-side by /api/home). A row with an href is a link. */
  import Icon from './glass/Icon.svelte';
  import Skeleton from './Skeleton.svelte';

  let { events = [], loading = false, max = 40 } = $props();

  const rows = $derived((events || []).slice(0, max));

  const pad = (n) => String(n).padStart(2, '0');
  const DAY = 86400000;
  function clockOf(t) {
    const d = new Date(t);
    if (isNaN(d)) return '';
    const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    const start = new Date(); start.setHours(0, 0, 0, 0);
    const diff = start.getTime() - new Date(d).setHours(0, 0, 0, 0);
    const days = Math.round(diff / DAY);
    if (days <= 0) return hm;
    if (days === 1) return `Yest ${hm}`;
    if (days <= 6) return `${d.toLocaleDateString('en-GB', { weekday: 'short' })} ${hm}`;
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  }
  const loud = (tone) => tone === 'live' || tone === 'ok' || tone === 'warn' || tone === 'crit';
  const dotOf = (tone) => (tone === 'live' ? 'ok' : tone);
</script>

<section class="mg-section feed">
  <div class="head">
    <h2>Activity</h2>
    {#if !loading || rows.length}<span class="mg-count">{rows.length} event{rows.length === 1 ? '' : 's'}</span>{/if}
  </div>

  {#if loading && !rows.length}
    <div class="body-rows">
      {#each Array(5) as _, i (i)}
        <div class="ev sk">
          <Skeleton h="11px" w="34px" delay={i * 50} />
          <Skeleton h="12px" w="58px" delay={i * 50 + 20} />
          <span class="text"><Skeleton h="12px" w="{70 - i * 7}%" delay={i * 50 + 40} /></span>
        </div>
      {/each}
    </div>
  {:else if !rows.length}
    <div class="mg-empty">
      <span class="ic"><Icon name="bolt" size={20} /></span>
      <h3>Nothing yet</h3>
      <p>Events appear here as the engine works.</p>
    </div>
  {:else}
    <div class="body-rows scroll mg-noscroll">
      {#each rows as e, i (e.t + e.kind + i)}
        <svelte:element this={e.href ? 'a' : 'div'} href={e.href || null} class="ev" class:link={!!e.href} title={e.text}>
          <span class="clock">{clockOf(e.t)}</span>
          <span class="who" class:loud={loud(e.tone)}>
            {#if e.tone}<span class="mg-dot sm {dotOf(e.tone)}"></span>{/if}<span class="wn">{e.who || 'Engine'}</span>
          </span>
          <span class="text">{e.text}</span>
        </svelte:element>
      {/each}
    </div>
  {/if}
</section>

<style>
  .scroll { max-height: 320px; overflow-y: auto; }
  .ev {
    display: flex; align-items: baseline; gap: 12px; min-height: 40px; width: 100%;
    padding: 8px 16px; border-bottom: 1px solid var(--mc-line-soft); color: inherit;
    transition: background var(--mc-t-fast);
  }
  @media (min-width: 640px) { .ev { padding: 8px 20px; } }
  .ev:last-child { border-bottom: 0; }
  .ev.sk { align-items: center; }
  .ev.link { cursor: pointer; }
  .ev.link:hover { background: rgba(255, 255, 255, 0.07); }
  .ev.link:active { background: rgba(255, 255, 255, 0.1); }

  .clock { flex: none; min-width: 34px; font: 400 11px/1.4 var(--mc-mono); font-variant-numeric: tabular-nums; color: var(--mc-ink3); }
  .who {
    flex: none; max-width: 34%; display: inline-flex; align-items: baseline; gap: 6px; min-width: 0;
    font: 500 12px/1.4 var(--mc-font); color: var(--mc-ink3);
  }
  .who.loud { color: var(--mc-ink); }
  .who .mg-dot { align-self: center; }
  .wn { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .text {
    flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    font: 400 12.5px/1.4 var(--mc-font); color: var(--mc-ink2);
  }
  .feed .mg-empty { padding: 32px 24px; }
</style>
