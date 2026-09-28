<script>
  /* Owner & deed — who owns this property, and the two ways to find out.

     1. What is already known: owner_details (GET /api/owner/<gid>, written
        by a LOOM lookup or by hand) and any owner contacts the lead holds.
     2. "Get deed info (agent)": stream C's Claude Code agent
        (POST /api/agent/tasks {kind: 'deed', group_id, listing_key}). It runs
        for minutes in the office's browser; this polls
        GET /api/agent/tasks/<id> every 3 s while it is queued or running and
        shows its latest progress lines, then its result. Past runs for the
        property come from GET /api/agent/tasks?group_id=&limit=5.
     3. The instant LOOM API lookup (POST /api/deed/<gid>) — only offered
        when a LOOM token is on file, and it needs a resolved erf.

     /api/property/capabilities says whether (2) exists on this server, so a
     deploy without stream C shows "Agents not available yet" instead of
     firing requests at routes that are not there. */
  import { api, propertyApi } from '$lib/api.js';
  import { toast } from '$lib/state.svelte.js';
  import { fmtInt } from '$lib/format.js';
  import Icon from '../glass/Icon.svelte';
  import Skeleton from '../Skeleton.svelte';

  let { gid, listingKey, erfResolved = false, contacts = [], onchange = null } = $props();

  let caps = $state(null);          // {agents, loom} | null while asking
  let owner = $state(null);         // owner_details row | {} | null
  let tasks = $state([]);           // newest first
  let tasksErr = $state(null);
  let starting = $state(false);
  let loomBusy = $state(false);
  let loomErr = $state(null);
  let openId = $state(null);        // an expanded past run

  const LIVE = ['queued', 'running'];
  const live = $derived(tasks.find((t) => LIVE.includes(t.status)) || null);
  const latest = $derived(tasks[0] || null);

  async function loadOwner() {
    try { owner = await api.owner(gid); } catch { owner = {}; }
  }
  async function loadTasks() {
    if (!caps?.agents) return;
    try {
      const d = await propertyApi.agentTasks(gid, 5);
      tasks = (d?.tasks || []).slice().sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
      tasksErr = null;
    } catch (e) {
      if (e.status === 404 || e.status === 405) caps = { ...caps, agents: false };
      else tasksErr = e.message;
    }
  }

  let seen = null;
  $effect(() => {
    const g = gid;
    if (g === seen) return;
    seen = g;
    owner = null; tasks = []; tasksErr = null; openId = null;
    loadOwner();
    (async () => {
      if (!caps) {
        try { caps = await propertyApi.capabilities(); }
        catch { caps = { agents: false, loom: false }; }
      }
      loadTasks();
    })();
  });

  /* Poll the live run every 3 s; stop when it settles, when the page goes
     away, and while the tab is hidden. */
  const liveId = $derived(live?.id ?? null);
  $effect(() => {
    const id = liveId;
    if (id == null) return;
    let dead = false;
    let timer = null;
    const step = async () => {
      if (dead) return;
      if (typeof document !== 'undefined' && document.hidden) { timer = setTimeout(step, 3000); return; }
      try {
        const fresh = await propertyApi.agentTask(id);
        if (dead) return;
        tasks = tasks.map((x) => (x.id === id ? fresh : x));
        if (!LIVE.includes(fresh.status)) {
          if (fresh.status === 'done') {
            toast('Deed agent finished', 'ok');
            loadOwner();
            onchange?.();
          } else if (fresh.status === 'failed') toast('Deed agent failed — see the run for why', 'error');
          return;
        }
      } catch { /* a missed beat; try again */ }
      timer = setTimeout(step, 3000);
    };
    timer = setTimeout(step, 3000);
    return () => { dead = true; clearTimeout(timer); };
  });

  async function deploy() {
    starting = true;
    try {
      const t = await propertyApi.startAgentTask({ kind: 'deed', group_id: String(gid), listing_key: listingKey });
      tasks = [t, ...tasks.filter((x) => x.id !== t.id)];
      toast('Deed agent deployed — it reports back here', 'ok');
    } catch (e) {
      if (e.status === 404 || e.status === 405) caps = { ...caps, agents: false };
      else toast(e.message || 'Could not start the agent', 'error');
    } finally { starting = false; }
  }
  async function cancel(t) {
    try {
      const fresh = await propertyApi.cancelAgentTask(t.id);
      tasks = tasks.map((x) => (x.id === t.id ? { ...x, ...(fresh || {}), status: fresh?.status || 'cancelled' } : x));
    } catch (e) { toast(e.message, 'error'); }
  }

  async function loom() {
    loomBusy = true; loomErr = null;
    try {
      owner = await api.deed(String(gid));
      toast('Deed fetched from LOOM', 'ok');
      onchange?.();
    } catch (e) {
      loomErr = e.code === 'loom_auth'
        ? 'The LOOM session has expired — refresh the token (loom_login.py).'
        : e.code === 'no_erf' ? 'Resolve this property’s erf number first.' : (e.message || String(e));
    } finally { loomBusy = false; }
  }

  /* ---- presentation */
  const money = (v) => (v ? 'R' + fmtInt(v) : null);
  const maskId = (v) => (v && String(v).length > 6 ? String(v).slice(0, 6) + '•'.repeat(String(v).length - 6) : v);

  function rowsOf(o) {
    if (!o) return [];
    return [
      ['Owner type', o.owner_type],
      ['ID / reg. no.', maskId(o.id_number)],
      ['Title deed', o.deed_number],
      ['Registered', o.purchase_date],
      ['Purchase price', money(o.purchase_price)],
      ['Bond holder', o.bond_holder]
    ].filter(([, v]) => v != null && v !== '');
  }

  /* The owner card merges what is stored with the newest finished agent
     result (the agent may know more than the store, or the store may be a
     later manual edit — the store wins where both speak). */
  const agentResult = $derived(tasks.find((t) => t.status === 'done' && t.result)?.result || null);
  const known = $derived.by(() => {
    const o = owner && Object.keys(owner).length ? owner : null;
    if (!o && !agentResult) return null;
    const out = { ...(agentResult || {}) };
    for (const [k, v] of Object.entries(o || {})) if (v != null && v !== '') out[k] = v;
    return out;
  });
  const ownerContacts = $derived((contacts || []).filter((c) => c.role === 'owner' && (c.name || c.phone || c.email)));

  function since(iso) {
    if (!iso) return '';
    const t = new Date(String(iso).replace(' ', 'T') + (/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? '' : 'Z')).getTime();
    if (isNaN(t)) return String(iso);
    const s = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (s < 60) return 'just now';
    if (s < 3600) return Math.round(s / 60) + ' min ago';
    if (s < 86400) return Math.round(s / 3600) + ' h ago';
    return Math.round(s / 86400) + ' d ago';
  }
  const evText = (e) => (typeof e === 'string' ? e : e?.text || e?.message || e?.line || JSON.stringify(e));
  const TONE = { queued: '', running: 'warn', done: 'ok', failed: 'crit', cancelled: '' };
  const STATUS = { queued: 'Queued', running: 'Working', done: 'Done', failed: 'Failed', cancelled: 'Cancelled' };
