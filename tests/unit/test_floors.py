"""Floor doctrine, against real federal and state wage law.

The case that motivated this whole module is
``test_california_governs_rather_than_being_preempted``: modelled as an
``ExpressPreemptionRule``, California's $16.50 minimum wage came back
PREEMPTED. 29 U.S.C. § 218(a) says the opposite in terms. Everything else
here follows from getting that one right.

Expected outcomes are read off the statutes, not off the implementation.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from legal_engine.core.models import JurisdictionTier
from legal_engine.obligations.express_preemption import ExpressPreemptionRule
from legal_engine.obligations.express_preemption import analyze as analyze_preemption
from legal_engine.obligations.floors import FloorRule, FloorStatus, Stringency, analyze_floor
from legal_engine.obligations.models import Modality, Obligation, SubjectMatter, Threshold

US = ("United States",)

FLSA_WAGE = FloorRule(
    citation="29 U.S.C. § 206(a)(1)",
    enacting_jurisdiction="United States",
    tier=JurisdictionTier.FEDERAL,
    subject=SubjectMatter.MINIMUM_WAGE,
    threshold=Threshold(Decimal("7.25"), "USD per hour"),
    stringency=Stringency.HIGHER_IS_STRICTER,
    text="Federal minimum wage.",
    savings_clause_citation="29 U.S.C. § 218(a)",
)

FLSA_WORKWEEK = FloorRule(
    citation="29 U.S.C. § 207(a)(1)",
    enacting_jurisdiction="United States",
    tier=JurisdictionTier.FEDERAL,
    subject=SubjectMatter.MAXIMUM_WORKWEEK,
    threshold=Threshold(Decimal(40), "hours per week"),
    # § 218(a) preserves a maximum workweek *lower* than the federal one.
    stringency=Stringency.LOWER_IS_STRICTER,
    text="Overtime required after 40 hours.",
    savings_clause_citation="29 U.S.C. § 218(a)",
)


def _wage_law(
    citation: str,
    jurisdiction: tuple[str, ...],
    value: str | None,
    tier: JurisdictionTier = JurisdictionTier.STATE,
    unit: str = "USD per hour",
    subject: SubjectMatter = SubjectMatter.MINIMUM_WAGE,
) -> Obligation:
    return Obligation(
        citation=citation,
        jurisdiction_tier=tier,
        jurisdiction_path=jurisdiction,
        subjects=frozenset({subject}),
        modality=Modality.OBLIGATION,
        text="...",
        threshold=Threshold(Decimal(value), unit) if value is not None else None,
    )


class TestTheCaseThatBrokeTheAbstraction:
    def test_california_governs_rather_than_being_preempted(self):
        """The spike's whole reason for existing. Under preemption
        doctrine a subordinate rule inside the reserved scope falls;
        under floor doctrine one that exceeds the floor governs. The
        federal minimum wage is the second kind, and § 218(a) says so."""
        california = _wage_law("Cal. Lab. Code § 1182.12", US + ("California",), "16.50")

        finding = analyze_floor(california, FLSA_WAGE)

        assert finding.status is FloorStatus.GOVERNS_AS_MORE_PROTECTIVE
        assert finding.operative_threshold == Threshold(Decimal("16.50"), "USD per hour")

    def test_the_preemption_module_gets_it_backwards(self):
        """Kept as an executable record of *why* floors.py exists. If
        someone later folds the two doctrines together, this fails and
        explains itself."""
        california = _wage_law("Cal. Lab. Code § 1182.12", US + ("California",), "16.50")
        as_preemption = ExpressPreemptionRule(
            citation="29 U.S.C. § 206(a)(1)",
            enacting_jurisdiction="United States",
            tier=JurisdictionTier.FEDERAL,
            reserved_subjects=frozenset({SubjectMatter.MINIMUM_WAGE}),
            text="Federal minimum wage.",
        )

        wrong = analyze_preemption(california, as_preemption)

        assert wrong.status.value == "preempted"
        assert analyze_floor(california, FLSA_WAGE).status is FloorStatus.GOVERNS_AS_MORE_PROTECTIVE


class TestComparison:
    def test_a_weaker_state_rule_is_displaced_and_the_floor_governs(self):
        georgia = _wage_law("Ga. Code § 34-4-3", US + ("Georgia",), "5.15")

        finding = analyze_floor(georgia, FLSA_WAGE)

        assert finding.status is FloorStatus.DISPLACED_AS_LESS_PROTECTIVE
        assert finding.operative_threshold == FLSA_WAGE.threshold

    def test_displaced_is_not_the_same_as_void(self):
        """A preempted ordinance is struck. A displaced floor rule may
        still operate for parties the federal law doesn't cover, so the
        reasoning says so rather than implying invalidity."""
        georgia = _wage_law("Ga. Code § 34-4-3", US + ("Georgia",), "5.15")
        assert "rather than void" in analyze_floor(georgia, FLSA_WAGE).reasoning

    def test_matching_the_floor_exactly_is_reported_distinctly(self):
        """Worth its own status: a state that merely matches loses its
        protection the moment Congress raises the floor."""
        texas = _wage_law("Tex. Lab. Code § 62.051", US + ("Texas",), "7.25")
        assert analyze_floor(texas, FLSA_WAGE).status is FloorStatus.EQUIVALENT

    def test_a_municipality_may_exceed_a_federal_floor(self):
        """Two tiers down and still governing — the inverse of preemption,
        where distance from the enacting authority only ever weakens a
        provision's position."""
        seattle = _wage_law(
            "Seattle Mun. Code 14.19",
            US + ("Washington", "Seattle"),
            "20.76",
            tier=JurisdictionTier.MUNICIPAL,
        )
        assert analyze_floor(seattle, FLSA_WAGE).status is FloorStatus.GOVERNS_AS_MORE_PROTECTIVE


