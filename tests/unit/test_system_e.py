"""Exercises the System E finite-model evaluator.

The two paradox suites are the point. Chisholm's Paradox and Forrester's
gentle-murder paradox are the standard tests for whether a deontic logic
handles contrary-to-duty obligations — Standard Deontic Logic derives a
contradiction from both, and a semantics that quietly did the same would
look fine on every other test in this file.

TestDilemmaDetection pins the correction to a proposed abstention gate
that would have halted on ties. See system_e.py's module docstring.
"""

from __future__ import annotations

import pytest

from legal_engine.deontic.formulas import And, Atom, Bottom, Implies, Not, Or, Top
from legal_engine.deontic.system_e import PreferenceModel, PreferenceModelError

GOES, TELLS = Atom("goes"), Atom("tells")
MURDERS, GENTLY = Atom("murders"), Atom("gently")


@pytest.fixture
def chisholm() -> PreferenceModel:
    """Jones ought to help his neighbours; if he goes he ought to tell
    them; if he doesn't go he ought not tell them; he doesn't go.

    Ranked best to worst: going and telling, going without telling,
    staying quietly away, and — worst — announcing a visit he never
    makes."""
    return PreferenceModel.from_ranking(
        tiers=[["go_tell"], ["go_silent"], ["stay_silent"], ["stay_tell"]],
        valuation={
            "go_tell": {"goes", "tells"},
            "go_silent": {"goes"},
            "stay_silent": set(),
            "stay_tell": {"tells"},
        },
    )


@pytest.fixture
def gentle_murder() -> PreferenceModel:
    """Smith ought not murder Jones; if he murders him he ought to do it
    gently; he murders him. "Gently" entails "murders", which is what
    makes SDL derive an obligation to murder."""
    return PreferenceModel.from_ranking(
        tiers=[["no_murder"], ["gentle_murder"], ["brutal_murder"]],
        valuation={
            "no_murder": set(),
            "gentle_murder": {"murders", "gently"},
            "brutal_murder": {"murders"},
        },
    )


class TestChisholmParadox:
    def test_all_four_premises_hold_together(self, chisholm):
        assert chisholm.obligation(GOES, Top()) is True
        assert chisholm.obligation(TELLS, GOES) is True
        assert chisholm.obligation(Not(TELLS), Not(GOES)) is True
        assert "stay_silent" in chisholm.extension(Not(GOES))

    def test_no_contradiction_is_derivable(self, chisholm):
        """SDL's failure: deriving both O(tell) and O(~tell)
        unconditionally. Here the two obligations stay conditional on
        different antecedents and never collide."""
        assert not (
            chisholm.obligation(TELLS, Top()) and chisholm.obligation(Not(TELLS), Top())
        )

    def test_the_secondary_obligation_governs_the_violated_case(self, chisholm):
        """The contrary-to-duty property: given that Jones has already
        failed the primary obligation, the norm still says something
        useful about what he should do now."""
        verdict = chisholm.evaluate(Not(TELLS), Not(GOES))
        assert verdict.obligation is True
        assert verdict.optimal_worlds == frozenset({"stay_silent"})

    def test_the_premises_are_logically_independent(self, chisholm):
        """None of the three obligations is a consequence of evaluating
        at the same optimal set — each consults a different one."""
        assert chisholm.optimal(Top()) == frozenset({"go_tell"})
        assert chisholm.optimal(GOES) == frozenset({"go_tell"})
        assert chisholm.optimal(Not(GOES)) == frozenset({"stay_silent"})


class TestGentleMurderParadox:
    def test_both_premises_hold_together(self, gentle_murder):
        assert gentle_murder.obligation(Not(MURDERS), Top()) is True
        assert gentle_murder.obligation(GENTLY, MURDERS) is True

    def test_gently_entails_murders_in_the_model(self, gentle_murder):
        """Without this the paradox isn't being reproduced at all — it's
        precisely the entailment that lets SDL detach an obligation to
        murder."""
        assert gentle_murder.extension(Implies(GENTLY, MURDERS)) == gentle_murder.worlds

    def test_no_obligation_to_murder_is_derivable(self, gentle_murder):
        """The paradoxical conclusion SDL reaches. Blocked here because
        O(gently | murders) is evaluated at the best *murder* worlds,
        which are not the best worlds simpliciter."""
        assert gentle_murder.obligation(MURDERS, Top()) is False
        assert gentle_murder.prohibition(MURDERS, Top()) is True

    def test_murder_stays_forbidden_while_gentleness_is_obligatory_given_it(self, gentle_murder):
        assert gentle_murder.evaluate(MURDERS, Top()).prohibition is True
        assert gentle_murder.evaluate(GENTLY, MURDERS).obligation is True


