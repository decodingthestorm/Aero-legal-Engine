"""The target representation for ingested regulatory text.

This is the schema Layer 0 has to fill: whatever reads an ordinance —
a parser, an LLM, or a human — produces ``Obligation`` objects, and
everything downstream reasons over those rather than over prose.

## Why a subject-matter taxonomy exists at all

Because preemption is *scoped*, and tier alone cannot express that.
Fla. Stat. § 509.032(7)(b) forbids a Florida local government from
prohibiting vacation rentals or regulating their **duration or
frequency** — and says nothing about parking, noise, occupancy, or
permits. A city night-cap is void; the same city's parking requirement
is untouched. Both are municipal, both concern short-term rentals, and
both sit below the state in the hierarchy. Only the subject matter
separates them.

``knowledge_graph/preemption.py`` resolves *which of several statutes
governs an entity* by tier, specificity, and recency. That is a
different question from *whether this particular provision falls inside
the scope a higher law expressly reserved*, which is what
``express_preemption.py`` answers using the subjects below.

## Why adopted_date is not effective_date

The Florida grandfather clause turns on an ordinance "adopted on or
before June 1, 2011". Adoption and effectiveness routinely differ — an
ordinance passed in May 2011 taking effect in January 2012 is
grandfathered on the text as written. ``StatuteDocument.effective_date``
answers a different question, so conflating them would silently decide
grandfathering cases the wrong way. Both are carried, and the preemption
analysis reads only the one the statute names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from legal_engine.core.models import JurisdictionTier


class SubjectMatter(str, Enum):
    """What a provision regulates.

    Deliberately narrow: these are the subjects that actually appear in
    short-term-rental regulation, which is the first corpus. A second
    domain would add its own members rather than forcing its concepts
    into these. A taxonomy that tried to cover all of law in advance
    would be wrong everywhere instead of right somewhere.

    The first three are grouped because Florida's preemption names
    exactly them, but they are genuinely distinct: a ban, a minimum-stay
    rule, and a nights-per-year cap are three different regulatory acts.
    """

    PROHIBITION = "prohibition"
    """Outright ban on the use."""

    DURATION = "duration"
    """Minimum or maximum length of an individual stay."""

    FREQUENCY = "frequency"
    """How often a property may be rented — nights or bookings per year."""

    PERMIT_REGISTRATION = "permit_registration"
    OCCUPANCY_LIMIT = "occupancy_limit"
    PRIMARY_RESIDENCE = "primary_residence"
    ZONING = "zoning"
    PARKING = "parking"
    NOISE = "noise"
    TAXATION = "taxation"
    SAFETY_INSPECTION = "safety_inspection"
    ADVERTISING_DISCLOSURE = "advertising_disclosure"
    PROPERTY_VALUATION = "property_valuation"
    """Present because Fla. Stat. § 509.032(7)(c) carves it out — a
    reminder that the taxonomy is driven by what statutes actually
    distinguish, not by what seems tidy in the abstract."""


class Modality(str, Enum):
    """The deontic force of a provision. Maps onto deontic/system_e.py's
    operators, though nothing here depends on that module."""

    PROHIBITION = "prohibition"
    OBLIGATION = "obligation"
    PERMISSION = "permission"


@dataclass(frozen=True)
class Obligation:
    """One operative provision, not one document.

    An ordinance section that both requires a permit *and* caps nights is
    two obligations. Keeping them separate is what lets the night cap be
    struck while the permit requirement survives — collapsing them into
    one record would force an all-or-nothing answer to a question the
    statute answers separately.

    ``adopted_date`` is optional because real corpora are incomplete, and
    a missing date must produce an *undetermined* preemption result
    rather than a guess. See ``express_preemption.py``.
    """

    citation: str
    jurisdiction_tier: JurisdictionTier
    jurisdiction_path: tuple[str, ...]
    """The chain of polities containing this provision, outermost first —
    ``("United States", "Florida", "City of Miami Beach")``.

    A path rather than a single name because preemption is bounded by
    containment, and a bare name cannot express it: a Florida statute
    reaches Florida's subdivisions and no others. With only a name, an
    Arizona city ordinance is still "municipal" and still "below state",
    so a naive tier comparison would let Florida law void it. The tier
    ordering says nothing about *which* state, and that is not a detail
    — it is the difference between a correct answer and a confidently
    wrong one."""

    subjects: frozenset[SubjectMatter]
    modality: Modality
    text: str
    adopted_date: date | None = None
    effective_date: date | None = None
    source_url: str | None = None
    applies_to: frozenset[str] = field(default_factory=frozenset)

    @property
    def jurisdiction_name(self) -> str:
        """The enacting polity itself — the innermost element."""
        return self.jurisdiction_path[-1] if self.jurisdiction_path else ""

    def is_within(self, jurisdiction: str) -> bool:
        """Whether this provision sits inside ``jurisdiction``'s reach."""
        return jurisdiction in self.jurisdiction_path

    def regulates_any(self, subjects: frozenset[SubjectMatter]) -> bool:
        return bool(self.subjects & subjects)
