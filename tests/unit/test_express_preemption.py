"""Express preemption against a real statute.

Every expected outcome here is read off the text of Fla. Stat.
§ 509.032(7)(b)-(c) rather than off the implementation, which is the only
way this suite is worth anything: a test that encodes what the code does
proves nothing about whether the code is right about the law.

The four cases that matter most are the ones a naive implementation gets
wrong — a recent ordinance outside the reserved scope (survives), an
ordinance in the wrong state (untouched, despite being municipal and
therefore "below" a state), an ordinance adopted exactly on the cutoff
(inclusive), and one with no adoption date at all (refused, not guessed).
"""

from __future__ import annotations

from datetime import date

from legal_engine.core.models import JurisdictionTier
from legal_engine.obligations import corpus
from legal_engine.obligations.express_preemption import (
    PreemptionStatus,
    analyze,
    analyze_all,
)
from legal_engine.obligations.models import Modality, Obligation, SubjectMatter

RULE = corpus.FLORIDA_VACATION_RENTAL_PREEMPTION


def _status(obligation) -> PreemptionStatus:
    return analyze(obligation, RULE).status


class TestInsideTheReservedScope:
    """The statute names prohibition, duration, and frequency."""

    def test_a_nights_per_year_cap_is_preempted(self):
        assert _status(corpus.NIGHT_CAP_2019) is PreemptionStatus.PREEMPTED

    def test_an_outright_ban_is_preempted(self):
        assert _status(corpus.OUTRIGHT_BAN_2018) is PreemptionStatus.PREEMPTED

    def test_a_minimum_stay_rule_is_preempted(self):
        """Duration, distinct from frequency — the statute names both."""
        assert _status(corpus.MINIMUM_STAY_2016) is PreemptionStatus.PREEMPTED

    def test_a_preempted_provision_does_not_survive(self):
        assert analyze(corpus.NIGHT_CAP_2019, RULE).survives is False

    def test_the_finding_names_the_conflicting_subject(self):
        finding = analyze(corpus.NIGHT_CAP_2019, RULE)
        assert finding.conflicting_subjects == frozenset({SubjectMatter.FREQUENCY})
        assert "frequency" in finding.reasoning
        assert RULE.citation in finding.reasoning


class TestOutsideTheReservedScope:
    """Everything the statute doesn't name survives, however recent —
    this is the case tier-based reasoning alone gets wrong."""

    def test_a_parking_requirement_survives(self):
        assert _status(corpus.PARKING_2021) is PreemptionStatus.NOT_IN_SCOPE

    def test_a_permit_scheme_survives(self):
        assert _status(corpus.PERMIT_2022) is PreemptionStatus.NOT_IN_SCOPE

    def test_recency_is_irrelevant_when_out_of_scope(self):
        """A 2022 ordinance outranks nothing; the cutoff never enters the
        analysis because the subject matter was never reserved."""
        finding = analyze(corpus.PERMIT_2022, RULE)
        assert finding.survives is True
        assert "cutoff" not in finding.reasoning


class TestGrandfathering:
    def test_an_ordinance_predating_the_cutoff_survives(self):
        assert _status(corpus.NIGHT_CAP_2010) is PreemptionStatus.GRANDFATHERED

    def test_the_cutoff_date_itself_is_included(self):
        """"adopted on or before June 1, 2011" — an exclusive comparison
        would void an ordinance the statute expressly spares."""
        assert corpus.BOUNDARY_ORDINANCE.adopted_date == date(2011, 6, 1)
        assert _status(corpus.BOUNDARY_ORDINANCE) is PreemptionStatus.GRANDFATHERED

    def test_one_day_after_the_cutoff_is_preempted(self):
        just_after = Obligation(
            citation="City of Example Code § 99",
            jurisdiction_tier=JurisdictionTier.MUNICIPAL,
            jurisdiction_path=("United States", "Florida", "City of Example"),
            subjects=frozenset({SubjectMatter.FREQUENCY}),
            modality=Modality.PROHIBITION,
            text="...",
            adopted_date=date(2011, 6, 2),
        )
        assert _status(just_after) is PreemptionStatus.PREEMPTED

    def test_grandfathered_is_reported_distinctly_from_out_of_scope(self):
        """Both survive, for different reasons, and a lawyer needs to know
        which — a grandfathered rule is vulnerable to amendment in a way
        an out-of-scope rule is not."""
        assert _status(corpus.NIGHT_CAP_2010) is not _status(corpus.PARKING_2021)


class TestRefusal:
    def test_a_missing_adoption_date_is_undetermined(self):
        assert _status(corpus.UNDATED_NIGHT_CAP) is PreemptionStatus.UNDETERMINED

    def test_the_missing_fact_is_named(self):
        finding = analyze(corpus.UNDATED_NIGHT_CAP, RULE)
        assert finding.missing_facts == frozenset({"adopted_date"})

    def test_undetermined_does_not_count_as_surviving(self):
        """The trap: a caller checking only `survives` must not read an
        unresolved question as a clean bill of health."""
        assert analyze(corpus.UNDATED_NIGHT_CAP, RULE).survives is False


