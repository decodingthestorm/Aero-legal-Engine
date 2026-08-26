"""Reading statutory prose into obligations, over HTTP.

## Why the abstentions come first

``ExtractionResponse`` lists ``unread`` before ``obligations``, and that
ordering is the point of this module rather than a detail of it. Pydantic
serialises fields in declaration order, so a caller reading the response
top to bottom — or scrolling a terminal, or rendering the JSON in a UI
that respects key order — meets what the extractor could *not* read
before it meets what it could.

Held-out measurement across six states puts coverage between 47% and 79%,
varying with how a state drafts. Something between a fifth and a half of
every real statute comes back unclassified. A response that leads with
the obligations invites the reading that they are *the* obligations, and
a compliance officer who takes a 60%-complete list for a complete one has
been misled by the tool rather than informed by it.

So the shape of this response encodes the same commitment
``obligations/extraction.py`` makes internally: an unclassified provision
is a hole in the analysis, and the analysis has to say it has one.

## Why it is consent-gated

Same category as ``/verification`` and ``/simulation``: it produces
output a person might act on in a legal context, so the tenant must have
a current liability-disclaimer acceptance on file. Registered with
``consent_gated`` in ``main.py`` rather than gating here, matching how
those two routers do it.

## What this endpoint does not do

It reads text that is handed to it. It does not fetch, and it does not
decide whether the text is current, in force, or the whole of the
relevant law — ``/ingestion`` is the fetch path, and none of these
answers whether a corpus is complete. ``coverage`` is a share of the
provisions this extractor *recognised as normative*, never a share of the
statute; text whose deontic force the patterns cannot see at all never
enters the denominator.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from legal_engine.core.models import JurisdictionTier
from legal_engine.obligations.extraction import (
    AbstentionReason,
    ExtractionResult,
    KeywordObligationExtractor,
)

router = APIRouter()

_REMEDY = {
    AbstentionReason.NO_SUBJECT_MATCH: (
        "the text was read but this taxonomy has no subject for it — a human must "
        "classify this provision"
    ),
    AbstentionReason.TRUNCATED_FRAGMENT: (
        "the provision was cut apart before classification — the source text or its "
        "segmentation needs attention, not the taxonomy"
    ),
    AbstentionReason.MODEL_DECLINED: (
        "the extraction backend declined to classify this provision"
    ),
}


TierName = Literal["international_treaty", "federal", "state", "county", "municipal"]


class ExtractRequest(BaseModel):
    text: str
    citation: str
    jurisdiction_tier: TierName = Field(
        description=(
            "Named rather than numeric. JurisdictionTier is an int enum whose ordering "
            "*is* the Supremacy Clause — lower value means higher authority — so over "
            "the wire a bare 4 is both opaque and dangerous: an off-by-one silently "
            "changes which law outranks which, and the response would look entirely "
            "ordinary."
        )
    )
    jurisdiction_path: list[str] = Field(
        description=(
            "Containing polities, outermost first — "
            '["United States", "Florida", "City of Miami Beach"]. A path rather than a '
            "name because preemption is bounded by containment: tier alone cannot say "
            "which state a municipal ordinance belongs to."
        )
    )


class UnreadProvision(BaseModel):
    text: str
    reason_code: AbstentionReason
    reason: str
    remedy: str = Field(
        description="What would actually resolve this — the two codes need different work."
    )


class ExtractedObligation(BaseModel):
    text: str
    subjects: list[str]
    modality: str
    bearer: str


class ExtractionResponse(BaseModel):
    """Field order is deliberate: what was not read comes first.

    See the module docstring. Reordering these fields changes what a
    caller sees first and quietly weakens the guarantee.
    """

    complete: bool = Field(
        description="False when any provision went unclassified. A partial extraction "
        "must not be treated as a total one."
    )
    coverage: float = Field(
        description="Classified share of provisions RECOGNISED AS NORMATIVE — an upper "
        "bound on how much of the statute was understood, not a measure of it."
    )
    unread_count: int
    unread: list[UnreadProvision] = Field(
        description="Provisions this extractor could not classify. Listed before the "
        "obligations because a caller must see the gaps before the findings."
    )
    triage: dict[str, int] = Field(
        description="Counts by abstention reason. The two causes are repaired in "
        "different places and conflating them improves the number without improving "
        "the analysis."
    )
    obligation_count: int
    obligations: list[ExtractedObligation]


def _to_response(result: ExtractionResult) -> ExtractionResponse:
    return ExtractionResponse(
        complete=result.is_complete,
        coverage=round(result.coverage, 4),
        unread_count=len(result.unclassified),
        unread=[
            UnreadProvision(
                text=provision.text,
                reason_code=provision.code,
                reason=provision.reason,
                remedy=_REMEDY[provision.code],
            )
            for provision in result.unclassified
        ],
        triage={
            reason.value: len(items) for reason, items in sorted(result.triage().items())
        },
        obligation_count=len(result.obligations),
        obligations=[
            ExtractedObligation(
                text=obligation.text,
                subjects=sorted(subject.value for subject in obligation.subjects),
                modality=obligation.modality.value,
                bearer=obligation.bearer.value,
            )
            for obligation in result.obligations
        ],
    )


@router.post("/analyze", response_model=ExtractionResponse)
async def analyze(request: ExtractRequest) -> ExtractionResponse:
    result = KeywordObligationExtractor().extract(
        request.text,
        request.citation,
        JurisdictionTier[request.jurisdiction_tier.upper()],
        tuple(request.jurisdiction_path),
    )
    return _to_response(result)
