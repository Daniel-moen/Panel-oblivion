/* Agent Z's thread — the AI that reads the book and answers in properties.
   (The floating chat in the corner of every page is the team talking to each
   other; that is chat.svelte.js, and the two share nothing.)

   Module state, deliberately: hopping to the prospect list and back keeps the
   conversation on screen, and nothing survives a reload — a chat that came back stale after a crawl would be lying about
   stock that has since moved. "New search" clears it.

   A turn is one POST with the whole history; the server keeps none of it.
   An assistant turn carries what came back with the reply — picks (each
   with the row its card needs), areas and the provenance line — so the page
   never has to join against whatever book the engine page happens to have
   loaded. */

import { api } from './api.js';
import { app, toast } from './state.svelte.js';

export const agent = $state({
  turns: [],        // {role:'user'|'agent', text, picks?, areas?, meta?, error?}
  busy: false
});

let nextId = 1;

/* What the server is told: roles and text only. */
const history = () =>
  agent.turns
    .filter((t) => !t.error)
    .map((t) => ({ role: t.role === 'user' ? 'user' : 'assistant', content: t.text }));

export async function ask(text) {
  text = (text || '').trim();
  if (text.length < 2 || agent.busy) return;
  agent.turns.push({ id: nextId++, role: 'user', text });
  agent.busy = true;
  try {
    const r = await api.agent(history(), app.showSole);
    agent.turns.push({
      id: nextId++,
      role: 'agent',
      text: r.reply,
      picks: r.picks || [],
      areas: r.areas || [],
      meta: {
        ai: r.ai,
        listingType: r.listing_type,
        candidates: r.candidates,
        relaxed: r.relaxed,
        criteria: r.criteria
      }
    });
  } catch (e) {
    agent.turns.push({
      id: nextId++,
      role: 'agent',
      error: true,
      text: e.message || String(e),
      picks: [],
      areas: []
    });
    toast('Agent Z could not answer: ' + (e.message || e), 'error');
  } finally {
    agent.busy = false;
  }
}

/* Drop the failed turn and re-send the question above it. */
export function retry() {
  const last = agent.turns[agent.turns.length - 1];
  if (!last?.error) return;
  agent.turns.pop();
  const q = agent.turns.pop();
  if (q) ask(q.text);
}

export function resetAgent() {
  agent.turns = [];
}
