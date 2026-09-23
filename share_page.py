"""The screening room: what a client sees when Oblivion sends them a link.

This is the only page in the whole application that is opened by someone who
is not signed in, on a device nobody controls, usually a phone, usually once.
It is also the page that represents the agency, so it gets the care.

It is deliberately a single self-contained document rather than a route in the
SvelteKit dashboard. A SvelteKit page would need ``/_app/*`` served without a
password, which means publishing the dashboard's entire JavaScript bundle to
anyone holding any share link. One HTML file with its own CSS and a few
hundred lines of vanilla JS keeps the public surface to exactly three URLs
(this page and the two ``/api/public/...`` prefixes in media.py), and loads in
one round trip on a bad mobile connection.

Everything it fetches goes to the vendored Zerko share API, which treats the
token in the URL as the credential and checks expiry, revocation, an optional
password and a per-IP failure limit on every call. This module never touches
the database itself — it renders the shell, and the shell talks to that API.
"""

from __future__ import annotations

from flask import Blueprint, Response

bp = Blueprint("share_page", __name__)


# The panel's "Studio Glass" vocabulary, inlined: the page must render
# correctly before any other request completes, it may load nothing from
# anywhere else (see the CSP on the response), and it is never shown in light
# mode — a screening room is dark.
PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<meta name="theme-color" content="#111113">
<title>Screening room</title>
<style>
  /* ————————————————————————————— Oblivion · Studio Glass ———————————————
     The panel's own vocabulary, inlined: `.mg-*` classes and `--mg-*` tokens
     copied from ui/src/lib/media-glass.css. The screening room can load
     nothing from anywhere else (see the CSP on the response), so the
     stylesheet travels with the page and the type falls back to the system
     stack. Always dark — a screening room is dark, and a light pane over a
     film is unreadable. The older names this page's JavaScript writes
     (.btn, .card, .screen …) are declared beside their `.mg-*` twin rather
     than duplicated: one rule, one system. */
  :root {
    --mg-bg: #111113;
    --mg-glass: rgba(18,18,22,0.52);
    --mg-glass-strong: rgba(14,14,18,0.74);
    --mg-glass-soft: rgba(255,255,255,0.06);
    --mg-glass-hover: rgba(255,255,255,0.1);
    --mg-line: rgba(255,255,255,0.12);
    --mg-line2: rgba(255,255,255,0.22);
    --mg-term: rgba(8,8,10,0.86);
    --mg-i: #f3f3f4; --mg-i2: #a7a7b0; --mg-i3: #6d6d78;
    --mg-ok: #3ecf8e; --mg-ok-bright: #5fe3a8; --mg-ok-ink: #06281a;
    --mg-warn: #f0b429; --mg-crit: #f26d64; --mg-mgr: #a78bfa;
    --mg-font: 'Inter', -apple-system, BlinkMacSystemFont, system-ui, 'Segoe UI', Helvetica, sans-serif;
    --mg-r: 22px; --mg-r-card: 18px; --mg-r-in: 14px; --mg-blur: 28px;
    --mg-sh: 0 24px 64px -16px rgba(0,0,0,0.65);
    --mg-lit: inset 0 1px 0 rgba(255,255,255,0.07);
    --mg-sat: env(safe-area-inset-top, 0px);
    --mg-sab: env(safe-area-inset-bottom, 0px);
    --ease: cubic-bezier(0.22, 1, 0.36, 1);
    color-scheme: dark;
  }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  html, body { height: 100%; }
  body {
    margin: 0; color: var(--mg-i);
    background: var(--mg-bg);
    background-image: radial-gradient(120% 90% at 50% 0%, #1b1b21 0%, #111113 45%, #0a0a0c 100%);
    background-attachment: fixed;
    font: 400 15px/1.55 var(--mg-font); -webkit-font-smoothing: antialiased;
    overscroll-behavior: none;
  }
  a { color: inherit; text-decoration: none; }
  button { font: inherit; color: inherit; cursor: pointer; background: none; border: 0; }
  ::selection { background: rgba(62,207,142,0.3); }
  :focus-visible { outline: 2px solid rgba(62,207,142,0.75); outline-offset: 3px; }
  * { scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.16) transparent; }
  *::-webkit-scrollbar { width: 8px; height: 8px; }
  *::-webkit-scrollbar-track { background: transparent; }
  *::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.14); border-radius: 9999px; }

  /* ———————————————————————————————————————————————————— surfaces ——— */
  .mg-glass {
    background: var(--mg-glass); border: 1px solid var(--mg-line);
    border-radius: var(--mg-r); box-shadow: var(--mg-sh), var(--mg-lit);
    -webkit-backdrop-filter: blur(var(--mg-blur)) saturate(150%);
    backdrop-filter: blur(var(--mg-blur)) saturate(150%);
  }
  .mg-glass-soft { background: var(--mg-glass-soft); border: 1px solid var(--mg-line); }

  /* ————————————————————————————————————————————————————— shell ——— */
  .wrap { position: relative; z-index: 1; min-height: 100%; display: flex; flex-direction: column; }

  /* The chrome is one slim row inside the scene — not a bar across it, and
     never sticky: the film is the page. */
  header {
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    padding: calc(16px + var(--mg-sat)) clamp(16px, 4vw, 2.6rem) 10px;
    max-width: 1580px; width: 100%; margin: 0 auto;
  }
  .brand { display: flex; align-items: center; gap: 8px;
           font: 700 15px/1 var(--mg-font); letter-spacing: -0.02em; }
  .brand i { width: 9px; height: 9px; border-radius: 3px; background: var(--mg-ok); display: block; flex: none; }
  .brand small { font: 400 12px/1 var(--mg-font); color: var(--mg-i3); letter-spacing: 0; }
  .htitle { min-width: 0; flex: 1; }
  .htitle h1 { margin: 0; font: 600 16px/1.3 var(--mg-font); letter-spacing: -0.015em;
               white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .htitle p { margin: 0; font-size: 12.5px; color: var(--mg-i3); }
  .hact { display: flex; gap: 8px; align-items: center; }

  /* ———————————————————————————————————————————————————— buttons ——— */
  /* Pills. primary = white fill (the one signature action), accent = green
     (confirm), secondary = frosted glass (everything else). */
  .mg-btn, .btn {
    display: inline-flex; align-items: center; justify-content: center; gap: 8px; flex: none;
    height: 40px; padding: 0 18px; border: 1px solid var(--mg-line); border-radius: 9999px;
    background: var(--mg-glass-soft); color: var(--mg-i);
    font: 500 13.5px/1 var(--mg-font); letter-spacing: -0.01em; white-space: nowrap;
    user-select: none; cursor: pointer;
    transition: background 0.18s, border-color 0.18s, color 0.18s, transform 0.12s;
  }
  .mg-btn:hover, .btn:hover { background: var(--mg-glass-hover); border-color: var(--mg-line2); }
  .mg-btn:active, .btn:active { transform: scale(0.97); }
  .mg-btn.primary, .btn.primary { background: var(--mg-i); border-color: transparent;
                                  color: #111113; font-weight: 600; }
  .mg-btn.primary:hover, .btn.primary:hover { background: #fff; }
  .mg-btn.accent { background: var(--mg-ok); border-color: transparent;
                   color: var(--mg-ok-ink); font-weight: 600; }
  .mg-btn.accent:hover { background: var(--mg-ok-bright); }
  .mg-btn.sm, .btn.sm { height: 32px; padding: 0 14px; font-size: 12.5px; }
  .mg-btn.icon { width: 40px; padding: 0; }
  .mg-btn:disabled, .btn:disabled { opacity: 0.4; pointer-events: none; }

  /* ————————————————————————————————————————————————————— layout ——— */
  main { flex: 1; display: grid; gap: clamp(12px, 2vw, 20px);
         grid-template-columns: minmax(0, 1fr) 340px;
         padding: 0 clamp(16px, 4vw, 2.6rem) 48px;
         max-width: 1580px; width: 100%; margin: 0 auto; align-items: start; }

  /* ————————————————————————————————————————————————————— stage ——— */
  .stage { min-width: 0; padding: clamp(14px, 2vw, 20px); }
  .screen { position: relative; border-radius: var(--mg-r-card); overflow: hidden;
            background: var(--mg-term); border: 1px solid var(--mg-line);
            aspect-ratio: 16 / 9; display: grid; place-items: center; }
  .screen video, .screen img.full { width: 100%; height: 100%; object-fit: contain;
                                    display: block; background: #000; }
  .screen .placeholder { color: var(--mg-i3); font-size: 13px; padding: 2rem; text-align: center; }

  .meta { display: flex; align-items: baseline; gap: 6px 16px; flex-wrap: wrap; margin: 14px 0 0; }
  .meta h2 { margin: 0; font: 600 20px/1.2 var(--mg-font); letter-spacing: -0.015em;
             overflow-wrap: anywhere; }
  .meta .facts { color: var(--mg-i3); font-size: 12.5px; display: flex; gap: 8px; flex-wrap: wrap;
                 font-variant-numeric: tabular-nums; }
  .meta .facts span { white-space: nowrap; }
  .meta .facts span + span::before { content: '·'; margin-right: 8px; color: var(--mg-line2); }

  .stageact { display: flex; gap: 8px; align-items: center; margin-top: 14px; flex-wrap: wrap; }

  /* The pick — a spring, not a fade. Green, because it means yes. */
  .heart { display: inline-flex; align-items: center; gap: 8px; border: 1px solid var(--mg-line);
           border-radius: 9999px; height: 40px; padding: 0 18px;
           font: 500 13.5px/1 var(--mg-font); color: var(--mg-i);
           background: var(--mg-glass-soft);
           transition: color 0.2s, border-color 0.2s, background 0.2s; }
  .heart svg { width: 17px; height: 17px; overflow: visible;
               transition: transform 0.42s var(--ease), fill 0.2s, stroke 0.2s; }
  .heart:hover { background: var(--mg-glass-hover); border-color: var(--mg-line2); }
  .heart[aria-pressed='true'] { color: var(--mg-ok); border-color: rgba(62,207,142,0.4);
                                background: rgba(62,207,142,0.12); }
  .heart[aria-pressed='true'] svg { fill: var(--mg-ok); stroke: var(--mg-ok); }
  .heart.pop svg { animation: pop 0.45s var(--ease); }
  @keyframes pop { 0% { transform: scale(1); } 32% { transform: scale(1.42); } 62% { transform: scale(0.92); } 100% { transform: scale(1); } }

  .note { margin-top: 16px; }
  .note label { display: block; font: 500 11px/1.4 var(--mg-font); letter-spacing: 0.01em;
                color: var(--mg-i3); margin-bottom: 6px; }
  .note textarea, .centre input, .mg-input {
    width: 100%; color: var(--mg-i);
    background: var(--mg-glass-soft); border: 1px solid var(--mg-line);
    border-radius: var(--mg-r-in); padding: 10px 14px; font: 400 14px/1.55 var(--mg-font);
    outline: none; transition: border-color 0.18s, box-shadow 0.18s, background 0.18s;
  }
  .note textarea { min-height: 84px; resize: vertical; }
  .note textarea:hover, .centre input:hover { border-color: var(--mg-line2); }
  .note textarea:focus, .centre input:focus {
    border-color: rgba(62,207,142,0.6); box-shadow: 0 0 0 1px rgba(62,207,142,0.4); }
  .note textarea::placeholder, .centre input::placeholder { color: var(--mg-i3); }
  .noterow { display: flex; align-items: center; gap: 12px; margin-top: 10px; }
  .saved { font-size: 12.5px; color: var(--mg-ok); opacity: 0; transition: opacity 0.25s; }
  .saved.on { opacity: 1; }

  /* ————————————————————————————————————————————————————— reel ——— */
  .reel { position: sticky; top: 16px; padding: clamp(14px, 2vw, 20px); }
  .reel h3 { margin: 0 0 12px; font: 500 11px/1.4 var(--mg-font); letter-spacing: 0.01em;
             color: var(--mg-i3); }
  .cards { display: flex; flex-direction: column; gap: 8px;
           max-height: calc(100vh - 150px); overflow-y: auto; padding-right: 4px; }
  .mg-card, .card { display: grid; grid-template-columns: 92px minmax(0,1fr); gap: 12px;
          align-items: center; width: 100%; text-align: left; padding: 8px;
          border-radius: var(--mg-r-card);
          border: 1px solid var(--mg-line); background: var(--mg-glass-soft); color: inherit;
          transition: border-color 0.2s, background 0.2s, transform 0.24s var(--ease);
          animation: mg-fadeup 0.42s var(--ease) both; }
  .card:hover { background: var(--mg-glass-hover); border-color: var(--mg-line2); }
  .card:active { transform: scale(0.98); }
  .card[aria-current='true'] { border-color: rgba(62,207,142,0.4); background: rgba(62,207,142,0.12); }
  @keyframes mg-fadeup { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
  .card .th { position: relative; aspect-ratio: 16/9; border-radius: 10px; overflow: hidden;
              background: var(--mg-term); flex: none; }
  .card .th img { width: 100%; height: 100%; object-fit: cover; display: block;
                  opacity: 0; transition: opacity 0.45s; }
  .card .th img.in { opacity: 1; }
  .card .th .dur { position: absolute; right: 4px; bottom: 4px; font-size: 11px; font-weight: 600;
                   background: rgba(8,8,10,0.8); color: #fff; padding: 1px 5px; border-radius: 6px;
                   font-variant-numeric: tabular-nums; }
  .card .nm { min-width: 0; }
  .card .nm b { display: block; font-size: 13px; font-weight: 500; line-height: 1.35;
                overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .card .nm span { font-size: 11.5px; color: var(--mg-i3); font-variant-numeric: tabular-nums; }
  .card .pick { position: absolute; left: 4px; top: 4px; width: 18px; height: 18px;
                display: grid; place-items: center; border-radius: 50%;
                background: var(--mg-ok); color: var(--mg-ok-ink); font-size: 10px;
                transform: scale(0); transition: transform 0.35s var(--ease); }
  .card .pick.on { transform: scale(1); }

  /* ————————————————————————————————————————————————————— states ——— */
  /* .msg / .mg-strip — a slim notice inside a pane, never a boxed alert. */
  .msg, .mg-strip { margin: 0 0 14px; padding: 10px 14px; border-radius: var(--mg-r-in);
         background: var(--mg-glass-soft); border: 1px solid var(--mg-line);
         color: var(--mg-i2); font-size: 13px; line-height: 1.6; overflow-wrap: anywhere; }
  .centre { flex: 1; display: grid; place-items: center; padding: 3rem 16px; text-align: center; }
  .centre .box { max-width: 420px; width: 100%; }
  .centre h2 { margin: 0 0 8px; font: 600 22px/1.25 var(--mg-font); letter-spacing: -0.02em; }
  .centre p { margin: 0 0 20px; color: var(--mg-i2); font-size: 14px; }
  .centre input { text-align: center; letter-spacing: 0.08em; margin-bottom: 10px; }
  .bad { color: var(--mg-crit); font-size: 12.5px; min-height: 1.2em; margin: 0 0 8px; }

  /* the shimmer while the payload lands */
  .skel { border-radius: var(--mg-r); background: var(--mg-glass-soft);
          border: 1px solid var(--mg-line); position: relative; overflow: hidden; }
  .skel::after { content: ''; position: absolute; inset: 0; transform: translateX(-100%);
                 background: linear-gradient(90deg, transparent, rgba(255,255,255,0.045), transparent);
                 animation: sweep 1.5s infinite; }
  @keyframes sweep { 100% { transform: translateX(100%); } }

  footer { padding: 20px clamp(16px, 4vw, 2.6rem) calc(28px + var(--mg-sab));
           color: var(--mg-i3); font-size: 12px; display: flex; justify-content: space-between;
           gap: 12px; flex-wrap: wrap; max-width: 1580px; width: 100%; margin: 0 auto; }
  kbd { font: 500 11px var(--mg-font); background: var(--mg-glass-soft);
        border: 1px solid var(--mg-line); border-radius: 6px; padding: 1px 6px; color: var(--mg-i2); }

  @media (max-width: 960px) {
    main { grid-template-columns: minmax(0, 1fr); }
    .reel { position: static; }
    .cards { max-height: none; flex-direction: row; overflow-x: auto; padding-bottom: 8px;
             scrollbar-width: none; }
    .cards::-webkit-scrollbar { display: none; }
    .card { grid-template-columns: minmax(0,1fr); width: 176px; flex: none; }
    .card:hover { transform: none; }
  }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: 0.001ms !important; transition-duration: 0.06s !important; }
    .card { animation: none; opacity: 1; transform: none; }
  }
</style>
</head>
<body>
<div class="wrap" id="wrap">
  <div class="centre" id="boot">
    <div class="box">
      <div class="skel" style="height:190px;margin-bottom:1rem"></div>
      <p style="color:var(--mg-i3);font-size:13px">Opening the screening room…</p>
    </div>
  </div>
</div>

<script>
(function () {
  'use strict';
  // The token is the last path segment; the API lives under the media mount.
  var TOKEN = decodeURIComponent(location.pathname.split('/').filter(Boolean).pop() || '');
  var API = '/zerko/api/public/share/' + encodeURIComponent(TOKEN);
  var wrap = document.getElementById('wrap');
  var pw = '';                 // held in memory only; never stored
  var data = null, idx = 0, picks = {}, notes = {}, saveTimer = null;

  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  var q = function (extra) {
    var p = pw ? 'password=' + encodeURIComponent(pw) : '';
    if (extra) p = p ? p + '&' + extra : extra;
    return p ? '?' + p : '';
  };
  var dur = function (s) {
    if (!s && s !== 0) return '';
    s = Math.round(s);
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    var pad = function (n) { return (n < 10 ? '0' : '') + n; };
    return h ? h + ':' + pad(m) + ':' + pad(x) : m + ':' + pad(x);
  };

  function screenHTML(m) {
    if (!m) return '<div class="placeholder">Nothing in this link yet.</div>';
    var src = API + '/stream/' + m.id + q();
    if ((m.media_type || 'video') === 'photo' || /^image\//.test(m.mime || '')) {
      return '<img class="full" alt="' + esc(m.filename) + '" src="' + src + '">';
    }
    return '<video id="player" controls playsinline preload="metadata" ' +
           'poster="' + API + '/thumb/' + m.id + q() + '" src="' + src + '"></video>';
  }

  function render() {
    var m = data.videos[idx] || null;
    var canPick = data.allow_selects, canDl = data.allow_download;
    var picked = m && picks[m.id];

    var cards = data.videos.map(function (v, i) {
      return '<button class="card mg-card" role="listitem" data-i="' + i + '" ' +
        'aria-current="' + (i === idx) + '" style="animation-delay:' + Math.min(i * 34, 400) + 'ms">' +
        '<span class="th"><img alt="" loading="lazy" data-src="' + API + '/thumb/' + v.id + q() + '">' +
        (v.duration ? '<span class="dur">' + dur(v.duration) + '</span>' : '') +
        '<span class="pick' + (picks[v.id] ? ' on' : '') + '">&#10084;</span></span>' +
        '<span class="nm"><b>' + esc(v.filename) + '</b><span>' +
        esc([v.resolution, v.file_size_formatted].filter(Boolean).join(' · ')) +
        '</span></span></button>';
    }).join('');

    wrap.innerHTML =
      '<header>' +
        '<span class="brand"><i></i>Oblivion<small>Screening room</small></span>' +
        '<span class="htitle"><h1>' + esc(data.title) + '</h1>' +
        '<p>' + data.count + ' clip' + (data.count === 1 ? '' : 's') +
        (data.expires_at ? ' · link expires ' + esc(data.expires_at.slice(0, 10)) : '') + '</p></span>' +
        '<span class="hact">' +
          (canDl && data.count ? '<button class="mg-btn" id="dlall">Download all</button>' : '') +
        '</span>' +
      '</header>' +
      '<main>' +
        '<section class="stage mg-glass">' +
          (data.message ? '<p class="msg">' + esc(data.message) + '</p>' : '') +
          '<div class="screen" id="screen">' + screenHTML(m) + '</div>' +
          (m ? '<div class="meta"><h2>' + esc(m.filename) + '</h2>' +
               '<span class="facts">' +
               [m.resolution, dur(m.duration), m.file_size_formatted].filter(Boolean)
                 .map(function (x) { return '<span>' + esc(x) + '</span>'; }).join('') +
               '</span></div>' : '') +
          (m ? '<div class="stageact">' +
            (canPick ? '<button class="heart" id="heart" aria-pressed="' + !!picked + '">' +
              '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" ' +
              'stroke-linecap="round" stroke-linejoin="round"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1.1L12 21.2l7.8-7.7 1-1.1a5.5 5.5 0 0 0 0-7.8z"/></svg>' +
              '<span>' + (picked ? 'Picked' : 'Pick this') + '</span></button>' : '') +
            (canDl ? '<a class="mg-btn primary" href="' + API + '/stream/' + m.id + q('download=true') +
                     '" download>Download</a>' : '') +
            '<button class="mg-btn icon" id="prev" aria-label="Previous">&#8592;</button>' +
            '<button class="mg-btn icon" id="next" aria-label="Next">&#8594;</button>' +
          '</div>' : '') +
          (m && canPick ? '<div class="note"><label for="cmt">Your note on this clip</label>' +
            '<textarea id="cmt" placeholder="Anything you want us to know — a timecode, a change, a yes."></textarea>' +
            '<div class="noterow"><button class="mg-btn" id="savenote">Save note</button>' +
            '<span class="saved" id="savedmark">Saved</span></div></div>' : '') +
        '</section>' +
        '<aside class="reel mg-glass"><h3>In this link</h3>' +
          '<div class="cards" role="list">' + cards + '</div>' +
        '</aside>' +
      '</main>' +
      '<footer><span>Sent by Oblivion Estates</span>' +
      '<span><kbd>&#8592;</kbd> <kbd>&#8594;</kbd> move · <kbd>space</kbd> play' +
      (canPick ? ' · <kbd>F</kbd> pick' : '') + '</span></footer>';

    // thumbnails only once they are near the viewport
    var imgs = wrap.querySelectorAll('img[data-src]');
    var show = function (img) {
      img.onload = function () { img.classList.add('in'); };
      img.src = img.getAttribute('data-src');
      img.removeAttribute('data-src');
    };
    if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (es) {
        es.forEach(function (e) { if (e.isIntersecting) { show(e.target); io.unobserve(e.target); } });
      }, { rootMargin: '250px' });
      imgs.forEach(function (i) { io.observe(i); });
    } else { imgs.forEach(show); }

    wrap.querySelectorAll('.card').forEach(function (c) {
      c.onclick = function () { go(+c.dataset.i); };
    });
    var on = function (id, fn) { var el = document.getElementById(id); if (el) el.onclick = fn; };
    on('prev', function () { go(idx - 1); });
    on('next', function () { go(idx + 1); });
    on('heart', toggle);
    on('savenote', function () { saveNote(true); });
    on('dlall', function () {
      location.href = API + '/download-zip' + q('ids=' + data.videos.map(function (v) { return v.id; }).join(','));
    });
    var cmt = document.getElementById('cmt');
    if (cmt && m) {
      cmt.value = notes[m.id] || '';
      cmt.oninput = function () {
        notes[m.id] = cmt.value;
        clearTimeout(saveTimer);
        saveTimer = setTimeout(function () { saveNote(false); }, 1200);
      };
    }
    var card = wrap.querySelector('.card[aria-current="true"]');
    if (card && card.scrollIntoView) card.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }

  function go(i) {
    if (!data.videos.length) return;
    idx = (i + data.videos.length) % data.videos.length;
    render();
  }

  function post(body) {
    return fetch(API + '/select', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({ password: pw || undefined }, body))
    });
  }

  function toggle() {
    var m = data.videos[idx]; if (!m) return;
    var next = !picks[m.id];
    picks[m.id] = next;
    var h = document.getElementById('heart');
    if (h) { h.setAttribute('aria-pressed', String(next)); h.classList.remove('pop');
             void h.offsetWidth; h.classList.add('pop');
             h.querySelector('span').textContent = next ? 'Picked' : 'Pick this'; }
    var pick = wrap.querySelector('.card[data-i="' + idx + '"] .pick');
    if (pick) pick.classList.toggle('on', next);
    post({ video_id: m.id, picked: next, comment: notes[m.id] || null })
      .catch(function () { /* a lost heart is not worth an error dialog */ });
  }

  function saveNote(explicit) {
    var m = data.videos[idx]; if (!m) return;
    post({ video_id: m.id, picked: !!picks[m.id], comment: notes[m.id] || '' })
      .then(function () {
        var s = document.getElementById('savedmark');
        if (s) { s.classList.add('on'); setTimeout(function () { s.classList.remove('on'); }, 1600); }
      })
      .catch(function () { if (explicit) alert('That note did not save — try again in a moment.'); });
  }

  function gate(message, wrong) {
    wrap.innerHTML =
      '<div class="centre"><div class="box">' +
      '<h2>' + esc(message || 'This link needs a password') + '</h2>' +
      '<p>Enter the password you were given to open this screening room.</p>' +
      '<p class="bad">' + (wrong ? 'That password is not right.' : '') + '</p>' +
      '<input id="pwin" type="password" autocomplete="off" placeholder="Password" autofocus>' +
      '<button class="mg-btn primary" id="pwgo" style="width:100%;justify-content:center">Open</button>' +
      '</div></div>';
    var input = document.getElementById('pwin');
    var submit = function () { pw = input.value; load(); };
    document.getElementById('pwgo').onclick = submit;
    input.onkeydown = function (e) { if (e.key === 'Enter') submit(); };
    input.focus();
  }

  function dead(title, body) {
    wrap.innerHTML = '<div class="centre"><div class="box"><h2>' + esc(title) + '</h2>' +
                     '<p>' + esc(body) + '</p></div></div>';
  }

  function load() {
    fetch(API + q()).then(function (r) {
      if (r.status === 401) { gate(null, false); return null; }
      if (r.status === 403) { gate(null, true); return null; }
      if (r.status === 404) { dead('This link is not available', 'It may have been turned off, or the address is not quite right.'); return null; }
      if (r.status === 410) { dead('This link has expired', 'Ask whoever sent it for a fresh one — it only takes a moment.'); return null; }
      if (r.status === 429) { dead('Too many attempts', 'Give it fifteen minutes and try again.'); return null; }
      if (!r.ok) { dead('Something went wrong', 'The screening room could not be opened just now.'); return null; }
      return r.json();
    }).then(function (d) {
      if (!d) return;
      // A password-protected share answers 200 with a lock flag in some
      // versions; treat both shapes the same.
      if (d.locked) { gate(null, !!d.wrong); return; }
      data = d;
      data.videos = data.videos || [];
      idx = 0;
      render();
    }).catch(function () {
      dead('No connection', 'The screening room could not be reached. Check the connection and reload.');
    });
  }

  document.addEventListener('keydown', function (e) {
    if (!data) return;
    var t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return;
    if (e.key === 'ArrowRight') { e.preventDefault(); go(idx + 1); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); go(idx - 1); }
    else if (e.key === ' ') {
      var p = document.getElementById('player');
      if (p) { e.preventDefault(); p.paused ? p.play() : p.pause(); }
    } else if ((e.key === 'f' || e.key === 'F') && data.allow_selects) { e.preventDefault(); toggle(); }
  });

  load();
})();
</script>
</body>
</html>"""


@bp.get("/media/s/<token>")
def share_room(token: str):
    """The screening room shell.

    The token is not validated here on purpose: every fetch the page makes
    carries it to the share API, which is the one place that knows whether it
    is live, expired, revoked or password-locked. Rendering the shell
    unconditionally means a dead link still lands on a designed page that says
    what happened, rather than a bare 404 from a framework.
    """
    return Response(PAGE, headers={
        "Content-Type": "text/html; charset=utf-8",
        # Never cached: a revoked link must stop working on the next reload.
        "Cache-Control": "no-store",
        "X-Robots-Tag": "noindex, nofollow",
        # The page loads nothing from anywhere else, so say so.
        "Content-Security-Policy":
            "default-src 'none'; img-src 'self' data:; media-src 'self'; "
            "style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
            "connect-src 'self'; form-action 'none'; frame-ancestors 'none'",
        "Referrer-Policy": "no-referrer",
    })
