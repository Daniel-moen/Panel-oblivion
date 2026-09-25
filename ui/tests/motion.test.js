/* Unit tests for the motion vocabulary ($lib/motion.js).

   Run:  cd ui && npm test        (node --test tests/, no dependencies)

   motion.js mirrors Mission Control's src/lib/motion.js
   (~/widget-claude/remote/app) one-to-one. The reference shapes are written
   out here by hand so a drift on either side fails loudly. play() reads
   prefers-reduced-motion through the global matchMedia, which each test
   stubs on globalThis and removes afterwards. */
import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import {
  spring, ease, springAt, springMs, springCss, springEase,
  fadeUp, fadeIn, scaleIn, sheetUp, slideIn, stagger, press, hoverLift,
  reduced, prefersReduced, play
} from '../src/lib/motion.js';

// ——— the reference (Mission Control's motion.js), verbatim shapes ———

const REF_SPRING = {
  snappy: { type: 'spring', stiffness: 520, damping: 42, mass: 0.8 },
  smooth: { type: 'spring', stiffness: 300, damping: 34 },
  gentle: { type: 'spring', stiffness: 170, damping: 26 }
};
const REF_EASE_OUT = [0.2, 0.8, 0.2, 1];
const REF = {
  fadeUp: {
    initial: { opacity: 0, y: 10 },
    animate: { opacity: 1, y: 0 },
    exit: { opacity: 0, y: 6 },
    transition: { duration: 0.28, ease: REF_EASE_OUT }
  },
  fadeIn: {
    initial: { opacity: 0 },
    animate: { opacity: 1 },
    exit: { opacity: 0 },
    transition: { duration: 0.2 }
  },
  scaleIn: {
    initial: { opacity: 0, scale: 0.96 },
    animate: { opacity: 1, scale: 1 },
    exit: { opacity: 0, scale: 0.98 },
    transition: REF_SPRING.smooth
  },
  sheetUp: {
    initial: { y: '100%' },
    animate: { y: 0 },
    exit: { y: '100%' },
    transition: REF_SPRING.smooth
  },
  slideIn: {
    initial: { x: 40, opacity: 0 },
    animate: { x: 0, opacity: 1 },
    exit: { x: 40, opacity: 0 },
    transition: REF_SPRING.smooth
  },
  press: { whileTap: { scale: 0.97 }, transition: REF_SPRING.snappy },
  hoverLift: { whileHover: { y: -1 }, whileTap: { scale: 0.98 }, transition: REF_SPRING.snappy }
};

/* matchMedia stub: `reduce` answers the reduced-motion query. */
function stubMatchMedia(reduce) {
  globalThis.matchMedia = (q) => ({
    matches: reduce && /prefers-reduced-motion:\s*reduce/.test(q),
    media: q, addEventListener() {}, removeEventListener() {}
  });
}
afterEach(() => { delete globalThis.matchMedia; });

/* A node with a box, as play() measures '%' values against it. */
const fakeNode = (w = 200, h = 400) => ({
  getBoundingClientRect: () => ({ x: 0, y: 0, width: w, height: h, top: 0, left: 0, right: w, bottom: h })
});

// ——— springs ———

test('spring numbers equal the reference', () => {
  assert.deepEqual(spring, REF_SPRING);
  assert.deepEqual(ease.out, REF_EASE_OUT);
});

test('springAt starts at 0 and settles at 1', () => {
  for (const [name, s] of Object.entries(spring)) {
    assert.equal(springAt(s, 0), 0, `${name} at t=0`);
    assert.equal(springAt(s, -1), 0, `${name} before t=0`);
    assert.ok(Math.abs(1 - springAt(s, 3)) < 1e-3, `${name} at 3 s is ${springAt(s, 3)}`);
    const mid = springAt(s, 0.05);
    assert.ok(mid > 0 && mid < 1.2, `${name} moves forward early (${mid})`);
  }
});

test('springAt handles critically and over-damped springs', () => {
  const crit = { stiffness: 100, damping: 20 };          // zeta = 1
  const over = { stiffness: 100, damping: 40 };          // zeta = 2
  for (const s of [crit, over]) {
    let prev = 0;
    for (let t = 0.01; t < 3; t += 0.01) {
      const v = springAt(s, t);
      assert.ok(v >= prev - 1e-9 && v <= 1 + 1e-9, `monotone, no overshoot at ${t}: ${v}`);
      prev = v;
    }
    assert.ok(1 - springAt(s, 3) < 0.01);
  }
});

test('springMs: snappy < smooth < gentle, all under 1.5 s', () => {
  const a = springMs(spring.snappy), b = springMs(spring.smooth), c = springMs(spring.gentle);
  assert.ok(a > 50, `snappy ${a}ms`);
  assert.ok(a < b && b < c, `${a} < ${b} < ${c}`);
  assert.ok(c < 1500, `gentle ${c}ms`);
  assert.equal(springMs(spring.smooth), b, 'cached value is stable');
  // settled for good after springMs
  for (const s of Object.values(spring)) {
    const T = springMs(s) / 1000;
    for (let t = T; t < T + 1; t += 0.01) assert.ok(Math.abs(1 - springAt(s, t)) <= 0.001);
  }
});

test('springEase maps 0→0 and 1→1', () => {
  const e = springEase(spring.smooth);
  assert.equal(e(0), 0);
  assert.equal(e(1), 1);
  assert.ok(e(0.5) > 0.5);
});

