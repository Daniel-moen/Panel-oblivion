<script>
  /* Frosted glass without a live blur.

     A pane that is `backdrop-filter`ed re-blurs the photograph under it on
     every frame the photo drifts or the pane moves — on an iPad the single
     most expensive thing on screen. Frost fills its parent instead with a
     FIXED layer holding the hour's photo already blurred (the `-frost` twin,
     $lib/hero.js), cut to the parent's rounded shape by a clip-path — which,
     unlike overflow, clips fixed descendants too. Scrolling moves the clip,
     never the pixels, so nothing is re-blurred per frame. (The photo's slow
     1.0→1.06 drift is deliberately not copied: under a 28 px blur and the
     tint the difference cannot be seen, and a still layer is never redrawn.)

     Drop it as the FIRST child of a positioned element; it paints under that
     element's content. The element keeps its own border, radius and shadow;
     pass the radius (and the tint) through CSS variables:
       --frost-r      the clip's corner radii (default var(--mc-r-lg))
       --frost-tint   the glass colour over the photo (default glass-strong)

     A custom backdrop (the panel's `mc.backdrop` url) has no twin: that photo
     is blurred by a CSS filter on this layer, which never moves, so it is
     rasterised once. */
  import { chrome } from '$lib/shell.svelte.js';
</script>

<div class="mg-frostclip" aria-hidden="true">
  <div class="mg-frost" class:live={chrome.frostLive} style:background-image={chrome.frost ? `url(${chrome.frost})` : null}></div>
</div>
