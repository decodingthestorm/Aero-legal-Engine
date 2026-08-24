"""Unit coverage for the semantic-entropy abstention gate.

The class of bug these tests exist to prevent is a threshold set above
log(N), which makes the gate pass every input and turns its abstention
path into unreachable code — silently, with nothing raising and nothing
logged. TestThresholdReachability is the direct guard; the property test
in tests/property/test_semantic_entropy_bounds.py establishes the bound
that guard relies on.
"""

from __future__ import annotations

import math

import pytest

from legal_engine.uncertainty.entailment import LexicalEntailmentModel
from legal_engine.uncertainty.semantic_entropy import (
    SemanticEntropyGate,
    cluster_by_bidirectional_entailment,
    max_entropy,
    semantic_entropy,
)


def _gate(n_samples: int = 10, entropy_threshold: float = 1.0, **kwargs) -> SemanticEntropyGate:
    return SemanticEntropyGate(
        model=LexicalEntailmentModel(),
        n_samples=n_samples,
        entropy_threshold=entropy_threshold,
        **kwargs,
    )


class TestMaxEntropy:
    def test_bound_is_log_n(self):
        assert max_entropy(10) == pytest.approx(math.log(10))
        assert max_entropy(10) == pytest.approx(2.302585, abs=1e-6)

    def test_single_sample_has_zero_bound(self):
        assert max_entropy(1) == 0.0

    @pytest.mark.parametrize("n", [0, -1])
    def test_non_positive_sample_count_is_rejected(self, n):
        with pytest.raises(ValueError, match="must be positive"):
            max_entropy(n)


class TestSemanticEntropyMath:
    def test_one_cluster_is_zero_entropy(self):
        assert semantic_entropy([["a"] * 10], 10) == pytest.approx(0.0)

    def test_all_singletons_hits_the_log_n_ceiling(self):
        clusters = [[str(i)] for i in range(10)]
        assert semantic_entropy(clusters, 10) == pytest.approx(math.log(10))

    def test_even_two_way_split_is_log_two(self):
        assert semantic_entropy([["a"] * 5, ["b"] * 5], 10) == pytest.approx(math.log(2))

    def test_known_three_way_split(self):
        """4/3/3 over N=10 — the case the default 1.0 threshold is chosen
        to fire on (see core/config.py)."""
        clusters = [["a"] * 4, ["b"] * 3, ["c"] * 3]
        assert semantic_entropy(clusters, 10) == pytest.approx(1.0889, abs=1e-4)

    def test_dominant_answer_with_outliers_stays_low(self):
        """8/1/1 over N=10 — deliberately below the default threshold: a
        clear majority answer with two strays is not confabulation."""
        clusters = [["a"] * 8, ["b"], ["c"]]
        assert semantic_entropy(clusters, 10) == pytest.approx(0.6390, abs=1e-4)


class TestClustering:
    def test_identical_generations_form_one_cluster(self):
        clusters = cluster_by_bidirectional_entailment(["same text"] * 5, LexicalEntailmentModel(), 0.9)
        assert len(clusters) == 1
        assert len(clusters[0]) == 5

    def test_unrelated_generations_stay_separate(self):
        generations = ["the contract is void", "penalties accrue quarterly", "jurisdiction is federal"]
        clusters = cluster_by_bidirectional_entailment(generations, LexicalEntailmentModel(), 0.9)
        assert len(clusters) == 3

    def test_a_statement_never_clusters_with_its_own_negation(self):
        """The single worst failure this gate could have: merging an
        answer with its negation drives entropy toward zero and reports
        confident agreement where the model actually contradicted itself.
        No stopword filtering anywhere in entailment.py exists to keep
        this true — see that module's docstring."""
        generations = ["the clause is enforceable", "the clause is not enforceable"]
        clusters = cluster_by_bidirectional_entailment(generations, LexicalEntailmentModel(), 0.9)
        assert len(clusters) == 2

    def test_every_generation_lands_in_exactly_one_cluster(self):
        generations = ["alpha", "beta", "alpha", "gamma", "beta"]
        clusters = cluster_by_bidirectional_entailment(generations, LexicalEntailmentModel(), 0.9)
        flattened = [g for cluster in clusters for g in cluster]
        assert sorted(flattened) == sorted(generations)

    def test_empty_input_yields_no_clusters(self):
        assert cluster_by_bidirectional_entailment([], LexicalEntailmentModel(), 0.9) == []


