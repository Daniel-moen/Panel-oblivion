"""Portal scraper registry.

Three kinds of source feed the crawl:

  * the big consumer portals (Property24, Private Property),
  * agency sites — Pam Golding and RE/MAX on their own platforms, plus the
    thirteen tenants of the Prop Data platform that share one scraper, and
  * aggregators (MyProperty, ImmoAfrica), which reach agencies that have no
    scrapeable site of their own and act as a second witness to how many
    agencies are marketing a property.
"""

from sources.base import Source  # noqa: F401
from sources.immoafrica import ImmoAfrica
from sources.myproperty import MyProperty
from sources.pamgolding import PamGolding
from sources.privateproperty import PrivateProperty
from sources.propdata import (Century21, ChasEveritt, Dogon, Greeff, Harcourts,
                              Jawitz, JustProperty, LewGeffen, OnlyRealty,
                              PropDataSource, TysonProp)
from sources.property24 import Property24
from sources.rawson import Rawson
from sources.remax import ReMax
from sources.seeff import Seeff

_CLASSES = (
    # portals
    Property24, PrivateProperty,
    # agency platforms
    PamGolding, ReMax,
    # Prop Data tenants
    Seeff, LewGeffen, Greeff, Dogon, ChasEveritt, Harcourts, Jawitz,
    Century21, TysonProp, JustProperty, OnlyRealty,
    # own-platform agencies
    Rawson,
    # aggregators
    MyProperty, ImmoAfrica,
)

REGISTRY: dict[str, type] = {cls.name: cls for cls in _CLASSES}


def build(name: str, logger=None):
    """Instantiate a source by name."""
    return REGISTRY[name](logger=logger)


def all_names() -> list[str]:
    return list(REGISTRY)


def propdata_names() -> list[str]:
    """Sources served by the shared Prop Data scraper.

    They discover their own areas from each tenant's sitemap, so they are
    exempt from the locations.json probing the other portals need.
    """
    return [n for n, cls in REGISTRY.items()
            if issubclass(cls, PropDataSource)]
