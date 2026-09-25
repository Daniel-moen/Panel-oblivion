<script>
  /* The phone dock: a tab bar over the bottom edge, where a thumb already
     is. Icon over a 10px label, the active one in full ink, the rest quiet.
     Hidden from 1024px, where the Rail takes over.

     No props: it reads the route and the nav registry. Sections added with
     `addNav()` (shell.svelte.js) appear after the built-in six. */
  import { page } from '$app/state';
  import Icon from './Icon.svelte';
  import { slots, SECTIONS, inSection } from '$lib/shell.svelte.js';
  import { can } from '$lib/me.svelte.js';

  const ITEMS = $derived([...SECTIONS, ...slots.nav].filter((it) => !it.need || can(it.need)));
  const path = $derived(page.url.pathname);
  const active = $derived(ITEMS.reduce((best, it) => (inSection(it.href, path) ? it.href : best), null));
</script>

<nav class="dock" aria-label="Sections">
  <div class="bar mg-noscroll">
    {#each ITEMS as it (it.href)}
      <a href={it.href} class:on={it.href === active} aria-label={it.label}
         aria-current={it.href === active ? 'page' : undefined}>
        <Icon name={it.icon} size={22} stroke={it.href === active ? 2 : 1.7} />
        <span>{it.label}</span>
      </a>
    {/each}
  </div>
</nav>

<style>
  .dock {
    position: fixed; left: 0; right: 0; bottom: 0; z-index: 50;
    padding-bottom: var(--sab);
    background: rgba(24, 24, 27, 0.92);
    -webkit-backdrop-filter: blur(16px); backdrop-filter: blur(16px);
    border-top: 1px solid var(--mc-line);
    box-shadow: 0 -12px 40px -12px rgba(0, 0, 0, 0.7);
  }
  .bar {
    display: flex; align-items: stretch; gap: 2px;
    height: var(--mc-dock-h); padding: 6px 8px 4px;
    max-width: 640px; margin: 0 auto; overflow-x: auto;
  }
  a {
    position: relative; flex: 1 1 0; min-width: 52px;
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px;
    border-radius: 12px; color: var(--mc-ink3);
    transition: color var(--mc-t-fast), background var(--mc-t-fast), transform 120ms var(--mc-ease);
  }
  a span { font: 500 10px/1 var(--mc-font); letter-spacing: 0.01em; white-space: nowrap; }
  a:hover { color: var(--mc-ink2); }
  a.on { color: var(--mc-ink); }
  a:active { transform: scale(0.94); }

  @media (min-width: 1024px) { .dock { display: none; } }
  @media (prefers-reduced-motion: reduce) { a:active { transform: none; } }
</style>
