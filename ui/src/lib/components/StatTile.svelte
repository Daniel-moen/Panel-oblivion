<script>
  /* One headline figure — Mission Control's Overview tile: a HUD label, a
     26px number, a one-line caption, and optionally a full-width Meter (how
     much of the whole this figure is) and a quiet sparkline tucked into the
     bottom-right corner (hidden on a phone, where it would sit on the caption).

     An `<a>` when it goes somewhere, a `<div>` otherwise. While `loading` and
     the value has not arrived it holds a skeleton; once loading is over a
     missing value reads as an em dash rather than a zero it does not know.
     The meter here is a share of a whole, not a utilization, so it keeps one
     calm colour (`pctTone`, accent by default) instead of turning amber at 70 %. */
  import CountUp from './CountUp.svelte';
  import Skeleton from './Skeleton.svelte';
  import Meter from './glass/Meter.svelte';
  import Sparkline from './glass/Sparkline.svelte';
  import { fmtInt } from '$lib/format.js';

  let {
    label, value = null, sub = '', tone = '', href = null, live = false,
    pct = null, pctDetail = '', pctTone = 'ok', spark = null, sparkColor = 'var(--mc-accent)', sparkTitle = '',
    i = 0, loading = false
  } = $props();

  const hasSpark = $derived(Array.isArray(spark) && spark.length >= 2 && spark.some((v) => v));
  const fmt = (n) => fmtInt(n);

  /* The sparkline sits beside the number, in whatever room the number leaves
     (≤ 110px); on a tile too narrow for a readable one (< 48px) it is left
     out rather than drawn over the caption. */
  let tw = $state(0);
  let vw = $state(0);
  const sw = $derived(Math.min(110, Math.floor(tw - 32 - vw - 16)));
</script>

<svelte:element this={href ? 'a' : 'div'} {href} bind:clientWidth={tw} class="mg-stat-tile mg-rise tile" class:link={!!href} style:--i={i}
                title={hasSpark && sparkTitle ? sparkTitle : null}>
  <span class="hud">{label}{#if live}<span class="mg-dot warn sm mg-pulse"></span>{/if}</span>
  <div class="v {tone}"><span class="vv" bind:clientWidth={vw}>
    {#if value != null}
      {#if typeof value === 'number'}<CountUp {value} format={fmt} />{:else}{value}{/if}
    {:else if loading}<Skeleton h="26px" w="52px" />
    {:else}—{/if}
  </span></div>
  <div class="sub" class:warn={tone === 'warn'} class:crit={tone === 'crit'}>{sub}</div>
  {#if pct != null && isFinite(pct)}
    <div class="meter"><Meter pct={pct} detail={pctDetail} tone={pctTone} width={null} height={6} /></div>
  {/if}
  {#if hasSpark && sw >= 48}
    <div class="spark"><Sparkline data={spark} width={sw} height={30} color={sparkColor} /></div>
  {/if}
</svelte:element>

<style>
  .tile { display: block; color: inherit; transition: border-color var(--mc-t-fast), transform var(--mc-t) var(--mc-ease); }
  .tile.link:hover { border-color: var(--mc-line2); }
  .tile.link:active { transform: scale(0.985); }
  .tile.link:focus-visible { outline: 2px solid rgba(62, 207, 142, 0.7); outline-offset: 2px; }
  .v { position: relative; z-index: 1; }
  .sub { position: relative; z-index: 1; }
  .sub.crit { color: var(--mc-crit); }
  .meter { position: relative; z-index: 1; margin-top: 10px; }
  .meter :global(.meter) { width: 100%; }

  .vv { display: inline-flex; align-items: baseline; }
  /* level with the number, right-aligned; never on a phone */
  .spark { position: absolute; right: 16px; top: 34px; opacity: 0.7; pointer-events: none; display: none; }
  @media (min-width: 640px) { .spark { display: block; } }
</style>
