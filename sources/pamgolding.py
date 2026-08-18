"""Pam Golding — the single most valuable source in the crawl.

Pam Golding is a Nuxt app that ships its entire server state in a
`__NUXT_DATA__` payload (devalue's flat-array format: values are stored once
and referenced by integer index). Hydrating it yields the full listing record,
including two fields no other portal publishes:

  isExclusiveMandate : hard ground truth on whether the listing is a sole
                       mandate. This is the difference between guessing from
                       description prose and simply knowing. Non-exclusive
                       listings here are directly sellable for Oblivion.
  mandateCreated     : when the mandate started. SA mandates typically run
                       3-6 months, so an exclusive one created 5+ months ago
                       is about to come up for renewal — the ideal moment to
                       pitch. See scorer.py, which uses this for timing.
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

import locations
from sources.base import Source, area_m2, money, num

# Fields lifted out of the payload. Keys are specific enough that scanning
# every dict for the first non-null occurrence is unambiguous.
WANTED = (
    "isExclusiveMandate", "mandateCreated", "mandateId", "priceZAR", "poa",
    "marketingHeader", "marketingDescription", "propertyDescription",
    "streetAddress", "officeName", "agentName", "lattitude", "longitude",
    "dateFirstOnWeb", "priceReduced", "priceReducedDate", "underOffer",
    "isSold", "webListingReference", "propertyType", "erfSize", "buildingSize",
    "bedrooms", "bathrooms", "garages", "parkingBays",
    "fullLocationDescription", "images",
)


def _hydrate(html: str) -> dict | None:
    """Pull the flat devalue payload out of the page and flatten the fields."""
    m = re.search(r'id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        flat = json.loads(m.group(1))
    except ValueError:
        return None
    if not isinstance(flat, list):
        return None

    def deref(v):
        if isinstance(v, int) and 0 <= v < len(flat):
            return flat[v]
        return v

    out: dict = {}
    for entry in flat:
        if not isinstance(entry, dict):
            continue
        for key in WANTED:
            if key in entry and key not in out:
                val = deref(entry[key])
                # devalue encodes "absent" as -1 into the value table
                if val is not None and val != -1:
                    out[key] = val
    return out or None


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)


class PamGolding(Source):
    name = "pamgolding"
    label = "Pam Golding"

    def search_urls(self, slug: str, max_pages: int) -> list[str]:
        ref = locations.get(self.name, slug)
        if not ref:
            return []
        urls: list[str] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            page_url = f"{self.fetcher.base_url}/property-search/{ref}"
            if page > 1:
                page_url += f"?page={page}"
            html = self.fetcher.get(page_url)
            if not html:
                break
            found = re.findall(r'href="(/property-details/[^"?#]+/([a-z]{2}\d+))"',
                               html, re.I)
            new = 0
            for href, ref_id in found:
                key = ref_id.lower()
                if key not in seen and self.belongs_to(href, slug):
                    seen.add(key)
                    urls.append(self.fetcher.base_url + href)
                    new += 1
            if new == 0:
                break
        return urls

    def parse_detail(self, url: str, slug: str) -> dict | None:
        html = self.fetcher.get(url)
        if not html:
            return None
        data = _hydrate(html)
        if not data:
            return None

        ref = data.get("webListingReference")
        if not ref:
            m = re.search(r"/([a-z]{2}\d+)(?:[/?#]|$)", url, re.I)
            ref = m.group(1).upper() if m else None
        if not ref:
            return None

        # Sold stock is not a prospect.
        if data.get("isSold"):
            return None

        rec = self.blank(url, slug, str(ref).upper())

        rec["title"] = (data.get("marketingHeader")
                        or data.get("propertyDescription") or "")
        rec["description"] = _strip_html(data.get("marketingDescription"))
        rec["price_zar"] = None if data.get("poa") else money(data.get("priceZAR"))
        rec["property_type"] = data.get("propertyType")
        rec["bedrooms"] = num(data.get("bedrooms"))
        rec["bathrooms"] = num(data.get("bathrooms"))
        rec["garages"] = num(data.get("garages"))
        rec["parking"] = num(data.get("parkingBays"))
        rec["floor_size_m2"] = area_m2(data.get("buildingSize"))
        rec["erf_size_m2"] = area_m2(data.get("erfSize"))
        rec["street_address"] = data.get("streetAddress")
        rec["latitude"] = num(data.get("lattitude"))
        rec["longitude"] = num(data.get("longitude"))
        rec["agency"] = ("Pam Golding" if not data.get("officeName")
                         else f"Pam Golding ({data['officeName']})")
        rec["agent_name"] = data.get("agentName")
        rec["listing_date"] = (data.get("dateFirstOnWeb") or "")[:10] or None
        images = data.get("images")
        rec["photo_count"] = len(images) if isinstance(images, list) else 0
        rec["price_reduced"] = 1 if data.get("priceReduced") else 0
        rec["under_offer"] = 1 if data.get("underOffer") else 0
        # Structured development link when present. It often isn't — Pam
        # Golding listed an unbuilt Clifton development as a plain "House"
        # with developmentId None — so finish() also reads the copy.
        rec["is_development"] = 1 if (data.get("developmentId")
                                      or data.get("linkedDevelopment")) else 0

        # The headline signal: hard mandate ground truth.
        exclusive = data.get("isExclusiveMandate")
        if exclusive is True:
            rec["mandate_explicit"] = "sole"
        elif exclusive is False:
            rec["mandate_explicit"] = "not_sole"

        rec["raw_overview"] = json.dumps({
            "mandateCreated": data.get("mandateCreated"),
            "mandateId": data.get("mandateId"),
            "isExclusiveMandate": exclusive,
            "priceReducedDate": data.get("priceReducedDate"),
            "location": data.get("fullLocationDescription"),
        }, ensure_ascii=False)

        return self.finish(rec, html)
