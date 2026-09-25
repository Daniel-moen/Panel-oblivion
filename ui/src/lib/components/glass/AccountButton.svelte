<script>
  /* The signed-in account, as a round header button: the person's initial
     in the `.mg-round` glass, linked to /account (name, role, passkeys,
     settings — what the old sidebar's foot showed). Drawn by the strip on
     every route and by Home's own top-right cluster, so it is one tap away
     at every width. The name and role are its label and tooltip. */
  import { page } from '$app/state';
  import { me } from '$lib/me.svelte.js';

  const who = $derived(me.display_name || me.username || 'Signed in');
  const role = $derived(me.is_owner ? 'Owner' : me.role ? me.role[0].toUpperCase() + me.role.slice(1) : 'Member');
  const initial = $derived((String(who).trim()[0] || 'O').toUpperCase());
  const label = $derived(`Account — ${who}, ${role}`);
  const on = $derived(page.url.pathname.startsWith('/account'));
</script>

<a class="mg-round acct" class:on href="/account" data-testid="account-btn" aria-label={label} title={label}
   aria-current={on ? 'page' : undefined}>
  <span class="av" aria-hidden="true">{initial}</span>
</a>

<style>
  .av { font: 600 14px/1 var(--mc-font); letter-spacing: 0; color: #fff; }
</style>
