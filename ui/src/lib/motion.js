/* The motion vocabulary — every enter, leave, press and glide in the app
   pulls from here. It mirrors Mission Control's `src/lib/motion.js`
   (widget-claude/remote/app) one-to-one: the same three springs with the
   same numbers, the same variants, the same `reduced()` rule. Consistency IS
   the premium feel: one spring family, one ease, one set of variants.

   The panel runs these through Framer's `motion`; here they are plain Svelte
   transitions plus CSS, with the SAME spring physics solved in closed form
   (`springAt`) — so a sheet here settles on exactly the curve a sheet there
   does, without shipping a second animation runtime:

     - a Svelte transition takes the spring as its `easing`, over the time the
       spring needs to settle (`springMs`);
     - a CSS transition (the dock's gliding highlight, Seg's pill, a press)
       takes the spring as a `linear()` easing string (`springCss`).

   Everything stays on the compositor: transform and opacity only, blur never
   animates. Under prefers-reduced-motion every one of these keeps its fade
   and drops its travel and scale (`reduced`).

   Older names (`fade`, `slide`, `pop`, `rise`, `settle`) are kept as thin
   aliases onto the vocabulary so no call site renders on a missing export. */

/* ——————————————————————————————————————————————————————— springs ——— */

export const spring = {
  snappy: { type: 'spring', stiffness: 520, damping: 42, mass: 0.8 }, // buttons, chips, indicators
  smooth: { type: 'spring', stiffness: 300, damping: 34 }, // sheets, panes, layout
  gentle: { type: 'spring', stiffness: 170, damping: 26 } // large moves, numbers
};

export const ease = { out: [0.2, 0.8, 0.2, 1] };
export const EASE_OUT_CSS = 'cubic-bezier(0.2, 0.8, 0.2, 1)';

/** Progress 0→1 of a spring released from rest at 0 toward 1, `t` seconds in.
    The closed-form damped harmonic oscillator — what `motion` integrates. */
export function springAt(s, t) {
  const m = s.mass ?? 1, k = s.stiffness ?? 100, c = s.damping ?? 10;
  const w0 = Math.sqrt(k / m);
  const zeta = c / (2 * Math.sqrt(k * m));
  if (t <= 0) return 0;
  if (zeta < 1) {
    const wd = w0 * Math.sqrt(1 - zeta * zeta);
    return 1 - Math.exp(-zeta * w0 * t) * (Math.cos(wd * t) + ((zeta * w0) / wd) * Math.sin(wd * t));
  }
  if (zeta === 1) return 1 - Math.exp(-w0 * t) * (1 + w0 * t);
  const r = Math.sqrt(zeta * zeta - 1);
  const s1 = -w0 * (zeta - r), s2 = -w0 * (zeta + r);
  return 1 - (s2 * Math.exp(s1 * t) - s1 * Math.exp(s2 * t)) / (s2 - s1);
}

const settleCache = new Map();
/** Milliseconds until the spring stays within 0.1 % of rest (motion's own
    rest threshold, scaled to a unit move). */
export function springMs(s) {
  const key = `${s.stiffness}/${s.damping}/${s.mass ?? 1}`;
  if (settleCache.has(key)) return settleCache.get(key);
  let last = 0;
  for (let t = 0; t <= 4; t += 0.005) if (Math.abs(1 - springAt(s, t)) > 0.001) last = t;
  const ms = Math.round((last + 0.005) * 1000);
  settleCache.set(key, ms);
  return ms;
}

/** The spring as a Svelte easing over `springMs(s)`: t (0..1) → progress. */
export function springEase(s) {
  const T = springMs(s) / 1000;
  return (t) => (t >= 1 ? 1 : springAt(s, t * T));
}

const cssCache = new Map();
/** The spring as a CSS transition value: `<ms>ms linear(…)`. For glides that
    CSS drives (Seg's pill, the dock's highlight, presses). */
export function springCss(s, points = 40) {
  const key = `${s.stiffness}/${s.damping}/${s.mass ?? 1}/${points}`;
  if (cssCache.has(key)) return cssCache.get(key);
  const ms = springMs(s);
  const T = ms / 1000;
  const stops = [];
  for (let i = 0; i <= points; i++) stops.push(+springAt(s, (i / points) * T).toFixed(4));
  stops[points] = 1;
  /* linear() needs Safari 17.2 / Chrome 113; without it the whole
     transition value would be dropped, so fall back to the app's ease. */
  const linear = typeof CSS === 'undefined' || !CSS.supports || CSS.supports('transition-timing-function', 'linear(0, 1)');
  const v = linear ? `${ms}ms linear(${stops.join(', ')})` : `${ms}ms ${EASE_OUT_CSS}`;
  cssCache.set(key, v);
  return v;
}

