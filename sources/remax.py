"""RE/MAX South Africa.

The cleanest source in the crawl: every detail page ships a complete
schema.org `@graph` containing the offer price, bedroom/bathroom counts, land
area, street address, geo coordinates, the listing date, the selling agent and
the branch office. Almost nothing needs to be scraped out of the markup.
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

import locations
from sources.base import (Source, additional_property, area_m2, coord, jsonld_blocks,
                          jsonld_by_type, money, num, make_soup)


class ReMax(Source):
    name = "remax"
    label = "RE/MAX"

    def search_urls(self, slug: str, max_pages: int) -> list[str]:
        path = locations.get(self.name, slug)
        if not path:
            return []
        urls: list[str] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            page_url = f"{self.fetcher.base_url}/property-for-sale-south-africa/{path}/"
            if page > 1:
                page_url += f"?page={page}"
            html = self.fetcher.get(page_url)
            if not html:
                break
            found = re.findall(
                r'href="(/property-for-sale-south-africa/[^"?#]*?-(\d{5,}))"', html)
            new = 0
            for href, listing_id in found:
                if listing_id not in seen and self.belongs_to(href, slug):
                    seen.add(listing_id)
                    urls.append(self.fetcher.base_url + href)
                    new += 1
            if new == 0:
                break
        return urls

    def parse_detail(self, url: str, slug: str) -> dict | None:
        html = self.fetcher.get(url)
        if not html:
            return None
        soup = make_soup(html)
        blocks = jsonld_blocks(soup)

        m = re.search(r"-(\d{5,})(?:[/?#]|$)", url)
        if not m:
            return None
        rec = self.blank(url, slug, m.group(1))

        listing = jsonld_by_type(blocks, "RealEstateListing")
        offer = jsonld_by_type(blocks, "Offer")
        prop = jsonld_by_type(blocks, "House", "Apartment", "Residence",
                              "SingleFamilyResidence", "Product")

        if listing:
            rec["title"] = listing.get("name") or ""
            rec["description"] = listing.get("description") or ""
            rec["listing_date"] = (listing.get("datePosted") or "")[:10] or None
        if not rec["title"]:
            h1 = soup.find("h1")
            rec["title"] = h1.get_text(" ", strip=True) if h1 else ""

        if offer:
            rec["price_zar"] = money(offer.get("price"))

        if prop:
            rec["bedrooms"] = num(prop.get("numberOfBedrooms"))
            rec["bathrooms"] = num(prop.get("numberOfBathroomsTotal"))
            address = prop.get("address") or {}
            if isinstance(address, dict):
                rec["street_address"] = address.get("streetAddress")
            geo = prop.get("geo") or {}
            if isinstance(geo, dict):
                rec["latitude"] = coord(geo.get("latitude"))
                rec["longitude"] = coord(geo.get("longitude"))
            props = additional_property(prop)
            rec["parking"] = num(props.get("Parking Spaces"))
            rec["garages"] = num(props.get("Garages"))
            rec["erf_size_m2"] = area_m2(props.get("Land Area"))
            rec["floor_size_m2"] = area_m2(props.get("Floor Area")
                                           or props.get("Building Area"))
            rec["property_type"] = props.get("Property Type") or None

        agent = jsonld_by_type(blocks, "Person")
        if agent:
            rec["agent_name"] = agent.get("name")
        office = jsonld_by_type(blocks, "RealEstateAgent")
        rec["agency"] = (office.get("name") or office.get("legalName")
                         if office else "RE/MAX") or "RE/MAX"

        rec["photo_count"] = len({
            b.get("contentUrl") for b in blocks
            if b.get("@type") == "ImageObject" and b.get("contentUrl")
        })

        if rec["property_type"] is None:
            type_m = re.search(r"\b(House|Apartment|Townhouse|Penthouse|Villa|"
                               r"Farm|Vacant Land|Duplex|Cluster)\b",
                               rec["title"] or "", re.I)
            rec["property_type"] = type_m.group(1).title() if type_m else None

        rec["raw_overview"] = json.dumps(
            additional_property(prop) if prop else {}, ensure_ascii=False, default=str)
        return self.finish(rec, html)
