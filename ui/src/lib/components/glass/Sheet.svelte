<script>
  /* One sheet, two shapes.

     From 640px up it is a centred dialog on a raised plane; below that it
     rises from the bottom edge with a grab handle you can throw downwards,
     because that is where a thumb is. Both sit on a dimming scrim.

     Motion (lib/motion.js, Mission Control's vocabulary): the scrim is
     `fadeIn`; the dialog is `scaleIn` and the phone sheet `sheetUp`, both on
     spring.smooth — which one is decided when the sheet opens. Transform and
     opacity only, both directions, so closing is as smooth as opening.
     Reduced motion collapses all of it to a fade (play() does that).

     The floating dock (z-60) stays above every sheet: the phone sheet runs
     to the bottom edge but pads its content by --mc-dock-clear, and the
     dialog is centred in the space above the dock.

     It renders through a portal: the node is moved to the end of <body> on
     mount, so no ancestor's `overflow`, `transform` or stacking context can
     clip it. That is also why it carries `.mg-portal` — outside `.mg-scene`
     it has to restate the font and ink it would otherwise inherit.

     Props:
       open      boolean — mount and show the sheet
       title     optional; with none, no header row is drawn and the content
                 owns its own (a chromeless sheet)
       size      'sm' 420 · 'md' 560 (default) · 'lg' 760 · 'full' 1100 —
                 the max width of the desktop dialog; ignored on a phone
       onclose   called by Esc, the scrim, the ✕ and a downward throw. The
                 sheet never closes itself: flip your own `open` in here
       children  snippet — the body (scrolls)
       footer    optional snippet — a pinned action row under the body

     Esc, the focus trap and the body scroll lock all live here, so a page
     that opens a Sheet has nothing to remember. */
  import { tick } from 'svelte';
  import Icon from './Icon.svelte';
  import { play, fadeIn, scaleIn, sheetUp, spring, springCss } from '$lib/motion.js';
  import { holdModal } from '$lib/shell.svelte.js';

  let { open = false, title = '', size = 'md', onclose, children, footer } = $props();

  const MAXW = { sm: 420, md: 560, lg: 760, full: 1100 };
  const max = $derived(MAXW[size] || MAXW.md);

  let box = $state(null);
  let wide = $state(true);
  let drag = $state(0); // px the phone sheet has been pulled down

  /* Move the node to <body> so nothing upstream can clip it. */
  function portal(node) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }

  $effect(() => {
    if (typeof matchMedia === 'undefined') return;
    const mq = matchMedia('(min-width: 640px)');
    const sync = () => (wide = mq.matches);
    sync();
    mq.addEventListener('change', sync);
    return () => mq.removeEventListener('change', sync);
  });

  /* Open: lock the page behind (the dock too), take focus, keep Tab inside,
     and hand focus back to whatever opened it on the way out. */
  $effect(() => {
    if (!open) return;
    drag = 0;
    const opener = document.activeElement;
    const release = holdModal();
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    tick().then(() => {
      const first = box?.querySelector('[autofocus], input, textarea, select, button, a[href]');
      (first || box)?.focus?.({ preventScroll: true });
    });

    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onclose?.();
        return;
      }
      if (e.key !== 'Tab' || !box) return;
      const f = box.querySelectorAll(
        'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
      );
      if (!f.length) return;
      const first = f[0];
      const last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    window.addEventListener('keydown', onKey, true);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener('keydown', onKey, true);
      release();
      /* after the flush: the opener may sit in the dock, which is inert
         until the release lands, and an inert element refuses focus */
      tick().then(() => {
        if (opener?.isConnected && opener !== document.body) opener.focus?.({ preventScroll: true });
      });
    };
  });

  /* ——— the phone throw: only the grab handle starts it ——— */
  let from = 0;
  let held = $state(null);

  function grabStart(e) {
    if (wide) return;
    from = e.clientY;
    held = e.currentTarget;
    held.setPointerCapture?.(e.pointerId);
  }
  function grabMove(e) {
    if (held == null) return;
    drag = Math.max(0, e.clientY - from);
  }
  function grabEnd() {
    if (held == null) return;
    held = null;
    if (drag > 120) onclose?.();
    drag = 0;
  }
</script>

{#if open}
  <div class="mg-portal" use:portal>
    <div class="mg-scrim" class:bottom={!wide} onclick={() => onclose?.()} role="presentation"
         transition:play|global={fadeIn}></div>
    <div class="host" class:bottom={!wide} role="presentation">
      {#if wide}
        <div class="box mg-dialog" bind:this={box} role="dialog" aria-modal="true"
             aria-label={title || 'Dialog'} tabindex="-1" style:max-width="{max}px"
             transition:play|global={scaleIn}>
          {#if title}
            <div class="head">
              <h2>{title}</h2>
              <button type="button" class="mg-btn secondary icon sm" onclick={() => onclose?.()}
                      aria-label="Close" title="Close (Esc)"><Icon name="close" size={15} /></button>
            </div>
          {/if}
          <div class="body">{@render children?.()}</div>
          {#if footer}<div class="foot">{@render footer()}</div>{/if}
        </div>
      {:else}
        <div class="box phone mg-dialog" bind:this={box} role="dialog" aria-modal="true"
             aria-label={title || 'Dialog'} tabindex="-1"
             style:transform={drag ? `translate3d(0,${drag}px,0)` : null}
             style:transition={held == null ? `transform ${springCss(spring.smooth)}` : 'none'}
             transition:play|global={sheetUp}>
          <div class="grab" onpointerdown={grabStart} onpointermove={grabMove}
               onpointerup={grabEnd} onpointercancel={grabEnd} role="presentation"><i></i></div>
          {#if title}
            <div class="head">
              <h2>{title}</h2>
              <button type="button" class="mg-btn secondary icon sm" onclick={() => onclose?.()}
                      aria-label="Close" title="Close"><Icon name="close" size={15} /></button>
            </div>
          {/if}
          <div class="body">{@render children?.()}</div>
          {#if footer}<div class="foot">{@render footer()}</div>{/if}
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  /* .mg-scrim / .mg-dialog come from mc.css; what is here is the two shapes. */
  .mg-scrim { z-index: 55; }
  .host {
    position: fixed; inset: 0; z-index: 56; display: flex; justify-content: center; align-items: center;
    padding: 24px 24px var(--mc-dock-clear); pointer-events: none;
  }
  .host.bottom { align-items: flex-end; padding: 0; }
  .host > .box { pointer-events: auto; }

  .box {
    width: 100%; max-height: min(92dvh, calc(100dvh - 24px - var(--mc-dock-clear))); outline: none;
    background: var(--mc-glass-strong); border: 1px solid var(--mc-glass-line);
    border-radius: var(--mc-r-lg); box-shadow: var(--mc-sh-3), var(--mc-lit);
    -webkit-backdrop-filter: blur(var(--mc-blur)) saturate(150%); backdrop-filter: blur(var(--mc-blur)) saturate(150%);
    will-change: transform, opacity;
  }
  .box.phone {
    max-width: none; max-height: 92dvh;
    border-radius: var(--mc-r-lg) var(--mc-r-lg) 0 0; border-bottom: 0;
    /* runs under the dock; its content stops above it */
    padding-bottom: var(--mc-dock-clear);
  }
</style>
