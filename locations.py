"""Suburb -> per-portal search path resolution.

Private Property and Pam Golding key their search pages off internal numeric
ids; the human-readable slug in the URL is decorative and a wrong id silently
serves a completely different suburb's listings (asking for Camps Bay and
getting Waterkloof, Pretoria). Guessing is therefore not an option — the ids
are mined from each site's own sitemap.

Seeff and RE/MAX use plain slug paths that can be derived from config, but
they are still validated against a live page before being trusted.

Results are cached in locations.json. Refresh with:

    python main.py discover-locations [suburb-slug ...]
"""

from __future__ import annotations

import json
import os
import re

import config

_cache: dict | None = None


# ---------------------------------------------------------------- storage

def load() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(config.LOCATIONS_PATH, encoding="utf-8") as f:
                _cache = json.load(f)
        except (OSError, ValueError):
            _cache = {}
    return _cache


def save(data: dict) -> None:
    global _cache
    _cache = data
    tmp = config.LOCATIONS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
    os.replace(tmp, config.LOCATIONS_PATH)


# Portals whose to-rent search path is the for-sale path with a different
# leading segment, so the sale entry in locations.json serves both books.
# Verified live, one suburb each:
#   property24       /to-rent/camps-bay/cape-town/western-cape/11014   (same id)
#   privateproperty  /to-rent/western-cape/.../camps-bay/652           (same id)
#   remax            /property-to-rent-south-africa/western-cape/cape-town/camps-bay
#   seeff (Prop Data) /results/residential/to-let/<town>/<suburb>
# Pam Golding is NOT here: its area reference embeds the book itself
# ("residential-properties-to-rent-stellenbosch/2932"), with a different id
# from the for-sale one, so it gets its own discovered entry.
_RENT_SHARES_SALE_PATH = frozenset(
    {"property24", "privateproperty", "remax", "seeff"})


def get(source: str, slug: str, listing_type: str = "sale") -> str | None:
    """Search-path fragment for this suburb on this portal, or None if the
    portal has no page for it.

    A stored `null` means discovery checked and this portal genuinely has no
    page for the area — that is different from "never checked", and must not
    fall through to a guessed path. Guessing there is what made Seeff serve
    all of Somerset West under "Erinvale Golf Estate".

    For listing_type="rent" the rent-specific entry ("<source>_rent") wins;
    failing that, portals in _RENT_SHARES_SALE_PATH fall back to their sale
    path, which is the same path. Any other portal returns None — the rental
    crawl then skips it, which is the right answer for a path nobody has
    confirmed.
    """
    entry = load().get(slug) or {}
    if listing_type != "sale":
        key = f"{source}_{listing_type}"
        if key in entry:
            return entry[key] or None
        if source in _RENT_SHARES_SALE_PATH:
            return get(source, slug, "sale")
        return None
    if source in entry:
        return entry[source] or None
    return _derived(source, slug)      # never checked — try a derived default


def _candidates(source: str, slug: str) -> list[str]:
    """Plausible search paths for the slug-based portals, best guess first.

    Both sites disambiguate repeated suburb names inconsistently — Seeff files
    Camps Bay under `cape-town/camps-bay` but Clifton under
    `cape-town/clifton-cape-town`, and RE/MAX drops the town segment for
    places that are themselves towns. Whole-town areas (scope == "town") get
    the town-level shapes the proven entries use — Seeff files Langebaan under
    `langebaan/langebaan`, RE/MAX under `western-cape/langebaan` — plus, for
    Seeff, the bare `<town>` landing page some towns get instead. Discovery
    tries each candidate and keeps whichever actually returns listings, so a
    wrong guess here costs a probe, not a mislabelled crawl.
    """
    info = config.SUBURBS.get(slug)
    if not info:
        return []
    town, province = info["town"], info["province"]
    town_scope = info.get("scope") == "town" or town == slug
    if source == "seeff":
        out = []
        if town_scope:
            # Places we treat as towns but that sit inside the Cape Town
            # metro (Noordhoek, Simon's Town) are filed under cape-town.
            out += [f"{town}/{town}", town, f"cape-town/{slug}"]
        out += [f"{town}/{slug}", f"{town}/{slug}-{town}"]
        return list(dict.fromkeys(out))
    if source == "remax":
        out = []
        if town_scope:
            out += [f"{province}/{town}", f"{province}/cape-town/{slug}"]
        out.append(f"{province}/{town}/{slug}")
        if town != slug:
            out.append(f"{province}/{slug}")
        return list(dict.fromkeys(out))
    return []


