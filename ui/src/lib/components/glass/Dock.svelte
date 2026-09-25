<script>
  /* The phone dock: a tab bar over the bottom edge, where a thumb already
     is. Icon over a 10px label, the active one in full ink, the rest quiet.
     Hidden from 1024px, where the Rail takes over.

     No props: it reads the route and the nav registry. Sections added with
     `addNav()` (shell.svelte.js) appear after the built-in six.

     Quiet (`chrome.quiet`, set by Home after a few idle seconds): it slides
     below the edge — transform and opacity only, never the blur — and takes
     no taps while hidden. Reduced motion keeps it put. */
  import { page } from '$app/state';
  import Icon from './Icon.svelte';
  import { slots, chrome, SECTIONS, inSection } from '$lib/shell.svelte.js';
  import { can } from '$lib/me.svelte.js';

  const ITEMS = $derived([...SECTIONS, ...slots.nav].filter((it) => !it.need || can(it.need)));
  const path = $derived(page.url.pathname);
  const active = $derived(ITEMS.reduce((best, it) => (inSection(it.href, path) ? it.href : best), null));
</script>

<nav class="dock" class:quiet={chrome.quiet} aria-label="Sections">
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
    background: var(--mc-glass-strong);
    -webkit-backdrop-filter: blur(var(--mc-blur)) saturate(150%); backdrop-filter: blur(var(--mc-blur)) saturate(150%);
    border-top: 1px solid var(--mc-glass-line);
    box-shadow: 0 -12px 40px -12px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.07);
    transition: transform 260ms var(--mc-ease), opacity 260ms var(--mc-ease);
  }
  /* hidden = also out of the screen-reader and tab order (after the slide);
     a focus inside brings it straight back */
  .dock.quiet { transform: translateY(calc(100% + 8px)); opacity: 0; pointer-events: none; visibility: hidden;
    transition: transform 260ms var(--mc-ease), opacity 260ms var(--mc-ease), visibility 0s linear 260ms; }
  .dock.quiet:focus-within { transform: none; opacity: 1; pointer-events: auto; visibility: visible; transition: none; }
  .bar {
    display: flex; align-items: stretch; gap: 4px;
    height: var(--mc-dock-h); padding: 7px 8px 5px;
    max-width: 640px; margin: 0 auto; overflow-x: auto;
  }
  a {
    position: relative; flex: 1 1 0; min-width: 52px;
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px;
    border-radius: 14px; color: var(--mc-ink3);
    transition: color var(--mc-t-fast), background var(--mc-t-fast), transform 120ms var(--mc-ease);
  }
  a span { font: 500 10px/1 var(--mc-font); letter-spacing: 0.01em; white-space: nowrap; }
  a:hover { color: var(--mc-ink2); }
  a.on { color: var(--mc-ink); background: var(--mc-glass-on); }
  a:active { transform: scale(0.94); }

  @media (min-width: 1024px) { .dock { display: none; } }
  @media (prefers-reduced-motion: reduce) {
    a:active { transform: none; }
    .dock, .dock.quiet { transform: none; opacity: 1; pointer-events: auto; visibility: visible; transition: none; }
  }
</style>
