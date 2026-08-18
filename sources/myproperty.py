"""MyProperty — a national aggregator carrying many agencies' stock.

Two things make an aggregator worth crawling alongside the agency sites it
syndicates. It reaches brands that have no site this engine scrapes directly,
and because the same house appears here under whichever agency loaded it,
dedupe gains another independent witness to how many agencies are marketing a
property — which is the open-mandate proof the whole engine is built around.

The page is a Next.js app. Everything structural comes out of a clean
schema.org `RealEstateListing` block, but the marketing agency is not in it —
that lives in the streamed React payload as `"officeName":"..."`, alongside
the agent's name, and is dug out with a regex because the surrounding payload
is a serialised component tree rather than a document.
"""

from __future__ import annotations

import html as htmllib
import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

import config
from sources.base import (Source, area_m2, jsonld_blocks, jsonld_by_type,
                          money, num, make_soup)


def _slug_for_path(path: str) -> str | None:
    """The configured suburb a detail URL belongs to, or None.

    Detail URLs are `/en-za/for-sale/<type>/<province>/<town>/<suburb>/
    <n>-bedroom/<id>`, so the area is pinned by position and the town can be
    checked rather than assumed — the same guard `PropDataSource` needs, for
    the same reason (a Newlands and a Noordhoek exist in several provinces).
    """
    parts = [p for p in path.split("/") if p]
    if len(parts) < 6 or parts[1] != "for-sale":
        return None
    province, town, suburb = parts[3], parts[4], parts[5]
    for slug in (suburb, town):
        info = config.SUBURBS.get(slug)
        if not info or info["province"] != province:
            continue
        if town == info["town"] or slug == town:
            return slug
    return None


class MyProperty(Source):
    name = "myproperty"
    label = "MyProperty"

    def search_urls(self, slug: str, max_pages: int) -> list[str]:
        info = config.SUBURBS.get(slug)
        if not info:
            return []
        # A whole-town area is searched at town level. Repeating the town as
        # its own suburb (".../hermanus/hermanus") is a valid URL that returns
        # an empty grid, so the mistake shows up as "no listings" rather than
        # as an error.
        area = (f"{info['province']}/{info['town']}"
                if info.get("scope") == "town" or info["town"] == slug
                else f"{info['province']}/{info['town']}/{slug}")
        base = f"{self.fetcher.base_url}/en-za/for-sale/{area}"
        urls: list[str] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            html = self.fetcher.get(base if page == 1 else f"{base}?page={page}")
            if not html:
                break
            new = 0
            for href in re.findall(r'href="(/en-za/for-sale/[^"?#]+)"', html):
                ident = self.listing_id(href)
                if ident and ident not in seen and self.belongs_to(href, slug):
                    seen.add(ident)
                    urls.append(self.fetcher.base_url + href)
                    new += 1
            if new == 0:
                break            # past the last page — the grid comes back empty
        return urls

    def belongs_to(self, href: str, slug: str) -> bool:
        return _slug_for_path(urlparse(href).path) == slug

    @staticmethod
    def listing_id(url: str) -> str | None:
        """Trailing id — numeric on some listings, a web reference on others
        ("rl61722"), so it cannot be assumed to be digits."""
        parts = [p for p in urlparse(url).path.split("/") if p]
        if len(parts) < 7 or parts[1] != "for-sale":
            return None
        last = parts[-1]
        return last if re.fullmatch(r"[a-z]{0,4}\d{4,}", last, re.I) else None

    def parse_detail(self, url: str, slug: str) -> dict | None:
        html = self.fetcher.get(url)
        if not html:
            return None
        ident = self.listing_id(url)
        if not ident:
            return None
        soup = make_soup(html)
        listing = jsonld_by_type(jsonld_blocks(soup), "RealEstateListing")
        if not listing:
            return None

        rec = self.blank(url, slug, ident)
        rec["title"] = listing.get("name") or ""
        # The description ships as an HTML fragment; the mandate classifier and
        # the AI scorer both want prose, and "<p>Sole mandate</p>" must not
        # arrive with the tags attached.
        rec["description"] = _text(listing.get("description"))
        rec["listing_date"] = (str(listing.get("datePosted") or ""))[:10] or None
        rec["bedrooms"] = num(listing.get("numberOfBedrooms"))
        rec["bathrooms"] = num(listing.get("numberOfBathroomsTotal"))

        offers = listing.get("offers")
        if isinstance(offers, dict):
            rec["price_zar"] = money(offers.get("price"))
        rec["erf_size_m2"] = _quantity(listing.get("lotSize"))
        rec["floor_size_m2"] = _quantity(listing.get("floorSize"))

        address = listing.get("address")
        if isinstance(address, dict):
            rec["street_address"] = address.get("streetAddress") or None

        images = listing.get("image")
        if isinstance(images, list):
            rec["photo_count"] = len(images)
        elif images:
            rec["photo_count"] = 1

        # Agency and agent live only in the streamed component payload.
        office = re.search(r'\\?"officeName\\?":\\?"([^"\\]{2,80})', html)
        rec["agency"] = htmllib.unescape(office.group(1)) if office else None
        agent = re.search(r'\\?"agents\\?":\[\{\\?"name\\?":\\?"([^"\\]{2,60})', html)
        rec["agent_name"] = htmllib.unescape(agent.group(1)) if agent else None

        segs = [p for p in urlparse(url).path.split("/") if p]
        rec["property_type"] = segs[2].replace("-", " ").title() if len(segs) > 2 else None

        features = [b.get_text(" ", strip=True)
                    for b in soup.select(".mp-badge--feature")]
        rec["pool"] = int(any("pool" in f.lower() for f in features))
        rec["raw_overview"] = json.dumps({"features": features[:40]},
                                         ensure_ascii=False)
        return self.finish(rec, html)


def _text(value) -> str:
    """Plain text from an HTML fragment."""
    if not value:
        return ""
    return BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)


def _quantity(value) -> float | None:
    """Value out of a schema.org QuantitativeValue, hectares converted."""
    return area_m2(value)
