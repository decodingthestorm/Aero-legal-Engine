"""Floor doctrine: a higher authority sets a minimum, and lower
authorities may exceed it.

This module exists because of a spike that tried to express the Fair
Labor Standards Act using ``express_preemption.py`` and got the answer
exactly backwards. Modelled as an ``ExpressPreemptionRule`` reserving
``MINIMUM_WAGE`` to the federal government, California's $16.50 wage came
back **PREEMPTED**. The correct answer is that California governs, and
the statute says so in terms — 29 U.S.C. § 218(a), fetched verbatim:

    No provision of this chapter or of any order thereunder shall excuse
    noncompliance with any Federal or State law or municipal ordinance
    establishing a minimum wage higher than the minimum wage established
    under this chapter or a maximum work week lower than the maximum
    workweek established under this chapter...

## What the spike actually found

**Preemption is content-independent; a floor is content-dependent.**
``express_preemption.analyze`` decides by *scope*: if the subject matter
is reserved and no exception applies, the lower rule falls, and the
number in it is never read. A floor cannot be decided without reading the
number, because whether the lower rule survives depends on how it
compares to the higher one.

That is not a missing feature in the preemption module. It is a different
doctrine, and forcing both through one code path would mean a rule type
that sometimes reads content and sometimes doesn't, with a flag deciding
which — the kind of abstraction that is technically general and
practically unreadable.

**The output shape differs too.** Preemption returns a validity verdict:
the ordinance is void. A floor returns an *operative value*: if a state
minimum sits below the federal one, the state rule is not struck from the
books — the federal number simply governs for covered employees. So
``FloorFinding`` carries ``operative_threshold``, which has no analogue in
``PreemptionFinding``.

**Stringency direction is per-subject, not global.** The same sentence of
§ 218(a) preserves a *higher* minimum wage and a *lower* maximum
workweek. A single "stricter means bigger" assumption would get the
second one backwards, so direction is a property of the rule.

## What was shared

The preliminaries: does this rule reach this polity, is the provision
subordinate, does the subject matter overlap. Those are identical across
both doctrines and now live in ``authority.py``, which is the one real
consolidation the spike produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from legal_engine.core.models import JurisdictionTier
from legal_engine.obligations.authority import AuthorityCheck, precheck
from legal_engine.obligations.models import Obligation, SubjectMatter, Threshold


class Stringency(str, Enum):
    """Which direction of deviation is more protective.

    A property of the rule rather than a global constant, because
    29 U.S.C. § 218(a) preserves both a *higher* minimum wage and a
    *lower* maximum workweek in one sentence."""

    HIGHER_IS_STRICTER = "higher_is_stricter"
    LOWER_IS_STRICTER = "lower_is_stricter"


class FloorStatus(str, Enum):
    GOVERNS_AS_MORE_PROTECTIVE = "governs_as_more_protective"
    """The subordinate rule exceeds the floor and is what actually
    applies."""

    DISPLACED_AS_LESS_PROTECTIVE = "displaced_as_less_protective"
    """The subordinate rule is weaker, so the floor governs instead. Note
    the wording: *displaced*, not void. The rule may still operate for
    parties the higher law doesn't cover."""

    EQUIVALENT = "equivalent"
    """Same standard by both measures — worth distinguishing, because a
    jurisdiction that merely matches the floor loses its protection the
    moment the floor moves."""

    NOT_IN_SCOPE = "not_in_scope"
    OUTSIDE_JURISDICTION = "outside_jurisdiction"
    NOT_SUBORDINATE = "not_subordinate"

    UNDETERMINED = "undetermined"
    """The comparison needs a number the provision doesn't carry, or the
    units differ. Never guessed."""


@dataclass(frozen=True)
class FloorRule:
    citation: str
    enacting_jurisdiction: str
    tier: JurisdictionTier
    subject: SubjectMatter
    """One subject, not a set. A floor is a level *for a thing*, and a
    rule covering two subjects would need two thresholds — which is two
    rules."""

    threshold: Threshold
    stringency: Stringency
    text: str
    savings_clause_citation: str | None = None
    """The provision that expressly preserves stricter subordinate law.
    Recorded because a floor without one is an inference, and this
    codebase does not want those silently mixed with rules that say so —
    29 U.S.C. § 218(a) says so; many statutes don't."""

    source_url: str | None = None