</script>

<section class="mg-section od" id="owner" data-owner-section>
  <div class="head"><h2>Owner &amp; deed</h2>
    {#if live}<span class="mg-chip warn xs"><span class="mg-spin"></span> Agent working</span>{/if}
  </div>

  <div class="body">
    <!-- 1. what is known -->
    {#if owner === null}
      <Skeleton h="16px" w="50%" /><div class="gap"><Skeleton h="12px" lines={2} /></div>
    {:else if known || ownerContacts.length}
      <div class="who">
        <span class="av"><Icon name="user" size={18} /></span>
        <div class="wn">
          <b class="name">{known?.owner_name || ownerContacts[0]?.name || 'Owner on file'}</b>
          <span class="src">{known?.source || known?.notes || (ownerContacts.length ? 'from the lead’s contacts' : '')}</span>
        </div>
      </div>
      <div class="reach">
        {#each [known?.phone, ...ownerContacts.map((c) => c.phone)].filter((v, i, a) => v && a.indexOf(v) === i) as ph (ph)}
          <a class="mg-btn sm primary" href="tel:{ph}"><Icon name="phone" size={14} /> <span class="mg-tnum">{ph}</span></a>
        {/each}
        {#each [known?.email, ...ownerContacts.map((c) => c.email)].filter((v, i, a) => v && a.indexOf(v) === i) as em (em)}
          <a class="mg-btn sm secondary" href="mailto:{em}"><Icon name="send" size={14} /> {em}</a>
        {/each}
      </div>
      {#if rowsOf(known).length}
        <dl class="mg-kv">
          {#each rowsOf(known) as [k, v] (k)}<div><dt>{k}</dt><dd class="mg-tnum">{v}</dd></div>{/each}
        </dl>
      {/if}
      <p class="mg-hint">POPIA: use for a mandate approach only.{owner?.updated_at ? ` Saved ${String(owner.updated_at).slice(0, 16)}.` : ''}</p>
    {:else}
      <p class="none">No owner on file yet. Send the deed agent, or look it up in LOOM.</p>
    {/if}

    <!-- 2. the agent -->
    <div class="agent">
      <div class="ahead">
        <span class="aic"><Icon name="agent" size={16} /></span>
        <div class="at">
          <b>Deed agent</b>
          <span>A Claude Code agent searches the deeds registry in the office browser and reports back here. A few minutes.</span>
        </div>
      </div>

      {#if caps === null}
        <Skeleton h="36px" w="200px" r="999px" />
      {:else if !caps.agents}
        <div class="mg-strip" data-agents-missing>
          <span class="ic"><Icon name="clock" size={14} /></span>
          <span><b>Agents not available yet.</b> The agent service isn’t running on this server — the instant lookup below still works.</span>
        </div>
      {:else}
        <div class="acts">
          <button type="button" class="mg-btn primary" data-deploy-agent disabled={starting || !!live} onclick={deploy}>
            {#if starting}<span class="mg-spin"></span> Deploying…{:else}<Icon name="agent" size={15} /> Get deed info (agent){/if}
          </button>
          <a class="mg-btn secondary" href="/mia?about={encodeURIComponent(gid)}"><Icon name="chat" size={14} /> Ask Mia about this property</a>
        </div>
        {#if tasksErr}<div class="mg-strip crit"><span class="ic"><Icon name="alert" size={14} /></span><span>{tasksErr}</span></div>{/if}

        {#if latest}
          {@const t = latest}
          <div class="run {t.status}" data-agent-run={t.status}>
            <div class="rl">
              <span class="mg-chip xs {TONE[t.status] || ''}">{#if LIVE.includes(t.status)}<span class="mg-spin"></span>{/if}{STATUS[t.status] || t.status}</span>
              <span class="rt">{t.title || 'Deed lookup'}</span>
              <span class="when">{since(t.finished_at || t.started_at || t.created_at)}{t.created_by ? ` · ${t.created_by}` : ''}</span>
              {#if LIVE.includes(t.status)}
                <button type="button" class="mg-btn ghost sm" onclick={() => cancel(t)}>Cancel</button>
              {/if}
            </div>
            {#if t.events?.length && (LIVE.includes(t.status) || t.status === 'failed')}
              <ol class="events mg-noscroll">
                {#each t.events.slice(-6) as e, i (i)}<li>{evText(e)}</li>{/each}
              </ol>
            {/if}
            {#if t.summary}<p class="sum">{t.summary}</p>{/if}
            {#if t.status === 'done' && t.result}
              <p class="mg-hint">{t.result.owner_name ? 'Its findings fill the owner card above.' : 'It found no registered owner.'}{t.result.source ? ` Source: ${t.result.source}.` : ''}</p>
            {/if}
            {#if t.report_id}<a class="mg-btn sm secondary rep" href="/reports/{encodeURIComponent(t.report_id)}"><Icon name="list" size={14} /> Open the report</a>{/if}
          </div>
        {/if}

        {#if tasks.length > 1}
          <details class="past">
            <summary>Earlier runs · {tasks.length - 1}</summary>
            <div class="mg-list">
              {#each tasks.slice(1) as t (t.id)}
                <button type="button" class="prow" onclick={() => (openId = openId === t.id ? null : t.id)} aria-expanded={openId === t.id}>
                  <span class="mg-chip xs {TONE[t.status] || ''}">{STATUS[t.status] || t.status}</span>
                  <span class="rt">{t.result?.owner_name || t.summary || t.title || 'Deed lookup'}</span>
                  <span class="when">{since(t.created_at)}</span>
                </button>
                {#if openId === t.id}
                  <div class="pbody">
                    {#if t.result}
                      <dl class="mg-kv">
                        {#each [['Owner', t.result.owner_name], ...rowsOf(t.result), ['Phone', t.result.phone], ['Email', t.result.email], ['Source', t.result.source]].filter(([, v]) => v != null && v !== '') as [k, v] (k)}
                          <div><dt>{k}</dt><dd>{v}</dd></div>
                        {/each}
                      </dl>
                    {:else}<p class="mg-hint">{t.summary || 'No result.'}</p>{/if}
                    {#if t.report_id}<a class="mg-btn sm ghost" href="/reports/{encodeURIComponent(t.report_id)}">Report <Icon name="arrowRight" size={13} /></a>{/if}
                  </div>
                {/if}
              {/each}
            </div>
          </details>
        {/if}
      {/if}
    </div>

    <!-- 3. the instant LOOM lookup -->
    {#if caps?.loom}
      <div class="loom">
        <button type="button" class="mg-btn secondary sm" data-loom-lookup disabled={loomBusy || !erfResolved} onclick={loom}
                title={erfResolved ? 'Registered owner and deed straight from the LOOM API' : 'Needs a resolved erf number'}>
          {#if loomBusy}<span class="mg-spin"></span> Asking LOOM…{:else}<Icon name="key" size={14} /> Instant LOOM lookup{/if}
        </button>
        <span class="mg-hint">{erfResolved ? 'Direct deeds-registry API, seconds.' : 'Needs a resolved erf number.'}</span>
      </div>
      {#if loomErr}<div class="mg-strip crit"><span class="ic"><Icon name="alert" size={14} /></span><span>{loomErr}</span></div>{/if}
    {/if}

    {#if caps && !caps.agents}
      <a class="mg-btn ghost sm mia" href="/mia?about={encodeURIComponent(gid)}"><Icon name="chat" size={14} /> Ask Mia about this property</a>
    {/if}
  </div>
</section>

<style>
  .od .head { align-items: center; }
  .mg-chip.xs { height: 22px; padding: 0 8px; font-size: 11px; gap: 6px; }
  .mg-chip.xs .mg-spin { width: 10px; height: 10px; border-width: 1.5px; }
  .gap { margin-top: 10px; }
  .body { display: flex; flex-direction: column; gap: 12px; }

  .who { display: flex; gap: 12px; align-items: center; }
  .av { width: 40px; height: 40px; flex: none; border-radius: 50%; display: grid; place-items: center; background: var(--mc-ok-soft); border: 1px solid var(--mc-ok-line); color: var(--mc-accent); }
  .wn { display: flex; flex-direction: column; min-width: 0; }
  .name { font: 600 16px/1.3 var(--mc-font); color: var(--mc-ink); overflow-wrap: anywhere; }
  .src { font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); overflow-wrap: anywhere; }
  .reach { display: flex; gap: 6px; flex-wrap: wrap; }
  .reach:empty { display: none; }
  .none { margin: 0; font: 400 13px/1.5 var(--mc-font); color: var(--mc-ink3); }

  .agent { border-top: 1px solid var(--mc-glass-line); padding-top: 14px; display: flex; flex-direction: column; gap: 12px; }
  .ahead { display: flex; gap: 10px; align-items: flex-start; }
  .aic { width: 30px; height: 30px; flex: none; border-radius: 9px; display: grid; place-items: center; background: var(--mc-mgr-soft); border: 1px solid var(--mc-mgr-line); color: var(--mc-mgr); }
  .at { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .at b { font: 600 13.5px/1.3 var(--mc-font); color: var(--mc-ink); }
  .at span { font: 400 12.5px/1.45 var(--mc-font); color: var(--mc-ink3); }
  .agent .mg-strip { margin: 0; }
  .acts { display: flex; gap: 8px; flex-wrap: wrap; }

  .run { border: 1px solid var(--mc-glass-line); border-radius: var(--mc-r-md); padding: 12px; background: rgba(255, 255, 255, 0.03); display: flex; flex-direction: column; gap: 10px; }
  .run.running, .run.queued { border-color: var(--mc-warn-line); }
  .run.done { border-color: var(--mc-ok-line); }
  .run.failed { border-color: var(--mc-crit-line); }
  .rl { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .rt { font: 500 13px/1.4 var(--mc-font); color: var(--mc-ink); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1 1 120px; }
  .when { font: 400 12px/1.4 var(--mc-font); color: var(--mc-ink3); white-space: nowrap; }
  .events { margin: 0; padding: 8px 10px; list-style: none; background: var(--mc-term, rgba(0, 0, 0, 0.35)); border-radius: 8px; max-height: 150px; overflow-y: auto;
            font: 400 11.5px/1.6 var(--mc-mono); color: var(--mc-ink2); }
  .events li { overflow-wrap: anywhere; }
  .events li:last-child { color: var(--mc-ink); }
  .sum { margin: 0; font: 400 13px/1.5 var(--mc-font); color: var(--mc-ink2); }
  .rep { align-self: flex-start; }

  .past summary { cursor: pointer; font: 500 12.5px/1 var(--mc-font); color: var(--mc-ink3); padding: 4px 0; }
  .past summary:hover { color: var(--mc-ink2); }
  .prow { all: unset; box-sizing: border-box; cursor: pointer; display: flex; gap: 8px; align-items: center; width: 100%; padding: 8px 2px; border-bottom: 1px solid var(--mc-line-soft); }
  .prow:hover .rt { color: var(--mc-accent); }
  .pbody { padding: 6px 2px 10px; }

  .loom { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; border-top: 1px solid var(--mc-glass-line); padding-top: 12px; }
  .loom + .mg-strip { margin: 0; }
  .mia { align-self: flex-start; }
</style>
