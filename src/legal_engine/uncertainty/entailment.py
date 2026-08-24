"""Textual-entailment scoring, behind a Protocol so semantic_entropy.py
doesn't care which backend answers "does A entail B."

Same Protocol-plus-always-available-default-plus-lazy-real-backend shape
as knowledge_graph/embeddings.py's ``Embedder`` (and core/key_signer.py,
core/email_sender.py) — and for the same reason: the real backend is a
multi-hundred-MB ML install this environment can't load, so the default
has to be something exact, offline, and instant enough that the whole
test suite runs against it.

``LexicalEntailmentModel`` is that default. It is deliberately *not*
presented as a semantic model: it measures token containment, so it
treats "the contract is void" and "the agreement is invalid" as
unrelated even though a human (and a real NLI model) would call them the
same answer. The direction that error runs in matters, and it runs the
safe way: under-clustering splits one semantic answer across several
clusters, which *raises* measured entropy, which makes the gate abstain
more often than a real NLI model would. A hallucination gate that errs
toward abstention is failing safe; one that errs toward passing is not.
Treat lexical clustering as a conservative floor, not as parity with
``CrossEncoderEntailmentModel``.

One property the lexical model does get exactly right, and which matters
more here than paraphrase sensitivity: negation. "The clause is
enforceable" and "the clause is not enforceable" differ by a token that
containment scoring sees, so they never collapse into one cluster. No
stopword filtering is applied anywhere below, specifically to preserve
that — dropping "not" as a stopword would silently merge an answer with
its own negation, which is the single worst failure this gate could have.
"""

from __future__ import annotations

import re
from typing import Protocol

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class EntailmentModel(Protocol):
    def entails(self, premise: str, hypothesis: str) -> float:
        """Probability in [0.0, 1.0] that ``premise`` entails
        ``hypothesis``. Directional: entails(a, b) and entails(b, a) are
        different questions, and semantic_entropy.py asks both."""
        ...


class LexicalEntailmentModel:
    """Deterministic, dependency-free entailment scoring by token
    containment: the fraction of the hypothesis's tokens that also appear
    in the premise. A premise containing every token of the hypothesis
    scores 1.0 ("the premise already says everything the hypothesis
    says"); one missing half of them scores 0.5.

    Bag-of-tokens, so word order is ignored — see this module's docstring
    for why that under-clustering bias is the safe direction. An empty
    hypothesis is vacuously entailed (1.0), matching the logical
    convention rather than dividing by zero."""

    def entails(self, premise: str, hypothesis: str) -> float:
        premise_tokens = set(_TOKEN_RE.findall(premise.lower()))
        hypothesis_tokens = set(_TOKEN_RE.findall(hypothesis.lower()))
        if not hypothesis_tokens:
            return 1.0
        overlap = len(hypothesis_tokens & premise_tokens)
        return overlap / len(hypothesis_tokens)


class CrossEncoderEntailmentModel:
    """Wraps a real NLI cross-encoder via sentence-transformers. Requires
    the `semantic` install extra; not exercised in this environment (the
    same honesty category as ``SentenceTransformerEmbedder``, and for the
    identical reason — torch's native extensions don't load here).

    ``entailment_label_index`` is configurable rather than hardcoded
    because the 3-way NLI output order is a property of the specific
    checkpoint, not a standard: ``cross-encoder/nli-deberta-v3-base``
    emits ``[contradiction, entailment, neutral]`` (hence the default of
    1), but other checkpoints reorder these. Pointing this at the wrong
    index would not raise — it would silently score contradiction as
    entailment, collapsing an answer and its negation into one cluster
    and driving measured entropy to zero. Verify the index against the
    checkpoint's own config before changing the model name.
    """

    def __init__(self, model_name: str, entailment_label_index: int = 1) -> None:
        try:
            from sentence_transformers import CrossEncoder
        except Exception as exc:
            # Broad, not just ImportError — sentence-transformers pulls in
            # torch, whose native extensions fail to load for reasons that
            # surface as OSError or an internal ImportError rather than
            # "no module named X" (a Windows Application Control policy
            # blocking a DLL, a CUDA/driver mismatch). The actionable
            # message is the same either way, so it's normalized here,
            # exactly as knowledge_graph/embeddings.py does.
            raise ImportError(
                "CrossEncoderEntailmentModel requires a working sentence-transformers "
                f"install: pip install 'legal-engine[semantic]' (underlying error: "
                f"{exc.__class__.__name__}: {exc})"
            ) from exc
        self._model = CrossEncoder(model_name)
        self._entailment_label_index = entailment_label_index

    def entails(self, premise: str, hypothesis: str) -> float:
        scores = self._model.predict([(premise, hypothesis)], apply_softmax=True)
        return float(scores[0][self._entailment_label_index])