test('springCss is "<ms>ms linear(0, …, 1)"', () => {
  for (const [name, s] of Object.entries(spring)) {
    const css = springCss(s);
    assert.match(css, /^\d+ms linear\(0, .* 1\)$/, name);
    assert.equal(parseInt(css, 10), springMs(s), `${name} duration`);
    const stops = css.slice(css.indexOf('(') + 1, -1).split(', ').map(Number);
    assert.equal(stops.length, 41, `${name} default 40 segments`);
    assert.ok(stops.every(Number.isFinite), `${name} stops are numbers`);
  }
  assert.equal(springCss(spring.snappy, 10).slice(springCss(spring.snappy, 10).indexOf('(')).split(',').length, 11);
});

// ——— variants ———

test('variants deep-equal the reference shapes', () => {
  assert.deepEqual(fadeUp, REF.fadeUp);
  assert.deepEqual(fadeIn, REF.fadeIn);
  assert.deepEqual(scaleIn, REF.scaleIn);
  assert.deepEqual(sheetUp, REF.sheetUp);
  assert.deepEqual(slideIn, REF.slideIn);
  assert.deepEqual(press, REF.press);
  assert.deepEqual(hoverLift, REF.hoverLift);
});

test('stagger(delay)', () => {
  assert.deepEqual(stagger(0.04), { animate: { transition: { staggerChildren: 0.04 } } });
  assert.deepEqual(stagger(), stagger(0.04));
  assert.deepEqual(stagger(0.1), { animate: { transition: { staggerChildren: 0.1 } } });
});

test('reduced() strips x/y/scale/rotate, keeps opacity and transition', () => {
  assert.deepEqual(reduced(fadeUp), {
    initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 },
    transition: { duration: 0.28, ease: REF_EASE_OUT }
  });
  assert.deepEqual(reduced(scaleIn), {
    initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 }, transition: REF_SPRING.smooth
  });
  assert.deepEqual(reduced(slideIn).initial, { opacity: 0 });
  assert.deepEqual(reduced(sheetUp), { initial: {}, animate: {}, exit: {}, transition: REF_SPRING.smooth });
  assert.deepEqual(reduced({ animate: { rotate: 90, opacity: 0.5 } }), { animate: { opacity: 0.5 } });
  assert.deepEqual(reduced(press), { whileTap: {}, transition: REF_SPRING.snappy });
  assert.deepEqual(fadeUp, REF.fadeUp, 'reduced() does not mutate its input');
  assert.equal(reduced(null), null);
});

test('reduced() with no argument answers the media query', () => {
  assert.equal(prefersReduced(), false, 'no matchMedia → false');
  stubMatchMedia(true);
  assert.equal(reduced(), true);
  stubMatchMedia(false);
  assert.equal(reduced(), false);
});

// ——— play() ———

test('play(fadeUp) moves: css carries opacity and transform', () => {
  stubMatchMedia(false);
  const tr = play(fakeNode(), fadeUp);
  assert.equal(tr.duration, 280);
  assert.equal(typeof tr.easing, 'function');
  assert.equal(tr.delay, 0);
  const start = tr.css(0), end = tr.css(1);
  assert.match(start, /opacity:0/);
  assert.match(start, /transform:translate3d\(0px,10px,0\)/);
  assert.match(end, /opacity:1/);
  assert.match(end, /transform:translate3d\(0px,0px,0\)/);
});

test('play() spring variants take springMs as duration; % resolves against the node', () => {
  stubMatchMedia(false);
  const tr = play(fakeNode(200, 400), sheetUp);
  assert.equal(tr.duration, springMs(spring.smooth));
  assert.match(tr.css(0), /translate3d\(0px,400px,0\)/);
  const sc = play(fakeNode(), scaleIn).css(0);
  assert.match(sc, /scale\(0\.96\)/);
  const ex = play(fakeNode(), { v: fadeUp, exit: true, delay: 40 });
  assert.equal(ex.delay, 40);
  assert.match(ex.css(0), /translate3d\(0px,6px,0\)/);
});

test('play() under reduced motion is opacity-only', () => {
  stubMatchMedia(true);
  for (const v of [fadeUp, scaleIn, slideIn, sheetUp]) {
    const tr = play(fakeNode(), v);
    for (const p of [0, 0.3, 0.7, 1]) {
      const css = tr.css(p);
      assert.doesNotMatch(css, /transform/, `${JSON.stringify(v.initial)} at ${p}: ${css}`);
      assert.match(css, /^opacity:[\d.]+$/);
    }
  }
  assert.match(play(fakeNode(), fadeUp).css(0), /^opacity:0$/);
});

test('play() under reduced motion: a travel-only variant (sheetUp) still fades, on fadeIn timing', () => {
  stubMatchMedia(true);
  const tr = play(fakeNode(), sheetUp);
  assert.equal(tr.css(0), 'opacity:0', 'starts clear rather than popping in');
  assert.equal(tr.css(1), 'opacity:1');
  assert.equal(tr.duration, Math.round(fadeIn.transition.duration * 1000), 'no spring-length linger on the way out');
  const out = play(fakeNode(), { v: sheetUp, exit: true });
  assert.equal(out.css(0), 'opacity:0', 'leaves by fading');
});

test('play() with no variant falls back to fadeIn', () => {
  stubMatchMedia(false);
  const tr = play(fakeNode(), undefined);
  assert.equal(tr.duration, 200);
  assert.equal(tr.css(0.5), 'opacity:0.5');
});
