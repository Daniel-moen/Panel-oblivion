<script>
  /* Shimmer placeholder. Loading states are a design surface here: the
     library can take a second to answer over a slow link, and a shimmering
     block of the right shape tells you what is coming, where a spinner just
     says "wait".

     Only the Media section uses this (grep: every import is under
     routes/media or ClipDrawer), so it is tuned for dark glass — a white
     wash at 6% with a 10% sweep, which reads over a photograph where the
     prospect side's grey fill would go invisible. */
  let { h = '1rem', w = '100%', r = '10px', delay = 0 } = $props();
</script>

<span class="sk" style:height={h} style:width={w} style:border-radius={r}
      style:animation-delay="{delay}ms" aria-hidden="true"></span>

<style>
  .sk { display: block; background: rgba(255, 255, 255, 0.06); position: relative; overflow: hidden; }
  .sk::after {
    content: ''; position: absolute; inset: 0; transform: translateX(-100%);
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent);
    animation: sweep 1.4s infinite;
  }
  @keyframes sweep { 100% { transform: translateX(100%); } }
  @media (prefers-reduced-motion: reduce) { .sk::after { animation: none; } }
</style>
