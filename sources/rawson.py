"""Rawson Properties — scraped through the site's own markdown endpoints.

Rawson serves a plain-markdown rendering of every page: append `.md` to any
search or listing URL and the site returns a tidy, labelled document instead
of an application shell. The HTML pages carry no schema.org data and build
their result grids client-side, so the markdown is not merely more convenient
here — it is the only server-rendered form of the data, and it happens to be
the form the site publishes deliberately for machine readers.

The one thing the markdown does not give away in the URL is the suburb: a
listing lives under the *branch office* that took the mandate
(`/property/for-sale/cape-town-cbd/1356575` is a Camps Bay house sold out of
the CBD office). The usual "the slug must appear in the URL" guard would
reject every one of them, so membership is decided on the `Location:` field
in the document instead, which is a stronger check than the URL anyway.
"""

from __future__ import annotations

import json
import re

import config
from sources.base import Source, area_m2, money, num, rent_price

# "- **Price:** R19,995,000" and friends.
_FIELD = re.compile(r"^-\s+\*\*(?P<key>[^*]+?):?\*\*\s*(?P<value>.+?)\s*$", re.M)
_LISTING_LINK = re.compile(
    r"\((https://rawson\.co\.za/(?:commercial-)?property/(?:for-sale|to-rent)"
    r"/[^)\s]+?/(\d{5,}))\)")

# The rental book is the same markdown endpoint under /to-rent/ (verified:
# /property/to-rent/camps-bay.md returns "# Camps Bay Flats and Houses to
# Rent" with prices quoted "R75,000 p/m"). Rental detail URLs live under the
# branch's rentals office ("/property/to-rent/green-point-rentals/1335310"),
# which is exactly why membership here is decided on the document's own
# Location line rather than on the URL.
_BOOK_SECTION = {"sale": "for-sale", "rent": "to-rent"}
_SECTION = re.compile(r"^##\s+(.+?)\s*$", re.M)

# The HTML page shows status badges directly above the title that the
# markdown rendering drops entirely: "Sole Mandate" / "Joint Mandate" /
# "Under Offer" / "Reduced" / "New Listing". The block immediately precedes
# the hero <h1>, which is what anchors it to THIS property — search grids
# elsewhere carry the same badge classes per result card.
_BADGE_BLOCK = re.compile(
    r'((?:<div class="badge badge--\w+">[^<]{1,30}</div>\s*)+)'
    r'<h1 class="hero__title"')


def _hero_badges(html: str) -> set[str]:
    m = _BADGE_BLOCK.search(html or "")
    if not m:
        return set()
    return {b.strip().lower()
            for b in re.findall(r">([^<]+)</div>", m.group(1))}


