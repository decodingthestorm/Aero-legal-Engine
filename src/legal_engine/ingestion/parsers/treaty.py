"""UN, WTO, UNCLOS multilingual treaty parsers.

Parses a simplified, documented subset of treaty XML covering per-language
article text, a choice-of-law clause, and a territorial bounding box.
Real treaty publication formats vary by body (UN Treaty Series, WTO dispute
rulings, UNCLOS annexes); this is a documented baseline rather than a
scraper tuned to one publisher's current format.

Expected shape::

    <TREATY name="UN Convention on the Law of the Sea" citation="UNCLOS Art. 76">
      <ARTICLE lang="en">The continental shelf of a coastal State comprises...</ARTICLE>
      <ARTICLE lang="fr">Le plateau continental d'un Etat cotier comprend...</ARTICLE>
      <CHOICE-OF-LAW>International Tribunal for the Law of the Sea</CHOICE-OF-LAW>
      <TERRITORY lat-min="10.0" lat-max="15.0" lon-min="-70.0" lon-max="-60.0" />
    </TREATY>

Each ``<ARTICLE>`` becomes its own ``StatuteDocument`` (citation suffixed
with the language tag, since the same treaty citation legitimately has one
document per language) paired with the shared choice-of-law clause — that
pairing is why this module returns ``ParsedTreatyArticle`` rather than a
bare ``StatuteDocument`` list: choice-of-law isn't a field on
StatuteDocument itself, and folding it in would make every other source
type's model carry a field it never uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET

from legal_engine.core.exceptions import ParseError
from legal_engine.core.models import GeoBoundary, JurisdictionTier, SourceType, StatuteDocument


@dataclass
class ParsedTreatyArticle:
    statute: StatuteDocument
    language: str
    choice_of_law: str | None


def parse_treaty_xml(xml_text: str, source_url: str | None = None) -> list[ParsedTreatyArticle]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ParseError(f"Malformed treaty XML: {exc}") from exc

    results: list[ParsedTreatyArticle] = []
    for treaty_el in root.findall("TREATY"):
        name = treaty_el.get("name")
        citation = treaty_el.get("citation")
        if not name or not citation:
            raise ParseError("<TREATY> is missing a name or citation attribute")

        choice_of_law_el = treaty_el.find("CHOICE-OF-LAW")
        choice_of_law = (
            choice_of_law_el.text.strip()
            if choice_of_law_el is not None and choice_of_law_el.text
            else None
        )

        geo_boundary = _extract_territory(treaty_el, citation)

        articles = treaty_el.findall("ARTICLE")
        if not articles:
            raise ParseError(f"Treaty {citation!r} has no <ARTICLE> elements")

        for article_el in articles:
            language = article_el.get("lang")
            if not language:
                raise ParseError(f"Treaty {citation!r} has an <ARTICLE> missing lang attribute")
            text = (article_el.text or "").strip()
            if not text:
                raise ParseError(f"Treaty {citation!r} article [{language}] has empty text")

            statute = StatuteDocument(
                source_type=SourceType.INTERNATIONAL_TREATY,
                jurisdiction_tier=JurisdictionTier.INTERNATIONAL_TREATY,
                citation=f"{citation} [{language}]",
                title=name,
                text=text,
                source_url=source_url,
                geo_boundary=geo_boundary,
            )
            results.append(
                ParsedTreatyArticle(statute=statute, language=language, choice_of_law=choice_of_law)
            )

    return results


def _extract_territory(treaty_el: ET.Element, citation: str) -> GeoBoundary | None:
    territory_el = treaty_el.find("TERRITORY")
    if territory_el is None:
        return None
    try:
        return GeoBoundary(
            lat_min=float(territory_el.get("lat-min")),  # type: ignore[arg-type]
            lat_max=float(territory_el.get("lat-max")),  # type: ignore[arg-type]
            lon_min=float(territory_el.get("lon-min")),  # type: ignore[arg-type]
            lon_max=float(territory_el.get("lon-max")),  # type: ignore[arg-type]
        )
    except (TypeError, ValueError) as exc:
        raise ParseError(f"Treaty {citation!r} has a malformed <TERRITORY>") from exc
