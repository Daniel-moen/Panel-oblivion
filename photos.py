"""Listing photo URLs — for dashboard thumbnails and the AI locator.

Portals serve photos from public CDNs; the parsers now capture the hero image
at crawl time (listings.photo_url), and anything older is filled lazily: from
the on-disk page cache first (even a stale cache is fine — CDN image URLs are
stable), then over the network if allowed. A listing whose page yields no
image is marked with the "-" sentinel so it isn't refetched forever.
"""

from __future__ import annotations

import re
import sqlite3
import threading

import config
import httpclient

_IMG_SKIP = re.compile(r"logo|icon|sprite|avatar|agent|placeholder|banner|"
                       r"badge|map|favicon|\.svg", re.I)
_OG_IMAGE = re.compile(r'property=["\']og:image["\']\s+content=["\']([^"\']+)',
                       re.I)
_OG_IMAGE_REV = re.compile(r'content=["\']([^"\']+)["\']\s+'
                           r'property=["\']og:image["\']', re.I)
_ANY_IMAGE = re.compile(
    r"https?://[^\s\"'<>\\]+?\.(?:jpe?g|png|webp)[^\s\"'<>\\]*")

NO_PHOTO = "-"          # sentinel: page inspected, no usable image found

# One page-fetch at a time per portal, so a screenful of lazy thumbnails
# can't fan out into parallel requests against a rate-limited host.
_fetch_locks: dict[str, threading.Lock] = {
    s: threading.Lock() for s in config.SOURCES}


def extract(source: str, html: str) -> list[str]:
    """Gallery URLs from a listing page, best first."""
    if source == "property24":
        ids = list(dict.fromkeys(re.findall(r"prop24\.com/(\d+)", html)))
        return [f"https://images.prop24.com/{i}/Crop600x400" for i in ids]
    urls: list[str] = []
    for pat in (_OG_IMAGE, _OG_IMAGE_REV):
        m = pat.search(html)
        if m and not _IMG_SKIP.search(m.group(1)):
            urls.append(m.group(1))
            break
    seen = set(urls)
    for u in _ANY_IMAGE.findall(html):
        if _IMG_SKIP.search(u) or u in seen:
            continue
        seen.add(u)
        urls.append(u)
    return urls


def for_listing(source: str, url: str, *, allow_fetch: bool = True,
                log=lambda m: None) -> list[str]:
    """Photo URLs for one listing; cache-first, network only if allowed."""
    if source not in config.SOURCES:
        return []
    fetcher = httpclient.Fetcher(source, logger=log)
    # Read the page cache regardless of its TTL — CDN image URLs are stable,
    # so even a week-old page yields a perfectly good thumbnail.
    try:
        with open(fetcher._cache_path(url), encoding="utf-8") as f:
            html = f.read()
    except OSError:
        html = None
    # Never go to the network for a disabled source — on a hosted deploy
    # Property24 blocks the IP outright, and a thumbnail request must not
    # tie up a server thread walking the backoff ladder.
    if html is None and allow_fetch and \
            config.SOURCES.get(source, {}).get("enabled"):
        with _fetch_locks[source]:
            html = fetcher.get(url)
    return extract(source, html) if html else []


def first_photo(conn: sqlite3.Connection, listing_key: str, *,
                allow_fetch: bool = True) -> str | None:
    """The listing's hero image URL, resolved once and remembered."""
    row = conn.execute(
        "SELECT photo_url, source, url FROM listings WHERE listing_key = ?",
        (listing_key,)).fetchone()
    if row is None:
        return None
    if row["photo_url"]:
        return None if row["photo_url"] == NO_PHOTO else row["photo_url"]
    try:
        urls = for_listing(row["source"], row["url"], allow_fetch=allow_fetch)
    except Exception:                        # noqa: BLE001 - network trouble
        return None                          # leave NULL so a later try works
    if not urls:
        if not allow_fetch:
            return None                      # cache miss ≠ page has no photos
        urls = [NO_PHOTO]
    conn.execute("UPDATE listings SET photo_url = ? WHERE listing_key = ?",
                 (urls[0], listing_key))
    conn.commit()
    return None if urls[0] == NO_PHOTO else urls[0]


def backfill(conn: sqlite3.Connection, log=print) -> dict:
    """Fill photo_url for existing rows from the page cache (no network)."""
    rows = conn.execute("SELECT listing_key FROM listings"
                        " WHERE photo_url IS NULL").fetchall()
    stats = {"missing": len(rows), "filled": 0}
    for r in rows:
        if first_photo(conn, r["listing_key"], allow_fetch=False):
            stats["filled"] += 1
    log(f"  photos: {stats['filled']}/{stats['missing']} filled from cache")
    return stats
