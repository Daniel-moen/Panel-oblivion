<script>
  /* The Agent Z conversation itself — thread plus composer, rendered by the
     /agent page over the module state in $lib/agent.svelte.js. */
  import { tick } from 'svelte';
  import { agent, ask, retry } from '$lib/agent.svelte.js';
  import AgentPick from './AgentPick.svelte';

  const EXAMPLES = [
    'Find me a lock-up-and-go in Blouberg under R1.8m',
    'Anything with a sea view renting under R15k?',
    'Family home, pool and a garden, secure estate, R4–7m',
    'Quiet 2-bed near the beach for a retired couple'
  ];

  let text = $state('');
  let box = $state(null);        // the composer textarea
  let tail = $state(null);       // scroll anchor under the last turn

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
     does, which is what the length/busy read below tracks. */
  function scrollDown() {
    tail?.scrollIntoView({ behavior: 'smooth', block: 'end' });
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

<div class="wrap">
  <div class="thread">
    {#if empty}
      <div class="hello">
        <div class="glyph" aria-hidden="true"><span class="mono xl">Z</span></div>
        <p class="lead">What are we looking for?</p>
        <p class="sub">Plain words are fine — a budget, an area, the feel of the
          place. Come back with “cheaper” or “what about Parklands?” and it
          picks up where you left off.</p>
        <div class="chips">
          {#each EXAMPLES as ex, i (ex)}
            <button type="button" class="ex" style:--i={i} onclick={() => send(ex)}>{ex}</button>
          {/each}
        </div>
      </div>
    {/if}

    {#each agent.turns as t (t.id)}
      {#if t.role === 'user'}
        <div class="turn me"><p class="bubble">{t.text}</p></div>
      {:else}
        <div class="turn z-turn">
          <span class="mono sm" aria-hidden="true">Z</span>
          <div class="said">
            {#if t.error}
              <p class="bubble err">{t.text}</p>
              <button class="btn sm" onclick={retry}>Try again</button>
            {:else}
              <p class="bubble">{t.text}</p>

              {#if t.areas?.length}
                <div class="areas">
                  {#each t.areas as a (a.suburb)}
                    <button type="button" class="area" title={a.why}
                            onclick={() => send('What about ' + a.suburb + '?')}>
                      {a.suburb}
                    </button>
                  {/each}
                </div>
              {/if}

              {#if t.picks?.length}
                <div class="grid">
                  {#each t.picks as p, i (p.listing_key)}
                    <div class="cell" style:--i={i}><AgentPick pick={p} /></div>
                  {/each}
                </div>
              {/if}

              {#if note(t.meta)}<p class="note">{note(t.meta)}</p>{/if}
            {/if}
          </div>
        </div>
      {/if}
    {/each}

    {#if agent.busy}
      <div class="turn z-turn">
        <span class="mono sm pulse" aria-hidden="true">Z</span>
        <div class="said">
          <p class="bubble thinking" aria-live="polite">
            <i></i><i></i><i></i><span class="shimmer">Z is reading the book…</span>
          </p>
        </div>
      </div>
    {/if}

    <div bind:this={tail} class="tail"></div>
  </div>

  <div class="composer">
    <div class="field">
      <textarea
        bind:this={box} bind:value={text} rows="1"
        placeholder={empty ? 'Find me a lock-up-and-go in Blouberg under R1.8m'
                           : 'Refine it — cheaper, another suburb, one more bedroom…'}
        aria-label="Message Agent Z"
        oninput={grow} onkeydown={onKey}></textarea>
      <button class="btn primary send" onclick={() => send()} disabled={!canSend}
              aria-label="Send">
        {#if agent.busy}<span class="spin light"></span>{:else}↑{/if}
      </button>
    </div>
    <p class="hint">Enter to send · Shift + Enter for a new line</p>
  </div>
</div>

<style>
  .wrap { flex: 1; min-height: 0; display: flex; flex-direction: column; }

  /* ——— the Z mark: one accent gradient, used at three sizes ——— */
  .mono {
    flex: none; display: inline-flex; align-items: center; justify-content: center;
    width: 28px; height: 28px; border-radius: 9px;
    background: linear-gradient(140deg, var(--accent) 0%, var(--accent-2) 100%);
    color: #fff; font-weight: 800; font-size: 0.86rem; letter-spacing: -0.02em;
    box-shadow: 0 1px 6px rgba(37, 99, 235, 0.28);
  }
  .mono.xl { width: 56px; height: 56px; border-radius: 18px; font-size: 1.7rem;
             background: linear-gradient(140deg, var(--accent) 0%, var(--accent-2) 55%, var(--accent) 100%);
             background-size: 220% 220%;
             animation: drift 9s ease-in-out infinite;
             box-shadow: 0 8px 24px rgba(37, 99, 235, 0.32); }
  .mono.pulse { animation: breathe 1.6s ease-in-out infinite; }
  @keyframes breathe { 50% { opacity: 0.55; } }
  @keyframes drift { 50% { background-position: 100% 50%; } }

  /* ——— thread ——— */
  .thread { flex: 1; display: flex; flex-direction: column; gap: 1.5rem;
            padding-bottom: 1.2rem; }
  .tail { height: 1px; }

  .turn { display: flex; gap: 0.7rem;
          animation: turn-in 0.34s cubic-bezier(0.22, 0.68, 0.3, 1) both; }
  .turn.me { justify-content: flex-end; }
  .said { min-width: 0; flex: 1; display: flex; flex-direction: column;
          align-items: flex-start; gap: 0.75rem; }
  @keyframes turn-in { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }

  .bubble { margin: 0; font-size: 0.92rem; line-height: 1.55; color: var(--ink); }
  .me .bubble {
    max-width: min(74%, 620px); padding: 0.6rem 0.95rem;
    border-radius: 16px 16px 4px 16px; white-space: pre-wrap;
    background: var(--accent-soft); color: var(--accent-ink);
    border: 1px solid var(--accent-line);
  }
  .z-turn .bubble { padding-top: 0.25rem; }
  .bubble.err { color: var(--bad); }

  .thinking { display: inline-flex; align-items: center; gap: 0.3rem;
              color: var(--ink-3); font-size: 0.85rem; }
  .thinking i { width: 5px; height: 5px; border-radius: 50%; background: var(--ink-3);
                animation: blink 1.2s infinite; }
  .thinking i:nth-child(2) { animation-delay: 0.18s; }
  .thinking i:nth-child(3) { animation-delay: 0.36s; }
  .thinking span { margin-left: 0.4rem; }
  @keyframes blink { 0%, 60%, 100% { opacity: 0.25; } 30% { opacity: 1; } }

  /* a slow light runs left to right across the line while Z works */
  .shimmer {
    background: linear-gradient(100deg,
      var(--ink-3) 0%, var(--ink-3) 36%, var(--accent-2) 50%, var(--ink-3) 64%, var(--ink-3) 100%);
    background-size: 280% 100%;
    -webkit-background-clip: text; background-clip: text;
    color: transparent;
    animation: sheen 2.4s linear infinite;
  }
  @keyframes sheen { from { background-position: 120% 0; } to { background-position: -120% 0; } }

  .areas { display: flex; flex-wrap: wrap; gap: 0.35rem; }
  .area { background: var(--bg-3); border: 1px solid var(--line-2); color: var(--ink-2);
          border-radius: 999px; padding: 0.2rem 0.7rem;
          font: 600 0.76rem/1.4 var(--font-ui);
          transition: color 0.15s, border-color 0.15s, background 0.15s; }
  .area:hover { color: var(--accent-2); border-color: var(--accent-line);
                background: var(--accent-soft); }

  .grid { width: 100%; display: grid; gap: 1rem;
          grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); }
  /* the picks land one after another rather than all at once */
  .cell { min-width: 0;
          animation: cell-in 0.42s cubic-bezier(0.22, 0.68, 0.3, 1) both;
          animation-delay: calc(var(--i, 0) * 55ms); }
  @keyframes cell-in { from { opacity: 0; transform: translateY(12px) scale(0.985); }
                       to { opacity: 1; transform: none; } }

  .note { margin: 0; font-size: 0.73rem; color: var(--ink-3); }

  /* ——— empty state ——— */
  .hello { padding: 2.5rem 0.2rem 1rem; animation: turn-in 0.4s ease both; }
  .glyph { position: relative; width: max-content; margin-bottom: 1.1rem; }
  /* soft ambient light behind the mark */
  .glyph::before {
    content: ''; position: absolute; inset: -28px; border-radius: 50%;
    background: radial-gradient(closest-side, var(--accent) 0%, transparent 72%);
    opacity: 0.22; filter: blur(14px); z-index: 0;
    animation: halo 5.5s ease-in-out infinite;
  }
  .glyph .mono { position: relative; z-index: 1; }
  @keyframes halo { 0%, 100% { opacity: 0.16; transform: scale(0.96); }
                    50% { opacity: 0.3; transform: scale(1.06); } }

  .lead { margin: 0; font-size: 1.6rem; font-weight: 700; letter-spacing: -0.02em; }
  .sub { margin: 0.4rem 0 1.2rem; font-size: 0.9rem; color: var(--ink-2);
         max-width: 54ch; line-height: 1.6; }
  .chips { display: flex; flex-wrap: wrap; gap: 0.45rem; }
  .ex { background: var(--bg-2); border: 1px solid var(--line-2); color: var(--ink-2);
        border-radius: 999px; padding: 0.4rem 0.9rem; text-align: left;
        font: 500 0.82rem/1.4 var(--font-ui); box-shadow: var(--shadow-1);
        animation: turn-in 0.4s ease both; animation-delay: calc(140ms + var(--i, 0) * 60ms);
        transition: color 0.15s, border-color 0.15s, background 0.15s,
                    transform 0.15s, box-shadow 0.15s; }
  .ex:hover { color: var(--accent-2); border-color: var(--accent-line);
              background: var(--accent-soft); transform: translateY(-2px);
              box-shadow: var(--shadow-2); }

  /* ——— composer ——— */
  .composer { position: sticky; bottom: 0; z-index: 5; padding: 0.7rem 0 1rem;
              background: linear-gradient(180deg, transparent, var(--bg) 26%); }

  .field { display: flex; align-items: flex-end; gap: 0.5rem;
           background: color-mix(in srgb, var(--bg-2) 82%, transparent);
           backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
           border: 1px solid var(--line-2);
           border-radius: var(--r-lg); padding: 0.45rem 0.45rem 0.45rem 0.85rem;
           box-shadow: var(--shadow-1);
           transition: border-color 0.18s, box-shadow 0.18s, background 0.18s; }
  .field:hover { border-color: var(--line-3); }
  .field:focus-within { border-color: var(--accent); background: var(--bg-2);
                        box-shadow: 0 0 0 4px var(--accent-soft),
                                    0 6px 20px rgba(37, 99, 235, 0.16); }
  textarea {
    flex: 1; min-width: 0; resize: none; border: 0; outline: none; background: none;
    color: var(--ink); font: 400 0.92rem/1.5 var(--font-ui);
    padding: 0.35rem 0; max-height: 160px;
  }
  textarea::placeholder { color: var(--ink-3); }
  .btn.send { width: 38px; height: 38px; padding: 0; flex: none; border-radius: 10px;
              font-size: 1.05rem;
              background: linear-gradient(140deg, var(--accent) 0%, var(--accent-2) 100%);
              border-color: transparent;
              transition: transform 0.15s, box-shadow 0.15s, opacity 0.15s; }
  .btn.send:not(:disabled):hover { transform: translateY(-1px);
                                   box-shadow: 0 4px 14px rgba(37, 99, 235, 0.38); }
  .spin.light { border-color: rgba(255, 255, 255, 0.35); border-top-color: #fff; }
  .hint { margin: 0.45rem 0 0; text-align: center; font-size: 0.72rem; color: var(--ink-3); }

  @media (max-width: 640px) {
    .me .bubble { max-width: 88%; }
    .grid { grid-template-columns: 1fr; }
  }

  @media (prefers-reduced-motion: reduce) {
    .turn, .cell, .hello, .ex { animation: none !important; }
    .mono.xl, .mono.pulse, .glyph::before, .shimmer, .thinking i { animation: none !important; }
    .shimmer { color: var(--ink-3); background: none; -webkit-background-clip: border-box;
               background-clip: border-box; }
    .ex:hover, .btn.send:not(:disabled):hover { transform: none; }
  }
</style>
