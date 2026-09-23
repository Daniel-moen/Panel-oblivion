<script>
  /* The nothing-here state. Always says what would be here and what to do
     about it — an empty grid with no words is a bug report waiting to happen.
     Anything passed as children renders as the action row (a pill or two). */
  import Icon from './Icon.svelte';

  let { icon = 'sparkles', title = 'Nothing here yet', hint = '', children } = $props();
</script>

<div class="mg-empty mg-fadeup">
  <span class="ic"><Icon name={icon} size={20} /></span>
  <h3>{title}</h3>
  {#if hint}<p>{hint}</p>{/if}
  {#if children}<div class="act">{@render children()}</div>{/if}
</div>
