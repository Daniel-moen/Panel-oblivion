<script>
  /* The compact "who's online" for the home page: an avatar per person who
     is online or away, the count, and a link to the /online page. Nothing
     else — the sentence about what each of them is busy with lives there.
     Rendered empty (nothing at all) until the roster has loaded, so Home
     never shows a "0 online" that is not yet true.

     Mounted as a Home card (shell.svelte.js `slots.home`): one .mg-section
     holding one link row, in the same shape as Home's "Go to" rows. */
  import { onMount } from 'svelte';
  import { roster, watchRoster } from '$lib/presence.svelte.js';
  import Icon from '$lib/components/glass/Icon.svelte';

  onMount(() => watchRoster(30));

  const here = $derived(roster.users.filter((u) => u.status !== 'offline'));
  const away = $derived(here.length - roster.online);
  const title = (u) =>
    `${u.display_name} · ${u.status}` + (u.busy?.length ? ` · busy with ${u.busy[0].title}` : '');
</script>

{#if roster.loaded}
  <section class="mg-section" aria-label="Who is online">
    <a class="mg-listrow strip" href="/online" aria-label="{roster.online} online — open the Online page">
      <span class="avs">
        {#each here.slice(0, 6) as u (u.id)}
          <span class="av {u.status}" title={title(u)}>
            <span class="ini">{u.initials}</span>
            <span class="mg-dot sm dot" class:ok={u.status === 'online'} class:warn={u.status === 'away'}></span>
          </span>
        {/each}
        {#if here.length > 6}<span class="av more"><span class="ini">+{here.length - 6}</span></span>{/if}
        {#if !here.length}<span class="av"><span class="ini"><Icon name="user" size={14} /></span></span>{/if}
      </span>
      <span class="t">
        <b>{roster.online} online{away ? ` · ${away} away` : ''}</b>
        {#if here.length}
          <span>{here.slice(0, 2).map((u) => u.display_name.split(' ')[0] + (u.busy?.length ? ' · ' + u.busy[0].title : '')).join(' — ')}</span>
        {:else}
          <span>Nobody else is here right now</span>
        {/if}
      </span>
      <Icon name="chevronRight" size={15} class="chev" />
    </a>
  </section>
{/if}

<style>
  .strip { gap: 12px; }
  .avs { display: flex; align-items: center; flex: none; }
  .av { position: relative; width: 30px; height: 30px; margin-right: -8px; }
  .av:last-child { margin-right: 0; }
  .ini {
    width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center;
    background: var(--mc-raised); border: 2px solid var(--mc-surface);
    font: 600 10.5px/1 var(--mc-font); color: var(--mc-ink2); letter-spacing: 0.02em;
  }
  .av.online .ini { color: var(--mc-ink); }
  .av.more .ini { color: var(--mc-ink3); }
  .dot { position: absolute; right: -1px; bottom: -1px; box-shadow: 0 0 0 2px var(--mc-surface); }
  .strip :global(.chev) { color: var(--mc-ink3); flex: none; }
</style>