/** cubic-bezier(x1,y1,x2,y2) as an easing function (for `ease.out`). */
export function bezier(x1, y1, x2, y2) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  return (t) => {
    if (t <= 0) return 0;
    if (t >= 1) return 1;
    let u = t;
    for (let i = 0; i < 8; i++) {
      const xu = ((ax * u + bx) * u + cx) * u - t;
      const d = (3 * ax * u + 2 * bx) * u + cx;
      if (Math.abs(xu) < 1e-5 || d === 0) break;
      u -= xu / d;
    }
    return ((ay * u + by) * u + cy) * u;
  };
}
export const easeOut = bezier(...ease.out);

/* ————————————————————————————————————————————————————— variants ——— */
/* The same objects as the panel's, so a reader can hold the two files side
   by side. `play()` turns one into a Svelte transition. */

export const fadeUp = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: 6 },
  transition: { duration: 0.28, ease: ease.out }
};

export const fadeIn = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
  transition: { duration: 0.2 }
};

export const scaleIn = {
  initial: { opacity: 0, scale: 0.96 },
  animate: { opacity: 1, scale: 1 },
  exit: { opacity: 0, scale: 0.98 },
  transition: spring.smooth
};

export const sheetUp = {
  initial: { y: '100%' },
  animate: { y: 0 },
  exit: { y: '100%' },
  transition: spring.smooth
}; // phone bottom sheet

export const slideIn = {
  initial: { x: 40, opacity: 0 },
  animate: { x: 0, opacity: 1 },
  exit: { x: 40, opacity: 0 },
  transition: spring.smooth
};

export const stagger = (delay = 0.04) => ({ animate: { transition: { staggerChildren: delay } } });

export const press = { whileTap: { scale: 0.97 }, transition: spring.snappy };

export const hoverLift = { whileHover: { y: -1 }, whileTap: { scale: 0.98 }, transition: spring.snappy };

/* Reduced-motion fallback: keep the opacity fade, drop every translation and
   scale. `reduced(fadeUp)` still fades, it just doesn't travel. Called with
   no argument it answers the media query (the older call sites use it so). */
const MOTION_KEYS = ['y', 'x', 'scale', 'rotate'];
export function reduced(variants) {
  if (arguments.length === 0) return prefersReduced();
  if (!variants || typeof variants !== 'object') return variants;
  const out = {};
  for (const [key, value] of Object.entries(variants)) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      out[key] = value;
      continue;
    }
    if (key === 'transition') {
      out[key] = value;
      continue;
    }
    const stripped = { ...value };
    for (const k of MOTION_KEYS) delete stripped[k];
    out[key] = stripped;
  }
  return out;
}

