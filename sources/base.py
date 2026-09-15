"""Source plugin interface and shared parsing helpers.

Every portal scraper returns the same normalised listing dict, so the rest of
the pipeline (dedupe, scoring, reporting) is portal-agnostic. Fields absent on
a given portal are simply None.

Both books are crawled through the same objects. `search_urls()` and
`parse_detail()` take a `listing_type` of "sale" (the default, so nothing that
predates rentals changes) or "rent", and a source that cannot build a rent URL
it has actually verified returns nothing for "rent" rather than guessing — a
portal answers an unrecognised path with a fallback result set, not a 404, so
a guessed rent path silently files somebody else's stock under our suburb.

One Source instance serves both books deliberately: the Fetcher (and therefore
the adaptive rate limiter) belongs to the instance, and a second instance per
portal would mean two limiters racing each other at the same host — which on
Property24 is exactly how a sticky block gets earned.
"""

from __future__ import annotations

import json
import re
import threading

import config
from bs4 import BeautifulSoup

from httpclient import Fetcher

# Parsing is CPU-bound and holds the GIL, so every scraper funnels its tree
# building through this gate while network waits stay concurrent. Measured:
# 1 parsing thread does ~44 pages/sec, 8 threads only ~20, and 4 crawl threads
# parsing push a dashboard query from 93ms to 3.5s. See config.PARSE_WORKERS.
_PARSE_GATE = threading.Semaphore(max(1, config.PARSE_WORKERS))


def make_soup(html: str, parser: str | None = None) -> BeautifulSoup:
    """BeautifulSoup, gated so parsing cannot starve the web dashboard."""
    with _PARSE_GATE:
        return BeautifulSoup(html, parser or config.HTML_PARSER)


# Canonical listing keys produced by every source.
LISTING_FIELDS = (
    "source", "source_id", "listing_key", "url", "suburb_slug", "suburb",
    "title", "price_zar", "property_type", "bedrooms", "bathrooms", "garages",
    "parking", "floor_size_m2", "erf_size_m2", "price_per_m2", "levies",
    "rates", "pool", "listing_date", "agency", "agent_name", "description",
    "photo_count", "street_address", "street_address_raw", "latitude",
    "longitude", "mandate_text",
    "mandate_explicit", "price_reduced", "under_offer", "is_development",
    "listing_type", "rent_period", "available_from", "furnished", "deposit",
    "raw_overview",
)

# The two books. "sale" is the default everywhere, so every existing caller,
# CLI invocation and scheduled job keeps behaving exactly as it did.
LISTING_TYPES = ("sale", "rent")


