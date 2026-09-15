<script>
  /* One composer for every contact attempt: pick a channel and outcome with a
     tap, one line of notes, a follow-up in one click. Used inline on Today,
     the pipeline and the property page. */
  import { api } from '$lib/api.js';
  import { toast } from '$lib/state.svelte.js';
  import { label } from '$lib/panel.js';

  let { gid, contacts = [], channel = 'call', onsaved = () => {}, oncancel = null, compact = false } = $props();

  const CHANNELS = [['call', '📞', 'Call'], ['whatsapp', '💬', 'WhatsApp'], ['sms', '✉️', 'SMS'],
                    ['email', '📧', 'Email'], ['visit', '🚪', 'Visit'], ['letter', '📮', 'Letter']];
  const OUTCOMES = [['no_answer', 'No answer'], ['left_message', 'Left message'], ['spoke', 'Spoke'],
                    ['callback_requested', 'Call back'], ['interested', 'Interested'],
                    ['meeting_set', 'Meeting set'], ['not_interested', 'Not interested']];
  const FOLLOW = [['', 'None'], [1, 'Tomorrow'], [3, '3 days'], [7, 'Next week'], [30, 'Next month']];

  let ch = $state(channel);
  let outcome = $state('no_answer');
  let summary = $state('');
  let follow = $state('');
  let customDate = $state('');
  let contactId = $state(contacts[0]?.id ?? null);
  let saving = $state(false);

  const plus = (d) => new Date(Date.now() + d * 86400000).toISOString().slice(0, 10);

  async function save() {
    saving = true;
    try {
      await api.child.add(gid, 'interactions', {
        channel: ch, outcome, summary: summary.trim() || null, direction: 'outbound',
        contact_id: contactId,
        next_follow_up_at: customDate || (follow ? plus(Number(follow)) : null)
      });
      toast('Logged', 'ok');
      summary = ''; follow = ''; customDate = '';
      onsaved();
    } catch (e) { toast(e.message, 'error'); }
    finally { saving = false; }
  }

  function onkey(e) { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') save(); }
</script>

<div class="ql" class:compact onkeydown={onkey} role="form">
  <div class="row chips">
    {#each CHANNELS as [k, ico, l] (k)}
      <button class:on={ch === k} onclick={() => (ch = k)} title={l}><span>{ico}</span>{#if !compact}{l}{/if}</button>
    {/each}
    {#if contacts.length > 1}
      <select bind:value={contactId} class="who">
        {#each contacts as c (c.id)}<option value={c.id}>{c.name || c.phone}</option>{/each}
      </select>
    {/if}
  </div>
  <div class="row chips oc">
    {#each OUTCOMES as [k, l] (k)}
      <button class:on={outcome === k} class="o-{k}" onclick={() => (outcome = k)}>{l}</button>
    {/each}
  </div>
  <input type="text" placeholder="What was said? (optional)" bind:value={summary} />
  <div class="row bottom">
    <span class="fl">Follow up:</span>
    <div class="chips">
      {#each FOLLOW as [d, l] (l)}
        <button class:on={follow === d && !customDate} onclick={() => { follow = d; customDate = ''; }}>{l}</button>
      {/each}
      <input type="date" bind:value={customDate} onchange={() => (follow = '')} title="Pick a date" />
    </div>
    <div class="acts">
      {#if oncancel}<button class="btn sm" onclick={oncancel}>Cancel</button>{/if}
      <button class="btn sm primary" onclick={save} disabled={saving}>{saving ? 'Saving…' : 'Log ' + label(ch)}</button>
    </div>
  </div>
</div>

<style>
  .ql { display: flex; flex-direction: column; gap: 0.55rem; }
  .row { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; }
  .chips { display: flex; gap: 0.3rem; flex-wrap: wrap; }
  .chips button { background: var(--bg-3); border: 1px solid transparent; color: var(--ink-2); font-size: 0.78rem;
                  font-weight: 500; padding: 0.3rem 0.65rem; border-radius: 999px; cursor: pointer;
                  display: inline-flex; gap: 0.3rem; align-items: center; transition: all 0.12s; }
  .chips button:hover { border-color: var(--line-3); color: var(--ink); }
  .chips button.on { background: var(--accent); border-color: var(--accent); color: #fff; }
  .oc button.on.o-spoke, .oc button.on.o-interested, .oc button.on.o-meeting_set { background: var(--open); border-color: var(--open); }
  .oc button.on.o-not_interested { background: var(--bad); border-color: var(--bad); }
  .who { margin-left: auto; font-size: 0.78rem; padding: 0.25rem 1.6rem 0.25rem 0.5rem; }
  input[type='text'] { width: 100%; }
  .bottom { justify-content: space-between; }
  .fl { font-size: 0.76rem; color: var(--ink-3); }
  .bottom input[type='date'] { font-size: 0.74rem; padding: 0.2rem 0.4rem; }
  .acts { display: flex; gap: 0.4rem; margin-left: auto; }
  .compact .chips button { padding: 0.25rem 0.5rem; }
</style>
