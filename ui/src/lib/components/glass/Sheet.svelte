<script>
  /* One sheet, two shapes.

     From 640px up it is a centred dialog of strong glass; below that it rises
     from the bottom edge with a grab handle you can throw downwards, because
     that is where a thumb is. Both sit on a scrim that BLURS the scene rather
     than only dimming it — otherwise Home's huge headline stays legible
     straight through the dialog's glass.

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

  /* Open: lock the page behind, take focus, and keep Tab inside — a dialog
     you can tab out of is a dialog you can lose. */
  $effect(() => {
    if (!open) return;
    drag = 0;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    tick().then(() => {
      const first = box?.querySelector('[autofocus], input, textarea, select, button, a[href]');
      (first || box)?.focus?.();
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
    };
  });

  /* ——— the phone throw: only the grab handle starts it, or every scroll
         inside the sheet would try to fling it off the screen ——— */
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
    <div class="mg-scrim" class:bottom={!wide} onclick={() => onclose?.()} role="presentation">
      <div class="box mg-glass-strong mg-dialog" class:phone={!wide}
           bind:this={box} role="dialog" aria-modal="true" aria-label={title || 'Dialog'}
           tabindex="-1"
           style:max-width={wide ? max + 'px' : null}
           style:transform={drag ? `translateY(${drag}px)` : null}
           style:transition={held == null ? 'transform 0.24s cubic-bezier(0.2,0.8,0.2,1)' : 'none'}
           onclick={(e) => e.stopPropagation()}>
        {#if !wide}
          <div class="grab" onpointerdown={grabStart} onpointermove={grabMove}
               onpointerup={grabEnd} onpointercancel={grabEnd} role="presentation">
            <i></i>
          </div>
        {/if}

        {#if title}
          <div class="head">
            <h2>{title}</h2>
            <button type="button" class="mg-btn secondary icon sm" onclick={() => onclose?.()}
                    aria-label="Close" title="Close">
              <Icon name="close" size={15} />
            </button>
          </div>
        {/if}

        <div class="body">{@render children?.()}</div>

        {#if footer}<div class="foot">{@render footer()}</div>{/if}
      </div>
    </div>
  </div>
{/if}

<style>
  /* .mg-scrim / .mg-dialog come from glass.css; what is here is the two
     shapes and the way in. */
  .mg-scrim { align-items: center; padding: 24px; animation: veil 0.2s ease both; }
  .mg-scrim.bottom { align-items: flex-end; padding: 0; }
  @keyframes veil { from { opacity: 0; } to { opacity: 1; } }

  .box {
    width: 100%; max-height: 92dvh; outline: none;
    animation: rise 0.28s cubic-bezier(0.2, 0.8, 0.2, 1) both;
  }
  @keyframes rise { from { opacity: 0; transform: translateY(8px) scale(0.97); } to { opacity: 1; transform: none; } }

  .box.phone {
    max-width: none; max-height: 92dvh;
    border-radius: var(--mg-r) var(--mg-r) 0 0; border-bottom: 0;
    padding-bottom: var(--mg-sab, 0px);
    animation: up 0.3s cubic-bezier(0.2, 0.8, 0.2, 1) both;
  }
  @keyframes up { from { transform: translateY(100%); } to { transform: none; } }

  @media (prefers-reduced-motion: reduce) {
    .mg-scrim, .box, .box.phone { animation: none; }
  }
</style>