class Source:
    """Base class for a portal scraper."""

    name: str = ""
    label: str = ""
    # Whether this portal's to-rent URL shape has been VERIFIED against the
    # live site. False means the rental crawl skips the source entirely rather
    # than probing a path we only think exists.
    supports_rent: bool = False

    def __init__(self, logger=None):
        self.fetcher = Fetcher(self.name, logger=logger)
        self.log = logger or print

    # -- interface ---------------------------------------------------------
    def search_urls(self, slug: str, max_pages: int,
                    listing_type: str = "sale") -> list[str]:
        """Detail-page URLs for a suburb, newest/most relevant first."""
        raise NotImplementedError

    def parse_detail(self, url: str, slug: str,
                     listing_type: str = "sale") -> dict | None:
        """Fetch one detail page and return a normalised listing dict."""
        raise NotImplementedError

    # -- helpers -----------------------------------------------------------
    def belongs_to(self, href: str, slug: str) -> bool:
        """Guard against portals silently serving a fallback result set.

        An instance method rather than a static one so a source whose URLs
        name the area in a known path position can decide membership exactly
        — see `PropDataSource.belongs_to`, which does not have to settle for
        the substring test below.

        Several portals answer an unrecognised suburb URL with generic
        city-wide stock instead of a 404 — Seeff returns Kenilworth and
        Claremont listings for a bad Clifton path. Every portal's detail URL
        embeds the real suburb slug, so requiring it here keeps a mislabelled
        listing from ever entering the database (and from polluting dedupe,
        which groups within a suburb).

        The detail URL must name the suburb itself. Accepting the *town*
        segment instead was tried and is wrong: Seeff has no Erinvale page, so
        a town-level match quietly relabelled every Somerset West listing as
        "Erinvale Golf Estate". An area with no real page on a portal must
        resolve to nothing, not to its town's stock.

        Whole-town areas (scope == "town") are the sanctioned exception: a
        validated town search page legitimately lists suburbs nobody has
        configured, so demanding a known slug would throw away most of the
        town. There the href is accepted when it names the town or any
        configured suburb OF that town, rejected when it names a configured
        area of a *different* town (promoted/"similar" tiles pointing
        elsewhere — exactly the pollution the strict check exists to stop),
        and otherwise accepted.
        """
        info = config.SUBURBS.get(slug, {})
        if info.get("scope") != "town":
            return slug in href
        town = info.get("town", slug)
        if town in href:
            return True
        names_other_area = False
        for other, oinfo in config.SUBURBS.items():
            if other in href:
                if oinfo.get("town") == town:
                    return True
                names_other_area = True
        return not names_other_area

    def blank(self, url: str, slug: str, source_id: str,
              listing_type: str = "sale") -> dict:
        info = config.SUBURBS.get(slug, {})
        suburb_slug = slug
        suburb = info.get("name", slug.replace("-", " ").title())
        if info.get("scope") == "town":
            # A whole-town crawl still files each listing under its real
            # suburb where the detail URL reveals it — dedupe groups by
            # suburb_slug, so "hermanus" stock must line up with the same
            # house crawled as "eastcliff" on another portal. Property24
            # re-derives *configured* suburbs from the URL before calling
            # blank() (promoted-tile guard), which simply means those arrive
            # here as suburb-scope slugs and skip this branch — the two
            # mechanisms compose.
            refined = refine_suburb(url, info.get("town", slug))
            if refined:
                suburb_slug, suburb = refined
        rec: dict = {k: None for k in LISTING_FIELDS}
        # Rentals get their own key namespace. The sale key shape is left
        # untouched so no existing row is re-keyed by this change, and the
        # prefix guarantees a portal that numbers both books from one sequence
        # (Property24 does) can never have a rental overwrite a sale.
        key = (f"{self.name}:{source_id}" if listing_type == "sale"
               else f"{self.name}:{listing_type}:{source_id}")
        rec.update({
            "source": self.name,
            "source_id": str(source_id),
            "listing_type": listing_type,
            "listing_key": key,
            "url": url,
            "suburb_slug": suburb_slug,
            "suburb": suburb,
            "photo_count": 0,
        })
        return rec

    def finish(self, rec: dict, html: str | None = None) -> dict:
        """Fill derived fields and classify the mandate from free text."""
        if html and not rec.get("photo_url"):
            import photos
            urls = photos.extract(self.name, html)
            rec["photo_url"] = urls[0] if urls else None
        # price_per_m2 is an asking-price metric and feeds the suburb medians
        # cma.py and scorer.py read. A rent divided by floor area is a
        # different number in a different unit, so it is deliberately left
        # NULL on rentals rather than quietly poisoning those medians.
        if (rec.get("listing_type", "sale") == "sale"
                and rec.get("price_zar") and rec.get("floor_size_m2")):
            try:
                rec["price_per_m2"] = round(rec["price_zar"] / rec["floor_size_m2"], 2)
            except ZeroDivisionError:
                pass
        rec["mandate_text"] = classify_mandate(rec.get("description") or "")
        # Keep what the portal actually printed before normalising. The
        # normalised form exists to match the same house across portals and is
        # lossy by design (lowercased, abbreviated, cut down to the street
        # segment) — no good for display or for a deeds search. Placeholders
        # are still dropped: "Contact agent for street address" is not an
        # address in either form.
        raw = (rec.get("street_address") or "").strip()
        rec["street_address"] = normalise_address(raw)
        rec["street_address_raw"] = raw if rec["street_address"] else None
        if not rec.get("is_development"):
            rec["is_development"] = int(
                detect_development(rec.get("title"), rec.get("description")))
        return rec


# ----------------------------------------------------- suburb refinement

# Detail-URL path segments that are portal plumbing, never place names.
_URL_NOISE_SEGMENTS = {
    "for-sale", "to-rent", "to-let", "results", "residential", "commercial",
    "property", "property-for-sale-south-africa",
    "property-to-rent-south-africa", "rentals",
}
_PROVINCE_SLUGS = {
    "western-cape", "eastern-cape", "northern-cape", "gauteng",
    "kwazulu-natal", "free-state", "north-west", "mpumalanga", "limpopo",
}
_SLUG_SEGMENT = re.compile(r"[a-z]+(?:-[a-z]+)*")


