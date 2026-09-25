/* Which photograph the scene is lit by — one rule for the Backdrop, Home's
   frosted pane and (in Python) auth.py's sign-in page: 20:00–05:00 night,
   before 10 morning, before 17 day, else dusk.

   Each hero has a `-frost` twin in ui/static: the same photo at 480px,
   pre-blurred (≈ blur(28px) at screen scale), saturated ×1.5 and dimmed like
   the veil — what `backdrop-filter` would compute, baked once. Home's overview
   pane shows it through a clip instead of blurring live, because a live blur
   that moves across the photo on every scrolled frame is the most expensive
   thing an iPad can be asked to draw. */

export const heroFor = (d = new Date()) => {
  const h = d.getHours();
  return h >= 20 || h < 5 ? 'night' : h < 10 ? 'morning' : h < 17 ? 'day' : 'dusk';
};

export const heroSrc = (tone) => `/hero-${tone}.jpg`;
export const frostSrc = (tone) => `/hero-${tone}-frost.jpg`;

/** The panel's own `mc.backdrop` override ({ dim, url }), or {}. */
export function readBackdropOverride() {
  try { return JSON.parse(localStorage.getItem('mc.backdrop') || 'null') || {}; }
  catch { return {}; }
}
