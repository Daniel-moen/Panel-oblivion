<script>
  /* The Agent Z conversation itself — thread plus composer, rendered by the
     /agent page over the module state in $lib/agent.svelte.js.

     It is one panel that fills the height it is given: the thread scrolls
     inside it and the composer is pinned to its foot. You speak in accent-
     tinted bubbles on the right; Z answers on the left on the raised plane,
     under a violet label (violet = the agent, everywhere in the app). */
  import { tick } from 'svelte';
  import { agent, ask, retry } from '$lib/agent.svelte.js';
  import AgentPick from './AgentPick.svelte';
  import Icon from './glass/Icon.svelte';

  const EXAMPLES = [
    'Find me a lock-up-and-go in Blouberg under R1.8m',
    'Anything with a sea view renting under R15k?',
    'Family home, pool and a garden, secure estate, R4–7m',
    'Quiet 2-bed near the beach for a retired couple'
  ];

  let text = $state('');
  let box = $state(null);        // the composer textarea
  let thread = $state(null);     // the scrolling thread

  const empty = $derived(agent.turns.length === 0);
  const canSend = $derived(text.trim().length > 1 && !agent.busy);

  async function send(q = text) {
    q = (q || '').trim();
    if (q.length < 2 || agent.busy) return;
    text = '';
    grow();
    ask(q);
    await tick();
    scrollDown();
  }

  /* Newest turn in view — after the question lands and again when the answer
     does, which is what the length/busy read below tracks. The thread is its
     own scroller, so only it moves; the page stays put. */
  function scrollDown() {
    thread?.scrollTo({ top: thread.scrollHeight, behavior: 'smooth' });
  }
  $effect(() => {
    agent.turns.length;
    agent.busy;
    tick().then(scrollDown);
  });

  function onKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  /* The composer grows with the message and stops at a few lines. */
  function grow() {
    if (!box) return;
    box.style.height = 'auto';
    box.style.height = Math.min(box.scrollHeight, 160) + 'px';
  }

  function note(m) {
    if (!m) return '';
    const bits = [];
    if (m.candidates) bits.push(`${m.candidates} passed the hard limits`);
    if (m.listingType === 'rent') bits.push('to rent');
    if (m.relaxed) bits.push('area and bedroom limits loosened');
    bits.push(m.ai ? 'ranked by AI' : 'keyword match — no AI credentials set');
    return bits.join(' · ');
  }
</script>

