/* The team features' one hook into the shell.

   The to-do lists (/tasks), the who's-online strip and the /online page are
   a feature, not chrome, so nothing in the shell knows about them by name.
   This module registers them through the shell's extension points
   (shell.svelte.js): the "Tasks" section in the Dock — its badge counts the
   tasks somebody else gave you that you have not opened yet — and the
   Online card on Home. (Home's "My tasks" card is mounted by the Home route
   itself, next to "Needs you"; /online is reached from the Online card and
   from /tasks.) It also runs the presence heartbeat, which needs to know
   the route — that is the one thing it takes from the layout — and the
   task inbox poll, which toasts newly assigned tasks on the next load.

   `installTeam(pathOf)` is called once from the root layout's onMount and
   returns the stop function. `pathOf` reads the current pathname; it is
   wrapped in an effect root here so the layout has no effect of its own to
   write. */
import { addNav, addHomeCard } from './shell.svelte.js';
import { beat, startHeartbeat } from './presence.svelte.js';
import { taskInbox, startInbox } from './tasks.svelte.js';
import OnlineStrip from './components/OnlineStrip.svelte';

export function installTeam(pathOf) {
  addNav({ href: '/tasks', label: 'Tasks', icon: 'check', badge: () => taskInbox.unseen, badgeLabel: 'new' });
  addHomeCard({ id: 'online', component: OnlineStrip });

  /* Presence: one heartbeat now and every 45 s while the tab is visible;
     the route effect sends one more on every navigation, so the /online
     page's "current page" is never a page old. */
  const stopBeat = startHeartbeat();
  const stopInbox = startInbox();
  const stopRoute = $effect.root(() => {
    $effect(() => { beat(pathOf()); });
  });
  return () => { stopRoute(); stopBeat(); stopInbox(); };
}
