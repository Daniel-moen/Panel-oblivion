<script>
  /* Agent Z — the finder as a conversation. You say what you want in plain
     words, Z answers in a line or two and lays the properties out as cards
     underneath; you refine ("cheaper", "what about Parklands?") and it reads
     the whole thread again rather than starting over.

     The thread lives in $lib/agent.svelte.js (module state), so leaving for
     the map and coming back keeps it. This page is the framing around it: one
     header row, then the conversation as a panel that fills the rest of the
     viewport — the thread scrolls inside it and the composer is pinned to its
     foot, above the phone Dock. (The chat button up in the strip is the
     team's own line — a different conversation entirely.) */
  import { agent, resetAgent } from '$lib/agent.svelte.js';
  import { app } from '$lib/state.svelte.js';
  import AgentThread from '$lib/components/AgentThread.svelte';
  import Icon from '$lib/components/glass/Icon.svelte';

  const empty = $derived(agent.turns.length === 0);
  const asked = $derived(agent.turns.filter((t) => t.role === 'user').length);
  const aiOk = $derived(app.status.ai_ok);

  function again() {
    resetAgent();
  }
</script>

<svelte:head><title>Agent Z · Oblivion</title></svelte:head>

<section class="z">
  <div class="mg-row top">
    <div class="titles">
      <h1 class="mg-h2">Agent Z</h1>
      <p class="mg-hint">Tell it what you're after. It searches the book and keeps the thread.</p>
    </div>

    <div class="mg-actions">
      {#if aiOk != null}
        <span class="mg-chip {aiOk ? 'mgr' : ''}"
              title={aiOk ? 'AI ranking ready' : (app.status.ai_reason || 'no AI credentials set')}>
          <i class="dot"></i>{aiOk ? 'AI ranking' : 'Keyword only'}
        </span>
      {/if}
      {#if !empty}
        <span class="mg-count">{asked} question{asked === 1 ? '' : 's'}</span>
        <button type="button" class="mg-btn secondary sm" onclick={again}>
          <Icon name="refresh" size={14} /> New search
        </button>
      {/if}
    </div>
  </div>

  <AgentThread />
</section>

<style>
  /* The page is exactly one viewport tall: the strip above, the page's own
     top gutter, and the Dock (phone) or a bottom gutter (rail) below. The
     negative bottom margin eats half of .mg-page's dock clearance so the
     composer sits 12px above the Dock rather than 24px. */
  .z {
    --z-top: 16px;
    --z-bottom: calc(var(--mc-dock-h) + var(--sab) + 12px);
    display: flex; flex-direction: column; min-height: 0;
    height: calc(100vh - var(--sat) - var(--mc-strip-h) - 1px - var(--z-top) - var(--z-bottom));
    height: calc(100dvh - var(--sat) - var(--mc-strip-h) - 1px - var(--z-top) - var(--z-bottom));
    min-height: 360px;
    margin-bottom: -12px;
  }
  @media (min-width: 640px) { .z { --z-top: 20px; } }
  @media (min-width: 1024px) { .z { --z-bottom: calc(var(--sab) + 16px); margin-bottom: -16px; } }

  .top { flex: none; flex-wrap: nowrap; margin-bottom: 12px; }
  .titles { flex: 1 1 0; min-width: 0; }
  .titles .mg-hint { margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .top > .mg-actions { flex: none; flex-wrap: nowrap; }
  .mg-actions .mg-chip { height: 28px; }

  @media (max-width: 639px) {
    .titles .mg-hint { display: none; }
    .mg-actions .mg-count { display: none; }
  }
</style>