def refine_suburb(url: str, town: str) -> tuple[str, str] | None:
    """(suburb_slug, suburb name) mined from a detail URL, or None.

    Every portal puts the suburb in the path segment next to the town —
    Property24 /for-sale/<suburb>/<town>/<province>/..., Seeff and Private
    Property .../<town>/<suburb>/..., RE/MAX .../<province>/<town>/<suburb>/...
    — so a listing found via a whole-town search can usually be filed under
    its real suburb.

    Deliberately conservative: numeric ids, listing-title slugs (they contain
    digits), provinces and portal plumbing are all excluded, and on any doubt
    None is returned so the caller keeps the town slug. A town-wide dedupe
    group is merely coarser; a *wrong* suburb splits real cross-portal
    matches apart. In particular a segment configured under a different town
    is doubt, not evidence — Private Property has a Waterfront inside
    Langebaan that must not be filed as the V&A.
    """
    from urllib.parse import urlparse
    segs = [s for s in urlparse(url).path.lower().split("/") if s]

    def plausible(s: str) -> bool:
        return (s != town and _SLUG_SEGMENT.fullmatch(s) is not None
                and s not in _URL_NOISE_SEGMENTS
                and s not in _PROVINCE_SLUGS)

    # Best evidence anywhere in the path: a configured suburb of this town
    # (catches Private Property's extra nesting, e.g. .../hermanus/
    # hermanus-outlying/hemel-en-aarde-valley/T123).
    for s in segs:
        if plausible(s) and config.SUBURBS.get(s, {}).get("town") == town:
            return s, config.SUBURBS[s]["name"]

    # Otherwise the plausible segment adjacent to the town. After the town is
    # the Seeff/Private Property/RE/MAX position. Before the town is only
    # trusted in Property24's <suburb>/<town>/<province> shape (identified by
    # the province following the town) — on Private Property the segment
    # before the town is its region grouping ("overberg", "west-coast"),
    # which must not be filed as a suburb.
    if town in segs:
        i = segs.index(town)
        candidates = [i + 1]
        if i + 1 < len(segs) and segs[i + 1] in _PROVINCE_SLUGS:
            candidates.append(i - 1)
        for j in candidates:
            if 0 <= j < len(segs) and plausible(segs[j]):
                if segs[j] in config.SUBURBS:
                    return None      # configured under another town — doubt
                return segs[j], segs[j].replace("-", " ").title()
    return None


# ------------------------------------------------------------ text helpers