def _derived(source: str, slug: str) -> str | None:
    cands = _candidates(source, slug)
    return cands[0] if cands else None


# ---------------------------------------------------------------- discovery

_PP_SITEMAP = "https://www.privateproperty.co.za/SiteMap/residential-shapes-0.xml"
_PG_SITEMAP = "https://www.pamgolding.co.za/sitemaps/propertysearchlocationssale.xml"
# The same sitemap for the rental book. Far thinner than the sale one (178
# residential-to-rent areas nationally against thousands for sale), so most
# configured suburbs legitimately resolve to nothing here.
_PG_RENT_SITEMAP = "https://www.pamgolding.co.za/sitemaps/propertysearchlocationsrent.xml"
_P24_SITEMAP = "https://www.property24.com/sitemap/Suburbs?SearchType=ForSale"
_P24_CITIES_SITEMAP = "https://www.property24.com/sitemap/Cities?SearchType=ForSale"


def _sitemap_locs(fetcher, url: str) -> list[str]:
    body = fetcher.get(url)
    if not body:
        return []
    return re.findall(r"<loc>([^<]+)</loc>", body)


def _discover_property24(fetcher, slugs, log) -> dict[str, str]:
    """slug -> 'clifton/cape-town/western-cape/11015'.

    Property24's own sitemap lists every suburb with its area id, which beats
    hardcoding: the id is what actually selects the area (the slug in the URL
    is decorative), and the path shape is inconsistent — most suburbs are
    <suburb>/<town>/<province> but some towns are <town>/<province>. Taking
    the whole path from the sitemap sidesteps guessing either.

    Matching is on (slug, town, province) together. Suburb names repeat across
    the country — there is a Noordhoek in Velddrif and a Newlands in Pretoria —
    and matching on name alone silently crawls the wrong one.
    """
    log("[Property24] reading suburb sitemap (20k+ areas)...")
    body = fetcher.get(_P24_SITEMAP)
    if not body:
        log("  could not fetch the Property24 sitemap (blocked?) — "
            "keeping existing ids")
        return {}
    entries = re.findall(
        r"<loc>https://www\.property24\.com/for-sale/([^<]+?)/(\d+)</loc>", body)

    # Some of the areas we target are whole towns (Langebaan, Saldanha,
    # St Helena Bay), which Property24 files in a separate Cities sitemap.
    cities = fetcher.get(_P24_CITIES_SITEMAP)
    if cities:
        entries += re.findall(
            r"<loc>https://www\.property24\.com/for-sale/([^<]+?)/(\d+)</loc>", cities)

    index: dict[tuple, str] = {}
    for path, area_id in entries:
        parts = path.split("/")
        if len(parts) < 2:
            continue
        suburb, province = parts[0], parts[-1]
        town = parts[-2] if len(parts) >= 3 else parts[0]
        index.setdefault((suburb, town, province), f"{path}/{area_id}")

    found: dict[str, str] = {}
    for slug in slugs:
        info = config.SUBURBS[slug]
        key = (slug, info["town"], info["province"])
        hit = index.get(key)
        if not hit and info["town"] == slug:
            # towns are sometimes filed as <town>/<province> with no suburb
            hit = index.get((slug, slug, info["province"]))
        if not hit:
            # The configured `town` is a best guess for newly added areas
            # (Property24 files Bloubergstrand under a parent we can't know
            # without looking). Fall back to every sitemap entry whose suburb
            # slug and province match: a single candidate is unambiguous, so
            # trust it and log the correction; several means the name repeats
            # within the province and guessing would crawl the wrong one.
            matches = sorted({(t, path) for (sub, t, prov), path in index.items()
                              if sub == slug and prov == info["province"]})
            if len(matches) == 1:
                town_found, hit = matches[0]
                log(f"  {slug}: config town {info['town']!r} not in the "
                    f"sitemap — using {town_found!r}")
            elif len(matches) > 1:
                towns = ", ".join(t for t, _ in matches)
                log(f"  {slug} -> ambiguous on Property24 (filed under: "
                    f"{towns}) — fix `town` in config.SUBURBS")
                continue
        if hit:
            found[slug] = hit
            log(f"  {slug} -> {hit}")
        else:
            log(f"  {slug} -> not in the Property24 sitemap")
    return found


