<script>
  /* The chrome's one piece of state: a dot and a word, 36px, glass-soft.

     Colour never travels alone here — the dot always has the label beside it,
     and the ping ring only turns on while something is genuinely happening
     (a pulse that never stops is a lie). Under 560px the pill collapses to
     just the dot, because a phone's top bar has room for the clock or a
     sentence, not both.

     Props:
       tone     'ok' (live, green) · 'warn' (needs you, amber) ·
                'crit' (broken, red) · 'off' (neutral grey, the default)
       label    the word. Required — the dot is meaningless without it.
       ping     true while work is in flight; adds the expanding ring
       href     makes it a link (e.g. media's pill goes to its settings)
       title    tooltip; falls back to the label
       onclick  makes it a button instead */
  let { tone = 'off', label = '', ping = false, href = null, title = null, onclick = null } =
    $props();

  const tip = $derived(title || label);
</script>

{#snippet body()}
  <span class="mg-dot {tone}">{#if ping}<i class="mg-ping"></i>{/if}</span>
  <span class="lb">{label}</span>
{/snippet}

{#if href}
  <a class="state mg-glass-soft mg-pill" {href} title={tip} aria-label={label}>{@render body()}</a>
{:else if onclick}
  <button type="button" class="state mg-glass-soft mg-pill" {onclick} title={tip} aria-label={label}>
    {@render body()}
  </button>
{:else}
  <span class="state mg-glass-soft mg-pill" title={tip} role="status" aria-label={label}>
    {@render body()}
  </span>
{/if}

<style>
  .state {
    display: inline-flex; align-items: center; gap: 8px; flex: none;
    height: 36px; padding: 0 14px; max-width: 46vw;
    font: 500 12.5px/1 var(--mg-font); color: var(--mg-i);
    transition: background 0.18s, border-color 0.18s;
  }
  a.state:hover, button.state:hover { background: var(--mg-glass-hover); border-color: var(--mg-line2); }
  button.state:active { transform: scale(0.97); }
  .lb { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  /* the ring lives inside .mg-dot and inherits its colour */
  .mg-dot > i { opacity: 0.6; }

  @media (max-width: 560px) {
    .lb { display: none; }
    .state { width: 36px; padding: 0; justify-content: center; }
  }
  @media (prefers-reduced-motion: reduce) {
    button.state:active { transform: none; }
  }
</style>