class Rawson(Source):
    name = "rawson"
    label = "Rawson"
    supports_rent = True

    def search_urls(self, slug: str, max_pages: int,
                    listing_type: str = "sale") -> list[str]:
        section = _BOOK_SECTION.get(listing_type)
        if not section:
            return []
        urls: list[str] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            url = f"{self.fetcher.base_url}/property/{section}/{slug}.md"
            if page > 1:
                url += f"?page={page}"
            body = self.fetcher.get(url)
            if not body or not body.lstrip().startswith("#"):
                break
            new = 0
            for link, listing_id in _LISTING_LINK.findall(body):
                if listing_id in seen or "commercial-property" in link:
                    continue
                seen.add(listing_id)
                urls.append(link)
                new += 1
            if new == 0:
                break
        return urls

    def parse_detail(self, url: str, slug: str,
                     listing_type: str = "sale") -> dict | None:
        body = self.fetcher.get(url + ".md")
        if not body:
            return None
        m = re.search(r"/(\d{5,})(?:[/?#]|$)", url)
        if not m:
            return None

        fields = {k.strip().lower(): v.strip()
                  for k, v in _FIELD.findall(body)}

        # The URL names the branch office, not the area, so the document's own
        # Location line is what decides whether this listing is in the suburb
        # we asked for.
        if not self._location_matches(fields.get("location", ""), slug):
            return None

        heading = re.search(r"^#\s+(.+?)\s*$", body, re.M)
        title = heading.group(1).strip() if heading else ""

        # The search returns already-concluded stock alongside live listings,
        # and says so only in the heading: "2 Bedroom apartment **sold** in
        # Hermanus Beach Club" for sales, "2 Bedroom apartment **rented** in
        # Sea Point" for rentals (observed on the live to-rent crawl). There
        # is nothing left to win on either, and letting them through would put
        # sold homes in the prospect report and let flats in the rental book.
        if re.search(r"\b(?:sold|rented|let)\s+in\b", title, re.I):
            return None

        rec = self.blank(url, slug, m.group(1), listing_type)
        rec["agency"] = "Rawson Properties"
        rec["title"] = title
        if listing_type == "rent":
            # "- **Price:** R75,000 p/m"
            rec["price_zar"], rec["rent_period"] = rent_price(fields.get("price"))
            rec["available_from"] = (fields.get("available from")
                                     or fields.get("occupation date"))
            rec["furnished"] = fields.get("furnished")
            if fields.get("deposit"):
                rec["deposit"] = money(fields["deposit"])
        else:
            rec["price_zar"] = money(fields.get("price"))
        rec["property_type"] = fields.get("property type")
        rec["bedrooms"] = num(fields.get("bedrooms"))
        rec["bathrooms"] = num(fields.get("bathrooms"))
        rec["garages"] = num(fields.get("garages"))

        sections = _sections(body)
        rec["description"] = sections.get("description", "").strip()

        # The Details/Interior/Exterior bullet lists are free text, so the
        # numbers are read out of them rather than looked up by key.
        spec = " ".join(sections.get(s, "") for s in
                        ("details", "interior features", "exterior features"))
        for pattern, field in (
                # Capture the unit too: farms are listed in hectares, and the
                # bare number would file a 22 ha estate as a 22 m² erf.
                (r"ERF Size\s+([\d\s,.]+\s*(?:ha\b|m))", "erf_size_m2"),
                (r"Building Size\s+([\d\s,.]+\s*(?:ha\b|m))", "floor_size_m2"),
                (r"Rates\s+R([\d\s,.]+)", "rates"),
                (r"Levy\s+R([\d\s,.]+)", "levies"),
                (r"(\d+)\s+Parking Spaces?", "parking")):
            hit = re.search(pattern, spec, re.I)
            if hit and rec.get(field) is None:
                rec[field] = (money(hit.group(1))
                              if field in ("rates", "levies")
                              else area_m2(hit.group(1))
                              if field.endswith("_m2")
                              else num(hit.group(1)))
        # The search document labels the room counts; the detail document only
        # lists them as features, so each needs a fallback read out of the
        # bullet lists or it stays empty on every listing crawled directly.
        for pattern, field in ((r"(\d+)\s+Bedrooms?", "bedrooms"),
                               (r"(\d+)\s+Bathrooms?", "bathrooms"),
                               (r"(\d+)\s+Garages?", "garages")):
            if rec.get(field) is None:
                hit = re.search(pattern, spec, re.I)
                rec[field] = num(hit.group(1)) if hit else None

        if not rec["property_type"]:
            # Only the search document labels the type; on a listing page it
            # has to come out of the heading — "5 Bedroom house for sale in
            # Camps Bay", "Vacant Land for sale in Fisherhaven". Getting this
            # right is what lets the vacant-land filter see a Rawson plot at
            # all, since nothing in its URL says so.
            hit = re.search(r"^(?:[\d.]+\s+Bedroom\s+)?(.+?)\s+"
                            r"(?:for\s+sale|sold|to\s+let|to\s+rent)\b",
                            rec["title"], re.I)
            rec["property_type"] = hit.group(1).strip().title() if hit else None
        rec["pool"] = int(bool(re.search(r"^\s*-\s*Pool\b", spec, re.I | re.M)
                               or re.search(r"\bPool\b", spec)))

        # "- Alisdair Crofton — 072 416 1491 — alisdair.c@rawson.co.za"
        agent = re.search(r"^-\s+([^—\n]{3,60}?)\s+—\s+[\d\s]{9,}",
                          sections.get("agent", ""), re.M)
        rec["agent_name"] = agent.group(1).strip() if agent else None

        # The markdown drops the page's status badges, so the HTML page is
        # fetched as well (same rate limit, cached like any other page). It
        # buys explicit mandate ground truth — Rawson badges "Sole Mandate"
        # and "Joint Mandate" on the listing itself — plus under-offer and
        # price-reduced status, and gives finish() a gallery to capture the
        # hero photo from at crawl time instead of lazily.
        page_html = self.fetcher.get(url)
        badges = _hero_badges(page_html)
        if "sole mandate" in badges:
            rec["mandate_explicit"] = "sole"
        elif "joint mandate" in badges:
            # The engine's glossary: a joint mandate means the seller already
            # accepts multiple agencies — non-exclusive.
            rec["mandate_explicit"] = "not_sole"
        rec["under_offer"] = int("under offer" in badges)
        rec["price_reduced"] = int("reduced" in badges)

        rec["raw_overview"] = json.dumps(
            {**fields, "office": sections.get("office", "").strip()[:120],
             **({"badges": sorted(badges)} if badges else {})},
            ensure_ascii=False)
        return self.finish(rec, page_html)

    @staticmethod
    def _location_matches(location: str, slug: str) -> bool:
        """True if a "Camps Bay, Cape Town" location line names this area.

        Compared on slugified words so "Camps Bay" matches `camps-bay`, and
        the town half is accepted for whole-town areas, which is exactly the
        set of areas a town name should satisfy.
        """
        if not location:
            return False
        parts = [re.sub(r"[^a-z0-9]+", "-", p.strip().lower()).strip("-")
                 for p in location.split(",")]
        info = config.SUBURBS.get(slug, {})
        if slug in parts:
            return True
        return info.get("scope") == "town" and info.get("town") in parts


def _sections(body: str) -> dict[str, str]:
    """Markdown "## Heading" sections, keyed by lower-cased heading.

    The document is a flat sequence of headings — Details, Interior features,
    Exterior features, Description, Agent, Office — so splitting on them keeps
    the room list from being mistaken for the seller's copy.
    """
    out: dict[str, str] = {}
    marks = list(_SECTION.finditer(body))
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        out[mark.group(1).strip().lower()] = body[mark.end():end]
    return out
