<script>
  /* /online — who is signed in, where they are, and what they are busy with.

     The list itself is OnlineUsers; this page is its header: a live count
     and the thresholds in words, so nobody has to guess what "away" means.
     Everyone signed in can open it. Admins see sessions per person inside
     the list; members do not. */
  import { roster } from '$lib/presence.svelte.js';
  import OnlineUsers from '$lib/components/OnlineUsers.svelte';

  const mins = (s) => Math.round(s / 60);
</script>

<svelte:head><title>Online — Oblivion</title></svelte:head>

<div class="mg-row">
  <div class="titles">
    <h1 class="mg-h2">Online
      {#if roster.loaded}<span class="mg-count">{roster.online} of {roster.users.length}</span>{/if}
    </h1>
    <p class="mg-hint">
      Online means seen in the last {mins(roster.thresholds.online)} minutes, away within
      {mins(roster.thresholds.away)}. "Busy with" is whatever someone has pressed
      <b>I'm on it</b> on in their tasks.
    </p>
  </div>
  <div class="mg-actions">
    <span class="mg-chip ok"><span class="mg-dot ok sm"><i class="mg-ping"></i></span>live · every 30 s</span>
  </div>
</div>

<OnlineUsers />

<style>
  .titles { min-width: 0; display: flex; flex-direction: column; gap: 4px; max-width: 60ch; }
  .titles .mg-h2 { display: flex; align-items: baseline; gap: 8px; }
  .mg-hint b { color: var(--mc-ink2); font-weight: 500; }
  .mg-chip .mg-dot { margin-right: 2px; }
</style>