def num(text) -> float | None:
    """First number in a string, tolerating R 12 500 000 / 1,234.56 / 250 m²."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).replace("\xa0", " ")
    m = re.search(r"\d[\d\s,.]*", s)
    if not m:
        return None
    cleaned = m.group(0).strip().replace(" ", "").replace(",", "")
    # trailing dot from "250 m2." etc.
    cleaned = cleaned.rstrip(".")
    if cleaned.count(".") > 1:                      # 1.234.567 -> thousands dots
        cleaned = cleaned.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


# (?<![a-z]) rather than \b before the unit: portals write "22ha" with no
# space, and a digit→letter transition is not a word boundary.
_HECTARES = re.compile(r"(?<![a-z])(?:ha|hectares?)\b", re.I)


def area_m2(value) -> float | None:
    """An area in m², whatever unit the portal printed it in.

    Farms and wine estates are advertised in hectares ("22 ha", "1.5
    hectares"); running that through num() alone filed a 22 ha farm as a
    22 m² erf. Accepts plain numbers (assumed m²), strings with either unit,
    and schema.org QuantitativeValue dicts (unitCode HAR = hectare).
    """
    if isinstance(value, dict):
        unit = str(value.get("unitCode") or value.get("unitText") or "")
        v = num(value.get("value"))
        if v is not None and (unit.upper() == "HAR" or _HECTARES.search(unit)):
            return v * 10_000
        return v
    if isinstance(value, str) and _HECTARES.search(value):
        # Hectares are small numbers, so a comma followed by one or two
        # digits is the South African decimal comma ("1,5 ha"), not a
        # thousands separator — num() would read it as 15.
        v = num(re.sub(r"(\d),(\d{1,2})(?!\d)", r"\1.\2", value))
        return v * 10_000 if v is not None else None
    return num(value)


def money(text) -> int | None:
    v = num(text)
    if v is None or v <= 0:
        return None
    return int(v)


# ------------------------------------------------------------ rent pricing
#
# Rentals are quoted with their period attached and the period is not
# decorative: on the Atlantic Seaboard a furnished villa is advertised at
# "R 25 000 per day" (verified on Property24) while the flat next door is
# "R 25 000 per month". Reading both as 25 000 would rank a holiday let and a
# long let identically and would let day-rate stock sail through a monthly
# floor. So the amount and the period are parsed together and stored together.
_RENT_PERIODS = (
    # Longest/most specific patterns first — "per calendar month" must not be
    # decided by the "day" branch, and "p/m" must not match "pm" inside a word.
    (re.compile(r"per\s*night|nightly|per\s*day|daily|\bp\s*/\s*d\b|/\s*day\b", re.I), "day"),
    (re.compile(r"per\s*week|weekly|\bp\s*/\s*w\b|/\s*week\b", re.I), "week"),
    (re.compile(r"per\s*calendar\s*month|per\s*month|monthly|"
                r"\bp\s*[/.]?\s*m\b|\bpcm\b|/\s*month\b", re.I), "month"),
)

# Nights and weeks per month, for comparing two rentals on one scale. 365/12
# and 52/12 rather than 30 and 4, because the error compounds against the
# minimum-rent floor.
_MONTHS = {"month": 1.0, "week": 52.0 / 12.0, "day": 365.0 / 12.0}


def rent_period(text) -> str | None:
    """'month' | 'week' | 'day' from a rent string, or None if unstated."""
    if not text:
        return None
    blob = str(text).replace("\xa0", " ")
    for pattern, period in _RENT_PERIODS:
        if pattern.search(blob):
            return period
    return None


def rent_price(text) -> tuple[int | None, str | None]:
    """(amount, period) from "R 45 000 per month" / "R25,000 p/m" / "R9 500pd".

    The period defaults to "month" whenever an amount parsed but no period
    word appeared: every South African portal quotes long lets monthly and
    only flags the exception (per day, per week). Defaulting to None instead
    would leave most rentals uncomparable for the sake of a case that does not
    occur.
    """
    amount = money(text)
    if amount is None:
        return None, None
    return amount, rent_period(text) or "month"


def monthly_equivalent(amount, period: str | None) -> float | None:
    """A rent on one scale, so a day rate and a monthly rent can be compared.

    Explicitly an equivalence, not a price anyone pays: nobody rents a Camps
    Bay villa for 30 consecutive days at the nightly rate. It exists so the
    MIN_RENT_ZAR floor and any sorting are not fooled by the period.
    """
    if amount is None:
        return None
    try:
        return float(amount) * _MONTHS.get(period or "month", 1.0)
    except (TypeError, ValueError):
        return None


def coord(value) -> float | None:
    """A signed decimal degree.

    `num()` deliberately hunts for the first run of digits and so discards a
    leading minus — harmless for prices and floor areas, which are never
    negative, but fatal for a latitude. Every South African latitude is
    negative, so parsing "-33.94" as 33.94 moves the property from Cape Town
    to the Mediterranean and sends erf.py's cadastre lookup somewhere it will
    never find a match. Portals that hand back JSON numbers survive `num()`
    intact; the ones that quote their coordinates as strings do not, hence
    this.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"-?\d+(?:\.\d+)?", str(value))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


_ADDRESS_NOISE = re.compile(r"\b(unit|apt|apartment|flat|no\.?|number)\b", re.I)
_STREET_ABBREV = {
    "road": "rd", "street": "st", "avenue": "ave", "drive": "dr",
    "crescent": "cres", "close": "cl", "lane": "ln", "boulevard": "blvd",
    "place": "pl", "terrace": "terr", "square": "sq", "way": "way",
}


# Portals substitute prose for a withheld address. Treating these as real
# would make every such listing "match" every other one — Private Property
# alone would collapse a whole suburb into a single fake property and report
# it as marketed by a dozen agencies.
_ADDRESS_PLACEHOLDERS = re.compile(
    r"contact\s+agent|on\s+request|upon\s+request|withheld|undisclosed|"
    r"not\s+disclosed|address\s+available|on\s+application|^n\s*/?\s*a$|"
    r"^poa$|^tba$|^unknown$", re.I)


_STREET_WORDS = set(_STREET_ABBREV) | set(_STREET_ABBREV.values()) | {
    "mews", "rise", "row", "circle", "walk", "park", "heights",
}