def _discover_privateproperty(fetcher, slugs, log) -> dict[str, str]:
    """slug -> 'western-cape/cape-town/atlantic-seaboard/camps-bay/652'."""
    log("[Private Property] reading area sitemap...")
    found: dict[str, str] = {}
    found_rank: dict[str, tuple] = {}
    for loc in _sitemap_locs(fetcher, _PP_SITEMAP):
        m = re.search(r"/for-sale/(.+?)/(\d+)$", loc)
        if not m:
            continue
        path, area_id = m.group(1), m.group(2)
        parts = path.split("/")
        leaf = parts[-1]
        if leaf not in slugs:
            continue
        info = config.SUBURBS[leaf]
        # Same-name areas exist all over the province, not just across
        # provinces: Private Property files a Noordhoek inside Velddrif, a
        # Newlands inside Beaufort West and a Waterfront inside Langebaan.
        # Path shape is <province>/<pp-region>/<town...>/<suburb>, so beyond
        # the province and PP-region segments, any *different* configured
        # town in the path means this is the wrong same-named area.
        if info["province"] not in parts:
            continue
        foreign = {v["town"] for v in config.SUBURBS.values()} - {info["town"]}
        if any(p in foreign for p in parts[2:-1]):
            continue
        # Rank: a path routed through this entry's own town beats any depth —
        # depth alone is what used to pick Beaufort West's Newlands (5 parts)
        # over Cape Town's (4 parts).
        candidate = f"{path}/{area_id}"
        own_town = info["town"] in parts[:-1]
        rank = (own_town, len(parts))
        if leaf not in found or rank > found_rank[leaf]:
            found[leaf] = candidate
            found_rank[leaf] = rank
    for slug in slugs:
        if slug in found:
            log(f"  {slug} -> {found[slug]}")
        else:
            log(f"  {slug} -> not listed on Private Property")
    return found


def _discover_pamgolding(fetcher, slugs, log,
                         listing_type: str = "sale") -> dict[str, str]:
    """slug -> 'residential-properties-for-sale-camps-bay/2113'.

    listing_type="rent" reads the rental sitemap instead and yields
    'residential-properties-to-rent-stellenbosch/2932'. The area id differs
    between the two books, which is why Pam Golding cannot share one entry.
    """
    rent = listing_type == "rent"
    log(f"[Pam Golding] reading area sitemap ({listing_type})...")
    by_slug: dict[str, list[tuple[str, str]]] = {}
    prefix = ("residential-properties-to-rent-" if rent
              else "residential-properties-for-sale-")
    sitemap = _PG_RENT_SITEMAP if rent else _PG_SITEMAP
    for loc in _sitemap_locs(fetcher, sitemap):
        m = re.search(rf"/property-search/({prefix}[a-z0-9-]+)/(\d+)$", loc)
        if not m:
            continue
        name, area_id = m.group(1), m.group(2)
        tail = name[len(prefix):]
        for slug in slugs:
            # exact match, or slug qualified by its town (green-point-cape-town)
            if tail == slug or tail == f"{slug}-{config.SUBURBS[slug]['town']}":
                by_slug.setdefault(slug, []).append((tail, f"{name}/{area_id}"))

    found: dict[str, str] = {}
    for slug, options in by_slug.items():
        exact = [p for t, p in options if t == slug]
        found[slug] = exact[0] if exact else options[0][1]
    for slug in slugs:
        if slug in found:
            log(f"  {slug} -> {found[slug]}")
        else:
            log(f"  {slug} -> not listed on Pam Golding ({listing_type})")
    return found


