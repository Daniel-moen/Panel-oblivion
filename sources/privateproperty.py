"""Private Property — SA's second-largest portal.

Search pages are server-rendered (detail links carry a `T<id>` reference), and
detail pages expose a JSON-LD `Residence` block plus labelled feature tiles.

The tiles are only the headline summary. Everything else the seller filled in
— levies, rates, the listing date, the pool, the split between garaged and
open parking, the full room breakdown — is in two name/value lists further
down the page (`.property-details__list-item` and
`.property-features__list-item`), and reading only the tiles left every one of
those fields empty on every listing.

Two limits are real rather than parser bugs:

  * The street address is published on roughly half the stock; the rest say
    "Contact agent for street address", which `normalise_address` strips to
    None so it can never be matched on. The coordinates follow the address,
    so they are present on the same listings and absent on the others.
  * The agency/agent block is rendered client-side and appears nowhere in the
    server HTML — no embedded JSON, no referenced endpoint — so `agency` is
    left None here. Private Property still earns its place: it supplies the
    address, coordinates, listing date and the seller's own description,
    which is what cross-portal matching and mandate reading actually need.

Whole-town areas are deep here. Langebaan alone runs to 46 pages of results
(~905 listings), which is why pipeline.py gives a `scope: "town"` area a much
larger page budget than a single suburb.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from bs4 import BeautifulSoup

import locations
from sources.base import (Source, additional_property, area_m2, jsonld_blocks,
                          jsonld_by_type, money, num, make_soup)


class PrivateProperty(Source):
    name = "privateproperty"
    label = "Private Property"

    def search_urls(self, slug: str, max_pages: int) -> list[str]:
        path = locations.get(self.name, slug)
        if not path:
            return []
        urls: list[str] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            page_url = f"{self.fetcher.base_url}/for-sale/{path}"
            if page > 1:
                page_url += f"?page={page}"
            html = self.fetcher.get(page_url)
            if not html:
                break
            found = re.findall(r'href="(/for-sale/[^"?#]*?/(T\d+))"', html)
            new = 0
            for href, ref in found:
                if ref not in seen and self.belongs_to(href, slug):
                    seen.add(ref)
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

        m = re.search(r"/(T\d+)(?:[/?#]|$)", url)
        if not m:
            return None

        # Sale-status banners on the gallery. Only the details-page container
        # is read (`--details`), because search cards elsewhere in the markup
        # carry the same banner classes for other properties.
        status = ""
        banners = soup.select_one(".listing-banners--details")
        if banners:
            status = " ".join(
                cls for tag in banners.find_all(True)
                for cls in (tag.get("class") or []))
        if "listing-banner--sold" in status:
            return None      # sold stock stays in search results for a while

        rec = self.blank(url, slug, m.group(1))
        rec["under_offer"] = int("listing-banner--offer-pending" in status)
        rec["price_reduced"] = int("listing-banner--price-reduced" in status)

        title = soup.select_one(".listing-details__title") or soup.find("h1")
        rec["title"] = title.get_text(" ", strip=True) if title else ""

        price = soup.select_one(".listing-price-display__price")
        rec["price_zar"] = money(price.get_text(strip=True)) if price else None

        desc = soup.select_one(".listing-description__text")
        rec["description"] = desc.get_text(" ", strip=True) if desc else ""

        addr = soup.select_one(".listing-details__address")
        rec["street_address"] = addr.get_text(" ", strip=True) if addr else None

        # Feature tiles carry a `title` attribute naming the metric.
        for tile in soup.select(".listing-details__main-feature"):
            label = str(tile.get("title") or "").strip().lower()
            value = tile.get_text(" ", strip=True)
            if label == "bedrooms":
                rec["bedrooms"] = num(value)
            elif label == "bathrooms":
                rec["bathrooms"] = num(value)
            elif label in ("parking spaces", "garages"):
                rec["parking"] = num(value)
            elif label == "land size":
                rec["erf_size_m2"] = area_m2(value)
            elif label == "floor size":
                rec["floor_size_m2"] = area_m2(value)

        # The headline tiles are only a summary. Everything else the seller
        # filled in — levies, rates, the listing date, the pool, the split
        # between garaged and open parking — sits in two name/value lists
        # further down the page, and reading only the tiles left all of it
        # empty on every Private Property listing.
        spec = _spec_lists(soup)
        for label, field, cast in (
                ("bedrooms", "bedrooms", num),
                ("bathrooms", "bathrooms", num),
                ("garage parking", "garages", num),
                ("open parking", "parking", num),
                ("land size", "erf_size_m2", area_m2),
                ("floor size", "floor_size_m2", area_m2),
                ("levies", "levies", money),
                ("rates and taxes", "rates", money)):
            value = spec.get(label)
            if isinstance(value, str) and rec.get(field) is None:
                rec[field] = cast(value)

        # A flag-style entry has no value; its presence is the fact.
        rec["pool"] = int("pool" in spec)

        if isinstance(spec.get("property type"), str):
            rec["property_type"] = spec["property type"]
        rec["listing_date"] = _listing_date(spec.get("listing date"))

        blocks = jsonld_blocks(soup)
        residence = jsonld_by_type(blocks, "Residence", "SingleFamilyResidence",
                                   "House", "Apartment")
        if residence:
            props = additional_property(residence)
            rec["bedrooms"] = rec["bedrooms"] or num(props.get("Bedrooms"))
            rec["bathrooms"] = rec["bathrooms"] or num(props.get("Bathrooms"))
            rec["garages"] = rec["garages"] or num(props.get("Garages"))
            photos = residence.get("photo") or []
            rec["photo_count"] = len(photos) if isinstance(photos, list) else 1
            address = residence.get("address") or {}
            if isinstance(address, dict):
                rec["street_address"] = rec["street_address"] or address.get("streetAddress")

        # Private Property lazy-loads the gallery: only the first ~9 images are
        # in the server HTML, so this is a floor rather than the true count.
        # Scoring takes the highest photo_count across a property's listings,
        # so a richer portal in the same group supplies the real figure.
        rec["photo_count"] = max(
            rec["photo_count"] or 0,
            len(soup.select(".details-page-photogrid__photo")),
        )

        lat = re.search(r'"latitude"\s*:\s*"?(-?\d+\.\d+)', html)
        lon = re.search(r'"longitude"\s*:\s*"?(-?\d+\.\d+)', html)
        la = float(lat.group(1)) if lat else None
        lo = float(lon.group(1)) if lon else None
        # A minority of pages publish the pair swapped (latitude 18.05,
        # longitude -33.04) and a pin in the ocean can never point-match a
        # cadastre parcel. South African pins are always lat < 0 < lng, so a
        # swapped pair is recoverable in place.
        if la is not None and lo is not None and la > 0 > lo:
            la, lo = lo, la
        rec["latitude"] = la
        rec["longitude"] = lo

        if not rec["property_type"]:
            # "836 m² Land available in Langebaan Country Estate" is how the
            # portal titles a plot, which the type list above does not match —
            # so land has to be recognised here or it is filed as an untyped
            # listing and slips past the vacant-land filter.
            type_m = re.search(
                r"\b(House|Apartment|Townhouse|Penthouse|Villa|Farm|"
                r"Vacant Land|Land|Plot|Duplex|Cluster)\b",
                rec["title"] or "", re.I)
            rec["property_type"] = type_m.group(1).title() if type_m else None

        rec["raw_overview"] = json.dumps(spec, ensure_ascii=False, default=str)
        return self.finish(rec, html)


def _spec_lists(soup) -> dict[str, object]:
    """The page's two name/value lists as {label: value}.

    Entries come in two shapes: a labelled value ("Levies | R 1 315") and a
    bare flag whose presence is the fact ("Pool", "Pet friendly"). Flags are
    stored as True so a caller can test membership without having to know
    which shape a given feature uses.
    """
    spec: dict[str, object] = {}
    for item in soup.select(".property-details__list-item, "
                            ".property-features__list-item"):
        parts = [p.strip() for p in item.get_text("\x1f", strip=True).split("\x1f")
                 if p.strip()]
        if not parts:
            continue
        label = parts[0].lower()
        spec.setdefault(label, parts[1] if len(parts) > 1 else True)
    return spec


def _listing_date(value) -> str | None:
    """"22 Jul 2026" -> "2026-07-22"."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%d %b %Y").strftime("%Y-%m-%d")
    except ValueError:
        return None