def _street_segment(addr: str) -> str:
    """Pick the segment of a comma-separated address that names the street.

    Portals disagree on which side of the comma the street sits. Property24
    appends the area ("10 Woodford Avenue, Camps Bay") but Private Property
    prefixes the unit for sectional title ("312 The Chrystal, 35 Medburn
    Road"). Blindly keeping the first segment therefore stored the complex
    name and dropped the street, so the same flat listed on both portals
    presented two different addresses — which dedupe treats as a hard
    disqualifier, hiding exactly the multi-agency listings we look for.
    """
    segments = [seg.strip() for seg in addr.split(",") if seg.strip()]
    if len(segments) < 2:
        return segments[0] if segments else addr

    def tokens(seg: str) -> list[str]:
        return re.sub(r"[^\w\s]", " ", seg).split()

    numbered, named = [], []
    for seg in segments:
        tok = tokens(seg)
        if not tok:
            continue
        has_street = any(t in _STREET_WORDS for t in tok)
        starts_num = bool(re.match(r"\d", tok[0]))
        if has_street and starts_num:
            return seg                        # "35 medburn road" — unambiguous
        if has_street:
            named.append(seg)
        elif starts_num and len(tok) > 1:
            numbered.append(seg)

    # No segment names a street type: "Glen Beach, 5 Glen Beach" — prefer the
    # numbered one, which is the more specific of the two.
    return (named or numbered or segments)[0]


