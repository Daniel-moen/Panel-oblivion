# Oblivion Estates — Prospecting Engine

Finds luxury Cape Town / West Coast properties that Oblivion Estates can
actually win business on: homes whose sellers have **not** signed a sole
(exclusive) mandate, where the current agency is under-marketing the property
and Oblivion's cinematic-film pitch has an opening.

It crawls five property portals, works out which listings are the *same
physical home*, and uses that to decide whether the mandate is open.

```bash
source .venv/bin/activate

python webapp.py                 # dashboard at http://127.0.0.1:5051
python main.py run               # full pipeline, then opens the HTML report
```

---

## Dashboard UI

The dashboard front end is a SvelteKit 2 / Svelte 5 SPA in `ui/`, prerendered
to static files by `adapter-static`. `python webapp.py` still serves
everything on one port: Flask hands out `ui/build/` for `/` and `/map` when
that directory exists, and falls back to the old single-file
`dashboard.html` / `map.html` when it doesn't — so a checkout with no Node
build still runs. The old dashboard stays reachable at `/legacy`.

The SPA talks to the same Flask JSON API (`/api/...`); `/api/config` was added
to feed it the suburb/portal registry that the legacy page got inlined at
render time. CMA reports stay server-rendered Python (`/cma`, `/cma/<group_id>`)
and are linked from the new UI.

```bash
cd ui && npm install && npm run build   # after editing anything in ui/src (Node 20+)
cd ui && npm run dev                    # live dev at :5173, proxies /api and /cma to :5051
```

No server restart after a rebuild — Flask reads the build directory per
request. `npm run dev` needs `webapp.py` running alongside it for the API.

### Find me… (AI brief)

`/prospects` carries a **Find me…** field that takes a plain-English brief —
"3-4 bed in Langebaan, R2.5 - 4m, secure and quiet". Two model calls bracket
the work: the first turns the brief into structured criteria (beds, price
band, types, suburbs, wish words), Python filters the prospect table against
them, and the second ranks the shortlist and writes the summary. With no
working key in `AI_BACKEND_ORDER` — the same credentials scoring uses — both
fall back to regex parsing and keyword matching, and the reply says so
(`ranked_by: "heuristic"`). The endpoint is `POST /api/find` with
`{brief, sole}`; the logic lives in `finder.py`.

### Call brief

