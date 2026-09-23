<script>
  /* Agent Z — the finder as a conversation. You say what you want in plain
     words, Z answers in a line or two and lays the properties out as cards
     underneath; you refine ("cheaper", "what about Parklands?") and it reads
     the whole thread again rather than starting over.

     The thread lives in $lib/agent.svelte.js (module state), so leaving for
     the map and coming back keeps it. This page is the framing around it:
     one header row inside the app's pane, then the conversation. The photo
     behind everything belongs to the scene now, so there is no hero here.
     (The chat button up in the chrome is the team's own line — a different
     conversation entirely.)

     TODO(agent agent): the thread itself (AgentThread.svelte, AgentPick,
     the result cards) is still on the old vocabulary. */
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
  <div class="mg-row">
    <div class="titles">
      <h1 class="mg-h2">Agent Z</h1>
      <p>Tell it what you're after. It searches the book and keeps the thread.</p>
    </div>

    <div class="mg-actions">
      {#if aiOk != null}
        <span class="mg-chip {aiOk ? 'ok' : ''}"
              title={aiOk ? 'AI ranking ready' : (app.status.ai_reason || 'no AI credentials set')}>
          <i class="dot"></i>{aiOk ? 'AI ranking' : 'keyword only'}
        </span>
      {/if}
      {#if !empty}
        <span class="mg-count">{asked} question{asked === 1 ? '' : 's'}</span>
        <button class="mg-btn secondary sm" onclick={again}>New search</button>
      {/if}
    </div>
  </div>

  <AgentThread />
</section>

<style>
  .z { display: flex; flex-direction: column; min-height: 0; }
  .titles { min-width: 0; }
  .titles p { margin: 3px 0 0; font: 400 12.5px/1.5 var(--mg-font); color: var(--mg-i3); }
</style>
