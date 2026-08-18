"""Seeff — large national agency with a strong Atlantic Seaboard presence.

Seeff runs on the Prop Data platform, so everything about the scrape lives in
`sources/propdata.py`; this module only names the tenant. It was written as a
bespoke scraper before the platform was recognised, and moving it onto the
shared base gained it the listing date, street address, coordinates, erf size
and photo count that the hand-rolled version never read out of the page's
schema.org block.
"""

from __future__ import annotations

from sources.propdata import PropDataSource


class Seeff(PropDataSource):
    name = "seeff"
    label = "Seeff"
    agency = "Seeff"
