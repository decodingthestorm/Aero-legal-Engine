"""Express preemption: does a higher law explicitly displace a lower one?

*Express* preemption is the narrow case where a statute says so in terms
— as distinct from field preemption (the higher authority occupied the
whole area) or conflict preemption (compliance with both is impossible).
Only the express case is modelled here, because it is the only one that
can be decided from the text without judgment about legislative intent.
Claiming to decide the other two from a taxonomy would be the kind of
overreach this codebase keeps refusing.

## The worked example this was built from

Fla. Stat. § 509.032(7)(b), fetched verbatim from the Florida Senate:

    A local law, ordinance, or regulation may not prohibit vacation
    rentals or regulate the duration or frequency of rental of vacation
    rentals. This paragraph does not apply to any local law, ordinance,
    or regulation adopted on or before June 1, 2011.

Three features, all of which a flattened if/else destroys:

**It is scoped.** Prohibition, duration, frequency — and nothing else.
A Florida city's night cap is void; the same city's parking requirement
is untouched. Both are municipal, both concern short-term rentals, both
sit below the state. Tier cannot tell them apart; only subject matter
can.

**It is defeasible.** The grandfather clause is an exception attached to
the rule, keyed on the *adoption* date of the very ordinance being
tested. The rule does not become false — it declines to apply.

**It is bounded by polity.** A Florida statute reaches Florida's
subdivisions. Nothing in the tier ordering says so, which is why
``jurisdiction_path`` exists.

## Why an outcome can be "undetermined"

If an ordinance carries no adoption date and the rule has a grandfather
cutoff, the honest answer is that this cannot be decided — not that it
is preempted, and not that it survives. Real corpora are incomplete, and
an ingestion pipeline that invents a date to reach a clean answer is
worse than one that refuses. ``UNDETERMINED`` routes to a human with the
missing fact named, matching how ``knowledge_graph/preemption.py``
returns ``requires_review`` rather than picking arbitrarily.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from legal_engine.core.models import JurisdictionTier
from legal_engine.obligations.models import Obligation, SubjectMatter


class PreemptionStatus(str, Enum):
    PREEMPTED = "preempted"
    """Inside the reserved scope, no exception applies. The provision is
    displaced."""

    NOT_IN_SCOPE = "not_in_scope"
    """The provision regulates something the higher law left alone."""

    GRANDFATHERED = "grandfathered"
    """Inside the scope, but predates the cutoff, so the rule declines to
    apply. Reported distinctly from NOT_IN_SCOPE because the reasons
    differ and a lawyer needs to know which one saved the ordinance."""

    EXEMPTED = "exempted"
    """Inside the scope, but a named statutory carve-out applies."""

    OUTSIDE_JURISDICTION = "outside_jurisdiction"
    """The rule's enacting polity doesn't govern this provision's."""

    NOT_SUBORDINATE = "not_subordinate"
    """The provision is at or above the preempting authority's tier."""

    UNDETERMINED = "undetermined"
    """A fact the rule turns on is missing. Never a guess."""


@dataclass(frozen=True)
class Exemption:
    """A named carve-out, e.g. Fla. Stat. § 509.032(7)(c), which exempts
    ordinances "exclusively relating to property valuation" in areas of
    critical state concern.

    ``requires_all`` distinguishes an exemption that fires when a
    provision touches any listed subject from one that fires only when it
    is *exclusively* about them. The Florida carve-out says
    "exclusively", and the difference decides real cases: an ordinance
    covering valuation *and* frequency is not exclusively about
    valuation and stays preempted.
    """

    citation: str
    subjects: frozenset[SubjectMatter]
    description: str
    requires_all: bool = True

    def applies_to(self, obligation: Obligation) -> bool:
        if self.requires_all:
            return bool(obligation.subjects) and obligation.subjects <= self.subjects
        return bool(obligation.subjects & self.subjects)


@dataclass(frozen=True)
class ExpressPreemptionRule:
    """A higher-law provision that reserves a scope to itself."""

    citation: str
    enacting_jurisdiction: str
    """The polity whose subdivisions this reaches — "Florida"."""

    tier: JurisdictionTier
    reserved_subjects: frozenset[SubjectMatter]
    text: str
    grandfather_cutoff: date | None = None
    """Provisions *adopted* on or before this date escape. Note "on or
    before": the Florida text is inclusive, and an off-by-one here
    decides cases wrongly at the boundary."""

    exemptions: tuple[Exemption, ...] = field(default_factory=tuple)
    source_url: str | None = None


@dataclass(frozen=True)
class PreemptionFinding:
    """``reasoning`` is not decoration. A finding that a municipal
    ordinance is void, without a statable reason, is unusable — the
    person who has to act on it needs to know which provision displaced
    theirs and why, and needs to be able to check it."""

    obligation: Obligation
    rule: ExpressPreemptionRule
    status: PreemptionStatus
    reasoning: str
    conflicting_subjects: frozenset[SubjectMatter] = field(default_factory=frozenset)
    missing_facts: frozenset[str] = field(default_factory=frozenset)

    @property
    def survives(self) -> bool:
        """Whether the provision remains operative. UNDETERMINED is
        deliberately *not* survival — an unresolved question must not read
        as a clean bill of health to a caller that only checks a
        boolean."""
        return self.status in (
            PreemptionStatus.NOT_IN_SCOPE,
            PreemptionStatus.GRANDFATHERED,
            PreemptionStatus.EXEMPTED,
            PreemptionStatus.OUTSIDE_JURISDICTION,
            PreemptionStatus.NOT_SUBORDINATE,
        )


