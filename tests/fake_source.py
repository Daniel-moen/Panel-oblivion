"""A fake portal for local load tests: no network, real parse cost.

Loaded through the CRAWL_SOURCES_PLUGIN hook in sources/__init__.py
(``CRAWL_SOURCES_PLUGIN=tests.fake_source``). It registers a source named
"fake" whose search returns FAKE_LISTINGS synthetic detail URLs and whose
parse_detail sleeps FAKE_NET_MS (a pretend download), then builds a
BeautifulSoup tree over a page-sized synthetic HTML document through the
same parse gate every real scraper uses, so the CPU and commit pattern of a
crawl is reproduced without touching any portal. Every run uses fresh ids,
so recently_seen() never short-circuits it.

Never load this on a real deployment.
"""

from __future__ import annotations

import os
import random
import time

import config
from sources.base import make_soup

N_LISTINGS = int(os.environ.get("FAKE_LISTINGS", "300"))
NET_MS = float(os.environ.get("FAKE_NET_MS", "40"))
RUN_ID = str(int(time.time()))[-6:]

# ~150 KB of markup, roughly one portal detail page (measured: a cached
# Private Property page is 158 KB).
_HTML = ("<html><head><title>Fake listing</title></head><body>"
         + "".join(f'<div class="card" id="c{i}"><h3 class="t">Item {i}</h3>'
                   f'<p class="d">{"lorem ipsum " * 8}</p>'
                   f'<span class="p">R {i * 1000:,}</span></div>'
                   for i in range(1100))
         + "</body></html>")


class _StubFetcher:
    circuit_open = False

    def __init__(self):
        self.stats = {"fetched": 0, "cached": 0, "failed": 0}

    def close(self):
        pass

    def _cache_path(self, url):
        return os.path.join(config.CACHE_DIR, "fake", "none")


class FakePortal:
    name = "fake"
    label = "Fake portal"
    supports_rent = True

    def __init__(self, logger=None):
        self.log = logger or print
        self.fetcher = _StubFetcher()

    def search_urls(self, slug, max_pages, listing_type="sale"):
        return [f"https://fake.test/{slug}/{listing_type}/{RUN_ID}{i:04d}"
                for i in range(N_LISTINGS)]

    def parse_detail(self, url, slug, listing_type="sale"):
        time.sleep(NET_MS / 1000.0)
        soup = make_soup(_HTML)
        cards = soup.select("div.card")
        self.fetcher.stats["fetched"] += 1
        ident = url.rsplit("/", 1)[1]
        key = (f"fake:rent:{ident}" if listing_type == "rent"
               else f"fake:{ident}")
        price = 15000 + random.randint(0, 200) * 500
        return {
            "source": self.name, "source_id": ident, "listing_key": key,
            "url": url, "suburb_slug": slug,
            "suburb": config.SUBURBS.get(slug, {}).get("name", slug),
            "title": f"Fake home {ident} ({len(cards)} cards)",
            "price_zar": price, "property_type": "House",
            "bedrooms": 3, "bathrooms": 2, "listing_type": listing_type,
            "rent_period": "month" if listing_type == "rent" else None,
            "agency": "Fake Agency", "description": "synthetic",
            "photo_count": 0, "photo_url": "-",
        }


def register(registry: dict) -> None:
    config.SOURCES.setdefault("fake", {
        "label": "Fake portal", "base_url": "https://fake.test",
        "delay": 0.0, "jitter": 0.0, "backoffs": [], "enabled": True,
        "delay_min": 0.0, "delay_max": 0.0, "workers": 3,
    })
    registry["fake"] = FakePortal
