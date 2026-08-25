"""A worked short-term-rental corpus: one real statute, several
illustrative ordinances.

## What is real and what is not

``FLORIDA_VACATION_RENTAL_PREEMPTION`` carries the **verbatim text of
Fla. Stat. § 509.032(7)(b)**, retrieved from the Florida Senate's own
publication of the statute (see ``source_url``). The scope, the cutoff
date, and the § 509.032(7)(c) exemption are all read directly off that
text rather than summarised.

The municipal ordinances below are **illustrative, not verbatim**. They
are modelled on patterns that recur across Florida STR ordinances —
nights-per-year caps, minimum-stay rules, permit schemes, parking
minimums — but no sentence here is quoted from any real city code, and
the citations are of the form "City of Example". Municode, which
publishes most municipal codes, disallows this crawler in its robots.txt
(``User-agent: ClaudeBot`` / ``Disallow: /``, plus ``ai-train=no``), so
real ordinance text was not collected.

That split is deliberate and worth stating plainly: **the hard edge of
the demonstration is the statute**, because that is what supplies the
scope, the grandfather cutoff, and the carve-out. The ordinances only
need to be structurally faithful to exercise it. Replacing them with
real text would strengthen the demonstration and would not change the
engine.

Nothing here is legal advice, and none of it should be relied on to
determine whether any actual ordinance is preempted.
"""

from __future__ import annotations

from datetime import date

from legal_engine.core.models import JurisdictionTier
from legal_engine.obligations.express_preemption import Exemption, ExpressPreemptionRule
from legal_engine.obligations.models import Modality, Obligation, SubjectMatter

_FL_SOURCE = "https://www.flsenate.gov/Laws/Statutes/2023/509.032"

FLORIDA_VACATION_RENTAL_PREEMPTION = ExpressPreemptionRule(
    citation="Fla. Stat. § 509.032(7)(b)",
    enacting_jurisdiction="Florida",
    tier=JurisdictionTier.STATE,
    # Exactly the three the text names. Everything a city might otherwise
    # regulate about a vacation rental — parking, noise, permits,
    # occupancy, taxes, inspections — is outside this and survives.
    reserved_subjects=frozenset(
        {SubjectMatter.PROHIBITION, SubjectMatter.DURATION, SubjectMatter.FREQUENCY}
    ),
    text=(
        "A local law, ordinance, or regulation may not prohibit vacation rentals or "
        "regulate the duration or frequency of rental of vacation rentals. This paragraph "
        "does not apply to any local law, ordinance, or regulation adopted on or before "
        "June 1, 2011."
    ),
    # "on or before June 1, 2011" — inclusive, per the text.
    grandfather_cutoff=date(2011, 6, 1),
    exemptions=(
        Exemption(
            citation="Fla. Stat. § 509.032(7)(c)",
            subjects=frozenset({SubjectMatter.PROPERTY_VALUATION}),
            description=(
                "local rules exclusively relating to property valuation as a criterion for "
                "vacation rental, where approval by the state land planning agency is required "
                "under an area of critical state concern designation"
            ),
            # "exclusively relating to" — an ordinance that also caps
            # frequency is not exclusively about valuation and stays
            # preempted.
            requires_all=True,
        ),
    ),
    source_url=_FL_SOURCE,
)

_FL_CITY = ("United States", "Florida", "City of Example")
_AZ_CITY = ("United States", "Arizona", "City of Elsewhere")


def _ordinance(
    citation: str,
    subjects: set[SubjectMatter],
    text: str,
    adopted: date | None,
    modality: Modality = Modality.PROHIBITION,
    path: tuple[str, ...] = _FL_CITY,
) -> Obligation:
    return Obligation(
        citation=citation,
        jurisdiction_tier=JurisdictionTier.MUNICIPAL,
        jurisdiction_path=path,
        subjects=frozenset(subjects),
        modality=modality,
        text=text,
        adopted_date=adopted,
        applies_to=frozenset({"short-term-rental"}),
    )


# --- inside the reserved scope, adopted after the cutoff: preempted ---

