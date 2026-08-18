"""Property24 — the largest SA portal; carries listings from most agencies.

Notes from the field:
- Throttling is aggressive and sticky (see config.SOURCES["property24"]).
- Detail pages embed a `p24_propertyOverviewRow` table, an `"agencyName"`
  JSON field, and — importantly for cross-portal matching — the property's
  street address and map coordinates.
- Promoted tiles on a suburb search page can point at listings in OTHER
  suburbs, so the suburb is re-derived from the detail URL.
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

import config
import locations
from sources.base import Source, area_m2, money, num, make_soup


class Property24(Source):
    name = "property24"
    label = "Property24"

    def search_urls(self, slug: str, max_pages: int) -> list[str]:
        info = config.SUBURBS.get(slug)
        if not info:
            return []
        # Preferred: the full '<path>/<area_id>' mined from Property24's own
        # sitemap (locations.py). Falls back to the legacy hardcoded id for
        # areas discovery hasn't run for yet.
        area_path = locations.get(self.name, slug)
        if not area_path:
            if not info.get("p24"):
                return []
            legacy = config.SEARCH_PATH_OVERRIDES.get(
                slug, f"{slug}/{info['town']}/{info['province']}")
            area_path = f"{legacy}/{info['p24']}"
        floor = (f"?sp=pf%3d{config.SEARCH_PRICE_FLOOR}"
                 if config.SEARCH_PRICE_FLOOR else "")

        urls: list[str] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            suffix = f"/p{page}" if page > 1 else ""
            page_url = f"{self.fetcher.base_url}/for-sale/{area_path}{suffix}{floor}"
            html = self.fetcher.get(page_url)
            if not html:
                break
            found = re.findall(
                r'href="(/for-sale/[a-z-]+/[a-z-]+/[a-z-]+/\d+/(\d+))', html)
            new = 0
            for href, listing_no in found:
                if listing_no not in seen:
                    seen.add(listing_no)
                    urls.append(self.fetcher.base_url + href)
                    new += 1
            if new == 0:            # ran past the last page
                break
        return urls

    def parse_detail(self, url: str, slug: str) -> dict | None:
        html = self.fetcher.get(url)
        if not html:
            return None
        soup = make_soup(html)

        # Trust the URL's suburb over the page we happened to be crawling.
        url_match = re.search(r"/for-sale/([a-z-]+)/", url)
        if url_match and url_match.group(1) in config.SUBURBS:
            slug = url_match.group(1)

        overview: dict[str, str] = {}
        for row in soup.select(".p24_propertyOverviewRow"):
            key_el = row.select_one(".p24_propertyOverviewKey")
            val_els = row.select(".p24_info")
            if key_el and val_els:
                overview[key_el.get_text(strip=True)] = val_els[0].get_text(" ", strip=True)

        m = re.search(r"/(\d+)(?:\?|$)", url)
        listing_number = m.group(1) if m else overview.get("Listing Number")
        if not listing_number:
            return None

        rec = self.blank(url, slug, listing_number)

        h1 = soup.find("h1")
        rec["title"] = h1.get_text(strip=True) if h1 else ""

        price_el = soup.select_one(".p24_price")
        rec["price_zar"] = money(price_el.get_text(strip=True)) if price_el else None

        desc_el = soup.select_one(".js_expandedText")
        rec["description"] = desc_el.get_text(" ", strip=True) if desc_el else ""

        agency = re.search(r'"agencyName":"([^"]+)"', html)
        rec["agency"] = agency.group(1) if agency else None

        agent = re.search(r'"agentName":"([^"]+)"', html)
        rec["agent_name"] = agent.group(1) if agent else None

        # Unique CDN image ids = photo count
        rec["photo_count"] = len(set(re.findall(r"prop24\.com/(\d+)", html)))

        addr = re.search(r'"streetAddress"\s*:\s*"([^"]+)"', html)
        rec["street_address"] = addr.group(1) if addr else None

        lat = re.search(r'"latitude"\s*:\s*(-?\d+\.\d+)', html)
        lon = re.search(r'"longitude"\s*:\s*(-?\d+\.\d+)', html)
        rec["latitude"] = float(lat.group(1)) if lat else None
        rec["longitude"] = float(lon.group(1)) if lon else None

        # Sale-status badges sit in the main gallery's badge strip as fixed
        # classes (p24_underOfferBanner / p24_reducedBanner). Anchored to the
        # p24_Gallerybadge <ul> so a promoted tile for some OTHER under-offer
        # listing elsewhere on the page can never mark this one.
        strip = re.search(r"p24_Gallerybadge(.{0,400}?)</ul>", html, re.S)
        badges = strip.group(1) if strip else ""
        rec["under_offer"] = int("p24_underOfferBanner" in badges)
        rec["price_reduced"] = int("p24_reducedBanner" in badges)

        rec.update({
            "property_type": overview.get("Type of Property"),
            "bedrooms": num(overview.get("Bedrooms")),
            "bathrooms": num(overview.get("Bathrooms")),
            "garages": num(overview.get("Garage")),
            "parking": num(overview.get("Parking")),
            "floor_size_m2": area_m2(overview.get("Floor Size")),
            "erf_size_m2": area_m2(overview.get("Erf Size")),
            "levies": money(overview.get("Levies")),
            "rates": money(overview.get("Rates and Taxes")),
            "pool": overview.get("Pool"),
            "listing_date": overview.get("Listing Date"),
            "raw_overview": json.dumps(overview, ensure_ascii=False),
        })
        if overview.get("Price per m²"):
            rec["price_per_m2"] = num(overview["Price per m²"])
        return self.finish(rec, html)
