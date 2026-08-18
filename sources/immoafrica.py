"""ImmoAfrica — aggregator, and the only route to some agencies.

Worth crawling for the same reason as MyProperty: it is an independent
witness to which agencies are marketing a property. It also names agencies
this engine cannot otherwise see at all — a Camps Bay listing here is
attributed to "Engel & Völkers Camps Bay", a brand with no scrapeable site of
its own.

Two quirks shape the discovery here. The search results paginate in the
browser only: `?page=2` is served the same first eighteen results as page 1,
so a suburb search yields at most eighteen listings no matter how many exist.
The per-property-type paths are therefore crawled separately (houses,
apartments, townhouses and so on each get their own eighteen) and unioned
with the province sitemaps, which list detail URLs directly. Where that still
falls short of the site's own advertised result count, the shortfall is
logged rather than passed off as full coverage.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

import config
from sources.base import (Source, area_m2, jsonld_blocks, jsonld_by_type,
                          money, num, make_soup)

# Residential for-sale categories to search. Rentals and commercial are
# deliberately absent, and "vacant-land" is left out because a plot has no
# home to film and no homeowner whose mandate Oblivion can win.
TYPES = ("houses", "apartments", "townhouses", "mansion-villas", "studios",
         "farms")

# The sitemaps carry every category, including ones no search path above asks
# for, so the same exclusions have to be applied to whatever they yield —
# otherwise the sitemap quietly re-admits what TYPES exists to keep out (it
# put 172 Langebaan building plots into the crawl before this existed). A
# denylist rather than an allowlist, because the site invents long-tail
# category names ("equestrian-farms", "golf-estates") that are all perfectly
# good prospects.
_EXCLUDED_TYPES = frozenset({
    "vacant-land", "commercial", "industrial", "retail", "offices",
    "warehouses", "land", "development",
})

_SITEMAP_INDEX = "/sitemaps/net/sitemap_index.xml"
_DETAIL = re.compile(r"^/([a-z-]+)-for-sale/([^/]+)/([^/]+)/([^/]+)/"
                     r"south-africa/(IA\d+)$")


def _slug_for_path(path: str) -> str | None:
    """The configured suburb a detail URL belongs to, or None.

    Detail URLs are `/<type>-for-sale/<suburb>/<town>/<province>/south-africa/
    IA<id>`, so suburb, town and province are all pinned by position and a
    same-named area elsewhere cannot slip through.
    """
    m = _DETAIL.match(urlparse(path).path)
    if not m:
        return None
    kind, suburb, town, province, _id = m.groups()
    if kind in _EXCLUDED_TYPES:
        return None
    for slug in (suburb, town):
        info = config.SUBURBS.get(slug)
        if not info or info["province"] != province:
            continue
        if town == info["town"] or slug == town:
            return slug
    return None


class ImmoAfrica(Source):
    name = "immoafrica"
    label = "ImmoAfrica"

    def __init__(self, logger=None):
        super().__init__(logger=logger)
        self._sitemap: dict[str, list[str]] | None = None

    # ------------------------------------------------------------ discovery
    def _sitemap_index(self) -> dict[str, list[str]]:
        """slug -> detail URLs mined from the provincial sitemaps.

        Only the provinces the configured areas actually sit in are fetched,
        so a Cape-and-West-Coast crawl never downloads Gauteng's.
        """
        if self._sitemap is not None:
            return self._sitemap
        index: dict[str, list[str]] = {}
        body = self.fetcher.get(self.fetcher.base_url + _SITEMAP_INDEX) or ""
        wanted = {v["province"].replace("-", "")
                  for v in config.SUBURBS.values()}
        maps = [loc for loc in re.findall(r"<loc>([^<]+)</loc>", body)
                if any(w in loc.replace("-", "") for w in wanted)]
        for url in maps:
            page = self.fetcher.get(url) or ""
            for loc in re.findall(r"<loc>([^<]+)</loc>", page):
                slug = _slug_for_path(loc)
                if slug:
                    index.setdefault(slug, []).append(loc)
        self._sitemap = index
        return index

    def belongs_to(self, href: str, slug: str) -> bool:
        return _slug_for_path(href) == slug

    def search_urls(self, slug: str, max_pages: int) -> list[str]:
        info = config.SUBURBS.get(slug)
        if not info:
            return []
        area = f"{slug}/{info['town']}/{info['province']}/south-africa"
        found: dict[str, str] = {}
        for loc in self._sitemap_index().get(slug, []):
            found[_ident(loc)] = loc

        advertised = 0
        for kind in TYPES:
            page = self.fetcher.get(
                f"{self.fetcher.base_url}/{kind}-for-sale/{area}/")
            if not page:
                continue
            advertised = max(advertised, _advertised_total(page))
            for href in re.findall(r'href="(/[a-z-]+-for-sale/[^"?#]+)"', page):
                if self.belongs_to(href, slug):
                    found[_ident(href)] = self.fetcher.base_url + href

        # Never let a browser-side pagination limit read as full coverage.
        if advertised > len(found):
            self.log(f"[{self.label}] {info['name']}: site advertises "
                     f"{advertised} listings, server-rendered pages expose "
                     f"{len(found)} (results paginate client-side)")
        return list(found.values())

    # ------------------------------------------------------------ parsing
    def parse_detail(self, url: str, slug: str) -> dict | None:
        html = self.fetcher.get(url)
        if not html:
            return None
        ident = _ident(url)
        if not ident:
            return None
        soup = make_soup(html)
        blocks = jsonld_blocks(soup)
        listing = jsonld_by_type(blocks, "RealEstateListing")
        if not listing:
            return None

        rec = self.blank(url, slug, ident)
        rec["title"] = listing.get("name") or ""
        rec["description"] = listing.get("description") or ""
        rec["listing_date"] = (str(listing.get("datePosted") or ""))[:10] or None

        offer = listing.get("offers")
        if isinstance(offer, dict):
            rec["price_zar"] = money(offer.get("price"))
            item = offer.get("itemOffered")
            if isinstance(item, dict):
                rec["bedrooms"] = num(item.get("numberOfBedrooms"))
                rec["bathrooms"] = num(item.get("numberOfBathroomsTotal"))
                floor = item.get("floorSize")
                if isinstance(floor, dict):
                    rec["floor_size_m2"] = area_m2(floor)
                address = item.get("address")
                if isinstance(address, dict):
                    rec["street_address"] = address.get("streetAddress") or None
                rec["property_type"] = str(item.get("@type") or "") or None

        # The aggregator's own description is a one-line précis; the full
        # seller copy — which is what the mandate classifier reads — sits in
        # the page body. Prefer whichever is longer.
        body = soup.select_one("[itemprop=description]") or \
            soup.select_one(".listing-description, #description")
        if body:
            full = body.get_text(" ", strip=True)
            if len(full) > len(rec["description"] or ""):
                rec["description"] = full

        agent = jsonld_by_type(blocks, "RealEstateAgent")
        if agent:
            rec["agency"] = _unescape(agent.get("name"))
            staff = agent.get("employee")
            if isinstance(staff, list) and staff and isinstance(staff[0], dict):
                rec["agent_name"] = _unescape(staff[0].get("name"))

        house = jsonld_by_type(blocks, "House", "Apartment", "Residence")
        if house and not rec["property_type"]:
            rec["property_type"] = str(house.get("@type"))

        # The listing block names only the hero image, so the gallery is
        # counted off the page. Photo count feeds the "how well is this
        # marketed" signal, and reporting 1 for every listing would flatten it.
        images = listing.get("image")
        rec["photo_count"] = len(images) if isinstance(images, list) else (
            1 if images else 0)
        gallery = len({src for src in re.findall(
            r'https://images\.immoafrica\.net[^"\'\s<>]+', html)})
        rec["photo_count"] = max(rec["photo_count"], gallery)

        rec["raw_overview"] = json.dumps(
            {"type_path": urlparse(url).path.split("/")[1]}, ensure_ascii=False)
        return self.finish(rec, html)


def _ident(url: str) -> str:
    m = re.search(r"(IA\d+)", url)
    return m.group(1) if m else ""


def _unescape(value) -> str | None:
    if not value:
        return None
    import html as htmllib
    return htmllib.unescape(str(value))


def _advertised_total(page: str) -> int:
    """The result count the page itself claims, for the coverage warning."""
    m = re.search(r"(\d[\d,]*)\s+(?:propert|result|listing)", page, re.I)
    return int(m.group(1).replace(",", "")) if m else 0