export function prefersReduced() {
  return typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/* ———————————————————————————————————————— variants → Svelte transitions ——— */

function timing(tr) {
  if (tr && tr.type === 'spring') return { duration: springMs(tr), easing: springEase(tr) };
  const d = Math.round((tr?.duration ?? 0.2) * 1000);
  return { duration: d, easing: tr?.ease ? bezier(...tr.ease) : easeOut };
}

/* A value with units ('100%') resolves against the node's own box. */
function px(v, node, axis) {
  if (typeof v === 'number') return v;
  if (typeof v === 'string' && v.endsWith('%')) {
    const r = node.getBoundingClientRect?.();
    const size = r ? (axis === 'x' ? r.width : r.height) : 0;
    return (parseFloat(v) / 100) * size;
  }
  return parseFloat(v) || 0;
}

/** Turn a variant into a Svelte transition function.

      <div in:play={fadeUp}>                      enter with fadeUp
      <div in:play={fadeUp} out:play={{ v: fadeUp, exit: true }}>
      <div in:play={{ v: fadeUp, delay: i * 40 }}>   staggered

    The transition interpolates from the variant's `initial` (or, leaving,
    towards its `exit`) to `animate`. Reduced motion → `reduced(v)`. */
export function play(node, arg) {
  const o = arg && arg.v ? arg : { v: arg };
  /* `skip: true` — the element simply appears (a gated stagger, below). */
  if (o.skip) return { duration: 0 };
  let v = o.v || fadeIn;
  /* Reduced motion: the travel and scale go, the fade stays. A variant that
     only moved (sheetUp has no opacity of its own) becomes fadeIn, so it
     neither pops nor lingers opaque for a spring's length on the way out. */
  let { duration, easing } = timing(v.transition);
  if (prefersReduced()) {
    const mv = (x) => x && MOTION_KEYS.some((k) => x[k] != null && x[k] !== 0 && !(k === 'scale' && x[k] === 1));
    const moved = mv(v.initial) || mv(v.exit);
    v = reduced(v);
    if (moved) {
      v = { ...v, initial: { ...v.initial, opacity: 0 }, exit: { ...v.exit, opacity: 0 } };
      ({ duration, easing } = timing(fadeIn.transition));
    }
  }
  const from = (o.exit ? v.exit : v.initial) || {};
  const to = v.animate || {};
  const f = {
    x: px(from.x ?? 0, node, 'x'), y: px(from.y ?? 0, node, 'y'),
    s: from.scale ?? 1, o: from.opacity ?? 1
  };
  const t = { x: px(to.x ?? 0, node, 'x'), y: px(to.y ?? 0, node, 'y'), s: to.scale ?? 1, o: to.opacity ?? 1 };
  const moves = f.x !== t.x || f.y !== t.y || f.s !== t.s;
  return {
    delay: o.delay || 0,
    duration: o.duration ?? duration,
    easing,
    css: (p) => {
      /* p runs 0→1 on the way in and 1→0 on the way out, so the same
         lerp serves both; springs may overshoot past 1 by design. */
      const op = f.o + (t.o - f.o) * p;
      let s = `opacity:${Math.max(0, Math.min(1, op))}`;
      if (moves) {
        const x = f.x + (t.x - f.x) * p, y = f.y + (t.y - f.y) * p, sc = f.s + (t.s - f.s) * p;
        s += `;transform:translate3d(${x}px,${y}px,0)` + (sc !== 1 ? ` scale(${sc})` : '');
      }
      return s;
    }
  };
}

/** Delay for the i-th child of a `stagger(step)` list, in ms (capped so a
    long list never makes its tail wait). */
export function staggerDelay(i, step = 0.04, cap = 12) {
  return Math.min(i, cap) * step * 1000;
}

/* ——————————————————————————————————— stagger, on first paint only ——— */
/* `stagger(0.04)` is a *first paint* flourish: the list arrives, its items
   rise in 40ms apart, and from then on it is furniture. An item a poll adds
   later, a re-sort, a filter that brings rows back — those just appear.

   Svelte's own rules get this backwards (a local `in:` on an {#each} item
   plays only for items added AFTER the block's first render), so list items
   use `in:staggerIn|global={{ i }}` and the gate lives here, per container:
   the first time any child of a given parent element enters, that parent
   opens a batch that stays open until the next animation frame — every item
   mounted in that same flush staggers; anything that enters the same parent
   later is `skip`ped. A new container (the page re-mounted, a view switched)
   is a new first paint. Reduced motion → play's opacity-only fade. */
const batches = new WeakMap();
function batchOpen(host) {
  if (!host) return false;
  let b = batches.get(host);
  if (!b) {
    b = { open: true };
    batches.set(host, b);
    const close = () => (b.open = false);
    if (typeof requestAnimationFrame !== 'undefined') requestAnimationFrame(close);
    else setTimeout(close, 16);
  }
  return b.open;
}

/** fadeUp + staggerDelay(i), on the container's first paint only.
      {#each rows as r, i (r.id)}<div in:staggerIn|global={{ i }}>…{/each}
    `v` (default fadeUp) and `step` (default 0.04 s) may be overridden. */
export function staggerIn(node, { i = 0, v = fadeUp, step = 0.04 } = {}) {
  const first = batchOpen(node.parentElement);
  return play(node, { v, delay: staggerDelay(i, step), skip: !first });
}

/** Svelte `use:` action for `press` / `hoverLift`: sets the CSS custom
    properties the global `.mg-press` / `.mg-lift` rules read, so the scale on
    tap and the 1px lift on hover run on `spring.snappy`. */
export function pressable(node, kind = 'press') {
  node.classList.add(kind === 'lift' ? 'mg-lift' : 'mg-press');
  node.style.setProperty('--mg-spring-snappy', springCss(spring.snappy));
  return {
    destroy() {
      node.classList.remove('mg-press', 'mg-lift');
    }
  };
}

/* ———————————————————————————————— the older names, onto the vocabulary ——— */

/** Fade — the scrim, a swapped view. = fadeIn */
export function fade(node, { duration, delay = 0 } = {}) {
  return play(node, { v: fadeIn, delay, duration });
}

/** Slide in along one axis. x ≠ 0 → slideIn; y ≠ 0 → a rise of that many px
    on spring.smooth (sheetUp takes '100%'). */
export function slide(node, { x = 0, y = 0, delay = 0, opacity = 0 } = {}) {
  const v = x
    ? { ...slideIn, initial: { x, opacity }, exit: { x, opacity } }
    : { initial: { y, opacity }, animate: { y: 0, opacity: 1 }, exit: { y, opacity }, transition: spring.smooth };
  return play(node, { v, delay });
}

/** Pop — a centred dialog. = scaleIn */
export function pop(node, { delay = 0 } = {}) {
  return play(node, { v: scaleIn, delay });
}

/** Rise — a list item arriving; `i` staggers it. = fadeUp + stagger(0.04) */
export function rise(node, { i = 0 } = {}) {
  return play(node, { v: fadeUp, delay: staggerDelay(i) });
}

/** The old sheet curve, kept for any import of it. */
export const settle = bezier(0.32, 0.72, 0, 1);
