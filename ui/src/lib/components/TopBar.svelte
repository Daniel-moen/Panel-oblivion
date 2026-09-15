<script>
  import { page } from '$app/state';
  import { app } from '$lib/state.svelte.js';

  const path = $derived(page.url.pathname);
  const s = $derived(app.status);

  let theme = $state(document.documentElement.dataset.theme || 'dark');
  function flipTheme() {
    theme = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('oblivion-theme', theme);
  }
</script>

<header>
  <a class="logo" href="/">
    <span class="mark"></span>
    <span class="name">Oblivion</span>
    <span class="sub">Prospect Engine</span>
  </a>

  <nav>
    <a href="/prospects" class:on={path.startsWith('/prospects')}>Prospects</a>
    <a href="/map" class:on={path.startsWith('/map')}>Map</a>
    <a href="/leads" class="sw">Lead management →</a>
    <a href="/cma">CMA reports</a>
  </nav>

  <div class="right">
    {#if s.ai_ok != null}
      <span class="ai" class:ok={s.ai_ok} title={s.ai_ok ? 'AI scoring ready' : s.ai_reason}>
        <i></i>{s.ai_ok ? 'AI ready' : 'AI off'}
      </span>
    {/if}
    {#if s.running}
      <button class="job" onclick={() => (app.logOpen = !app.logOpen)} title="show crawl activity">
        <span class="spin"></span>
        {s.phase}{s.total ? ` · ${s.done}/${s.total}` : ''}
      </button>
    {/if}
    <button class="theme" onclick={flipTheme}
      title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>
      {theme === 'dark' ? '☀' : '☾'}
    </button>
    <button class="btn primary" onclick={() => (app.runOpen = true)}>+ New crawl</button>
  </div>
</header>

<style>
  header {
    position: sticky; top: 0; z-index: 30;
    display: flex; align-items: center; gap: 1.8rem;
    height: 60px; padding: 0 clamp(1rem, 3vw, 2rem);
    background: var(--bar); backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--line);
  }

  .theme { width: 32px; height: 32px; border-radius: var(--r-sm);
           border: 1px solid var(--line-2); background: var(--bg-2);
           color: var(--ink-2); font-size: 0.95rem; line-height: 1;
           transition: color 0.15s, border-color 0.15s; }
  .theme:hover { color: var(--ink); border-color: var(--line-3); }

  .logo { display: flex; align-items: baseline; gap: 0.55rem; white-space: nowrap; }
  .mark { width: 10px; height: 10px; border-radius: 3px;
          background: var(--accent); align-self: center; }
  .name { font-size: 1.02rem; font-weight: 800; letter-spacing: -0.01em; color: var(--ink); }
  .sub { font-size: 0.72rem; font-weight: 500; color: var(--ink-3); }

  nav { display: flex; gap: 0.25rem; flex: 1; }
  nav a {
    color: var(--ink-2); font-size: 0.86rem; font-weight: 500;
    padding: 0.4rem 0.85rem; border-radius: var(--r-sm);
    transition: color 0.15s, background 0.15s;
  }
  nav a:hover { color: var(--ink); background: var(--bg-3); }
  nav a.sw { margin-left: auto; color: var(--ink-3); }
  nav a.on { color: var(--accent-2); background: var(--accent-soft); font-weight: 600; }

  .right { display: flex; align-items: center; gap: 0.8rem; }

  .ai { display: inline-flex; align-items: center; gap: 0.4rem;
        font-size: 0.76rem; font-weight: 500; color: var(--ink-3); }
  .ai i { width: 7px; height: 7px; border-radius: 50%; background: var(--ink-3); }
  .ai.ok { color: var(--open); }
  .ai.ok i { background: var(--open); }

  .job { display: inline-flex; align-items: center; gap: 0.5rem;
         background: var(--accent-soft); border: 1px solid var(--accent-line);
         color: var(--accent-2); border-radius: 999px; padding: 0.3rem 0.85rem;
         font-size: 0.76rem; font-weight: 600; }

  @media (max-width: 760px) {
    header { gap: 1rem; }
    .sub, .ai { display: none; }
  }
</style>
