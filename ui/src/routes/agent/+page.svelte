<script>
  /* Agent Z — the finder as a conversation. You say what you want in plain
     words, Z answers in a line or two and lays the properties out as cards
     underneath; you refine ("cheaper", "what about Parklands?") and it reads
     the whole thread again rather than starting over.

     The thread lives in $lib/agent.svelte.js (module state), so leaving for
     the map and coming back keeps it. This page is the hero framing around
     it. (The floating button in the corner is the team's own chat — a
     different conversation entirely.) */
  import { agent, resetAgent } from '$lib/agent.svelte.js';
  import { app } from '$lib/state.svelte.js';
  import AgentThread from '$lib/components/AgentThread.svelte';

  const empty = $derived(agent.turns.length === 0);
  const asked = $derived(agent.turns.filter((t) => t.role === 'user').length);
  const aiOk = $derived(app.status.ai_ok);

  function again() {
    resetAgent();
  }
</script>

<svelte:head><title>Agent Z · Oblivion</title></svelte:head>

<section class="z">
  <header class="hero">
    <div class="aura" aria-hidden="true"></div>

    <span class="mono" aria-hidden="true">Z</span>
    <div class="who">
      <h1>Agent Z<i class="beam" aria-hidden="true"></i></h1>
      <p>Tell it what you're after. It searches the book and keeps the thread.</p>
    </div>

    <div class="tools">
      {#if aiOk != null}
        <span class="state" class:ok={aiOk}
              title={aiOk ? 'AI ranking ready' : (app.status.ai_reason || 'no AI credentials set')}>
          <i></i>{aiOk ? 'AI ranking' : 'keyword only'}
        </span>
      {/if}
      {#if !empty}
        <span class="count">{asked} question{asked === 1 ? '' : 's'}</span>
        <button class="btn sm" onclick={again}>New search</button>
      {/if}
    </div>
  </header>

  <AgentThread />
</section>

<style>
  .z { display: flex; flex-direction: column; min-height: calc(100vh - 60px);
       max-width: 1000px; margin: 0 auto; width: 100%; }

  /* ——————————————————————————————————————————————————— the hero ——— */
  .hero {
    position: relative; isolation: isolate;
    display: flex; align-items: center; gap: 1rem;
    margin: 1.1rem 0 0.4rem;
    padding: 1.25rem 1.3rem;
    border: 1px solid var(--line);
    border-radius: var(--r-lg);
    background: var(--bg-2);
    box-shadow: var(--shadow-1);
    overflow: hidden;
    animation: rise 0.45s cubic-bezier(0.22, 0.68, 0.3, 1) both;
  }
  @keyframes rise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }

  /* one slow wash of accent light across the card — barely there, never still */
  .aura {
    position: absolute; inset: -60% -20%; z-index: -1; pointer-events: none;
    background:
      radial-gradient(38% 60% at 18% 50%, var(--accent) 0%, transparent 70%),
      radial-gradient(34% 55% at 62% 40%, var(--accent-2) 0%, transparent 72%);
    opacity: 0.1;
    animation: wash 16s ease-in-out infinite alternate;
  }
  @keyframes wash { from { transform: translateX(-6%) scale(1); }
                    to { transform: translateX(8%) scale(1.12); } }

  .mono {
    flex: none; display: inline-flex; align-items: center; justify-content: center;
    width: 46px; height: 46px; border-radius: 15px;
    background: linear-gradient(140deg, var(--accent) 0%, var(--accent-2) 55%, var(--accent) 100%);
    background-size: 220% 220%;
    color: #fff; font-weight: 800; font-size: 1.45rem; letter-spacing: -0.03em;
    box-shadow: 0 6px 18px rgba(37, 99, 235, 0.32);
    animation: drift 9s ease-in-out infinite;
  }
  @keyframes drift { 50% { background-position: 100% 50%; } }

  .who { flex: 1; min-width: 0; }
  h1 { margin: 0; font-size: 1.25rem; font-weight: 800; letter-spacing: -0.025em;
       display: flex; align-items: center; gap: 0.6rem; }
  /* a hairline of accent that keeps sliding under the name */
  .beam { display: block; height: 2px; width: 74px; border-radius: 999px;
          background: linear-gradient(90deg, transparent, var(--accent), var(--accent-2), transparent);
          background-size: 200% 100%;
          animation: slide 3.6s linear infinite; }
  @keyframes slide { from { background-position: 140% 0; } to { background-position: -60% 0; } }
  .hero p { margin: 0.15rem 0 0; font-size: 0.83rem; color: var(--ink-3); }

  .tools { display: flex; align-items: center; gap: 0.7rem; flex: none; }
  .state { display: inline-flex; align-items: center; gap: 0.4rem;
           font: 500 0.74rem/1.3 var(--font-ui); color: var(--ink-3); }
  .state i { width: 7px; height: 7px; border-radius: 50%; background: var(--ink-3); }
  .state.ok { color: var(--open); }
  .state.ok i { background: var(--open); box-shadow: 0 0 0 3px var(--open-soft); }
  .count { font: 500 0.74rem/1.3 var(--font-ui); color: var(--ink-3);
           font-variant-numeric: tabular-nums; }

  @media (max-width: 640px) {
    .hero { gap: 0.75rem; padding: 1rem; flex-wrap: wrap; }
    .tools { width: 100%; justify-content: flex-end; }
    .beam { width: 46px; }
  }

  @media (prefers-reduced-motion: reduce) {
    .hero, .aura, .mono, .beam { animation: none; }
  }
</style>
