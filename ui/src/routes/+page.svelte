<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { app } from '$lib/state.svelte.js';

  let now = $state(new Date());
  let today = $state(null);
  let stats = $state(null);

  onMount(() => {
    const t = setInterval(() => (now = new Date()), 1000 * 15);
    api.panelToday().then((d) => (today = d)).catch(() => {});
    api.panelStats().then((d) => (stats = d)).catch(() => {});
    return () => clearInterval(t);
  });

  const hour = $derived(now.getHours());
  const greeting = $derived(hour < 5 ? 'Still up?' : hour < 12 ? 'Good Morning!' : hour < 17 ? 'Good Afternoon!' : 'Good Evening!');
  const hero = $derived(hour < 10 ? 'morning' : hour < 17 ? 'day' : 'dusk');
  const clock = $derived(now.toLocaleTimeString('en-ZA', { hour: '2-digit', minute: '2-digit' }));
  const date = $derived(now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' }));

  const hot = $derived(app.prospects.filter((r) => r.tier === 'hot').length);
  const dueCount = $derived(today ? today.overdue.length + today.due_today.length : null);

  const line = $derived.by(() => {
    if (!today) return 'Loading your day…';
    const od = today.overdue.length, dt = today.due_today.length, ex = today.expiring.length;
    if (od) return `${od} follow-up${od > 1 ? 's' : ''} overdue — start there.`;
    if (dt) return `${dt} follow-up${dt > 1 ? 's' : ''} to make today.`;
    if (ex) return `${ex} mandate${ex > 1 ? 's' : ''} expiring soon — time to renew.`;
    if (today.stale.length) return `${today.stale.length} lead${today.stale.length > 1 ? 's have' : ' has'} gone quiet. Worth a call.`;
    if (hot) return `All caught up. ${hot} hot prospect${hot > 1 ? 's' : ''} waiting in the engine.`;
    return 'All caught up. Enjoy the view.';
  });
</script>

<svelte:head><title>Oblivion</title></svelte:head>

<div class="home" style:background-image="url(/hero-{hero}.jpg)">
  <div class="veil"></div>

  <header>
    <div class="when">
      <span class="d">{date}</span>
      <span class="t">{clock}</span>
    </div>
    <div class="brand"><span class="mark"></span>Oblivion</div>
  </header>

  <main>
    <h1>{greeting}</h1>
    <p class="line">{line}</p>

    <div class="doors">
      <a class="door" href="/leads">
        <span class="k">Lead management</span>
        <span class="v">
          {#if today}
            {#if dueCount}<b class:alert={today.overdue.length}>{dueCount}</b> follow-up{dueCount === 1 ? '' : 's'} due
            {:else}<b>{today.counts.active}</b> active lead{today.counts.active === 1 ? '' : 's'}{/if}
            · {stats?.tracked ?? today.counts.tracked} tracked
          {:else}&nbsp;{/if}
        </span>
        <span class="go">Open →</span>
      </a>
      <a class="door" href="/prospects">
        <span class="k">Prospect engine</span>
        <span class="v">
          {#if app.loaded}
            <!-- the engine page opens on whichever book was last chosen, so
                 the door counts that book rather than always the sale one -->
            {#if app.dealType === 'rent'}
              <b>{app.stats?.rentals ?? app.prospects.length}</b> rental{(app.stats?.rentals ?? app.prospects.length) === 1 ? '' : 's'}
            {:else}
              <b class:hot={hot}>{hot}</b> hot · {app.stats?.sellable ?? '—'} sellable
            {/if}
            {#if app.status.running} · <i class="live"></i> crawling{/if}
          {:else}&nbsp;{/if}
        </span>
        <span class="go">Open →</span>
      </a>
      <!-- same tier as the two books: Z is a way into the stock, not a footnote -->
      <a class="door z" href="/agent">
        <span class="k"><span class="zm" aria-hidden="true">Z</span>Agent Z</span>
        <span class="v">Describe the buyer — it finds the property</span>
        <span class="go">Start a search →</span>
      </a>
    </div>
  </main>

  <footer>
    <a href="/map">Map</a><span>·</span><a href="/cma">CMA reports</a>
  </footer>
</div>

<style>
  .home { position: fixed; inset: 0; background-size: cover; background-position: center;
          color: #fff; display: flex; flex-direction: column; font-family: var(--font-display);
          animation: fade 0.8s ease both; }
  @keyframes fade { from { opacity: 0; } to { opacity: 1; } }
  .veil { position: absolute; inset: 0;
          background: linear-gradient(180deg, rgba(0,0,0,0.35) 0%, rgba(0,0,0,0.08) 35%, rgba(0,0,0,0.22) 70%, rgba(0,0,0,0.55) 100%); }
  header, main, footer { position: relative; z-index: 1; }

  header { display: flex; justify-content: space-between; align-items: flex-start;
           padding: 2.2rem 3rem; }
  .when { display: flex; flex-direction: column; text-shadow: 0 1px 12px rgba(0,0,0,0.4); }
  .d { font-size: 0.95rem; font-weight: 500; opacity: 0.95; }
  .t { font-size: 2.1rem; font-weight: 500; letter-spacing: -0.02em; line-height: 1.1; }
  .brand { display: flex; align-items: center; gap: 0.5rem; font-weight: 700; opacity: 0.9; }
  .mark { width: 10px; height: 10px; border-radius: 3px; background: #fff; }

  main { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
         text-align: center; padding: 0 1.5rem 4vh; }
  h1 { font-size: clamp(2.6rem, 6vw, 4.6rem); font-weight: 800; letter-spacing: -0.03em;
       text-shadow: 0 2px 24px rgba(0,0,0,0.45); margin: 0 0 0.4rem; }
  .line { font-size: clamp(1.05rem, 2vw, 1.5rem); font-weight: 400; opacity: 0.95;
          text-shadow: 0 1px 14px rgba(0,0,0,0.5); margin: 0 0 2.2rem; }

  .doors { display: flex; gap: 1rem; flex-wrap: wrap; justify-content: center; }
  .door { display: flex; flex-direction: column; align-items: flex-start; gap: 0.25rem;
          min-width: 260px; padding: 1.1rem 1.3rem; text-align: left; color: #fff;
          background: rgba(255,255,255,0.14); border: 1px solid rgba(255,255,255,0.28);
          border-radius: 16px; backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
          transition: background 0.2s, transform 0.2s, border-color 0.2s, box-shadow 0.2s; }
  .door:hover { background: rgba(255,255,255,0.24); transform: translateY(-2px); border-color: rgba(255,255,255,0.5); }
  .k { font-size: 1.05rem; font-weight: 700; }
  .v { font-size: 0.84rem; opacity: 0.9; display: flex; gap: 0.3rem; align-items: center; }
  .v b { font-weight: 800; }
  .v b.alert { color: #fca5a5; }
  .v b.hot { color: #fdba74; }
  .live { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #86efac;
          animation: pulse 1.4s infinite; }
  @keyframes pulse { 50% { opacity: 0.3; } }
  .go { margin-top: 0.5rem; font-size: 0.8rem; font-weight: 600; opacity: 0.8; }

  /* ——— the Agent Z door: the same monogram the app uses, on glass ——— */
  .door.z { background: linear-gradient(140deg, rgba(59, 130, 246, 0.34), rgba(29, 78, 216, 0.22));
            border-color: rgba(191, 219, 254, 0.45);
            box-shadow: 0 6px 22px rgba(29, 78, 216, 0.22); }
  .door.z:hover { background: linear-gradient(140deg, rgba(59, 130, 246, 0.46), rgba(29, 78, 216, 0.3));
                  border-color: rgba(219, 234, 254, 0.7);
                  box-shadow: 0 10px 30px rgba(29, 78, 216, 0.34); }
  .door.z .k { display: flex; align-items: center; gap: 0.5rem; }
  .zm { display: inline-flex; align-items: center; justify-content: center;
        width: 24px; height: 24px; border-radius: 8px; flex: none;
        font-size: 0.86rem; font-weight: 800; letter-spacing: -0.02em; line-height: 1;
        color: #fff;
        background: linear-gradient(140deg, #60a5fa 0%, #1d4ed8 55%, #60a5fa 100%);
        background-size: 220% 220%;
        box-shadow: 0 2px 10px rgba(29, 78, 216, 0.45);
        animation: drift 9s ease-in-out infinite; }
  @keyframes drift { 50% { background-position: 100% 50%; } }
  .door.z:hover .zm { transform: scale(1.06); }
  .zm { transition: transform 0.2s; }

  footer { display: flex; gap: 0.6rem; justify-content: center; padding: 1.6rem; font-size: 0.82rem; opacity: 0.75; }
  footer a { color: #fff; }
  footer a:hover { text-decoration: underline; }

  @media (max-width: 640px) {
    header { padding: 1.4rem 1.4rem; }
    .door { min-width: 0; width: 100%; }
  }

  @media (prefers-reduced-motion: reduce) {
    .home, .zm, .live { animation: none; }
    .door:hover { transform: none; }
    .door.z:hover .zm { transform: none; }
  }
</style>