class TestDilemmaDetection:
    """The ABS_02 correction: a tie is not a dilemma."""

    def test_a_tie_that_determines_the_subject_is_not_a_dilemma(self):
        """Two equally-good optimal worlds that agree about the subject.
        A gate triggering on "equal optimality" would halt here; nothing
        is actually undetermined."""
        model = PreferenceModel.from_ranking(
            tiers=[["best_a", "best_b"], ["worst"]],
            valuation={"best_a": {"safe", "x"}, "best_b": {"safe", "y"}, "worst": {"y"}},
        )
        verdict = model.evaluate(Atom("safe"), Top())

        assert len(verdict.optimal_worlds) == 2  # a genuine tie
        assert verdict.obligation is True
        assert verdict.is_dilemma is False

    def test_optimal_worlds_disagreeing_about_the_subject_is_a_dilemma(self):
        model = PreferenceModel.from_ranking(
            tiers=[["best_a", "best_b"], ["worst"]],
            valuation={"best_a": {"disclose"}, "best_b": {"protect"}, "worst": {"protect"}},
        )
        verdict = model.evaluate(Atom("disclose"), Top())

        assert verdict.is_dilemma is True
        assert verdict.obligation is False
        assert verdict.prohibition is False
        assert verdict.permission is True

    def test_a_single_optimal_world_is_never_a_dilemma(self):
        model = PreferenceModel.from_ranking(
            tiers=[["only_best"], ["worst"]],
            valuation={"only_best": {"safe"}, "worst": set()},
        )
        assert model.evaluate(Atom("safe"), Top()).is_dilemma is False

    def test_vacuity_is_reported_separately_from_dilemma(self, chisholm):
        """Opt(phi) empty makes every obligation conditional on phi true,
        including a proposition and its negation. Classically correct,
        practically a red flag, and a different condition from a
        dilemma."""
        verdict = chisholm.evaluate(TELLS, Bottom())

        assert verdict.is_vacuous is True
        assert verdict.is_dilemma is False
        assert verdict.obligation is True
        assert chisholm.obligation(Not(TELLS), Bottom()) is True  # both hold


class TestOperators:
    def test_permission_is_the_dual_of_obligation(self, chisholm):
        assert chisholm.permission(TELLS, GOES) is True
        assert chisholm.permission(Not(TELLS), GOES) is False

    def test_prohibition_is_obligation_of_the_negation(self, gentle_murder):
        assert gentle_murder.prohibition(MURDERS, Top()) == gentle_murder.obligation(
            Not(MURDERS), Top()
        )

    def test_optimal_of_top_is_the_best_tier(self, chisholm):
        assert chisholm.optimal(Top()) == frozenset({"go_tell"})

    def test_optimal_of_bottom_is_empty(self, chisholm):
        assert chisholm.optimal(Bottom()) == frozenset()

    def test_extension_of_a_conjunction(self, chisholm):
        assert chisholm.extension(And(GOES, TELLS)) == frozenset({"go_tell"})

    def test_extension_of_a_disjunction(self, chisholm):
        assert chisholm.extension(Or(GOES, TELLS)) == frozenset(
            {"go_tell", "go_silent", "stay_tell"}
        )

    def test_extension_of_an_implication(self, chisholm):
        assert chisholm.extension(Implies(GOES, TELLS)) == frozenset(
            {"go_tell", "stay_silent", "stay_tell"}
        )


class TestModelValidation:
    """System E's frame conditions, enforced at construction."""

    def test_from_ranking_produces_a_valid_model(self, chisholm):
        assert len(chisholm.worlds) == 4

    def test_non_total_betterness_is_rejected(self):
        with pytest.raises(PreferenceModelError, match="not total"):
            PreferenceModel(
                worlds=frozenset({"a", "b"}),
                betterness=frozenset({("a", "a"), ("b", "b")}),  # a and b incomparable
                valuation={"a": frozenset(), "b": frozenset()},
            )

    def test_non_reflexive_betterness_is_rejected(self):
        with pytest.raises(PreferenceModelError, match="not reflexive"):
            PreferenceModel(
                worlds=frozenset({"a"}),
                betterness=frozenset(),
                valuation={"a": frozenset()},
            )

    def test_non_transitive_betterness_is_rejected(self):
        with pytest.raises(PreferenceModelError, match="not transitive"):
            PreferenceModel(
                worlds=frozenset({"a", "b", "c"}),
                betterness=frozenset(
                    {("a", "a"), ("b", "b"), ("c", "c"), ("a", "b"), ("b", "c"), ("c", "a")}
                ),
            valuation={"a": frozenset(), "b": frozenset(), "c": frozenset()},
            )

    def test_a_world_in_two_tiers_is_rejected(self):
        with pytest.raises(PreferenceModelError, match="more than one tier"):
            PreferenceModel.from_ranking(
                tiers=[["a"], ["a"]], valuation={"a": {"p"}}
            )

    def test_missing_valuation_is_rejected(self):
        with pytest.raises(PreferenceModelError, match="no valuation"):
            PreferenceModel(
                worlds=frozenset({"a", "b"}),
                betterness=frozenset({("a", "a"), ("b", "b"), ("a", "b"), ("b", "a")}),
                valuation={"a": frozenset()},
            )

    def test_empty_model_is_rejected(self):
        with pytest.raises(PreferenceModelError, match="at least one world"):
            PreferenceModel.from_ranking(tiers=[], valuation={})

    def test_an_atom_no_world_assigns_is_rejected(self, chisholm):
        """A typo'd atom is false everywhere, which silently changes
        which worlds are optimal rather than erroring."""
        with pytest.raises(PreferenceModelError, match="no world assigns"):
            chisholm.obligation(Atom("tels"), Top())


class TestLimitedness:
    """Every satisfiable condition has a non-empty Opt on a finite total
    preorder — the axiom Åqvist needs in general is a theorem here."""

    def test_every_satisfiable_condition_has_optimal_worlds(self, chisholm):
        for condition in (Top(), GOES, Not(GOES), TELLS, Not(TELLS), Or(GOES, TELLS)):
            assert chisholm.optimal(condition), f"{condition} had no optimal worlds"

    def test_only_an_unsatisfiable_condition_has_none(self, chisholm):
        assert chisholm.optimal(And(GOES, Not(GOES))) == frozenset()
