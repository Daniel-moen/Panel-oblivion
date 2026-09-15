<script>
  import { mvLabel } from '$lib/format.js';

  /** One row of truth about a prospect: mandate verdict + deal signals.
      `max` caps the number of extra badges so cards stay calm. */
  let { r, verdict = true, max = 99 } = $props();

  const sigs = $derived.by(() => {
    const out = [];
    if (r.brand_count > 1) out.push(['multi', `${r.brand_count} agencies`,
      'listed by multiple agency brands — proven open mandate']);
    if (r.total_cut_pct) out.push(['cut', `−${r.total_cut_pct}%`,
      `price cut ${r.total_cut_pct}% across ${r.price_changes || 1} change(s)`]);
    if (r.under_offer) out.push(['uo', 'under offer', '']);
    if (r.price_reduced && !r.total_cut_pct) out.push(['cut', 'reduced', '']);
    if (r.relisted) out.push(['rel',
      r.days_off_market ? `relisted · ${r.days_off_market}d off` : 'relisted',
      'was delisted, came back — a mandate likely lapsed']);
    if (r.is_development) out.push(['dev', 'development', '']);
    if (r.tracker_status) out.push(['trk', 'tracked', 'already in the tracker sheet']);
    return out.slice(0, max);
  });
</script>

{#if verdict}
  <span class="mv {r.mandate_verdict || 'unknown'}">{mvLabel(r.mandate_verdict)}</span>
{/if}
{#each sigs as [cls, text, title]}
  <span class="sig {cls}" {title}>{text}</span>
{/each}
