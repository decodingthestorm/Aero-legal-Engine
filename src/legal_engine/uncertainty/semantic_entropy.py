"""Semantic entropy over bidirectional-entailment clusters, as an
abstention gate for stochastic model output.

The idea (Kuhn et al.; Farquhar et al., Nature 2024): sample the same
question N times, group the samples into *meaning* classes rather than
string classes, and measure the Shannon entropy of the distribution over
those classes. One meaning repeated N times is entropy 0 — the model is
consistent. N mutually incompatible meanings is maximum entropy — the
model is confabulating, and the honest response is to abstain rather
than to return whichever sample happened to come first.

## The bound that makes this gate work at all

Entropy here is computed over a partition of exactly N samples, so it is
bounded above by log(N), attained only when every sample lands in its own
cluster:

    H_sem = -sum_c p(c) log p(c),  p(c) = |c| / N   =>   0 <= H_sem <= log(N)

For the usual N=10 that ceiling is log(10) = 2.3026 nats (3.3219 bits).
Any threshold at or above the ceiling makes the gate unreachable — it can
never fire, and the abstention path it guards becomes dead code that
still looks present in a design document. That failure is silent: nothing
raises, nothing logs, every input "passes."

``SemanticEntropyGate`` therefore validates its threshold against
``max_entropy(n_samples)`` at *construction* and refuses to build an
unfireable gate. This is the one invariant in this module worth
protecting structurally rather than by convention, because a threshold
that looks plausible in prose (8.5) can be off by more than a factor of
three from a bound nobody re-derives when reading it.

Units are nats (natural log), not bits, throughout — stated explicitly
because "log" alone leaves a factor of ln(2) of ambiguity, and a
threshold ported between the two conventions without conversion is the
same class of silent miscalibration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from legal_engine.uncertainty.entailment import EntailmentModel


def max_entropy(n_samples: int) -> float:
    """Tight upper bound on semantic entropy for ``n_samples``
    generations, in nats. Attained exactly when every generation forms
    its own singleton cluster."""
    if n_samples <= 0:
        raise ValueError(f"n_samples must be positive, got {n_samples}")
    return math.log(n_samples)


def cluster_by_bidirectional_entailment(
    generations: list[str], model: EntailmentModel, entailment_threshold: float
) -> list[list[str]]:
    """Partitions ``generations`` into meaning classes: two texts share a
    cluster when each entails the other at or above
    ``entailment_threshold``.

    Greedy first-match against each existing cluster's *representative*
    (its first member), not a transitive closure over all pairs. That's
    deliberate and matches how the semantic-entropy literature does it:
    bidirectional entailment is not empirically transitive, so a closure
    over pairwise judgements can chain a to b to c while a and c are
    plainly different answers, silently merging distinct meanings and
    under-reporting entropy. Comparing against a fixed representative
    keeps every cluster anchored to one concrete text and guarantees a
    well-defined partition no matter how inconsistent the model's pairwise
    judgements are.

    Order-dependent by construction (the representative is whichever
    member arrived first). That is a real property of the algorithm, not
    a bug to paper over — generations arrive in sampling order and the
    partition is reported alongside the score for inspection.
    """
    clusters: list[list[str]] = []
    for generation in generations:
        for cluster in clusters:
            representative = cluster[0]
            forward = model.entails(representative, generation)
            backward = model.entails(generation, representative)
            if forward >= entailment_threshold and backward >= entailment_threshold:
                cluster.append(generation)
                break
        else:
            clusters.append([generation])
    return clusters


def semantic_entropy(clusters: list[list[str]], n_samples: int) -> float:
    """Shannon entropy in nats over the empirical cluster distribution
    p(c) = |c| / n_samples."""
    if n_samples <= 0:
        raise ValueError(f"n_samples must be positive, got {n_samples}")
    entropy = 0.0
    for cluster in clusters:
        probability = len(cluster) / n_samples
        if probability > 0.0:
            entropy -= probability * math.log(probability)
    return entropy


@dataclass(frozen=True)
class SemanticEntropyResult:
    """``max_possible_entropy`` travels with every result on purpose: a
    bare score of 1.4 means nothing without the ceiling it's measured
    against, and carrying the bound alongside the score is what makes a
    logged or dashboarded result interpretable later without re-deriving
    log(N)."""

    entropy: float
    max_possible_entropy: float
    threshold: float
    clusters: tuple[tuple[str, ...], ...]
    triage_pass: bool


class SemanticEntropyGate:
    """Refuses to be constructed with a threshold it could never fire on
    — see this module's docstring for why that's enforced here rather
    than left to whoever writes the config."""

    def __init__(
        self,
        model: EntailmentModel,
        n_samples: int,
        entropy_threshold: float,
        entailment_threshold: float = 0.9,
    ) -> None:
        ceiling = max_entropy(n_samples)
        if not 0.0 <= entropy_threshold < ceiling:
            raise ValueError(
                f"entropy_threshold={entropy_threshold} cannot fire for n_samples={n_samples}: "
                f"semantic entropy over {n_samples} generations is bounded by "
                f"log({n_samples}) = {ceiling:.4f} nats, so the gate would pass every input "
                f"and its abstention path would be unreachable. "
                f"Choose a threshold in [0.0, {ceiling:.4f})."
            )
        if not 0.0 <= entailment_threshold <= 1.0:
            raise ValueError(
                f"entailment_threshold must be a probability in [0.0, 1.0], "
                f"got {entailment_threshold}"
            )
        self._model = model
        self._n_samples = n_samples
        self._entropy_threshold = entropy_threshold
        self._entailment_threshold = entailment_threshold

    @property
    def max_possible_entropy(self) -> float:
        return max_entropy(self._n_samples)

    def evaluate(self, generations: list[str]) -> SemanticEntropyResult:
        """Requires exactly ``n_samples`` generations. Accepting fewer
        would lower the ceiling (log of the actual count) without
        re-checking the threshold against it, which is precisely how an
        unfireable gate would get back in through the side door after
        __init__ ruled it out the front."""
        if len(generations) != self._n_samples:
            raise ValueError(
                f"expected exactly {self._n_samples} generations "
                f"(the count this gate's threshold was validated against), "
                f"got {len(generations)}"
            )
        clusters = cluster_by_bidirectional_entailment(
            generations, self._model, self._entailment_threshold
        )
        entropy = semantic_entropy(clusters, self._n_samples)
        return SemanticEntropyResult(
            entropy=entropy,
            max_possible_entropy=self.max_possible_entropy,
            threshold=self._entropy_threshold,
            clusters=tuple(tuple(cluster) for cluster in clusters),
            triage_pass=entropy <= self._entropy_threshold,
        )
