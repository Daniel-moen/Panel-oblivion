<script>
  /* The floating dock — the app's navigation at EVERY width.

     A copy of Mission Control's dock (widget-claude/remote/app,
     src/shell/Dock.jsx): one pill of glass floating 14px above the bottom
     edge (plus the safe area), centred, the sections as pills inside it,
     a hairline divider, then the raised round primary (glass/PrimaryButton).
     From 1024px one secondary pill follows — CMA reports, the one thing
     that lives outside this app. There is no sidebar any more: a phone, an
     iPad either way up and a desktop all navigate from here.

     Geometry, as the reference: items 44px tall, 13px / 500, 14px sides
     (16px from 640), 18px icons, 4px apart, 6px of glass round them. Labels
     show only where all of them fit on one row (see the fit note in the
     styles); below that the icon carries the section and the label is the
     tooltip and the screen-reader name.

     The glide: ONE highlight (white 14 %) slides between items. React does
     that with a shared layoutId; here the active item is measured and an
     absolutely placed pill's transform + width transition on spring.snappy
     (as a CSS linear() easing — lib/motion.js springCss), the same motion
     glass/Seg.svelte uses. Parked until the first measurement, so it never
     flashes at the left edge; a ResizeObserver re-measures when labels
     appear or a font lands late. Reduced motion: it jumps.

     Badges are amber — something waiting on you — and pop in on
     spring.snappy. Only Leads carries one: follow-ups overdue + due today,
     read from the Today payload the Leads section and Home already fetch
     ($lib/leads.svelte.js). No chat badge (the header's chat button has its
     own), and nothing fetched here.

     Z-order: 60 — above the page, the strip and the map, so nothing's
     blur ever samples it.

     Quiet (`chrome.quiet`, set by Home after 3 s idle): the pill slides below
     the edge and fades — transform and opacity only, never the blur — then
     leaves the tab order. A focus inside brings it straight back. Reduced
     motion keeps it put.

     No props: it reads the route and the nav registry (SECTIONS + whatever
     `addNav()` added — the team feature's Online), minus what the account
     may not open. */
  import { onMount, untrack } from 'svelte';
  import { page } from '$app/state';
  import Icon from './Icon.svelte';
  import PrimaryButton from './PrimaryButton.svelte';
  import { slots, chrome, SECTIONS, inSection } from '$lib/shell.svelte.js';
  import { leads } from '$lib/leads.svelte.js';
  import { can } from '$lib/me.svelte.js';
  import { play, pressable, spring, springCss, springMs, prefersReduced } from '$lib/motion.js';

  const ITEMS = $derived([...SECTIONS, ...slots.nav].filter((it) => !it.need || can(it.need)));
  const path = $derived(page.url.pathname);
  const active = $derived(ITEMS.reduce((best, it) => (inSection(it.href, path) ? it.href : best), null));

  /* Follow-ups that need you today: overdue + due today. null until one of
     the sections that fetch Today has done so. */
  const due = $derived(leads.today ? (leads.today.overdue?.length || 0) + (leads.today.due_today?.length || 0) : 0);
  const badgeOf = (href) => (href === '/leads' ? due : 0);

  const ENTER = { initial: { opacity: 0, y: 18 }, animate: { opacity: 1, y: 0 }, transition: spring.smooth };
  const POP = { initial: { scale: 0.6, opacity: 0 }, animate: { scale: 1, opacity: 1 }, transition: spring.snappy };
  const GLIDE = springCss(spring.snappy);
  const SETTLE = springCss(spring.smooth);

  /* Mounted a frame late so the enter transition plays once, on first paint
     (the SPA's first render does not run intros). */
  let shown = $state(false);
  onMount(() => { shown = true; });

  let nav = $state(null);
  const els = {};
  let hl = $state({ x: 0, w: 0, ready: false, jump: true });

  function measure() {
    const el = active ? els[active] : null;
    if (!el || !el.offsetWidth) { hl = { ...hl, ready: false, jump: true }; return; }
    /* Labels are not whole pixels wide, so offsetLeft/offsetWidth (integers)
       would leave the pill a fraction off. The width is the computed (layout)
       width; the position is the item's CENTRE against the nav's padding
       edge — the highlight's containing block — which neither a press's
       scale (about the centre) nor a transform on the nav (its entrance,
       the quiet slide) can move. x is rounded to the pixel, so the
       sub-pixel re-snap after a scrollbar comes or goes is not a move. */
    const a = el.getBoundingClientRect(), n = nav.getBoundingClientRect();
    const w = parseFloat(getComputedStyle(el).width) || el.offsetWidth;
    const x = Math.round(a.left + a.width / 2 - n.left - nav.clientLeft - w / 2);
    if (hl.ready && hl.x === x && Math.abs(hl.w - w) < 0.5) return;
    /* From parked, the pill appears in place; after that it glides. */
    const jump = !hl.ready;
    hl = { x, w, ready: true, jump };
    if (jump) requestAnimationFrame(() => requestAnimationFrame(() => { hl = { ...hl, jump: false }; }));
  }

  $effect(() => {
    active;
    ITEMS.length;
    due;
    if (nav) untrack(measure);
  });

  $effect(() => {
    if (!nav || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => untrack(measure));
    ro.observe(nav);
    for (const el of nav.querySelectorAll('a[data-dock-item]')) ro.observe(el);
    document.fonts?.ready?.then(() => measure());
    return () => ro.disconnect();
  });

  const still = typeof window !== 'undefined' && prefersReduced();