class TestStringencyDirection:
    """§ 218(a) preserves a *higher* minimum wage and a *lower* maximum
    workweek in one sentence. A single "stricter means bigger" assumption
    gets the second backwards."""

    def test_a_lower_workweek_cap_is_more_protective(self):
        state = _wage_law(
            "State Code § 1",
            US + ("Somewhere",),
            "35",
            unit="hours per week",
            subject=SubjectMatter.MAXIMUM_WORKWEEK,
        )
        assert analyze_floor(state, FLSA_WORKWEEK).status is FloorStatus.GOVERNS_AS_MORE_PROTECTIVE

    def test_a_higher_workweek_cap_is_less_protective(self):
        state = _wage_law(
            "State Code § 2",
            US + ("Somewhere",),
            "48",
            unit="hours per week",
            subject=SubjectMatter.MAXIMUM_WORKWEEK,
        )
        assert analyze_floor(state, FLSA_WORKWEEK).status is FloorStatus.DISPLACED_AS_LESS_PROTECTIVE

    def test_the_same_number_means_opposite_things_under_the_two_rules(self):
        """35 beats a 40-hour cap and loses to a $7.25 wage floor. The
        direction has to travel with the rule."""
        as_hours = _wage_law(
            "X", US + ("Somewhere",), "35", unit="hours per week",
            subject=SubjectMatter.MAXIMUM_WORKWEEK,
        )
        as_wage = _wage_law("Y", US + ("Somewhere",), "3.50")
        assert analyze_floor(as_hours, FLSA_WORKWEEK).status is FloorStatus.GOVERNS_AS_MORE_PROTECTIVE
        assert analyze_floor(as_wage, FLSA_WAGE).status is FloorStatus.DISPLACED_AS_LESS_PROTECTIVE


class TestRefusal:
    def test_a_provision_with_no_threshold_is_undetermined(self):
        vague = _wage_law("Nev. Code § 1", US + ("Nevada",), None)

        finding = analyze_floor(vague, FLSA_WAGE)

        assert finding.status is FloorStatus.UNDETERMINED
        assert finding.missing_facts == frozenset({"threshold"})
        assert finding.operative_threshold is None

    def test_mismatched_units_are_not_silently_converted(self):
        """California's daily 8-hour overtime rule is a genuinely
        different protection from a weekly 40-hour cap, not a smaller
        version of it. Converting would fabricate a comparison the
        statutes don't support."""
        daily = _wage_law(
            "Cal. Lab. Code § 510",
            US + ("California",),
            "8",
            unit="hours per day",
            subject=SubjectMatter.MAXIMUM_WORKWEEK,
        )

        finding = analyze_floor(daily, FLSA_WORKWEEK)

        assert finding.status is FloorStatus.UNDETERMINED
        assert finding.missing_facts == frozenset({"unit_conversion"})


class TestSharedPreliminaries:
    """The three checks both doctrines run first, via authority.precheck."""

    def test_a_rule_does_not_floor_its_own_enactment(self):
        federal = _wage_law("29 U.S.C. § 218", US, "7.25", tier=JurisdictionTier.FEDERAL)
        assert analyze_floor(federal, FLSA_WAGE).status is FloorStatus.NOT_SUBORDINATE

    def test_an_unrelated_subject_is_out_of_scope(self):
        parking = Obligation(
            citation="City Code § 9",
            jurisdiction_tier=JurisdictionTier.MUNICIPAL,
            jurisdiction_path=US + ("California", "Oakland"),
            subjects=frozenset({SubjectMatter.PARKING}),
            modality=Modality.OBLIGATION,
            text="...",
        )
        assert analyze_floor(parking, FLSA_WAGE).status is FloorStatus.NOT_IN_SCOPE

    def test_the_reach_check_still_applies(self):
        """A floor rule enacted by one polity does not reach another's
        subdivisions any more than a preemption rule does."""
        elsewhere = _wage_law("Provincial Code § 1", ("Canada", "Ontario"), "17.20")
        assert analyze_floor(elsewhere, FLSA_WAGE).status is FloorStatus.OUTSIDE_JURISDICTION


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("7.26", FloorStatus.GOVERNS_AS_MORE_PROTECTIVE),
        ("7.25", FloorStatus.EQUIVALENT),
        ("7.24", FloorStatus.DISPLACED_AS_LESS_PROTECTIVE),
    ],
)
def test_the_boundary_is_exact_to_the_cent(value, expected):
    """Decimal, not float. A wage comparison decided by binary floating
    point is one that will eventually be wrong by a cent."""
    state = _wage_law("State Code § 3", US + ("Somewhere",), value)
    assert analyze_floor(state, FLSA_WAGE).status is expected