NIGHT_CAP_2019 = _ordinance(
    "City of Example Code § 14-2(a)",
    {SubjectMatter.FREQUENCY},
    "No dwelling unit may be rented as a vacation rental for more than 90 nights in any "
    "calendar year.",
    adopted=date(2019, 3, 12),
)

OUTRIGHT_BAN_2018 = _ordinance(
    "City of Example Code § 14-1",
    {SubjectMatter.PROHIBITION},
    "Vacation rentals are prohibited in all residential zoning districts.",
    adopted=date(2018, 7, 1),
)

MINIMUM_STAY_2016 = _ordinance(
    "City of Example Code § 14-3",
    {SubjectMatter.DURATION},
    "No vacation rental may be let for a term of fewer than 7 consecutive nights.",
    adopted=date(2016, 1, 20),
)

# --- inside the scope but adopted on or before the cutoff: survives ---

NIGHT_CAP_2010 = _ordinance(
    "City of Legacy Code § 8-14",
    {SubjectMatter.FREQUENCY},
    "No dwelling unit may be rented as a vacation rental for more than 120 nights in any "
    "calendar year.",
    adopted=date(2010, 5, 4),
)

BOUNDARY_ORDINANCE = _ordinance(
    "City of Boundary Code § 2-1",
    {SubjectMatter.DURATION},
    "No vacation rental may be let for a term of fewer than 30 consecutive nights.",
    # Exactly the cutoff. "on or before" makes this grandfathered; an
    # exclusive comparison would wrongly void it.
    adopted=date(2011, 6, 1),
)

# --- outside the reserved scope: untouched, however recent ---

PARKING_2021 = _ordinance(
    "City of Example Code § 14-9",
    {SubjectMatter.PARKING},
    "Each vacation rental shall provide one off-street parking space per bedroom.",
    adopted=date(2021, 9, 8),
    modality=Modality.OBLIGATION,
)

PERMIT_2022 = _ordinance(
    "City of Example Code § 14-5",
    {SubjectMatter.PERMIT_REGISTRATION},
    "Every vacation rental shall register annually with the city and display its permit "
    "number in any advertisement.",
    adopted=date(2022, 2, 15),
    modality=Modality.OBLIGATION,
)

# --- a fact the rule turns on is missing: undetermined ---

UNDATED_NIGHT_CAP = _ordinance(
    "City of Unknown Code § 5-2",
    {SubjectMatter.FREQUENCY},
    "Vacation rentals shall not be let more than 26 times per calendar year.",
    adopted=None,
)

# --- correct tier, wrong state: the case a bare tier check gets wrong ---

ARIZONA_NIGHT_CAP = _ordinance(
    "City of Elsewhere Code § 30-4",
    {SubjectMatter.FREQUENCY},
    "No dwelling unit may be rented as a short-term rental for more than 60 nights in any "
    "calendar year.",
    adopted=date(2020, 4, 1),
    path=_AZ_CITY,
)

# --- mixed subjects: not "exclusively" valuation, so not exempt ---

VALUATION_AND_FREQUENCY = _ordinance(
    "City of Mixed Code § 11-7",
    {SubjectMatter.PROPERTY_VALUATION, SubjectMatter.FREQUENCY},
    "Properties assessed above $2,000,000 may not be let as vacation rentals more than 30 "
    "nights per year.",
    adopted=date(2020, 6, 1),
)

STR_ORDINANCES: tuple[Obligation, ...] = (
    NIGHT_CAP_2019,
    OUTRIGHT_BAN_2018,
    MINIMUM_STAY_2016,
    NIGHT_CAP_2010,
    BOUNDARY_ORDINANCE,
    PARKING_2021,
    PERMIT_2022,
    UNDATED_NIGHT_CAP,
    ARIZONA_NIGHT_CAP,
    VALUATION_AND_FREQUENCY,
)

STR_PREEMPTION_RULES: tuple[ExpressPreemptionRule, ...] = (FLORIDA_VACATION_RENTAL_PREEMPTION,)
