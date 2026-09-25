/* Motion for the app's overlays and lists — Svelte transitions that stay on
   the compositor (transform + opacity only) and share one feel.

   Durations sit in the 150–320ms band; easings are the two the design system
   uses everywhere: `settle` for anything that arrives (a fast start and a
   long, soft landing — the closest CSS gets to a spring without overshoot),
   and `cubicOut` for anything that simply fades.

   Every transition here honours prefers-reduced-motion by collapsing to an
   opacity-only fade of 60ms. */

import { cubicOut } from 'svelte/easing';

/* cubic-bezier(0.32, 0.72, 0, 1) — the sheet curve — as a function. */
export function settle(t) {
  // Solve the bezier for x = t (Newton on the x-polynomial), then read y.
  const x1 = 0.32, y1 = 0.72, x2 = 0, y2 = 1;
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  let u = t;
  for (let i = 0; i < 6; i++) {
    const xu = ((ax * u + bx) * u + cx) * u - t;
    const d = (3 * ax * u + 2 * bx) * u + cx;
    if (Math.abs(xu) < 1e-4 || d === 0) break;
    u -= xu / d;
  }
  return ((ay * u + by) * u + cy) * u;
}

export const reduced = () =>
  typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Fade — the scrim, a toast, a swapped view. */
export function fade(node, { duration = 200, delay = 0 } = {}) {
  const d = reduced() ? 60 : duration;
  return { delay, duration: d, easing: cubicOut, css: (t) => `opacity:${t}` };
}

/** Slide in along one axis: `x` (px, from the right if positive) or `y`
    (px, from below if positive). Opacity rides along so the first frame is
    never a hard edge. The drawer, the phone sheet, the popovers. */
export function slide(node, { x = 0, y = 0, duration = 320, delay = 0, opacity = 0 } = {}) {
  if (reduced()) return { delay, duration: 60, easing: cubicOut, css: (t) => `opacity:${t}` };
  return {
    delay,
    duration,
    easing: settle,
    css: (t, u) => `transform:translate3d(${x * u}px,${y * u}px,0);opacity:${opacity + (1 - opacity) * t}`
  };
}

/** Pop — a centred dialog: a little rise, a little scale, a fade. */
export function pop(node, { duration = 260, delay = 0, y = 10, from = 0.97 } = {}) {
  if (reduced()) return { delay, duration: 60, easing: cubicOut, css: (t) => `opacity:${t}` };
  return {
    delay,
    duration,
    easing: settle,
    css: (t, u) => `transform:translate3d(0,${y * u}px,0) scale(${from + (1 - from) * t});opacity:${t}`
  };
}

/** Rise — a list item arriving; pass `i` to stagger. */
export function rise(node, { i = 0, step = 28, duration = 300, y = 10 } = {}) {
  if (reduced()) return { duration: 60, easing: cubicOut, css: (t) => `opacity:${t}` };
  return {
    delay: Math.min(i, 12) * step,
    duration,
    easing: settle,
    css: (t, u) => `transform:translate3d(0,${y * u}px,0);opacity:${t}`
  };
}
