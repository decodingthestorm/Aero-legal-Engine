"""The 0 <= H_sem <= log(N) bound, established over arbitrary partitions
rather than the handful of cluster shapes the unit tests enumerate.

This is the property SemanticEntropyGate's construction-time threshold
check depends on: if entropy could exceed log(N), rejecting thresholds at
or above log(N) would be wrong. Worth proving generatively, since the
whole defect being corrected here was someone assuming a ceiling three
times higher than the real one.
"""

from __future__ import annotations

import math

from hypothesis import given
from hypothesis import strategies as st

from legal_engine.uncertainty.entailment import LexicalEntailmentModel
from legal_engine.uncertainty.semantic_entropy import (
    cluster_by_bidirectional_entailment,
    max_entropy,
    semantic_entropy,
)

# A partition of N samples, described by its cluster sizes.
_cluster_sizes = st.lists(st.integers(min_value=1, max_value=20), min_size=1, max_size=20)
_generations = st.lists(
    st.from_regex(r"[a-z]{1,12}( [a-z]{1,12}){0,4}", fullmatch=True), min_size=1, max_size=12
)


@given(sizes=_cluster_sizes)
def test_entropy_never_exceeds_log_n(sizes):
    clusters = [["x"] * size for size in sizes]
    n_samples = sum(sizes)
    assert semantic_entropy(clusters, n_samples) <= max_entropy(n_samples) + 1e-9


@given(sizes=_cluster_sizes)
def test_entropy_is_never_negative(sizes):
    clusters = [["x"] * size for size in sizes]
    assert semantic_entropy(clusters, sum(sizes)) >= 0.0


@given(sizes=_cluster_sizes)
def test_single_cluster_is_the_only_zero_entropy_partition(sizes):
    clusters = [["x"] * size for size in sizes]
    entropy = semantic_entropy(clusters, sum(sizes))
    if len(clusters) == 1:
        assert entropy == 0.0
    else:
        assert entropy > 0.0


@given(n=st.integers(min_value=1, max_value=500))
def test_all_singletons_attains_the_bound_exactly(n):
    """The ceiling is tight, not merely an upper bound — which is what
    makes rejecting a threshold at log(N) correct rather than overly
    strict."""
    clusters = [["x"] for _ in range(n)]
    assert math.isclose(semantic_entropy(clusters, n), max_entropy(n), abs_tol=1e-12)


@given(generations=_generations)
def test_clustering_always_partitions_its_input(generations):
    """Every generation appears exactly once across the returned
    clusters, whatever the entailment model says about any pair — the
    guarantee that makes the cluster sizes a valid probability
    distribution to take entropy over."""
    clusters = cluster_by_bidirectional_entailment(generations, LexicalEntailmentModel(), 0.9)
    flattened = [g for cluster in clusters for g in cluster]
    assert sorted(flattened) == sorted(generations)


@given(generations=_generations)
def test_entropy_of_a_real_clustering_respects_the_bound(generations):
    clusters = cluster_by_bidirectional_entailment(generations, LexicalEntailmentModel(), 0.9)
    n = len(generations)
    assert 0.0 <= semantic_entropy(clusters, n) <= max_entropy(n) + 1e-9