def analyze(obligation: Obligation, rule: ExpressPreemptionRule) -> PreemptionFinding:
    """Applies one express preemption rule to one obligation.

    Order matters and follows how the question is actually reached: does
    this rule govern this polity at all, is the provision subordinate, is
    it inside the reserved scope, and only then whether an exception
    rescues it. Checking scope first would produce confident answers
    about ordinances in states the statute has never reached.
    """

    def finding(
        status: PreemptionStatus,
        reasoning: str,
        conflicting_subjects: frozenset[SubjectMatter] = frozenset(),
        missing_facts: frozenset[str] = frozenset(),
    ) -> PreemptionFinding:
        return PreemptionFinding(
            obligation=obligation,
            rule=rule,
            status=status,
            reasoning=reasoning,
            conflicting_subjects=conflicting_subjects,
            missing_facts=missing_facts,
        )

    if obligation.jurisdiction_name == rule.enacting_jurisdiction:
        return finding(
            PreemptionStatus.NOT_SUBORDINATE,
            f"{rule.citation} was enacted by {rule.enacting_jurisdiction}, which cannot "
            f"preempt its own enactment.",
        )

    if not obligation.is_within(rule.enacting_jurisdiction):
        return finding(
            PreemptionStatus.OUTSIDE_JURISDICTION,
            f"{obligation.citation} was enacted in "
            f"{' / '.join(obligation.jurisdiction_path)}, which is outside "
            f"{rule.enacting_jurisdiction}'s reach. Tier alone would have made this look "
            f"subordinate.",
        )

    if not _is_subordinate_to(obligation, rule):
        return finding(
            PreemptionStatus.NOT_SUBORDINATE,
            f"{obligation.citation} sits at {obligation.jurisdiction_tier.name}, which is not "
            f"below {rule.citation}'s {rule.tier.name} authority.",
        )

    overlap = obligation.subjects & rule.reserved_subjects
    if not overlap:
        return finding(
            PreemptionStatus.NOT_IN_SCOPE,
            f"{rule.citation} reserves "
            f"{_names(rule.reserved_subjects)}; {obligation.citation} regulates "
            f"{_names(obligation.subjects)}, none of which is reserved.",
        )

    for exemption in rule.exemptions:
        if exemption.applies_to(obligation):
            return finding(
                PreemptionStatus.EXEMPTED,
                f"{exemption.citation} exempts {exemption.description}; "
                f"{obligation.citation} falls within it.",
                conflicting_subjects=overlap,
            )

    if rule.grandfather_cutoff is not None:
        if obligation.adopted_date is None:
            return finding(
                PreemptionStatus.UNDETERMINED,
                f"{rule.citation} spares provisions adopted on or before "
                f"{rule.grandfather_cutoff.isoformat()}, but {obligation.citation} carries no "
                f"adoption date. This cannot be decided without it.",
                conflicting_subjects=overlap,
                missing_facts=frozenset({"adopted_date"}),
            )
        if obligation.adopted_date <= rule.grandfather_cutoff:
            return finding(
                PreemptionStatus.GRANDFATHERED,
                f"{obligation.citation} was adopted {obligation.adopted_date.isoformat()}, on or "
                f"before {rule.citation}'s cutoff of {rule.grandfather_cutoff.isoformat()}, so the "
                f"preemption does not apply to it.",
                conflicting_subjects=overlap,
            )

    return finding(
        PreemptionStatus.PREEMPTED,
        f"{obligation.citation} regulates {_names(overlap)}, which {rule.citation} reserves to "
        f"{rule.enacting_jurisdiction}"
        + (
            f", and it was adopted {obligation.adopted_date.isoformat()}, after the "
            f"{rule.grandfather_cutoff.isoformat()} cutoff."
            if rule.grandfather_cutoff is not None and obligation.adopted_date is not None
            else "."
        ),
        conflicting_subjects=overlap,
    )


def analyze_all(
    obligations: list[Obligation], rules: list[ExpressPreemptionRule]
) -> list[PreemptionFinding]:
    """Every obligation against every rule, keeping only findings where a
    rule actually engaged.

    A provision preempted by any rule is preempted, so the most severe
    finding wins. Returning only that one would hide *why* the others
    didn't apply, which is exactly what someone auditing the result needs,
    so all engaged findings are returned and ranked.
    """
    findings: list[PreemptionFinding] = []
    for obligation in obligations:
        engaged = [analyze(obligation, rule) for rule in rules]
        relevant = [
            f
            for f in engaged
            if f.status
            not in (PreemptionStatus.NOT_SUBORDINATE, PreemptionStatus.OUTSIDE_JURISDICTION)
        ]
        findings.extend(sorted(relevant, key=lambda f: _severity(f.status)))
    return findings


_SEVERITY = {
    PreemptionStatus.PREEMPTED: 0,
    PreemptionStatus.UNDETERMINED: 1,
    PreemptionStatus.EXEMPTED: 2,
    PreemptionStatus.GRANDFATHERED: 3,
    PreemptionStatus.NOT_IN_SCOPE: 4,
    PreemptionStatus.OUTSIDE_JURISDICTION: 5,
    PreemptionStatus.NOT_SUBORDINATE: 6,
}


def _severity(status: PreemptionStatus) -> int:
    return _SEVERITY[status]


def _is_subordinate_to(obligation: Obligation, rule: ExpressPreemptionRule) -> bool:
    # JurisdictionTier is ordered with lower values as higher authority
    # (treaty=0 ... municipal=4), so "below" is a larger value.
    return obligation.jurisdiction_tier.value > rule.tier.value


def _names(subjects: frozenset[SubjectMatter]) -> str:
    return ", ".join(sorted(s.value for s in subjects)) or "nothing"