def normalise_address(addr: str | None) -> str | None:
    """Canonical form so '10 Woodford Avenue' == '10 woodford ave.'.

    Returns None for placeholder text, which must never be used as a match.
    """
    if not addr:
        return None
    if _ADDRESS_PLACEHOLDERS.search(addr):
        return None
    s = _street_segment(addr.lower().strip())
    s = _ADDRESS_NOISE.sub(" ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    parts = [_STREET_ABBREV.get(p, p) for p in s.split()]
    s = " ".join(parts).strip()
    if len(s) < 4:
        return None
    return s or None


# Agencies name themselves differently on every portal: Property24 carries
# "Pam Golding Properties - Atlantic Seaboard" while pamgolding.co.za says
# "Pam Golding (Atlantic Seaboard)". Counting those as two agencies would
# manufacture the exact open-mandate proof this engine exists to find, so
# agency identity is reduced to a brand before being counted.
_AGENCY_BRANDS = (
    "pam golding", "seeff", "remax", "re max", "lew geffen", "sotheby",
    "greeff", "christie", "rawson", "engel", "harcourts", "chas everitt",
    "jawitz", "dogon", "firzt", "tyson", "leapfrog", "century 21",
    "keller williams", "exp ", "aida", "just property", "meridian",
    "homes of distinction", "fine and country", "knight frank",
    # Brands reached through the Prop Data platform, the aggregators and
    # Rawson's own site. Listed explicitly so a branch qualifier ("Harcourts
    # Platinum", "RE/MAX Living") collapses onto the same brand as the head
    # office — two spellings counted as two agencies is manufactured
    # open-mandate proof, which is the one error this engine must not make.
    "dogon", "rawson", "only realty", "real realty", "choprop", "acutts",
    "wakefields", "firzt", "trafalgar", "pace property", "hamiltons",
)

_AGENCY_FILLER = {
    "properties", "property", "estates", "estate", "realty", "real",
    "group", "agency", "agencies", "international", "international.",
    "sa", "south", "africa", "the", "and", "co", "inc", "ltd", "pty",
}


def canonical_agency(name: str | None) -> str | None:
    """Brand-level identity for an agency name, or None if unknown."""
    if not name or not name.strip():
        return None
    s = name.lower()
    s = re.sub(r"[^\w\s]", " ", s)            # 're/max' -> 're max'
    s = re.sub(r"\s+", " ", s).strip()
    for brand in _AGENCY_BRANDS:
        if brand.strip() in s:
            return brand.strip()
    # Unknown brand: drop the branch qualifier and generic words.
    head = re.split(r"\s+-\s+|\(", name.lower())[0]
    head = re.sub(r"[^\w\s]", " ", head)
    words = head.split()
    tokens = [t for t in words if t not in _AGENCY_FILLER]
    # An agency whose whole name is made of generic words — "REAL Realty",
    # "Property Estates" — must not reduce to nothing. Returning None there
    # discards a real agency, and a listing with no attributable agency can
    # never contribute to the multi-agency count.
    return " ".join((tokens or words)[:2]).strip() or None


MANDATE_PATTERNS = [
    (re.compile(r"\b(sole|exclusive)[\s-]+(and[\s-]+exclusive[\s-]+)?mandate", re.I), "sole"),
    (re.compile(r"\bdual[\s-]+mandate", re.I), "dual"),
    (re.compile(r"\bjoint[\s-]+mandate", re.I), "dual"),
    (re.compile(r"\bopen[\s-]+mandate", re.I), "open"),
    (re.compile(r"\bmulti[\s-]*(listed|mandate)", re.I), "open"),
]


# New developments are not prospects: the seller is a developer running its own
# launch campaign, there is frequently no built home to film, and there is no
# homeowner whose mandate Oblivion can win. Portals do not reliably flag these
# — Pam Golding listed an unbuilt Clifton development as propertyType "House"
# with developmentId None — so the copy is what gives it away.
_DEVELOPMENT_PATTERNS = re.compile(
    r"\b("
    r"new\s+development|off[\s-]?plan|yet\s+to\s+be\s+built|to\s+be\s+built|"
    r"under\s+construction|due\s+for\s+completion|completion\s+date|"
    r"launching\s+soon|now\s+selling|units?\s+(?:still\s+)?available|"
    r"remaining\s+units|phase\s+(?:one|two|three|1|2|3)\b|"
    r"developer'?s?\s+(?:release|launch)|brand\s+new\s+development|"
    # "apartments from R5.9m" is developer price-from copy. Note that
    # "in a boutique development" is deliberately NOT matched — that is a
    # resale inside a completed scheme, which is a perfectly good prospect.
    r"apartments?\s+from\s+R|"
    r"no\s+transfer\s+duty.{0,40}developer"
    r")\b", re.I)


def detect_development(title: str | None, description: str | None) -> bool:
    """True if the copy describes a new/off-plan development rather than a
    resale home."""
    blob = f"{title or ''} {description or ''}"
    return bool(_DEVELOPMENT_PATTERNS.search(blob))


# A bare plot fails the same test a new development does: there is no house to
# film and no homeowner sitting on a mandate worth winning. Portals label the
# category consistently, so unlike development detection this needs no prose
# reading. Gated by config.EXCLUDE_VACANT_LAND.
# Matched against property_type only — a controlled vocabulary — so a bare
# \bland\b is safe here and is what catches Private Property's "Residential
# Land", which "vacant land" alone misses. The word boundaries matter: they
# keep \bstand\b off Prop Data's "Freestanding".
_VACANT_TYPES = re.compile(
    r"\bland\b|\bplot\b|\bstand\b|\berf\b|smallholding\s*\(vacant\)", re.I)


def is_vacant_land(rec: dict) -> bool:
    """True if a parsed listing is a plot rather than a home."""
    ptype = (rec.get("property_type") or "").strip()
    if ptype and _VACANT_TYPES.search(ptype):
        return True
    # Some portals leave the type blank and say it in the URL category
    # ("/vacant-land-for-sale/...").
    return bool(re.search(r"vacant-land|/land-for-sale", rec.get("url") or "", re.I))


def classify_mandate(description: str) -> str:
    """Regex mandate hint. Only a fallback — scorer.py asks the AI to read the
    full description, which handles the many non-literal phrasings."""
    for pattern, label in MANDATE_PATTERNS:
        if pattern.search(description):
            return label
    return "unknown"


# ------------------------------------------------------------ JSON-LD

def jsonld_blocks(soup) -> list[dict]:
    """Every JSON-LD object on the page, with @graph flattened."""
    out: list[dict] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
        except (ValueError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if not isinstance(item, dict):
                continue
            if "@graph" in item and isinstance(item["@graph"], list):
                stack.extend(item["@graph"])
                continue
            out.append(item)
    return out


def jsonld_by_type(blocks: list[dict], *types: str) -> dict | None:
    wanted = {t.lower() for t in types}
    for b in blocks:
        t = b.get("@type")
        names = {t.lower()} if isinstance(t, str) else {
            x.lower() for x in t or [] if isinstance(x, str)}
        if names & wanted:
            return b
    return None


def additional_property(block: dict) -> dict[str, object]:
    """schema.org additionalProperty list -> {name: value}."""
    out: dict[str, object] = {}
    for p in block.get("additionalProperty") or []:
        if isinstance(p, dict) and p.get("name") is not None:
            out[str(p["name"])] = p.get("value")
    return out
