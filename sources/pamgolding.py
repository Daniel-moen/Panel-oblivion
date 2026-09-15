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
    # rentals
    "isFurnished", "availableFrom", "availableDate", "rentalDeposit",
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
    supports_rent = True

    def search_urls(self, slug: str, max_pages: int,
                    listing_type: str = "sale") -> list[str]:
        if listing_type not in ("sale", "rent"):
            return []
        # Pam Golding's area reference names the book it belongs to and
        # carries a DIFFERENT id per book ("residential-properties-for-sale-
        # camps-bay/2113" vs "residential-properties-to-rent-stellenbosch/
        # 2932"), so the rental path is discovered separately rather than
        # derived — see locations._discover_pamgolding.
        ref = locations.get(self.name, slug, listing_type)
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
            # Rental references run to three letters ("stl1750740") where the
            # sale book mostly uses two, so the width is deliberately loose.
            found = re.findall(
                r'href="(/property-details/[^"?#]+/([a-z]{2,4}\d+))"',
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

    def parse_detail(self, url: str, slug: str,
                     listing_type: str = "sale") -> dict | None:
        html = self.fetcher.get(url)
        if not html:
            return None
        data = _hydrate(html)
        if not data:
            return None

        ref = data.get("webListingReference")
        if not ref:
            m = re.search(r"/([a-z]{2,4}\d+)(?:[/?#]|$)", url, re.I)
            ref = m.group(1).upper() if m else None
        if not ref:
            return None

        # Sold stock is not a prospect.
        if data.get("isSold"):
            return None

        rec = self.blank(url, slug, str(ref).upper(), listing_type)

        rec["title"] = (data.get("marketingHeader")
                        or data.get("propertyDescription") or "")
        rec["description"] = _strip_html(data.get("marketingDescription"))
        # priceZAR is the monthly rent on a rental (verified: a Stellenbosch
        # student apartment reports 15000). The payload states no period, and
        # Pam Golding's rental book is long lets, so "month" is recorded
        # rather than left unknown.
        rec["price_zar"] = None if data.get("poa") else money(data.get("priceZAR"))
        if listing_type == "rent":
            rec["rent_period"] = "month" if rec["price_zar"] else None
            furnished = data.get("isFurnished")
            rec["furnished"] = (None if furnished is None
                                else "Yes" if furnished else "No")
            available = data.get("availableFrom") or data.get("availableDate")
            rec["available_from"] = (str(available)[:10] or None) if available else None
            rec["deposit"] = money(data.get("rentalDeposit")) \
                if data.get("rentalDeposit") else None
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