Every property carries a one-screen sheet for the minute before you phone the
owner: the hard numbers (asking, R/m², municipal GV, days on market, price
cuts, erf), talking points computed from them ("listed with 2 agencies on 3
portals — the mandate is open"), cool facts lifted from the advert plus a
hand-written line about the suburb, five discovery questions, the objection
answers, and what *not* to say. It is built from the database alone, so it
works with no API key; **Write with AI** re-reads the same facts and rewrites
them in spoken language with an opener (`brief.py`, `finder._ask`, same
credentials as scoring). Briefs are cached per property and rebuilt whenever
the price, the agencies, the score or the crawl move.

`GET /api/brief/<gid>` (JSON), `POST /api/brief/<gid>/ai` (the rewrite, 503
when no provider works), `GET /api/brief/<gid>/text` (plain text to paste),
and `GET /brief/<gid>` — a standalone, printable page for the phone in your
other hand. In the UI it is a tab in the prospect drawer and a panel on the
lead-management property page.

---

## Sign-in and passkeys

One account for the whole team, set by two environment variables:

| variable | meaning |
| --- | --- |
| `DASHBOARD_PASSWORD` | the password. **Required on a hosted deploy** — without it the app refuses to serve rather than publishing the prospect list. Unset and running locally, the dashboard is open and binds to loopback only. |
| `DASHBOARD_USER` | the username, default `oblivion`. |
| `DASHBOARD_SECRET` | optional. Signs the session cookie. Left unset, a 32-byte secret is generated once and kept in the `app_secrets` table, which lives on the Railway volume — so a redeploy does not sign everyone out. Set it if you ever run more than one replica without a shared volume. |
| `PASSKEY_RP_ID` | optional. The WebAuthn relying-party id, default: the request host with the port stripped. Only needed if the app is reached on a domain other than the one the browser sees (a custom domain in front of Railway). |

**In a browser** `/login` is the door: one button for a passkey, and the
password below it. A successful sign-in sets `oblivion_session` — signed,
HttpOnly, SameSite=Lax, Secure when hosted, 30 days — so the password is typed
once per device and never again once a passkey is on it.

**Adding a device.** Sign in with the password, then **Account** (the person
icon, top right) → *Add this device*. That runs the WebAuthn registration
ceremony: Touch ID, Windows Hello, a phone over QR, or a hardware key, all
offered. The credential is discoverable, so signing in afterwards needs no
username typed. The private half never leaves the device (or iCloud Keychain /
Windows Hello); the server stores only a public key, so a leak of the database
cannot sign anything. The same page lists every signed-in browser and can
revoke any of them, including the one you are sitting at.

**Scripts are untouched.** HTTP basic auth is still accepted on every route —
`curl -u oblivion:$DASHBOARD_PASSWORD https://…/api/status` works exactly as
before. Only *browser navigations* (a GET that asks for `text/html`) are
redirected to `/login`; everything else still gets `401` with a
`WWW-Authenticate: Basic` header. Passkey login and the password form share a
per-IP failure limit of 10 attempts per 15 minutes.

---

## Media

The cinematic pitch needs the films, so the footage library lives in the same
panel as the leads. `zerko/` is a vendored copy of the **Zerko File Manager**
backend (see `zerko/VENDORED.md` for the upstream commit and the handful of
changes); `media.py` adapts its FastAPI app to WSGI with `a2wsgi` and hangs it
off `webapp.app` under `/zerko` via werkzeug's `DispatcherMiddleware`. One
process, one port, one worker — Zerko's job progress lives in memory the same
way `webapp.job` does, so a second gunicorn worker would break both.

The pages are SvelteKit, at `/media`: a dashboard whose hero plays a montage of
the library's own proxies, a browse grid that scrubs on hover, transcript
search with play-from-here, tags, duplicates, share links, the general file
store and a settings/jobs screen.

```bash
export MEDIA_ROOT=/Volumes/Footage      # the drive holding the masters
python webapp.py                        # /media alongside everything else
```

`MEDIA_ROOT` is the only thing you set. Everything Zerko derives from it — the
catalogue, thumbnails, proxies, the file store — is redirected under
`DATA_DIR` by `zerko/__init__.py`, so it survives a redeploy on the mounted
volume. Leave `MEDIA_ROOT` unset and the Media pages say there is no footage
drive on this deployment rather than showing an empty library; the file store
and share links still work. **ffmpeg and ffprobe are required** for thumbnails,
proxies and duration probing (`brew install ffmpeg`; `nixpacks.toml` installs
them on Railway). Transcription is deliberately not installed — openai-whisper
pulls in torch, which will not fit the build image.

### Signing in, once

The dashboard's own sign-in — basic auth or the session cookie — is the only
login. `GET /api/media/token` turns it into the JWT the mounted app expects,
auto-provisioning a Zerko admin named after the signed-in user; the client sends it as a bearer token, and as
`?token=` on `<img>`/`<video>` URLs. Zerko's own login and first-run wizard are
never shown — the wizard is refused at the mount, along with the SSE endpoint
(it would pin a worker thread per open tab), the self-updater and the
"reveal in Finder" route.

`DispatcherMiddleware` sits *outside* Flask, so `_require_auth` never sees
`/zerko/*`; `media.py` re-checks the same credentials itself — basic auth
*and* the session cookie, because someone signed in with a passkey has no
password to send. Without that the
whole media API — including the `/thumbnails` static mount, which has no auth
of its own upstream — would be open to anyone who guessed the prefix.

### Client share links

`/media/s/<token>` is a screening room: dark, big player, hearts, inline notes,
keyboard navigation. Clients open it with no account and no password, so it and
the two `/zerko/api/public/...` prefixes are the only routes exempt from basic
auth — the share token is the credential, and Zerko checks its expiry,
revocation, optional password and per-IP failure limit on every call. The page
is rendered by `share_page.py` as one self-contained document rather than a
SvelteKit route, precisely so that serving it does not require publishing the
dashboard's JavaScript bundle. Picks and notes come back on the Shares page,
with FCPXML and CSV exports for the edit.

---

## Why multiple portals

A property marketed by **two different agencies** cannot be on a sole mandate.
That is the single most reliable open-mandate signal available, and it is only
visible if you look at more than one portal — Agency A lists on Property24,
Agency B lists on their own site.

| Portal | Speed | What it uniquely contributes |
|---|---|---|
| **Property24** | slow (heavily throttled) | Broadest coverage — most agencies list here. Address/coordinates only when the agent publishes them (usually withheld on prime Atlantic Seaboard stock), so matching there leans on erf size + price + beds. Under-offer / price-reduced badges are read off the gallery. |
| **Private Property** | fast | Independent listing pool, street address + coordinates. Agency is rendered client-side, so not captured. Under-offer / reduced / sold banners are read; sold stock is skipped. |
| **Pam Golding** | fast | **`isExclusiveMandate` — published mandate ground truth**, plus `mandateCreated` (when the mandate was signed). |
| **Seeff** | fast | Own listing pool with agent names. No coordinates. |
| **RE/MAX** | fast | Richest structured data: price, beds, baths, land size, geo, agent, branch, listing date — plus a CRM blob with **the mandate type itself** ("Open"/"Sole"/"Joint"/"Dual"), the sale state and the record's expiry date (the sole-mandate pitch window). |
| **Rawson** | fast | Hero badges publish **"Sole Mandate" / "Joint Mandate"** plus under-offer / reduced status. |

Each portal is crawled **concurrently** on its own rate limit, so a run takes
about as long as the Property24 crawl alone rather than the sum of five.

---

## How sellability is decided

In descending order of authority — the first two are facts and override the
model:

1. **Two or more distinct agency brands on one property** → open mandate.
   Proven, not inferred — *while both listings are live*. The proof is aged
   by its stalest brand: if every brand was confirmed within
   `PROOF_FRESH_HOURS` (72h) the verdict is `open` at full confidence;
   older proof degrades to `probably_open` with a re-verify note, and
   `verify.py` re-fetches exactly those stale members live for hot-tier
   prospects after every scored crawl (budget: `VERIFY_MAX_FETCHES`). The
   report shows when each proving brand was last seen.
2. **A portal's own mandate flag** (Pam Golding's `isExclusiveMandate`,
   RE/MAX's CRM `mandate` type, Rawson's Sole/Joint Mandate badge) →
   `sole` or `not_sole`.
