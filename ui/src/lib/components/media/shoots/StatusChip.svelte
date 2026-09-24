<script>
  import { STATUS } from '$lib/media/shoots.js';
  let { status = 'shot' } = $props();
  const s = $derived(STATUS[status] || { label: status, tone: '' });
</script>

<span class="mg-chip {s.tone}"><span class="dot"></span>{s.label}</span>
