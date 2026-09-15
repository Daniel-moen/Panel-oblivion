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
                          jsonld_by_type, money, num, make_soup, rent_period)


# Beyond the schema.org graph, every page embeds its CRM record as an
# escaped-JSON blob carrying fields the graph lacks — most importantly the
# mandate type itself: "Open" (787 of 1 600 cached listings), "Sole" (641),
# "Joint" (121), "Dual" (38) or "Opposition" (13). That is published mandate
# ground truth on the same footing as Pam Golding's isExclusiveMandate, on a
# portal that had none. `sale_state` ("Offer Made"/"Price Reduced"/"Sold")
# and an `expiry_date` epoch ride along. Search pages embed one blob per
# result card, so the fields are only trusted when the page carries exactly
# one mandate key — which is what distinguishes a detail page.
def _crm_blob(html: str) -> dict:
    mandates = re.findall(r'\\"mandate\\":\\"(\w+)\\"', html)
    if len(mandates) != 1:
        return {}
    out: dict = {"mandate": mandates[0]}
    state = re.search(r'\\"sale_state\\":\\"([^"\\]*)\\"', html)
    if state:
        out["sale_state"] = state.group(1)
    expiry = re.search(r'\\"expiry_date\\":(\d+)', html)
    if expiry and int(expiry.group(1)):
        from datetime import datetime, timezone
        out["expiryDate"] = datetime.fromtimestamp(
            int(expiry.group(1)), tz=timezone.utc).strftime("%Y-%m-%d")
    return out


# The engine's SA-mandate glossary (scorer.SYSTEM_PROMPT): sole/exclusive is
# closed to Oblivion; joint/dual means the seller has already accepted more
# than one agency — a prospect signal, not an exclusivity signal. "Opposition"
# (another agency holds the mandate) is left unmapped: too ambiguous to feed
# a hard rule.
_MANDATE_EXPLICIT = {"Sole": "sole", "Open": "not_sole",
                     "Joint": "not_sole", "Dual": "not_sole"}


# The rental book is the same site under a different root segment and the
# SAME area path (verified: /property-to-rent-south-africa/western-cape/
# cape-town/camps-bay lists Camps Bay rentals, and the detail pages carry the
# usual schema.org @graph with businessFunction LeaseOut).
_SECTION = {"sale": "property-for-sale-south-africa",
            "rent": "property-to-rent-south-africa"}


class ReMax(Source):
    name = "remax"
    label = "RE/MAX"
    supports_rent = True

    def search_urls(self, slug: str, max_pages: int,
                    listing_type: str = "sale") -> list[str]:
        section = _SECTION.get(listing_type)
        if not section:
            return []
        path = locations.get(self.name, slug, listing_type)
        if not path:
            return []
        urls: list[str] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            page_url = f"{self.fetcher.base_url}/{section}/{path}/"
            if page > 1:
                page_url += f"?page={page}"
            html = self.fetcher.get(page_url)
            if not html:
                break
            found = re.findall(
                rf'href="(/{section}/[^"?#]*?-(\d{{5,}}))"', html)
            new = 0
            for href, listing_id in found:
                if listing_id not in seen and self.belongs_to(href, slug):
                    seen.add(listing_id)
                    urls.append(self.fetcher.base_url + href)
                    new += 1
            if new == 0:
                break
        return urls

    def parse_detail(self, url: str, slug: str,
                     listing_type: str = "sale") -> dict | None:
        html = self.fetcher.get(url)
        if not html:
            return None
        soup = make_soup(html)
        blocks = jsonld_blocks(soup)

        m = re.search(r"-(\d{5,})(?:[/?#]|$)", url)
        if not m:
            return None

        crm = _crm_blob(html)
        if crm.get("sale_state") == "Sold":
            return None      # sold stock lingers in the for-sale search

        rec = self.blank(url, slug, m.group(1), listing_type)
        rec["mandate_explicit"] = _MANDATE_EXPLICIT.get(crm.get("mandate"))
        rec["under_offer"] = int(crm.get("sale_state") == "Offer Made")
        rec["price_reduced"] = int(crm.get("sale_state") == "Price Reduced")

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
        if listing_type == "rent":
            # The Offer block gives the bare number (250000) with no period,
            # so the period is read off the page copy ("R250 000 per month")
            # and defaults to monthly, which is what RE/MAX's rental book is.
            rec["rent_period"] = rent_period(rec["title"]) or rent_period(
                " ".join(re.findall(r"R[\d\s,.]{3,}\s*(?:per\s+\w+|p\s*/?\s*[mwd])",
                                    html, re.I)[:3])) or "month"

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

        raw = additional_property(prop) if prop else {}
        # expiryDate is the CRM's own end date for the record. On a "Sole"
        # listing that is the mandate's likely expiry — the pitch window —
        # so the scorer reads it back out of raw_overview.
        raw.update(crm)
        rec["raw_overview"] = json.dumps(raw, ensure_ascii=False, default=str)
        return self.finish(rec, html)