</script>

<div class="wrap">
  {#if shown}
    <nav class="dock" class:quiet={chrome.quiet} class:held={chrome.modal > 0} inert={chrome.modal > 0}
         bind:this={nav} data-testid="dock" aria-label="Sections"
         style:--glide={still ? 'none' : GLIDE} style:--settle={still ? 'none' : SETTLE} style:--settle-ms="{springMs(spring.smooth)}ms" in:play={ENTER}>
      <span class="hl" class:ready={hl.ready} class:jump={hl.jump} data-testid="dock-highlight" aria-hidden="true"
            style:transform="translateX({hl.x}px)" style:width="{hl.w}px"></span>

      {#each ITEMS as it (it.href)}
        {@const on = it.href === active}
        {@const n = badgeOf(it.href)}
        <a href={it.href} class="item" class:on bind:this={els[it.href]} use:pressable
           data-dock-item={it.href} aria-current={on ? 'page' : undefined} title={it.label}
           aria-label={n ? `${it.label}, ${n} due` : it.label}>
          <span class="ic">
            <Icon name={it.icon} size={18} />
            {#if n > 0}
              {#key n > 9 ? '9+' : n}
                <i class="badge mg-tnum" aria-hidden="true" in:play={POP}>{n > 9 ? '9+' : n}</i>
              {/key}
            {/if}
          </span>
          <span class="lb">{it.label}</span>
        </a>
      {/each}

      <span class="div" aria-hidden="true"></span>

      <PrimaryButton />

      <a class="cma" href="/cma" data-sveltekit-reload use:pressable data-testid="dock-cma" title="CMA reports (opens the CMA pages)">
        <Icon name="list" size={16} />
        CMA reports
      </a>
    </nav>
  {/if}
</div>

<style>
  .wrap {
    position: fixed; left: 0; right: 0; bottom: 0; z-index: 60;
    display: flex; justify-content: center;
    padding: 0 12px calc(var(--sab) + 14px);
    pointer-events: none;
  }

  /* The reference's `.glass`, on a pill: graphite at 52 % over the photo, a
     12 % hairline, shadow-3 and the lit top edge, blur 28 saturate 150 %.
     The ONE blurred rectangle the dock costs. */
  .dock {
    position: relative; pointer-events: auto;
    display: flex; align-items: center; gap: 4px; padding: 6px;
    max-width: 100%;
    border-radius: 9999px;
    background: var(--mc-glass);
    border: 1px solid var(--mc-glass-line);
    box-shadow: var(--mc-sh-3), var(--mc-lit);
    -webkit-backdrop-filter: blur(var(--mc-blur)) saturate(150%);
    backdrop-filter: blur(var(--mc-blur)) saturate(150%);
    transition: transform var(--settle), opacity var(--settle);
  }
  /* hidden = also out of the screen-reader and tab order (after the slide);
     a focus inside brings it straight back */
  .dock.quiet {
    transform: translateY(calc(100% + 14px + var(--sab))); opacity: 0; pointer-events: none; visibility: hidden;
    transition: transform var(--settle), opacity var(--settle), visibility 0s linear var(--settle-ms, 505ms);
  }
  /* A modal sheet or drawer is open (chrome.modal): the page behind is out
     of reach, so the dock is too — inert, and dimmed so it reads that way. */
  .dock.held { opacity: 0.45; }

  /* The one highlight: white 14 %, a pill the height of an item. */
  .hl {
    position: absolute; left: 0; top: 6px; height: 44px; width: 0;
    border-radius: 9999px; background: var(--mc-glass-on);
    opacity: 0; pointer-events: none;
    transition: transform var(--glide), width var(--glide), opacity 150ms;
    will-change: transform, width;
  }
  .hl.ready { opacity: 1; }
  .hl.jump { transition: opacity 150ms; }

  .item {
    position: relative; z-index: 1; flex: none;
    display: flex; align-items: center; gap: 8px;
    height: 44px; padding: 0 14px; border-radius: 9999px;
    font: 500 13px/1 var(--mc-font); white-space: nowrap;
    color: var(--mc-ink2);
    transition: color var(--mc-t-fast), transform var(--mg-spring-snappy);
  }
  .item:hover, .item.on { color: var(--mc-ink); }
  .ic { position: relative; display: flex; }
  .lb { display: none; }

  /* Amber = something is waiting on you, the same meaning it has everywhere. */
  .badge {
    position: absolute; right: -8px; top: -6px;
    min-width: 16px; height: 16px; padding: 0 4px; border-radius: 9999px;
    display: grid; place-items: center;
    background: var(--mc-warn); color: #241a02;
    font: 700 9.5px/1 var(--mc-font); font-style: normal; font-variant-numeric: tabular-nums;
  }

  .div { flex: none; width: 1px; height: 24px; margin: 0 4px; background: rgba(255, 255, 255, 0.15); }

  /* The reference's secondary Button (glass-soft pill), desktop only. */
  .cma {
    display: none; flex: none; align-items: center; gap: 8px;
    height: 44px; padding: 0 18px; margin-left: 4px; border-radius: 9999px;
    background: var(--mc-glass-soft); border: 1px solid var(--mc-glass-line);
    color: var(--mc-ink); font: 500 13.5px/1 var(--mc-font); letter-spacing: -0.01em; white-space: nowrap;
    transition: background var(--mc-t-fast), border-color var(--mc-t-fast), transform var(--mg-spring-snappy);
  }
  .cma:hover { background: var(--mc-glass-hover); border-color: var(--mc-glass-line2); }

  /* FIT. Seven sections + divider + primary must sit on one row at every
     width. Icon-only, an item is 18px + its two sides; the fixed cost round
     them (6px of glass each side, 2px of hairline, eight 4px gaps, the
     divider and its margins, the 44px primary) is 99px, inside 12px screen
     gutters. At the reference's 14px sides that is 421px — too wide for a
     390px phone — so below 400px ONLY the items' sides narrow (items stay
     44px tall): 10px → 365px of pill in 366px at 390; 9px at 375; 7.5px at
     360. Labels (the reference shows them from 640) need ~800px with all
     seven, so they appear from 900; from 1024 the CMA pill joins them. */
  @media (max-width: 399.98px) { .item { padding: 0 10px; } }
  @media (max-width: 375.98px) { .item { padding: 0 9px; } }
  @media (max-width: 360.98px) { .item { padding: 0 7.5px; } }
  @media (min-width: 640px) { .item { padding: 0 16px; } }
  @media (min-width: 900px) { .lb { display: inline; } }
  @media (min-width: 1024px) { .cma { display: inline-flex; } }

  @media (prefers-reduced-motion: reduce) {
    .dock, .dock.quiet { transform: none; opacity: 1; pointer-events: auto; visibility: visible; transition: none; }
    .hl { transition: none; }
  }
</style>