@dataclass(frozen=True)
class FloorFinding:
    obligation: Obligation
    rule: FloorRule
    status: FloorStatus
    reasoning: str
    operative_threshold: Threshold | None = None
    """What actually governs. The answer a payroll system needs, and the
    thing a validity verdict alone cannot give it."""

    missing_facts: frozenset[str] = frozenset()


def analyze_floor(obligation: Obligation, rule: FloorRule) -> FloorFinding:
    def finding(
        status: FloorStatus,
        reasoning: str,
        operative: Threshold | None = None,
        missing: frozenset[str] = frozenset(),
    ) -> FloorFinding:
        return FloorFinding(
            obligation=obligation,
            rule=rule,
            status=status,
            reasoning=reasoning,
            operative_threshold=operative,
            missing_facts=missing,
        )

    check = precheck(
        obligation,
        enacting_jurisdiction=rule.enacting_jurisdiction,
        tier=rule.tier,
        subjects=frozenset({rule.subject}),
        rule_citation=rule.citation,
    )
    if check.outcome is AuthorityCheck.NOT_SUBORDINATE:
        return finding(FloorStatus.NOT_SUBORDINATE, check.reasoning)
    if check.outcome is AuthorityCheck.OUTSIDE_JURISDICTION:
        return finding(FloorStatus.OUTSIDE_JURISDICTION, check.reasoning)
    if check.outcome is AuthorityCheck.NOT_IN_SCOPE:
        return finding(FloorStatus.NOT_IN_SCOPE, check.reasoning)

    local = obligation.threshold
    if local is None:
        return finding(
            FloorStatus.UNDETERMINED,
            f"{rule.citation} sets a floor of {_fmt(rule.threshold)}, but "
            f"{obligation.citation} carries no threshold to compare against. Whether it is "
            f"more protective cannot be decided without one.",
            missing=frozenset({"threshold"}),
        )

    if local.unit != rule.threshold.unit:
        return finding(
            FloorStatus.UNDETERMINED,
            f"{obligation.citation} is stated in {local.unit!r} and {rule.citation} in "
            f"{rule.threshold.unit!r}. Comparing them would require a conversion this "
            f"module will not invent.",
            missing=frozenset({"unit_conversion"}),
        )

    if local.value == rule.threshold.value:
        return finding(
            FloorStatus.EQUIVALENT,
            f"{obligation.citation} matches {rule.citation} exactly at {_fmt(local)}. It adds "
            f"nothing, and would fall below the floor if {rule.enacting_jurisdiction} raised it.",
            operative=rule.threshold,
        )

    stricter = (
        local.value > rule.threshold.value
        if rule.stringency is Stringency.HIGHER_IS_STRICTER
        else local.value < rule.threshold.value
    )
    direction = "higher" if rule.stringency is Stringency.HIGHER_IS_STRICTER else "lower"

    if stricter:
        return finding(
            FloorStatus.GOVERNS_AS_MORE_PROTECTIVE,
            f"{obligation.citation} sets {_fmt(local)}, which is {direction} than "
            f"{rule.citation}'s {_fmt(rule.threshold)} and therefore more protective"
            + (
                f". {rule.savings_clause_citation} expressly preserves it."
                if rule.savings_clause_citation
                else "."
            ),
            operative=local,
        )

    return finding(
        FloorStatus.DISPLACED_AS_LESS_PROTECTIVE,
        f"{obligation.citation} sets {_fmt(local)}, which is less protective than "
        f"{rule.citation}'s {_fmt(rule.threshold)}. The floor governs for covered parties; "
        f"the subordinate rule is displaced rather than void.",
        operative=rule.threshold,
    )


def _fmt(threshold: Threshold) -> str:
    return f"{threshold.value} {threshold.unit}"