<div class="chat mg-panel">
  <div class="thread" bind:this={thread} aria-live="polite">
    {#if empty}
      <div class="hello mg-rise">
        <span class="mark xl" aria-hidden="true">Z</span>
        <h2 class="mg-h2">What are we looking for?</h2>
        <p class="mg-sub">Plain words are fine — a budget, an area, the feel of the
          place. Come back with “cheaper” or “what about Parklands?” and it
          picks up where you left off.</p>
        <div class="examples">
          {#each EXAMPLES as ex, i (ex)}
            <button type="button" class="ex mg-rise" style:--i={i + 2} onclick={() => send(ex)}>
              <Icon name="sparkles" size={13} />{ex}
            </button>
          {/each}
        </div>
      </div>
    {/if}

    {#each agent.turns as t (t.id)}
      {#if t.role === 'user'}
        <div class="turn me mg-rise"><p class="bubble">{t.text}</p></div>
      {:else}
        <div class="turn z-turn mg-rise">
          <span class="who"><span class="mark" aria-hidden="true">Z</span>Agent Z</span>
          {#if t.error}
            <div class="mg-strip crit err">
              <span class="ic"><Icon name="alert" size={14} /></span>
              <span><b>Z could not answer.</b> {t.text}</span>
              <button type="button" class="mg-btn secondary sm" onclick={retry}>
                <Icon name="refresh" size={13} /> Try again
              </button>
            </div>
          {:else}
            <p class="bubble">{t.text}</p>

            {#if t.areas?.length}
              <div class="areas">
                {#each t.areas as a (a.suburb)}
                  <button type="button" class="mg-chip" title={a.why}
                          onclick={() => send('What about ' + a.suburb + '?')}>
                    <Icon name="mapPin" size={12} />{a.suburb}
                  </button>
                {/each}
              </div>
            {/if}

            {#if t.picks?.length}
              <div class="grid">
                {#each t.picks as p, i (p.listing_key)}
                  <div class="cell mg-rise" style:--i={i}><AgentPick pick={p} /></div>
                {/each}
              </div>
            {/if}

            {#if note(t.meta)}<p class="note">{note(t.meta)}</p>{/if}
          {/if}
        </div>
      {/if}
    {/each}

    {#if agent.busy}
      <div class="turn z-turn mg-rise">
        <span class="who"><span class="mark" aria-hidden="true">Z</span>Agent Z</span>
        <p class="bubble working">
          <span class="mg-dot mgr"><i class="mg-ping"></i></span>
          <span>Reading the book…</span>
        </p>
      </div>
    {/if}
  </div>

  <div class="composer">
    <div class="field">
      <textarea
        bind:this={box} bind:value={text} rows="1"
        placeholder={empty ? 'Find me a lock-up-and-go in Blouberg under R1.8m'
                           : 'Refine it — cheaper, another suburb, one more bedroom…'}
        aria-label="Message Agent Z"
        oninput={grow} onkeydown={onKey}></textarea>
      <button type="button" class="mg-btn accent icon send" onclick={() => send()} disabled={!canSend}
              aria-label="Send">
        {#if agent.busy}<span class="mg-spin"></span>{:else}<Icon name="send" size={16} />{/if}
      </button>
    </div>
    <p class="mg-hint hint">Enter to send · Shift + Enter for a new line</p>
  </div>
</div>

<style>
  .chat { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }

  /* ——— the Z mark: violet, the agent's colour ——— */
  .mark {
    flex: none; display: inline-grid; place-items: center;
    width: 18px; height: 18px; border-radius: 6px;
    background: var(--mc-mgr-soft); border: 1px solid var(--mc-mgr-line); color: var(--mc-mgr);
    font: 700 10.5px/1 var(--mc-font);
  }
  .mark.xl { width: 48px; height: 48px; border-radius: var(--mc-r-md); font-size: 20px; margin-bottom: 16px; }

  /* ——— thread ——— */
  .thread {
    flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain;
    display: flex; flex-direction: column; gap: 20px; padding: 20px 16px 16px;
  }

  .turn { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .turn.me { align-items: flex-end; }
  .z-turn { align-items: flex-start; container-type: inline-size; }

  .who { display: inline-flex; align-items: center; gap: 7px;
         font: 600 11px/1.4 var(--mc-font); letter-spacing: 0.05em; text-transform: uppercase; color: var(--mc-mgr); }

  .bubble {
    margin: 0; max-width: min(82%, 620px); padding: 10px 14px;
    font: 400 14px/1.55 var(--mc-font); color: var(--mc-ink); white-space: pre-wrap; overflow-wrap: anywhere;
  }
  .me .bubble {
    background: var(--mc-ok-soft); border: 1px solid var(--mc-ok-line);
    border-radius: var(--mc-r) var(--mc-r) 4px var(--mc-r);
  }
  .z-turn .bubble {
    background: var(--mc-raised); border: 1px solid var(--mc-line);
    border-radius: 4px var(--mc-r) var(--mc-r) var(--mc-r);
  }

  .working { display: inline-flex; align-items: center; gap: 10px; color: var(--mc-ink2); }
  .working span:last-child { font: 400 12.5px/1.4 var(--mc-mono); }

  .err { margin: 0; width: 100%; max-width: 620px; align-items: center; flex-wrap: wrap; }
  .err > span:nth-child(2) { flex: 1 1 200px; min-width: 0; }

  .areas { display: flex; flex-wrap: wrap; gap: 6px; }
  .areas .mg-chip { color: var(--mc-ink2); }
  .areas .mg-chip:hover { border-color: var(--mc-mgr-line); color: var(--mc-mgr); }

  .grid { width: 100%; display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }
  .cell { min-width: 0; }
  @container (max-width: 520px) { .grid { grid-template-columns: 1fr; gap: 8px; } }

  .note { margin: 0; font: 400 11.5px/1.5 var(--mc-mono); color: var(--mc-ink3); }

  /* ——— empty state ——— */
  .hello { margin: auto 0; padding: 12px 4px; display: flex; flex-direction: column; align-items: flex-start; }
  .hello .mg-sub { margin-top: 6px; max-width: 54ch; }
  .examples { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 20px; }
  .ex {
    display: inline-flex; align-items: center; gap: 8px; min-height: 36px; padding: 8px 14px;
    background: var(--mc-raised); border: 1px solid var(--mc-line); border-radius: var(--mc-r-md);
    color: var(--mc-ink2); font: 500 13px/1.4 var(--mc-font); text-align: left; cursor: pointer;
    transition: border-color var(--mc-t-fast), color var(--mc-t-fast);
  }
  .ex :global(svg) { flex: none; color: var(--mc-mgr); }
  .ex:hover { border-color: var(--mc-line2); color: var(--mc-ink); }

  /* ——— composer: pinned to the foot of the panel ——— */
  .composer { flex: none; padding: 12px; border-top: 1px solid var(--mc-line); background: var(--mc-surface); }
  .field {
    display: flex; align-items: flex-end; gap: 8px; padding: 6px 6px 6px 14px;
    background: var(--mc-inset); border: 1px solid var(--mc-line); border-radius: 14px;
    transition: border-color var(--mc-t-fast), box-shadow var(--mc-t-fast);
  }
  .field:hover { border-color: var(--mc-line2); }
  .field:focus-within { border-color: rgba(62, 207, 142, 0.6); box-shadow: 0 0 0 3px rgba(62, 207, 142, 0.18); }
  textarea {
    flex: 1; min-width: 0; resize: none; border: 0; background: none;
    color: var(--mc-ink); font: 400 14px/1.5 var(--mc-font);
    padding: 7px 0; max-height: 160px;
  }
  /* the field draws the focus ring; the textarea's own would be a second one */
  textarea:focus, textarea:focus-visible { outline: none; }
  textarea::placeholder { color: var(--mc-ink3); }
  /* a long placeholder stays one line (ellipsis) instead of wrapping under the fold */
  textarea:placeholder-shown { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .send { width: 36px; height: 36px; border-radius: 10px; }
  .hint { margin-top: 8px; text-align: center; font-size: 11.5px; }

  @media (pointer: coarse) {
    .send { width: 44px; height: 44px; }
    .ex { min-height: 44px; }
    .areas .mg-chip { height: 36px; }
    .hint { display: none; }
  }
  @media (max-width: 639px) {
    .thread { padding: 16px 12px 12px; gap: 16px; }
    .bubble { max-width: 88%; }
    .z-turn .bubble { max-width: 100%; }
    .composer { padding: 8px; }
  }
</style>
