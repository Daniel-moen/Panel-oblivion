<script>
  /* Shimmer placeholder: a block of the right shape that tells you what is
     coming, where a spinner only says "wait". Raised plane with a faint sweep.
     `delay` staggers a column of them; `lines` draws that many text rows. */
  let { h = '1rem', w = '100%', r = '8px', delay = 0, lines = 0 } = $props();
</script>

{#if lines}
  <span class="col" aria-hidden="true">
    {#each Array(lines) as _, i (i)}
      <span class="mg-skel" style:height={h} style:width={i === lines - 1 ? '62%' : w}
            style:border-radius={r} style:animation-delay="{delay + i * 60}ms"></span>
    {/each}
  </span>
{:else}
  <span class="mg-skel" style:height={h} style:width={w} style:border-radius={r}
        style:animation-delay="{delay}ms" aria-hidden="true"></span>
{/if}

<style>
  .col { display: flex; flex-direction: column; gap: 8px; }
</style>
