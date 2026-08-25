"""The questions both preemption and floor doctrine ask first.

Extracted during the floor/ceiling spike, once two doctrines existed and
the duplication became visible. Before that there was one caller and
extracting would have been speculative.

Three preliminaries, in the order the question is actually reached:

1. Did this authority enact the provision itself? Nothing preempts or
   floors its own enactment.
2. Does this authority reach the provision's polity at all? A Florida
   statute governs Florida's subdivisions and no others — and *tier alone
   says nothing about which state*, which is why an Arizona municipal
   ordinance looks subordinate to a naive comparison.
3. Is the provision subordinate, and does the subject matter overlap?

Only after all three does the doctrine-specific work begin, and the two
doctrines diverge completely there: preemption asks whether an exception
rescues the provision, a floor asks whether its number is more
protective. That divergence is why this module stops here rather than
growing a mode flag — see ``floors.py`` for what the spike concluded.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from legal_engine.core.models import JurisdictionTier
from legal_engine.obligations.models import Obligation, SubjectMatter


class AuthorityCheck(str, Enum):
    PROCEED = "proceed"
    """Preliminaries passed; the doctrine-specific analysis applies."""

    NOT_SUBORDINATE = "not_subordinate"
    OUTSIDE_JURISDICTION = "outside_jurisdiction"
    NOT_IN_SCOPE = "not_in_scope"


@dataclass(frozen=True)
class PrecheckResult:
    outcome: AuthorityCheck
    reasoning: str
    overlapping_subjects: frozenset[SubjectMatter] = frozenset()


def precheck(
    obligation: Obligation,
    *,
    enacting_jurisdiction: str,
    tier: JurisdictionTier,
    subjects: frozenset[SubjectMatter],
    rule_citation: str,
) -> PrecheckResult:
    if obligation.jurisdiction_name == enacting_jurisdiction:
        return PrecheckResult(
            AuthorityCheck.NOT_SUBORDINATE,
            f"{rule_citation} was enacted by {enacting_jurisdiction}, which cannot displace "
            f"its own enactment.",
        )

    if not obligation.is_within(enacting_jurisdiction):
        return PrecheckResult(
            AuthorityCheck.OUTSIDE_JURISDICTION,
            f"{obligation.citation} was enacted in "
            f"{' / '.join(obligation.jurisdiction_path)}, which is outside "
            f"{enacting_jurisdiction}'s reach. Tier alone would have made this look "
            f"subordinate.",
        )

    # JurisdictionTier orders lower values as higher authority
    # (treaty=0 ... municipal=4), so "below" is a larger value.
    if obligation.jurisdiction_tier.value <= tier.value:
        return PrecheckResult(
            AuthorityCheck.NOT_SUBORDINATE,
            f"{obligation.citation} sits at {obligation.jurisdiction_tier.name}, which is not "
            f"below {rule_citation}'s {tier.name} authority.",
        )

    overlap = obligation.subjects & subjects
    if not overlap:
        return PrecheckResult(
            AuthorityCheck.NOT_IN_SCOPE,
            f"{rule_citation} concerns {_names(subjects)}; {obligation.citation} regulates "
            f"{_names(obligation.subjects)}, which does not overlap.",
        )

    return PrecheckResult(AuthorityCheck.PROCEED, "", overlapping_subjects=overlap)


def _names(subjects: frozenset[SubjectMatter]) -> str:
    return ", ".join(sorted(s.value for s in subjects)) or "nothing"
