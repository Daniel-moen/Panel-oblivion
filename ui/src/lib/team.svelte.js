/* The team features' one hook into the shell.

   The per-person task tracker, the who's-online strip and the /online page
   are a feature, not chrome, so nothing in the shell knows about them by
   name. This module registers them through the shell's extension points
   (shell.svelte.js): the "Online" section in the Dock, and the
   two Home cards. It also runs the presence heartbeat, which needs to know
   the route — that is the one thing it takes from the layout.

   `installTeam(pathOf)` is called once from the root layout's onMount and
   returns the stop function. `pathOf` reads the current pathname; it is
   wrapped in an effect root here so the layout has no effect of its own to
   write. */
import { addNav, addHomeCard } from './shell.svelte.js';
import { beat, startHeartbeat } from './presence.svelte.js';
import TaskTracker from './components/TaskTracker.svelte';
import OnlineStrip from './components/OnlineStrip.svelte';

export function installTeam(pathOf) {
  addNav({ href: '/online', label: 'Online', icon: 'user' });
  addHomeCard({ id: 'tasks', component: TaskTracker });
  addHomeCard({ id: 'online', component: OnlineStrip });

  /* Presence: one heartbeat now and every 45 s while the tab is visible;
     the route effect sends one more on every navigation, so the /online
     page's "current page" is never a page old. */
  const stopBeat = startHeartbeat();
  const stopRoute = $effect.root(() => {
    $effect(() => { beat(pathOf()); });
  });
  return () => { stopRoute(); stopBeat(); };
}
