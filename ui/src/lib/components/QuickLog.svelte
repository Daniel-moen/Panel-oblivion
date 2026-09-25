<script>
  /* One composer for every contact attempt: pick a channel and outcome with a
     tap, one line of notes, a follow-up in one click. Used in the log sheet
     on Today / the pipeline, and inline on the property and contact pages. */
  import { api } from '$lib/api.js';
  import { toast } from '$lib/state.svelte.js';
  import { label } from '$lib/panel.js';
  import Icon from '$lib/components/glass/Icon.svelte';

  let { gid, contacts = [], channel = 'call', onsaved = () => {}, oncancel = null, compact = false } = $props();

  const CHANNELS = [['call', 'phone', 'Call'], ['whatsapp', 'message', 'WhatsApp'], ['sms', 'text', 'SMS'],
                    ['email', 'send', 'Email'], ['visit', 'home', 'Visit'], ['letter', 'inbox', 'Letter']];
  const OUTCOMES = [['no_answer', 'No answer'], ['left_message', 'Left message'], ['spoke', 'Spoke'],
                    ['callback_requested', 'Call back'], ['interested', 'Interested'],
                    ['meeting_set', 'Meeting set'], ['not_interested', 'Not interested']];
  const FOLLOW = [['', 'None'], [1, 'Tomorrow'], [3, '3 days'], [7, 'Next week'], [30, 'Next month']];
  const GOOD = ['spoke', 'interested', 'meeting_set'];

  let ch = $state(channel);
  let outcome = $state('no_answer');
  let summary = $state('');
  let follow = $state('');
  let customDate = $state('');
  let contactId = $state(contacts[0]?.id ?? null);
  let saving = $state(false);

  /* The contact list can change under us (the contact page switches the
     property being logged about) — never log against a contact that is no
     longer on offer. */
  $effect(() => {
    if (!contacts.some((c) => c.id === contactId)) contactId = contacts[0]?.id ?? null;
  });

  const plus = (d) => new Date(Date.now() + d * 86400000).toISOString().slice(0, 10);

  async function save() {
    if (saving) return;
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
  const tone = (k) => (outcome !== k ? '' : GOOD.includes(k) ? 'ok' : k === 'not_interested' ? 'crit' : 'on');
</script>

<div class="ql" class:compact onkeydown={onkey} role="form" aria-label="Log a contact attempt">
  <div class="grp">
    <span class="hud">Channel</span>
    <div class="chips">
      {#each CHANNELS as [k, ico, l] (k)}
        <button type="button" class="mg-chip" class:on={ch === k} aria-pressed={ch === k}
                onclick={() => (ch = k)} title={l} aria-label={l}>
          <Icon name={ico} size={14} />{#if !compact}{l}{/if}
        </button>
      {/each}
    </div>
  </div>

  {#if contacts.length > 1}
    <div class="grp">
      <span class="hud">With</span>
      <div class="mg-select who">
        <select bind:value={contactId} aria-label="Who you spoke to">
          {#each contacts as c (c.id)}<option value={c.id}>{c.name || c.phone}</option>{/each}
        </select>
        <span class="ic"><Icon name="chevronDown" size={14} /></span>
      </div>
    </div>
  {/if}

  <div class="grp">
    <span class="hud">Outcome</span>
    <div class="chips">
      {#each OUTCOMES as [k, l] (k)}
        <button type="button" class="mg-chip {tone(k)}" aria-pressed={outcome === k} onclick={() => (outcome = k)}>{l}</button>
      {/each}
    </div>
  </div>

  <input class="mg-input" type="text" placeholder="What was said? (optional)" bind:value={summary} aria-label="Summary" />

  <div class="grp">
    <span class="hud">Follow up</span>
    <div class="chips">
      {#each FOLLOW as [d, l] (l)}
        <button type="button" class="mg-chip" class:on={follow === d && !customDate} aria-pressed={follow === d && !customDate}
                onclick={() => { follow = d; customDate = ''; }}>{l}</button>
      {/each}
      <input class="mg-input date" type="date" bind:value={customDate} onchange={() => (follow = '')}
             title="Pick a date" aria-label="Follow-up date" class:set={!!customDate} />
    </div>
  </div>

  <div class="acts">
    <span class="mg-hint kbd">⌘↵ to save</span>
    {#if oncancel}<button type="button" class="mg-btn ghost" onclick={oncancel}>Cancel</button>{/if}
    <button type="button" class="mg-btn primary" onclick={save} disabled={saving}>
      {#if saving}<span class="mg-spin"></span> Saving…{:else}<Icon name="check" size={15} stroke={2} /> Log {label(ch)}{/if}
    </button>
  </div>
</div>

<style>
  .ql { display: flex; flex-direction: column; gap: 14px; }
  .grp { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .chips .mg-chip { height: 32px; }
  .who { width: 100%; max-width: 320px; }
  .date { width: auto; height: 32px; padding: 0 10px; font-size: 12.5px; color: var(--mc-ink2); border-radius: 9999px; }
  .date.set { border-color: var(--mc-ok-line); color: var(--mc-accent); }
  .acts { display: flex; align-items: center; gap: 8px; justify-content: flex-end; flex-wrap: wrap; }
  .kbd { margin-right: auto; }
  @media (pointer: coarse) {
    .chips .mg-chip, .date { height: 40px; }
    .acts .mg-btn { height: 44px; }
    .kbd { display: none; }
  }
</style>