class TestThresholdReachability:
    """The defect this whole module was built to correct."""

    def test_the_specs_own_threshold_is_rejected(self):
        """H_sem over N=10 cannot exceed log(10) = 2.3026 nats, so a
        threshold of 8.5 could never fire. Constructing that gate must
        fail loudly rather than silently pass every input."""
        with pytest.raises(ValueError, match="cannot fire"):
            _gate(n_samples=10, entropy_threshold=8.5)

    def test_the_error_names_the_actual_ceiling(self):
        with pytest.raises(ValueError, match=r"2\.3026"):
            _gate(n_samples=10, entropy_threshold=8.5)

    def test_a_threshold_exactly_at_the_ceiling_is_rejected(self):
        """Firing requires entropy strictly greater than the threshold,
        so threshold == log(N) is unreachable too, not merely marginal."""
        with pytest.raises(ValueError, match="cannot fire"):
            _gate(n_samples=10, entropy_threshold=math.log(10))

    def test_a_threshold_just_below_the_ceiling_is_accepted(self):
        gate = _gate(n_samples=10, entropy_threshold=math.log(10) - 1e-9)
        assert gate.max_possible_entropy == pytest.approx(math.log(10))

    def test_zero_threshold_is_accepted_as_the_strictest_usable_gate(self):
        """Abstain unless every generation agrees — valid, and the
        tightest setting that can still pass something."""
        gate = _gate(entropy_threshold=0.0)
        assert gate.evaluate(["identical"] * 10).triage_pass is True

    def test_negative_threshold_is_rejected(self):
        with pytest.raises(ValueError, match="cannot fire"):
            _gate(entropy_threshold=-0.1)

    @pytest.mark.parametrize("bad", [-0.01, 1.01])
    def test_entailment_threshold_must_be_a_probability(self, bad):
        with pytest.raises(ValueError, match="probability"):
            _gate(entailment_threshold=bad)


class TestGateEvaluation:
    def test_consistent_generations_pass(self):
        result = _gate().evaluate(["the contract is void"] * 10)
        assert result.triage_pass is True
        assert result.entropy == pytest.approx(0.0)
        assert len(result.clusters) == 1

    def test_fully_divergent_generations_abstain(self):
        generations = [f"entirely distinct answer number {i}" for i in range(10)]
        result = _gate().evaluate(generations)
        assert result.triage_pass is False
        assert result.entropy == pytest.approx(math.log(10))

    def test_three_way_disagreement_abstains_at_the_default_threshold(self):
        generations = ["alpha"] * 4 + ["beta"] * 3 + ["gamma"] * 3
        result = _gate().evaluate(generations)
        assert len(result.clusters) == 3
        assert result.triage_pass is False

    def test_dominant_answer_with_two_outliers_passes(self):
        generations = ["alpha"] * 8 + ["beta"] + ["gamma"]
        result = _gate().evaluate(generations)
        assert result.triage_pass is True

    def test_result_carries_the_ceiling_and_threshold_for_interpretation(self):
        result = _gate().evaluate(["same"] * 10)
        assert result.max_possible_entropy == pytest.approx(math.log(10))
        assert result.threshold == 1.0

    def test_clusters_are_reported_for_inspection(self):
        result = _gate().evaluate(["alpha"] * 6 + ["beta"] * 4)
        assert {len(c) for c in result.clusters} == {6, 4}

    def test_wrong_generation_count_is_rejected(self):
        """Fewer generations lower the ceiling without re-validating the
        threshold against it — the side door back to an unfireable gate."""
        with pytest.raises(ValueError, match="expected exactly 10"):
            _gate().evaluate(["only one"])

    def test_entropy_never_exceeds_the_reported_ceiling(self):
        generations = [f"distinct {i}" for i in range(10)]
        result = _gate().evaluate(generations)
        assert result.entropy <= result.max_possible_entropy + 1e-12


class TestLexicalEntailmentModel:
    def test_identical_text_entails_itself_fully(self):
        model = LexicalEntailmentModel()
        assert model.entails("the contract is void", "the contract is void") == 1.0

    def test_superset_premise_fully_entails_subset_hypothesis(self):
        model = LexicalEntailmentModel()
        assert model.entails("the contract is clearly void", "the contract is void") == 1.0

    def test_partial_overlap_scores_between_zero_and_one(self):
        model = LexicalEntailmentModel()
        score = model.entails("the contract is void", "the contract is not void")
        assert 0.0 < score < 1.0

    def test_disjoint_text_scores_zero(self):
        model = LexicalEntailmentModel()
        assert model.entails("alpha beta", "gamma delta") == 0.0

    def test_empty_hypothesis_is_vacuously_entailed(self):
        model = LexicalEntailmentModel()
        assert model.entails("anything at all", "") == 1.0

    def test_scoring_is_case_insensitive(self):
        model = LexicalEntailmentModel()
        assert model.entails("The Contract Is Void", "the contract is void") == 1.0

    def test_is_directional(self):
        """entails(a, b) and entails(b, a) are different questions — the
        asymmetry is exactly what makes the *bidirectional* check in
        clustering meaningful rather than redundant."""
        model = LexicalEntailmentModel()
        forward = model.entails("the contract is clearly and unambiguously void", "the contract is void")
        backward = model.entails("the contract is void", "the contract is clearly and unambiguously void")
        assert forward == 1.0
        assert backward < 1.0
