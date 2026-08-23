"""Federal Register XML, CFR, USC delta parsers.

Parses a simplified, documented subset of Federal Register/CFR XML — real
eCFR/Federal Register XML is a much larger DTD; this covers citation,
title, effective date, and body text, which is what the rest of the
pipeline (StatuteDocument, formal_logic/, knowledge_graph/) actually
consumes.

Expected shape::

    <FEDREG>
      <DOCUMENT citation="40 CFR 122.21" title="Application for permit"
                effective-date="2026-01-01">
        <TEXT>Any person who discharges...</TEXT>
      </DOCUMENT>
    </FEDREG>

``compute_deltas`` diffs a freshly-parsed batch against a previously-known
citation -> StatuteDocument mapping, so callers can flag what actually
changed (and, e.g., re-run formal_logic/ verification only on those)
instead of reprocessing every clause on every ingestion run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from xml.etree import ElementTree as ET

from legal_engine.core.exceptions import ParseError
from legal_engine.core.models import JurisdictionTier, SourceType, StatuteDocument


def parse_federal_register_xml(xml_text: str, source_url: str | None = None) -> list[StatuteDocument]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ParseError(f"Malformed Federal Register XML: {exc}") from exc

    statutes: list[StatuteDocument] = []
    for document in root.findall("DOCUMENT"):
        citation = document.get("citation")
        title = document.get("title")
        if not citation or not title:
            raise ParseError("<DOCUMENT> is missing a citation or title attribute")

        text_el = document.find("TEXT")
        if text_el is None or not (text_el.text or "").strip():
            raise ParseError(f"Document {citation!r} is missing non-empty <TEXT>")

        effective_date = None
        raw_date = document.get("effective-date")
        if raw_date:
            try:
                effective_date = datetime.fromisoformat(raw_date)
            except ValueError as exc:
                raise ParseError(
                    f"Document {citation!r} has an invalid effective-date: {raw_date!r}"
                ) from exc

        statutes.append(
            StatuteDocument(
                source_type=SourceType.FEDERAL_CODE,
                jurisdiction_tier=JurisdictionTier.FEDERAL,
                citation=citation,
                title=title,
                text=text_el.text.strip(),
                source_url=source_url,
                effective_date=effective_date,
            )
        )

    return statutes


class DeltaKind(str, Enum):
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


@dataclass
class StatuteDelta:
    citation: str
    kind: DeltaKind
    statute: StatuteDocument


def compute_deltas(
    incoming: list[StatuteDocument], known: dict[str, StatuteDocument]
) -> list[StatuteDelta]:
    """``known`` maps citation -> the previously-ingested StatuteDocument for it."""
    deltas: list[StatuteDelta] = []
    for statute in incoming:
        previous = known.get(statute.citation)
        if previous is None:
            deltas.append(StatuteDelta(statute.citation, DeltaKind.NEW, statute))
        elif previous.text != statute.text:
            deltas.append(StatuteDelta(statute.citation, DeltaKind.CHANGED, statute))
        else:
            deltas.append(StatuteDelta(statute.citation, DeltaKind.UNCHANGED, statute))
    return deltas