def _validate_slug_portal(src, slugs, log) -> dict[str, str]:
    """Seeff / RE/MAX: try each candidate path, keep the one with listings."""
    log(f"[{src.label}] probing search paths...")
    found: dict[str, str] = {}
    cache = load()
    for slug in slugs:
        for path in _candidates(src.name, slug):
            # search_urls() resolves through get(); point it at this candidate
            cache.setdefault(slug, {})[src.name] = path
            urls = src.search_urls(slug, 1)
            if urls:
                found[slug] = path
                log(f"  {slug} -> {path} ({len(urls)} listings)")
                break
        else:
            cache.setdefault(slug, {}).pop(src.name, None)
            log(f"  {slug} -> no page found on {src.label}")
    return found


def discover(slugs: list[str] | None = None, sources: list[str] | None = None,
             log=print, listing_types: tuple[str, ...] = ("sale", "rent")) -> dict:
    """Mine/validate portal area references and update locations.json.

    Rental references are mined alongside the sale ones and stored under
    "<source>_rent". Only Pam Golding needs them — every other rent-capable
    portal reuses its sale path (see _RENT_SHARES_SALE_PATH) — so this adds
    exactly one extra sitemap fetch to a discovery run.
    """
    import sources as source_registry
    from httpclient import Fetcher

    slugs = slugs or list(config.SUBURBS)
    slugs = [s for s in slugs if s in config.SUBURBS]
    sources = sources or config.enabled_sources()

    data = load()
    result: dict[str, dict[str, str]] = {s: dict(data.get(s, {})) for s in slugs}

    if "property24" in sources:
        f = Fetcher("property24", logger=log)
        for slug, path in _discover_property24(f, slugs, log).items():
            result.setdefault(slug, {})["property24"] = path
    if "privateproperty" in sources:
        f = Fetcher("privateproperty", logger=log)
        for slug, path in _discover_privateproperty(f, slugs, log).items():
            result.setdefault(slug, {})["privateproperty"] = path
    if "pamgolding" in sources:
        f = Fetcher("pamgolding", logger=log)
        if "sale" in listing_types:
            for slug, path in _discover_pamgolding(f, slugs, log).items():
                result.setdefault(slug, {})["pamgolding"] = path
        if "rent" in listing_types:
            for slug, path in _discover_pamgolding(
                    f, slugs, log, listing_type="rent").items():
                result.setdefault(slug, {})["pamgolding_rent"] = path
    # Only RE/MAX still needs its search path probed. Seeff used to be here,
    # but as a Prop Data tenant it now reads the exact path out of its own
    # sitemap — and probing it would actively do harm, because search_urls()
    # returns the sitemap's listings whatever candidate path is being tried,
    # so every candidate "succeeds" and the first guess is stored as proven.
    for name in ("remax",):
        if name in sources:
            src = source_registry.build(name, logger=log)
            for slug, path in _validate_slug_portal(src, slugs, log).items():
                result.setdefault(slug, {})[name] = path

    # Record misses as null rather than leaving a stale path behind: a portal
    # that used to resolve (or that resolved wrongly before the guard was
    # tightened) must not keep serving that path forever.
    #
    # Prop Data tenants are skipped: they read each area straight out of their
    # own sitemap on every crawl, so there is nothing here to pin down, and
    # writing a null for them would only add noise to the file. Seeff is the
    # exception — it has hand-validated entries from before the platform was
    # recognised, and search_urls() still prefers them.
    # MyProperty, ImmoAfrica and Rawson likewise build their search URLs
    # straight from config.SUBURBS and never consult this file.
    self_discovering = (set(source_registry.propdata_names())
                        | {"myproperty", "immoafrica", "rawson"}) - {"seeff"}
    for slug in slugs:
        entry = result.setdefault(slug, {})
        for name in sources:
            if name not in self_discovering:
                entry.setdefault(name, None)
        # Pam Golding's rental book covers a fraction of the areas its sale
        # book does, so "no rental page here" is the common case and must be
        # recorded as a checked null — otherwise get() would fall through and
        # the rental crawl would keep asking for a page that isn't there.
        if "pamgolding" in sources and "rent" in listing_types:
            entry.setdefault("pamgolding_rent", None)

    merged = dict(data)
    for slug, entry in result.items():
        merged.setdefault(slug, {}).update(entry)
    save(merged)
    log(f"locations.json updated ({len(merged)} suburbs)")
    return merged
