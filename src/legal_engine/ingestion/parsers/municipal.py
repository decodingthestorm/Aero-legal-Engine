"""Municipal codes & GIS shapefile binding.

Parses a simplified, documented subset of municipal-code publisher HTML
(the general shape used by Municode/American Legal Publishing-style sites:
one ``<article class="ordinance">`` per section, with a nested
``<div class="geo-boundary">`` carrying a zoning overlay's bounding box as
data attributes). Real publisher markup varies site to site and changes on
redesign; this is a testable baseline schema rather than a scraper tuned to
one specific site's current HTML.

Expected shape::

    <article class="ordinance" data-citation="Sec. 12.04.030" data-title="ADUs">
      <div class="ordinance-text">No person shall...</div>
      <div class="geo-boundary" data-lat-min="34.0" data-lat-max="34.1"
           data-lon-min="-118.3" data-lon-max="-118.2"></div>
    </article>
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from legal_engine.core.exceptions import ParseError
from legal_engine.core.models import GeoBoundary, JurisdictionTier, SourceType, StatuteDocument


def parse_municipal_html(html: str, source_url: str | None = None) -> list[StatuteDocument]:
    soup = BeautifulSoup(html, "html.parser")
    statutes: list[StatuteDocument] = []

    for article in soup.select("article.ordinance"):
        citation = article.get("data-citation")
        title = article.get("data-title")
        if not citation or not title:
            raise ParseError("<article class=\"ordinance\"> is missing data-citation or data-title")

        text_el = article.select_one(".ordinance-text")
        if text_el is None:
            raise ParseError(f"Ordinance {citation!r} is missing a .ordinance-text element")
        text = text_el.get_text(strip=True)
        if not text:
            raise ParseError(f"Ordinance {citation!r} has empty .ordinance-text")

        statutes.append(
            StatuteDocument(
                source_type=SourceType.MUNICIPAL_CODE,
                jurisdiction_tier=JurisdictionTier.MUNICIPAL,
                citation=str(citation),
                title=str(title),
                text=text,
                source_url=source_url,
                geo_boundary=_extract_geo_boundary(article, str(citation)),
            )
        )

    return statutes


def _float_attr(element: Tag, name: str) -> float:
    """BeautifulSoup returns ``list[str]`` rather than ``str`` for
    attributes it treats as multi-valued, so the raw value isn't
    necessarily floatable. The TypeError raised here is the same one
    ``float()`` would have raised on a list, and lands in the same
    except-clause below — this just makes the narrowing explicit rather
    than leaving it to a coincidence of what float() rejects."""
    value = element[name]
    if not isinstance(value, str):
        raise TypeError(f"attribute {name!r} is multi-valued: {value!r}")
    return float(value)


def _extract_geo_boundary(article: Tag, citation: str) -> GeoBoundary | None:
    geo_el = article.select_one(".geo-boundary")
    if geo_el is None:
        return None
    try:
        return GeoBoundary(
            lat_min=_float_attr(geo_el, "data-lat-min"),
            lat_max=_float_attr(geo_el, "data-lat-max"),
            lon_min=_float_attr(geo_el, "data-lon-min"),
            lon_max=_float_attr(geo_el, "data-lon-max"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ParseError(f"Ordinance {citation!r} has a malformed .geo-boundary") from exc
