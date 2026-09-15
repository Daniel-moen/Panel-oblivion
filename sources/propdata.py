"""The Prop Data platform — one scraper, thirteen agencies.

Prop Data (propdata.net) white-labels the same property website to a large
slice of the South African agency market. Every tenant serves byte-identical
markup on its own domain: the same `/results/residential/for-sale/<town>/
<suburb>/<type>/<id>/` URL shape, the same `window.listing_event` analytics
blob, the same `.info-detail-*` pairs and the same schema.org `@graph`. Seeff
was already being scraped here before this was noticed; it is simply one
tenant among many.

That means the marginal cost of a new agency is a subclass with a domain and
an agency name — which is how Lew Geffen Sotheby's, Greeff Christie's and the
Dogon Group (the three agencies that between them hold most of the Atlantic
Seaboard luxury stock Oblivion competes for) come into the crawl.

Discovery is by sitemap rather than by search paging. Each tenant publishes
`/residential-for-sale/sitemap.txt` — and, for the rental book,
`/residential-to-let/sitemap.txt` — a flat list of every detail URL, with the
town and suburb in the path. One request therefore yields the
agency's entire inventory keyed by suburb, which is both far cheaper than
paging 84 suburb searches and immune to the fallback-result-set problem that
`Source.belongs_to` exists to guard against: a URL either sits under the
suburb or it does not.

The sitemap is capped at 10 000 URLs, and the three biggest tenants (Seeff,
Chase Everitt, Harcourts) exceed that, so the paged suburb search is still run
as well and the two sets are unioned. The search path does not have to be
guessed for it — the sitemap reveals the exact `<town>/<suburb>` pair each
tenant files an area under.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

import config
import locations
from sources.base import (Source, area_m2, coord, jsonld_blocks, jsonld_by_type, money,
                          num, make_soup, rent_period)

# One sitemap per book. The rental one is `to-let`, not `to-rent`, in both the
# sitemap name and the detail-URL path — verified on seeff.com, which publishes
# 2 122 rental URLs of the shape /results/residential/to-let/<town>/<suburb>/
# <type>/<id>/. (`/residential-to-rent/sitemap.txt` 307s; `/residential-to-let/`
# is the real one.)
SITEMAP_PATHS = {"sale": "/residential-for-sale/sitemap.txt",
                 "rent": "/residential-to-let/sitemap.txt"}
# The path segment the platform files each book under.
_SECTION = {"sale": "for-sale", "rent": "to-let"}

# Back-compat for anything still importing the single-book constant.
SITEMAP_PATH = SITEMAP_PATHS["sale"]

# The gallery container, across the theme generations in use on the estate:
# current builds (Greeff, Lew Geffen, Harcourts, …), Seeff's older hero
# carousel, and Jawitz's separate image-gallery layout. Matched as one
# selector list so the first that hits wins; the order only matters in that
# the listing gallery must be found before any thumbnail strip.
_GALLERY_SELECTORS = (
    ".listing-details-listing-images-swiper",
    ".hero-swiper",
    ".image-gallery",
)


def _listing_event(html: str) -> dict:
    """Parse the loosely-quoted JS object in window.listing_event."""
    m = re.search(r"window\.listing_event\s*=\s*\{(.*?)\}", html, re.S)
    if not m:
        return {}
    out: dict = {}
    for key, val in re.findall(r'(\w+)\s*:\s*("(?:[^"\\]|\\.)*"|[\d.]+)', m.group(1)):
        out[key] = val.strip('"') if val.startswith('"') else num(val)
    return out


def _slug_for_path(path: str, listing_type: str = "sale") -> tuple[str, str] | None:
    """(configured slug, '<town>/<suburb>' search path) for a detail URL.

    The path is `/results/residential/for-sale/<town>/<suburb>/<type>/<id>/`
    (or `/to-let/` for the rental book), so both halves of the area are known
    exactly — no guessing, and no `refine_suburb` heuristics needed.

    The book segment is checked rather than skipped: a rental URL must not
    satisfy a for-sale membership test, or the rent crawl's guard would let
    sale stock in and vice versa.

    The town segment must agree with the configured town. Suburb names repeat
    all over southern Africa and accepting the suburb segment alone pulls in
    the wrong place every time: measured across these sitemaps it wrongly
    claims Pretoria's Newlands, Bloemfontein's and Velddrif's Noordhoek,
    Malmesbury's Dalsig, Worcester's Brandwacht and a Waterfront in
    Swakopmund, Namibia. Requiring the town costs 0.7% of genuine matches and
    removes all of those.
    """
    parts = [p for p in path.split("/") if p]
    if len(parts) < 5 or parts[2] != _SECTION.get(listing_type):
        return None
    town_seg, suburb_seg = parts[3], parts[4]

    for slug, search in ((suburb_seg, f"{town_seg}/{suburb_seg}"),
                         (town_seg, town_seg)):
        info = config.SUBURBS.get(slug)
        if not info:
            continue
        # `slug == town_seg` is a whole-town area (Hermanus, Langebaan) filed
        # under its own name; otherwise the town segment must match config.
        if town_seg == info["town"] or slug == town_seg:
            return slug, search
    return None


class PropDataSource(Source):
    """Base scraper for one tenant of the Prop Data platform."""

    agency: str = ""          # agency name to record against every listing
    supports_rent = True

    def __init__(self, logger=None):
        super().__init__(logger=logger)
        # One cached sitemap index per book, so a run that crawls both does
        # not re-read (or overwrite) the other's.
        self._index: dict[str, dict[str, dict]] = {}

    # ------------------------------------------------------------ discovery
    def _sitemap_index(self, listing_type: str = "sale") -> dict[str, dict]:
        """slug -> {"urls": [...], "path": "<town>/<suburb>"} for this tenant.

        One fetch per crawl (and cached on disk for 20h by the Fetcher), so
        every suburb after the first is free.
        """
        cached = self._index.get(listing_type)
        if cached is not None:
            return cached
        index: dict[str, dict] = {}
        path = SITEMAP_PATHS.get(listing_type)
        body = (self.fetcher.get(self.fetcher.base_url + path) or "") if path else ""
        for line in body.splitlines():
            line = line.strip()
            if not line.startswith("http"):
                continue
            hit = _slug_for_path(urlparse(line).path, listing_type)
            if not hit:
                continue
            slug, search = hit
            entry = index.setdefault(slug, {"urls": [], "path": search})
            entry["urls"].append(line)
        if not index:
            self.log(f"[{self.label}] {listing_type} sitemap returned no "
                     f"usable listings")
        self._index[listing_type] = index
        return index

    def belongs_to(self, href: str, slug: str, listing_type: str = "sale") -> bool:
        """Exact-position check, replacing the base class's substring test.

        The platform puts the area in known path segments, so membership can
        be decided precisely instead of by asking whether the slug appears
        anywhere in the URL — which would accept Pretoria's Newlands for our
        Cape Town one.
        """
        hit = _slug_for_path(urlparse(href).path, listing_type)
        return bool(hit and hit[0] == slug)

    def search_urls(self, slug: str, max_pages: int,
                    listing_type: str = "sale") -> list[str]:
        if listing_type not in SITEMAP_PATHS:
            return []
        entry = self._sitemap_index(listing_type).get(slug) or {}
        urls: list[str] = list(entry.get("urls") or [])

        # The sitemap is capped at 10 000 URLs, so for the larger tenants it
        # is a sample rather than the whole book. Page the suburb search too
        # and union the results.
        #
        # The sitemap-derived path is preferred over locations.json because it
        # is read off real listing URLs rather than probed: it cannot be the
        # path that merely happened to return something. locations.json is the
        # fallback for an area with no sitemap entry — Seeff still has
        # hand-validated paths there from before this platform was recognised.
        path = entry.get("path") or locations.get(self.name, slug, listing_type)
        if path:
            urls.extend(self._search_pages(path, slug, max_pages, listing_type))

        seen: set[str] = set()
        out: list[str] = []
        for u in urls:
            ident = self.listing_id(u)
            if ident and ident not in seen:
                seen.add(ident)
                out.append(u)
        return out

    def _search_pages(self, path: str, slug: str, max_pages: int,
                      listing_type: str = "sale") -> list[str]:
        section = _SECTION[listing_type]
        found: list[str] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            page_url = f"{self.fetcher.base_url}/results/residential/{section}/{path}/"
            if page > 1:
                page_url += f"?page={page}"
            html = self.fetcher.get(page_url)
            if not html:
                break
            new = 0
            for href in re.findall(
                    rf'href="(/results/residential/{section}/[^"]*?/\d{{5,}}/[^"]*?)"', html):
                ident = self.listing_id(href)
                if ident and ident not in seen and self.belongs_to(href, slug, listing_type):
                    seen.add(ident)
                    found.append(self.fetcher.base_url + href)
                    new += 1
            if new == 0:
                break
        return found

    @staticmethod
    def listing_id(url: str) -> str | None:
        """The numeric id sitting after the property-type segment."""
        parts = [p for p in urlparse(url).path.split("/") if p]
        for p in parts:
            if p.isdigit() and len(p) >= 5:
                return p
        return None

    # ------------------------------------------------------------ parsing
    def parse_detail(self, url: str, slug: str,
                     listing_type: str = "sale") -> dict | None:
        html = self.fetcher.get(url)
        if not html:
            return None
        ident = self.listing_id(url)
        if not ident:
            return None

        soup = make_soup(html)
        blocks = jsonld_blocks(soup)
        rec = self.blank(url, slug, ident, listing_type)
        rec["agency"] = self.agency

        prop = jsonld_by_type(blocks, "House", "Apartment", "Residence",
                              "SingleFamilyResidence", "Product")
        offer = jsonld_by_type(blocks, "Offer")
        agent = jsonld_by_type(blocks, "RealEstateAgent")

        h1 = soup.find("h1")
        rec["title"] = (h1.get_text(" ", strip=True) if h1 else "") or \
            (prop.get("name") if prop else "") or ""

        # Price: the analytics blob carries it as a number, the Offer block as
        # display text ("R4,995,000"). Prefer the number.
        ev = _listing_event(html)
        rec["price_zar"] = money(ev.get("price")) or (
            money(offer.get("price")) if offer else None)
        if listing_type == "rent":
            # The rental blob states the period outright —
            # `purchase_type: "To Let"`, `price_term: "Per Month"` — which is
            # the cleanest period signal of any portal here.
            rec["rent_period"] = rent_period(ev.get("price_term")) or "month"
        rec["property_type"] = ev.get("property_type") or None
        rec["floor_size_m2"] = area_m2(ev.get("floor_size"))
        rec["erf_size_m2"] = area_m2(ev.get("land_size"))

        # Labelled detail pairs: Web Ref. / Land size / Monthly Rates / Levy.
        details: dict[str, str] = {}
        for lab, val in zip(soup.select(".info-detail-label"),
                            soup.select(".info-detail-value")):
            details[lab.get_text(" ", strip=True).rstrip(".:").lower()] = \
                val.get_text(" ", strip=True)
        # The listing-features layout states the same facts as one-line rows
        # ("Bedrooms 3", "Land Size 355m²", "Pool No") instead of paired
        # label/value elements.
        for row in soup.select(".feature-row"):
            pair = re.match(r"^(.+?)\s+([\d\s,.]+\s*(?:ha|m)?\s*²?|Yes|No)$",
                            row.get_text(" ", strip=True), re.I)
            if pair:
                details.setdefault(pair.group(1).strip().rstrip(".:").lower(),
                                   pair.group(2).strip())
        if not rec["erf_size_m2"] and details.get("land size"):
            rec["erf_size_m2"] = area_m2(details["land size"])
        if not rec["floor_size_m2"] and details.get("floor size"):
            rec["floor_size_m2"] = area_m2(details["floor size"])
        if details.get("monthly rates"):
            rec["rates"] = money(details["monthly rates"])
        for key in ("monthly levy", "monthly levies", "levies", "levy"):
            if details.get(key):
                rec["levies"] = money(details[key])
                break
        if listing_type == "rent":
            for key in ("available from", "available", "occupation date",
                        "date available"):
                if details.get(key):
                    rec["available_from"] = details[key]
                    break
            rec["furnished"] = details.get("furnished")
            for key in ("deposit", "rental deposit"):
                if details.get(key):
                    rec["deposit"] = money(details[key])
                    break

        # Room counts. The icon strip writes them as "3 Bedrooms"; the
        # listing-features layout writes "Bedrooms 3". Both orders are tried
        # before falling back to the raw page, so a tenant on either theme
        # yields the same numbers.
        features = " ".join(e.get_text(" ", strip=True) for e in
                            soup.select(".features-icons, .listing-features"))
        for word, field in (("Bedroom", "bedrooms"), ("Bathroom", "bathrooms"),
                            ("Garage", "garages"), ("Parking", "parking")):
            value = details.get(f"{field}")
            for pattern in (rf"(\d+(?:\.\d+)?)\s*{word}s?\b",
                            rf"\b{word}s?\s+(\d+(?:\.\d+)?)"):
                if value:
                    break
                m = re.search(pattern, features, re.I) or \
                    re.search(pattern, html, re.I)
                if m:
                    value = m.group(1)
            rec[field] = num(value)

        # "Pool" alone means the property has one; the feature-row layout
        # spells out "Pool No", which reads as a pool to a bare keyword match
        # and would have marked every poolless listing as having one.
        pool = details.get("pool")
        if pool is not None:
            rec["pool"] = int(pool.strip().lower() not in ("no", "0", "false"))
        else:
            rec["pool"] = int(bool(re.search(r"\bpool\b", features, re.I)))

        # Description: `.overview-content` is the seller's copy on its own.
        # The enclosing `.listing-details-overview` also swallows the heading
        # and the detail pairs, which would feed the mandate classifier a
        # paragraph of bond-repayment figures before it reaches the prose.
        body = (soup.select_one(".overview-content")
                or soup.select_one(".listing-description")
                or soup.select_one(".listing-details-overview"))
        rec["description"] = body.get_text(" ", strip=True) if body else ""

        if agent:
            rec["agent_name"] = agent.get("name")
        if not rec["agent_name"]:
            el = soup.select_one(".card-agent-name")
            if el:
                rec["agent_name"] = el.get_text(" ", strip=True)
        if not rec["agent_name"]:
            # The contact block leads with the practitioner's name and then
            # runs on into their PPRA registration and phone numbers, so only
            # the first line is the name.
            el = soup.select_one(".agent-contact-details")
            if el:
                first = el.get_text("\n", strip=True).split("\n")[0]
                rec["agent_name"] = first[:60] or None

        if prop:
            rec["listing_date"] = (str(prop.get("datePosted") or ""))[:10] or None
            address = prop.get("address")
            if isinstance(address, dict):
                rec["street_address"] = address.get("streetAddress") or None
            rec["latitude"], rec["longitude"] = _geo(prop.get("geo"))
            images = prop.get("image")
            if isinstance(images, list):
                rec["photo_count"] = len({i for i in images if isinstance(i, str)})
            elif isinstance(images, str):
                rec["photo_count"] = 1

        if not rec["street_address"]:
            # The platform appends the street to the URL whenever it knows it,
            # even on the tenants whose schema.org block omits the address —
            # which is most of them. Across a Langebaan crawl, Century 21,
            # Harcourts, Chas Everitt, Jawitz and Seeff published no address
            # in the markup while carrying one in the path.
            rec["street_address"] = _street_from_url(url)
        if not rec["listing_date"]:
            # "Date Listed 14-04-26" in the feature strip (dd-mm-yy).
            m = re.search(r"Date Listed\s+(\d{2})-(\d{2})-(\d{2})", features)
            if m:
                d, mo, y = m.groups()
                rec["listing_date"] = f"20{y}-{mo}-{d}"

        # Photo count needs all three of these, in this order, because no one
        # of them is reliable across the estate:
        #
        #   data-count  the gallery carries its own size. Authoritative, and
        #               present on every current-theme tenant — including the
        #               ones that render slides in JavaScript and so expose no
        #               <img> at all (Greeff, Dogon, Chas Everitt would each
        #               have counted zero).
        #   <img> tags  Seeff runs an older build with no data-count, but it
        #               does emit the slides. Where both exist they agree
        #               exactly, which is what makes the fallback safe.
        #   JSON-LD     last, because its image list is capped at five
        #               previews — trusting it first reported "5 photos" for
        #               every listing on half the tenants.
        #
        # All of it is scoped to the gallery element: the page also carries
        # "similar listings" thumbnails off the same CDN, and counting those
        # would inflate how well-marketed a property looks.
        gallery = soup.select_one(", ".join(_GALLERY_SELECTORS))
        if gallery:
            # Only the swiper wrapper's data-count is the gallery total. The
            # image-gallery layout also uses data-count, but there it numbers
            # each slide — reading it as a total reported "1 photo" for every
            # Jawitz and Only Realty listing.
            counter = gallery.select_one(".swiper-wrapper[data-count]")
            declared = num(counter.get("data-count")) if counter else None
            slides = len({_image_key(_img_src(img))
                          for img in gallery.find_all("img")
                          if _img_src(img)})
            if declared:
                rec["photo_count"] = int(declared)
            elif slides:
                rec["photo_count"] = slides

        rec["under_offer"] = int(bool(
            re.search(r"\bunder\s+offer\b|\bsale\s+pending\b", html, re.I)))

        rec["raw_overview"] = json.dumps(
            {**details, "features": features[:600]}, ensure_ascii=False)
        return self.finish(rec, html)


# "8th" in "22a-8th-street" is part of the street name, not a second house
# number; reading it as one would truncate the address to "8th Street".
_ORDINAL = re.compile(r"^\d+(st|nd|rd|th)$", re.I)


def _street_from_url(url: str) -> str | None:
    """The street address from the path segment after the listing id.

    Prop Data URLs are `…/<type>/<id>/<street-slug>/`, and the slug is a real
    address ("24-old-main-road", "22a-8th-street"). Two shapes have to be
    repaired before use, because a *wrong* address is worse than none — dedupe
    treats two listings with different addresses as definitely-not-the-same,
    so a malformed one actively splits a property apart:

      * exact duplication, "14-helios-place-14-helios-place"
      * a complex name in front of the street, "39-millenial-arch-1-sondela-close"

    Both are resolved by keeping the last house-number-led run of words, which
    is the street itself. Anything that does not start with a house number is
    rejected rather than guessed at.
    """
    segs = [s for s in urlparse(url).path.split("/") if s]
    idx = next((i for i, s in enumerate(segs) if s.isdigit() and len(s) >= 5), None)
    if idx is None or idx + 1 >= len(segs):
        return None
    words = segs[idx + 1].split("-")
    if not words or not re.fullmatch(r"\d+[a-z]?", words[0], re.I):
        return None

    # Start a new candidate at each house number that is not an ordinal.
    starts = [i for i, w in enumerate(words)
              if re.fullmatch(r"\d+[a-z]?", w, re.I) and not _ORDINAL.match(w)]
    last = words[starts[-1]:] if starts else words
    if len(last) < 2:                     # "1430" alone is not an address
        return None
    # Title-case, then put back the two things it gets wrong: the ordinal in
    # "8th Street" and the unit letter in "22a". Only cosmetic — matching runs
    # on the lowercased form — but this string is what the dashboard shows.
    pretty = " ".join(last).title()
    pretty = re.sub(r"(?<=\d)(St|Nd|Rd|Th)\b", lambda m: m.group(1).lower(), pretty)
    return re.sub(r"^(\d+)([A-Z])\b", lambda m: m.group(1) + m.group(2).lower(), pretty)


def _img_src(img) -> str:
    """An <img>'s URL, whichever attribute the tenant's lazy-loader uses.

    Only the first slide carries a real `src` on the image-gallery layout;
    the rest sit in `data-lazy` until the carousel opens. Reading `src` alone
    counted one photo for every Jawitz and Only Realty listing.
    """
    for attr in ("src", "data-src", "data-lazy", "data-original"):
        value = img.get(attr)
        if value:
            return value
    return ""


def _image_key(src: str | None) -> str:
    """A photo's identity, independent of the size it is being served at.

    The CDN renders every image at a dozen widths
    (`…_t_w_1024_h_576.avif`), and a gallery that shows each slide plus its
    thumbnail would otherwise count one photograph several times.
    """
    if not src:
        return ""
    return re.sub(r"(_t_w_\d+_h_\d+)?\.(jpe?g|png|webp|avif)$", "", src.strip())


def _geo(geo) -> tuple[float | None, float | None]:
    """Latitude/longitude from a GeoCoordinates block, un-swapping if needed.

    The platform emits the pair the wrong way round — a Hermanus listing
    reports latitude 19.14 and longitude -34.41. South Africa sits at negative
    latitude and positive longitude without exception, so the sign of each
    value identifies which is which and the pair can be repaired rather than
    thrown away (the coordinates feed erf.py's cadastre lookup, where a
    transposed point lands in Somalia).
    """
    if not isinstance(geo, dict):
        return None, None
    a, b = coord(geo.get("latitude")), coord(geo.get("longitude"))
    if a is None or b is None:
        return None, None
    if a > 0 and b < 0:
        a, b = b, a
    if not (-35.5 <= a <= -21.5 and 15.5 <= b <= 33.5):
        return None, None                 # outside southern Africa — distrust
    return a, b


# --------------------------------------------------------------- tenants
#
# Ordered roughly by how much stock each carries in Oblivion's target areas.
# Firzt, Wakefields and Acutts are on the same platform but are Johannesburg
# and KwaZulu-Natal books — between them they list four properties in the 84
# configured areas, so they are deliberately left out rather than crawled for
# nothing.

class LewGeffen(PropDataSource):
    name = "lewgeffen"
    label = "Lew Geffen Sotheby's"
    agency = "Lew Geffen Sotheby's International Realty"


class Greeff(PropDataSource):
    name = "greeff"
    label = "Greeff Christie's"
    agency = "Greeff Christie's International Real Estate"


class Dogon(PropDataSource):
    name = "dogon"
    label = "Dogon Group"
    agency = "Dogon Group Properties"


class ChasEveritt(PropDataSource):
    name = "chaseveritt"
    label = "Chas Everitt"
    agency = "Chas Everitt International"


class Harcourts(PropDataSource):
    name = "harcourts"
    label = "Harcourts"
    agency = "Harcourts South Africa"


class Jawitz(PropDataSource):
    name = "jawitz"
    label = "Jawitz Properties"
    agency = "Jawitz Properties"


class Century21(PropDataSource):
    name = "century21"
    label = "Century 21"
    agency = "Century 21 South Africa"


class TysonProp(PropDataSource):
    name = "tysonprop"
    label = "Tyson Properties"
    agency = "Tyson Properties"


class JustProperty(PropDataSource):
    name = "justproperty"
    label = "Just Property"
    agency = "Just Property"


class OnlyRealty(PropDataSource):
    name = "onlyrealty"
    label = "Only Realty"
    agency = "Only Realty"
