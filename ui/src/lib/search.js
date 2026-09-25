/* The strip's Search button, and the "/" shortcut.

   There is no global search index: every section already has its own search
   box, so "search" means "take me to the nearest one and put the cursor in
   it". A page marks its box with `data-page-search`; the first visible one
   wins. With none on this page:
     - on Media, go to the library search (it autofocuses its own box);
     - everywhere else, go to Prospects and focus its filter box. */
import { tick } from 'svelte';
import { goto } from '$app/navigation';

const SEL = '[data-page-search]';

/** The first page search box that is actually on screen (not display:none). */
function findBox() {
  for (const el of document.querySelectorAll(SEL)) {
    if (el.getClientRects().length) return el;
  }
  return null;
}

function focusBox(el) {
  el.focus({ preventScroll: true });
  el.select?.();
  el.scrollIntoView?.({ block: 'nearest' });
}

/* After a navigation the box mounts a frame or two later (and a lazy route
   chunk may still be loading): poll on rAF for up to ~1.5 s. */
async function waitForBox(ms = 1500) {
  await tick();
  const until = performance.now() + ms;
  while (performance.now() < until) {
    const el = findBox();
    if (el) return el;
    await new Promise((r) => requestAnimationFrame(r));
  }
  return null;
}

/** Focus this page's search box, or go to the one that fits. */
export async function openSearch() {
  if (typeof document === 'undefined') return;
  const here = findBox();
  if (here) { focusBox(here); return; }

  /* iOS raises the keyboard only for a focus() made inside the tap itself,
     and the real box is a navigation away. So focus a stand-in NOW (still
     inside the gesture); iOS keeps the keyboard up while focus then moves
     from it to the real box. */
  const proxy = holdKeyboard();
  const path = location.pathname;
  const to = path.startsWith('/media') ? '/media/search' : '/prospects';
  try {
    if (!path.startsWith(to)) await goto(to);
    const el = await waitForBox();
    if (el) focusBox(el);
  } finally {
    proxy.remove();
  }
}

function holdKeyboard() {
  const i = document.createElement('input');
  i.type = 'search';
  i.setAttribute('aria-hidden', 'true');
  i.tabIndex = -1;
  /* 16px: no iOS zoom-on-focus. Kept on screen (not display:none) or it
     cannot take focus; invisible and inert to the pointer. */
  i.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;font-size:16px;border:0;padding:0;pointer-events:none;';
  document.body.appendChild(i);
  i.focus({ preventScroll: true });
  return i;
}

/** True when a keystroke belongs to a field, not to the app. */
export function typing(e) {
  const t = e.target;
  if (!t || t === document.body) return false;
  if (t.isContentEditable) return true;
  const tag = t.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
}

/** The "/" shortcut, as a keydown handler (StatusStrip mounts it on the
    window; Home, which draws no strip, can mount the same one). */
export function searchKey(e) {
  if (e.key !== '/' || e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || typing(e)) return;
  if (document.querySelector('[aria-modal="true"]')) return; // a sheet owns the keyboard
  e.preventDefault();
  openSearch();
}