class TestJurisdictionalReach:
    def test_an_out_of_state_ordinance_is_untouched(self):
        """Municipal, therefore below a state tier — and completely
        outside Florida's reach. Tier alone would void it."""
        assert _status(corpus.ARIZONA_NIGHT_CAP) is PreemptionStatus.OUTSIDE_JURISDICTION

    def test_it_survives(self):
        assert analyze(corpus.ARIZONA_NIGHT_CAP, RULE).survives is True

    def test_the_state_cannot_preempt_its_own_statute(self):
        state_law = Obligation(
            citation="Fla. Stat. § 509.241",
            jurisdiction_tier=JurisdictionTier.STATE,
            jurisdiction_path=("United States", "Florida"),
            subjects=frozenset({SubjectMatter.FREQUENCY}),
            modality=Modality.OBLIGATION,
            text="...",
            adopted_date=date(2020, 1, 1),
        )
        assert _status(state_law) is PreemptionStatus.NOT_SUBORDINATE

    def test_a_county_ordinance_is_subordinate(self):
        county = Obligation(
            citation="Example County Code § 4-1",
            jurisdiction_tier=JurisdictionTier.COUNTY,
            jurisdiction_path=("United States", "Florida", "Example County"),
            subjects=frozenset({SubjectMatter.PROHIBITION}),
            modality=Modality.PROHIBITION,
            text="...",
            adopted_date=date(2019, 1, 1),
        )
        assert _status(county) is PreemptionStatus.PREEMPTED


class TestStatutoryExemption:
    def test_an_exclusively_valuation_rule_is_exempt(self):
        valuation_only = Obligation(
            citation="City of Keys Code § 3-3",
            jurisdiction_tier=JurisdictionTier.MUNICIPAL,
            jurisdiction_path=("United States", "Florida", "City of Keys"),
            subjects=frozenset({SubjectMatter.PROPERTY_VALUATION}),
            modality=Modality.PERMISSION,
            text="...",
            adopted_date=date(2020, 1, 1),
        )
        # Property valuation isn't a reserved subject at all, so the
        # statute never reaches it — the carve-out in (c) is belt and
        # braces for rules that also touch a reserved subject.
        assert _status(valuation_only) is PreemptionStatus.NOT_IN_SCOPE

    def test_valuation_plus_frequency_is_not_exclusively_valuation(self):
        """§ 509.032(7)(c) exempts rules "exclusively relating to"
        valuation. One that also caps frequency is not, and stays
        preempted — dropping "exclusively" would wrongly save it."""
        assert _status(corpus.VALUATION_AND_FREQUENCY) is PreemptionStatus.PREEMPTED


class TestCorpusSweep:
    def test_analyze_all_skips_rules_that_never_engaged(self):
        """An Arizona ordinance and a state statute produce no finding
        against a Florida local-preemption rule; including them would pad
        a report with non-answers."""
        findings = analyze_all(list(corpus.STR_ORDINANCES), list(corpus.STR_PREEMPTION_RULES))
        cited = {f.obligation.citation for f in findings}
        assert corpus.ARIZONA_NIGHT_CAP.citation not in cited
        assert corpus.NIGHT_CAP_2019.citation in cited

    def test_every_ordinance_gets_a_reason(self):
        for ordinance in corpus.STR_ORDINANCES:
            finding = analyze(ordinance, RULE)
            assert finding.reasoning.strip(), f"{ordinance.citation} produced no reasoning"

    def test_the_corpus_exercises_every_outcome(self):
        """If a status stops being reachable the corpus has drifted away
        from the doctrine it's meant to demonstrate."""
        observed = {analyze(o, RULE).status for o in corpus.STR_ORDINANCES}
        assert observed == {
            PreemptionStatus.PREEMPTED,
            PreemptionStatus.GRANDFATHERED,
            PreemptionStatus.NOT_IN_SCOPE,
            PreemptionStatus.UNDETERMINED,
            PreemptionStatus.OUTSIDE_JURISDICTION,
        }


class TestRuleFidelity:
    """Guards against the corpus silently drifting from the statute."""

    def test_the_reserved_scope_is_exactly_what_the_text_names(self):
        assert RULE.reserved_subjects == frozenset(
            {SubjectMatter.PROHIBITION, SubjectMatter.DURATION, SubjectMatter.FREQUENCY}
        )

    def test_the_cutoff_matches_the_statute(self):
        assert RULE.grandfather_cutoff == date(2011, 6, 1)

    def test_the_statutory_text_is_carried_verbatim(self):
        assert "may not prohibit vacation rentals" in RULE.text
        assert "adopted on or before June 1, 2011" in RULE.text
        assert RULE.source_url and "flsenate.gov" in RULE.source_url
