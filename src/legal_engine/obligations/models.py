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
from decimal import Decimal
from enum import Enum

from legal_engine.core.models import JurisdictionTier


class SubjectMatter(str, Enum):
    """What a provision regulates.

    Grown from corpora rather than designed up front. The first block
    below comes from short-term-rental regulation, the next two from
    measuring against Fla. Stat. ch. 509, and the employment block from
    the floor/ceiling spike. Nothing here was added because it rounded
    out a diagram; a taxonomy that tried to cover all of law in advance
    would be wrong everywhere instead of right somewhere.

    **Known limit — one enum, now two domains.** This was documented as
    narrow and STR-specific until employment subjects were added, and at
    two domains a single enum with labelled sections is still the
    simplest thing that works. It will not stay that way. The trigger to
    split is a third domain, or any subject name that has to be qualified
    to avoid colliding with another domain's ("DURATION" already means
    something different to a lease than to a stay). The fix at that point
    is per-domain taxonomies with ``Obligation.subjects`` taking a union
    — a much larger change than adding a member, which is precisely why
    it is worth hitting deliberately rather than by surprise.

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

    # The five below were added from measurement, not from imagination.
    # Running the extractor over six real sections of Fla. Stat. ch. 509
    # left 68% of normative provisions unclassified, and roughly a third
    # of those failed for want of a subject rather than for want of
    # parsing: sanitation and wastewater rules, fire and life-safety
    # requirements, fee schedules, agency rulemaking, and reporting
    # deadlines. No amount of better language understanding fills a hole
    # in the taxonomy — a model constrained to this schema has nowhere to
    # put "wastewater shall be properly treated" either.
    SANITATION = "sanitation"
    """Sewage, wastewater, vermin, potable water, food-borne illness, and
    linen hygiene. Bedding is here rather than in a subject of its own:
    "sheets shall be laundered before use by another guest" is a hygiene
    rule, and a LINENS subject would be lodging-specific in a way nothing
    else in this taxonomy is."""

    FIRE_SAFETY = "fire_safety"
    """Substantive life-safety requirements, as distinct from
    SAFETY_INSPECTION, which is the act of inspecting for them."""

    FEES = "fees"
    RULEMAKING = "rulemaking"
    """Authority to adopt rules — almost always borne by the regulator."""

    RECORDKEEPING = "recordkeeping"
    """Records, reports, filings, and the deadlines attached to them."""

    # A second measured round. Each of these generalises beyond lodging
    # law, which is the test applied before adding one: "linens" appears
    # repeatedly in ch. 509 and was *not* added, because a subject that
    # only ever fires on hotel statutes is overfitting to the corpus that
    # produced it rather than a category of regulation.
    ENFORCEMENT = "enforcement"
    """Sanctions, revocation, stop-orders, referral to law enforcement.
    Distinct from FEES: a fine is a sum of money, an enforcement action
    is a power the regulator exercises."""

    ADMINISTRATIVE_PROCEDURE = "administrative_procedure"
    """Variances, appeals, notice, hearings — how a decision gets made
    rather than what it decides. Present in essentially every regulatory
    statute."""

    HABITABILITY = "habitability"
    """Light, heat, ventilation, water — the conditions that make a
    dwelling fit to occupy."""

    BUILDING_STANDARDS = "building_standards"
    """Structural requirements: railings, stairways, egress construction.
    Distinct from FIRE_SAFETY, which is about a specific hazard."""
    # --- employment ---
    # A second domain, added to test whether the doctrine layer survives a
    # rule system running opposite to preemption. It did not, which is why
    # floors.py exists — see its module docstring. These are the subjects
    # 29 U.S.C. 218(a) actually names.
    MINIMUM_WAGE = "minimum_wage"
    MAXIMUM_WORKWEEK = "maximum_workweek"
    OVERTIME_PREMIUM = "overtime_premium"
    CHILD_LABOR = "child_labor"

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


class Bearer(str, Enum):
    """Who the duty falls on.

    Added because measurement demanded it. Of the provisions this schema
    could not represent across six real sections of Fla. Stat. ch. 509,
    the single largest group — 38% — were duties on the *agency*: "the
    division shall adopt rules", "the report shall be submitted by
    September 30". Those are not extraction failures. They are provisions
    an obligation model without a bearer literally cannot hold.

    The distinction is also what a compliance product actually needs. "What
    must I do" and "what does the regulator owe me" are different
    questions asked by different people, and a system that merges them
    answers neither well.
    """

    REGULATED_PARTY = "regulated_party"
    """The operator, owner, or licensee — the default reading."""

    REGULATOR = "regulator"
    """An agency, division, or department acting under the statute."""

    SUBORDINATE_LEGISLATURE = "subordinate_legislature"
    """A city, town, county, or other law-making body below the enacting
    authority.

    Found the same way REGULATOR was — by measuring. Against A.R.S.
    § 9-500.39, held out and never tuned against, **five of seven**
    unclassified provisions were directed at a city or town, including
    the headline sentence of the entire statute: "A city or town may not
    prohibit vacation rentals."

    It is a genuinely distinct bearer, not a variant of REGULATOR. An
    agency administers a statute; a subordinate legislature *makes rules*
    under one. Provisions binding it regulate rule-making rather than
    conduct, which is what a preemption statute mostly consists of — so a
    model that cannot express this bearer cannot represent the very
    documents this system exists to read."""

    UNSPECIFIED = "unspecified"


@dataclass(frozen=True)
class Threshold:
    """A quantified standard: $16.50 per hour, 40 hours per week.

    ``Decimal`` rather than ``float`` because these are money and legal
    limits, and a wage comparison that turns on binary floating point is
    a wage comparison that will eventually be wrong by a cent in the
    direction nobody wants to explain.

    Added for the floor/ceiling spike. Preemption never needed it —
    scope-based doctrine decides without reading the number — which is
    itself the finding: content-dependent doctrine needs content.
    """

    value: Decimal
    unit: str
    """Free text, compared for equality only. "per hour" and "hourly" do
    not compare equal, and silently treating them as equal would be worse
    than refusing."""


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
    bearer: Bearer = Bearer.REGULATED_PARTY
    threshold: Threshold | None = None
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