3. **An LLM reads the full description**, which is where SA agents actually
   state mandate status ("SOLE MANDATE", "joint mandate", "proudly presented
   exclusively by…"). The prompt defines the SA mandate glossary, because a
   *joint* mandate means the seller accepts multiple agencies — a good signal,
   not an exclusivity signal.
4. **Heuristic fallback** when no API credits are available.

Properties confirmed to be on a live sole mandate are marked `sellable = 0` and
**hidden from the report by default** (`main.py report --all` to see them).

**New/off-plan developments are excluded too.** A developer launch has no
homeowner mandate to win and often no built home to film. Portals don't
reliably flag these — Pam Golding listed an unbuilt Clifton development as
`propertyType: House` with `developmentId: None` — so the copy is what gives it
away ("new development", "yet to be built", "off-plan", "units available").
Detection is deliberately narrow: *"a resale in a boutique development"* is a
perfectly good prospect and is not flagged.

**Stale sole mandates are surfaced deliberately.** SA mandates run 3–6 months,
so one signed 150+ days ago is about to come up for renewal — the best possible
moment to pitch. Those come back with a timing note instead of being hidden.
Where RE/MAX publishes the record's actual expiry date, that date drives the
window (within 60 days of expiry) instead of the signed-N-days-ago guess.

**Deal signals feed scoring and the report.** Under-offer and price-reduced
badges are parsed on every portal that shows them; `price_history` is a
chronology of price *changes* (re-cuts to an earlier price count);
relisted-after-delisting (often a failed mandate) and crawl-observed
days-on-market go into the scoring payload; and the report renders a deal
strip per property — UNDER OFFER, cut % over N moves, days on market,
relist gap.

### Matching listings across portals

Portals publish different subsets of facts, so matching accumulates evidence
rather than applying one rule:

| Evidence | Weight |
|---|---|
| Same street address | 1.00 (decisive) |
| Coordinates within 60 m | 0.80 |
| Erf size within 3% | 0.45 |
| Floor size within 3% | 0.45 |
| Price within 7% | 0.35 |
| Beds / baths / type agree | 0.12 / 0.08 / 0.05 |

Pairs merge at a combined score of 1.0. Bedroom counts that disagree, or prices
more than 30% apart, are hard disqualifiers.

Precision is favoured over recall on purpose: a false merge would tell the team
"this is an open mandate" when it isn't, wasting a pitch.

Two safeguards matter more than they look:

- **Placeholder addresses are discarded.** Private Property writes "Contact
  agent for st address" into the address field; treating that as real collapsed
  20 unrelated Camps Bay listings into one fake "property marketed by 4
  agencies".
- **Agency names are reduced to a brand.** Property24 says "Pam Golding
  Properties - Atlantic Seaboard" and pamgolding.co.za says "Pam Golding
  (Atlantic Seaboard)". Counting those as two agencies would manufacture the
  exact proof the engine exists to find.

---

## Commands

```bash
python main.py run [suburbs...] [--sources a,b] [--pages N] [--no-ai] [--all]
python main.py scrape [suburbs...]        # crawl only
python main.py crawl --rentals            # crawl the to-rent book instead
python main.py crawl --type both          # both books in one pass
python main.py dedupe                     # re-match across portals
python main.py score [--no-ai] [--limit N] [--new-only]
python main.py report [--all]             # --all includes sole-mandate stock
python main.py discover-locations         # refresh portal area ids
python main.py import-tracker <xlsx>      # the team's prospecting sheet
python main.py sources | suburbs
```

Examples:

```bash
# Fast portals only, prime suburbs
python main.py run camps-bay clifton bantry-bay --sources privateproperty,pamgolding,seeff,remax

# Everything, deeper crawl (slow — Property24 sets the pace)
python main.py run --pages 4

# Nightly: only score what's new or re-scraped since it was last judged
python main.py run --new-only
```

`--new-only` matters with a reasoning model. A full re-score judges every
property from scratch (~15–20 min on Kimi's 3-request concurrency cap);
`--new-only` skips anything already scored and unchanged.

---

## Rentals

The same crawl also reads each portal's **to-rent** book. It is off by
default and always has to be asked for — no flag means the for-sale crawl,
exactly as before.

```bash
python main.py crawl --rentals                      # rentals only
python main.py crawl camps-bay sea-point --rentals  # ...for specific areas
python main.py crawl --type both                    # sale + rent, one pass
```

Why bother, when a tenant is not a mandate: a home advertised **both** for
sale and to rent is a seller hedging — an owner who could not sell and is
bridging with a tenant, which is a live prospecting conversation and one only
a rental crawl can see. Rentals also name the *managing* agency, frequently a
different brand from the one holding the sale mandate.

**Rentals are a separate book, not a variant of a sale.** They live in the
same `listings` table under `listing_type='rent'`, keyed
`<source>:rent:<id>`, and are deliberately kept out of everything for-sale:
they are never scored (the AI scorer costs money per property and has nothing
to say about a lease), never deduped or grouped, never erf-resolved, never
CMA comps, and never part of the sold-proxy lifecycle. The dashboard reaches
them through the **For sale / To rent** selector in the toolbar, which is a
different query rather than a client-side filter.

`price_zar` holds the rent **as advertised**, and `rent_period`
(`month`/`week`/`day`) says for what: Atlantic Seaboard holiday stock is
quoted per day, so R25 000 can be a month in Sea Point or a night in Camps
Bay. Compare two rentals with `sources.base.monthly_equivalent()`, which is
also what `config.MIN_RENT_ZAR` (default R20 000/month equivalent) is applied
against. `available_from`, `furnished` and `deposit` are filled where the
portal publishes them.

Portal coverage — every path below was verified against the live site:

| Portal | To-rent path | Notes |
| --- | --- | --- |
| Property24 | `/to-rent/<area>/<id>` | Mirrors `/for-sale/` exactly: same area ids, same `?sp=pf=` floor |
| Private Property | `/to-rent/<area>/<id>` | Same area ids; rental refs are `RR…`, sales `T…` |
| Pam Golding | `/property-search/residential-properties-to-rent-<area>/<id>` | Own area ids — mined into `locations.json` as `pamgolding_rent`. Thin book: 6 of 84 areas |
| Prop Data (Seeff + 10 tenants) | `/results/residential/to-let/<town>/<suburb>/` | Note `to-let`, not `to-rent`; sitemap `/residential-to-let/sitemap.txt` |
| RE/MAX | `/property-to-rent-south-africa/<area>/` | Same area path as the sale book |
| Rawson | `/property/to-rent/<suburb>.md` | Same markdown endpoints |
| MyProperty, ImmoAfrica | — | **Skipped.** Rent URL shape could not be confirmed (429/403), and these portals answer an unknown path with a fallback result set rather than a 404 — guessing would file another area's stock under ours. Flip `supports_rent` once a real page has been read |

Both books go through **one** `Source` instance per portal, so they share one
rate limiter, one learned request spacing and one give-up circuit. A second
instance for rentals would put two limiters on the same host, each believing
it owned the whole budget — which on Property24 is how a sticky block is
earned.

---

## Layout

```
config.py       areas, per-portal rate limits, thresholds, model choice
httpclient.py   per-host rate limiting, backoff, disk cache
locations.py    suburb -> per-portal search path (mined from sitemaps)
sources/        one module per portal, all returning the same listing dict
dedupe.py       cross-portal matching -> property groups
scorer.py       payload building, hard mandate rules, AI + heuristic scoring
pipeline.py     concurrent crawl orchestration
db.py           SQLite schema + migration
report.py       ranked HTML report
webapp.py       dashboard + JSON API, serves ui/build when present
ui/             SvelteKit dashboard SPA (src/ = source, build/ = what Flask serves)
tracker.py      import of the team's xlsx + revealed-preference profile
panel.py        management panel: stages, contacts, interactions, mandates
caller.py       AI voice agent: phones owners, pitches the meeting (docs/CALLER.md)
media.py        mounts the vendored media library at /zerko (ASGI -> WSGI)
share_page.py   the client screening room at /media/s/<token>, no login
zerko/          vendored Zerko media backend (see zerko/VENDORED.md)
```

### Areas

70 areas across 9 regions (`config.SUBURBS`, grouped by `region` and shown
grouped in the dashboard sidebar):

| Region | Areas |
|---|---|
| Atlantic Seaboard | Clifton, Camps Bay, Bantry Bay, Fresnaye, Bakoven, Llandudno, Sea Point, Three Anchor Bay, Green Point, Mouille Point, V&A Waterfront |
| City Bowl | City Centre, De Waterkant, Gardens, Higgovale, Tamboerskloof, Oranjezicht, Vredehoek, Devil's Peak Estate |
| Southern Suburbs | Constantia, Nova/High Constantia, Bishopscourt, Newlands, Claremont Upper, Kenilworth Upper, Rondebosch, Wynberg Upper, Tokai, Steenberg |
| Hout Bay | Central, Beachfront, Heights, Scott Estate |
| South Peninsula | St James, Kalk Bay, Chapman's Peak, Kommetjie |
| Winelands | Stellenbosch Farms, Mostertsdrift, Dalsig, Paradyskloof, Die Boord, Brandwacht, Devonvallei, De Zalze, Franschhoek, Val de Vie, Pearl Valley, Boschenmeer |
| Helderberg | Somerset West Central, Erinvale, Parel Vallei, Heldervue |
| Whale Coast | Voëlklip, Eastcliff, Kwaaiwater, Hermanus Heights, Hemel-en-Aarde, Onrus, Pringle Bay, Betty's Bay |
| West Coast | Langebaan, Saldanha, Jacobsbaai, Paternoster, Yzerfontein, St Helena Bay, Vredenburg, Velddrif |

Region coverage follows the team's own tracker: the Atlantic Seaboard and City
Bowl dominate, but **Stellenbosch is the third most-worked area**, and the team
has pursued Somerset West and Pringle Bay — hence Winelands, Helderberg and
Whale Coast.

**Adding an area** needs only a name, town and province:

```python
"voelklip": {"name": "Voelklip", "town": "hermanus",
             "province": "western-cape", "region": "Whale Coast"},
```

Then `python main.py discover-locations` resolves every portal's internal id
for it. Property24 ids come from its own `sitemap/Suburbs` (20k+ areas) plus
`sitemap/Cities` for whole towns, so nothing is hand-copied.

`town` and `province` are not decoration — suburb names repeat across South
Africa. There is a Noordhoek in Velddrif, a Newlands in Pretoria and a Dalsig
in Malmesbury, and matching on name alone silently crawls the wrong one.

### locations.json

Private Property and Pam Golding key their search pages off internal numeric
ids; the slug in the URL is decorative, and a wrong id **silently serves a
different suburb's listings**. Those ids are mined from each site's sitemap.
Seeff and RE/MAX use slug paths, which are probed against live pages.

Refresh with `python main.py discover-locations` if a suburb stops returning
results.

Discovery verifies that returned detail URLs actually belong to the requested
suburb — several portals answer an unknown suburb with generic city-wide stock
instead of a 404 (Seeff serves Kenilworth and Claremont listings for a bad
Clifton path).

---

## Deployment (Railway)

Live: **https://prospect-engine-production-2170.up.railway.app**
(project `oblivion-prospecting`, service `prospect-engine`, separate from the
`Obvlnestates` project that serves oblivionestate.com).

```bash
railway up --service prospect-engine     # redeploy after code changes
railway logs                             # runtime logs
railway variables                        # env vars
```

Required variables: `MOONSHOT_API_KEY`, `OPENAI_API_KEY`, `DASHBOARD_PASSWORD`,
`DATA_DIR=/data`.

**Access.** The dashboard shows Oblivion's prospect list and can start crawls,
so it sits behind HTTP basic auth (`DASHBOARD_USER` / `DASHBOARD_PASSWORD`).
If `DASHBOARD_PASSWORD` is unset the app **refuses to serve** when hosted
rather than publishing the data; locally it stays open for convenience.

**Persistence.** SQLite lives on a 5 GB volume mounted at `/data`
(`DATA_DIR`). Without the volume every redeploy would silently start from an
empty database. `.railwayignore` keeps `.env` and the local `prospects.db` out
of the upload, so a deploy never overwrites production data.

**One worker, many threads.** Crawl jobs run in background threads and report
progress through an in-memory dict. A second gunicorn worker would be a
separate process with its own copy, so the dashboard would poll one process
while the job ran in another. Scale threads, never workers.

### Property24 does not work from Railway

Measured on Railway EU West: 2 successful detail fetches, then sustained 503s
that survived the full 60/180/360s backoff ladder. The same crawl from a
residential IP manages ~15 requests before any throttling. It is an IP-level
block, so slowing down does not help.

Property24 is therefore **disabled by default on hosted deploys** and shown in
the dashboard as "blocked here". The other four portals serve Railway fine and
carry the hosted crawl. Options:

- Run Property24 crawls locally (`python main.py run --sources property24`);
  the volume keeps everything in one database if you sync it up.
- Set `ENABLE_PROPERTY24=1` if you put a residential proxy in front.

Because Property24 has the broadest agency coverage, a hosted-only crawl finds
fewer cross-agency matches than a local one. The mandate flags from Pam Golding
and the other three portals still work unchanged.

## Auto-crawl (the constant loop)

Set `AUTO_CRAWL=1` and the dashboard process schedules itself:

- **Nightly full pass** at `AUTO_CRAWL_HOUR` (default 01:00 local): every
  suburb, every enabled portal — Property24 included, riding its overnight
  pacing.
- **Freshness sweep** every `AUTO_SWEEP_HOURS` (default 6, `0` disables):
  page 1 of the fast portals only. Keeps `last_seen` current, which is what
  the proof-freshness gate, the delisting sweep and price history feed on.

Scheduled runs use the same single-job guard as the Scrape button, so the
loop and a human can never collide; on a Mac that sleeps overnight the pass
fires on wake. A **yield canary** protects the comps feed: a source whose
crawled-suburb listings were confirmed at under `LIFECYCLE_MIN_COVERAGE`
(50%) this run — a parser regression or a block — is excluded from that
run's delisting sweep instead of reading as a mass delisting.

## AI caller (`/caller`)

Once the panel has an owner's phone number, an AI voice agent can phone them,
disclose it's an AI calling for the agency, and pitch a free film-consultation
meeting — the mandate itself is always won by the human in that meeting. Calls
log into the panel as normal interactions and advance stages; CPA calling
hours, upfront AI disclosure, a POPIA identity gate and a do-not-call list are
enforced in code. A zero-cost text **simulator** on `/caller` runs the exact
live-call prompt for tuning the pitch. Setup and details: `docs/CALLER.md`.

## Notes

- **Throttling.** Property24 blocks hard after ~15 quick requests and stays
  blocked for 10–20 minutes; poking it during the block extends it. The crawler
  uses 12–18s jittered spacing and 60/180/360s backoffs. The other four portals
  run at ~2–3s.
- **HTTP cache.** Responses are cached under `.httpcache/` for 20 hours, so
  re-runs and interrupted crawls are cheap.
- **Scoring backends** are a chain, tried in order (`config.AI_BACKEND_ORDER`):

  | Order | Provider | Key | Model |
  |---|---|---|---|
  | 1 | Kimi (Moonshot) | `MOONSHOT_API_KEY` | `kimi-k3` → `kimi-k2.6` |
  | 2 | OpenAI | `OPENAI_API_KEY` | `gpt-5-mini` → `gpt-4o-mini` |
  | 3 | Claude | `ANTHROPIC_API_KEY` | `claude-opus-4-8` |
  | 4 | heuristic | — | no credentials needed |

  Kimi uses the **global** endpoint (`api.moonshot.ai`); `api.moonshot.cn`
  rejects international keys. `kimi-k3` supports schema-enforced structured
  output through the OpenAI SDK, so it drops straight into the same code path.

  Failures are handled by kind, which matters for score consistency:
  - **Fatal** (out of credits, bad key) retires that provider for the run and
    hands over to the next one — logged once, not once per property.
  - **Transient** (429, concurrency, timeout) retries the *same* model with
    exponential backoff. Moonshot enforces an org-wide concurrency limit
    (3 on this account), and treating that as model failure silently demoted
    properties to a weaker model, so identical homes were judged by different
    models. `config.MAX_CONCURRENCY` caps requests per provider to prevent it.
- **The team's tracker** (`import-tracker`) does two jobs: already-prospected
  properties are excluded from reports (including their sibling listings on
  other portals), and the history becomes a revealed-preference profile injected
  into the scoring prompt.
- **Port 5051** — 5000 collides with macOS AirPlay.
- `.env` holds the API key (chmod 600, gitignored).
