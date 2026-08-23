"""Maps natural-language statutory qualifiers to quantifier types and parameter roles.

This is a small, honest, rule-based lookup — not a full NLU pipeline. Statutory
text is famously ambiguous ("reasonable", "substantially", "any person acting
in good faith"); resolving that ambiguity into a precise logical formula is a
legal-drafting judgment call, not something a keyword table can safely fully
automate. What this module *does* do reliably: map a small, well-defined set
of quantifier-signaling qualifier phrases onto EPR quantifier kinds, so the
rest of the pipeline (epr_compiler.py) can build a formula's exists/forall
prefix from clause metadata that a human reviewer (or a future, more capable
NLP stage) has already tagged.
"""

from __future__ import annotations

from enum import Enum


class QuantifierKind(str, Enum):
    EXISTS = "exists"
    FORALL = "forall"


_UNIVERSAL_QUALIFIERS = {
    "all",
    "any",
    "every",
    "each",
    "no",
    "none",
}

_EXISTENTIAL_QUALIFIERS = {
    "some",
    "a",
    "an",
    "there exists",
    "at least one",
    "certain",
}


def classify_qualifier(qualifier: str) -> QuantifierKind:
    """Classify a single statutory qualifier word/phrase as universal or existential.

    Raises ValueError for anything not in the known table rather than
    guessing — an unrecognized qualifier should be routed to a human
    reviewer, not silently defaulted.
    """
    normalized = qualifier.strip().lower()
    if normalized in _UNIVERSAL_QUALIFIERS:
        return QuantifierKind.FORALL
    if normalized in _EXISTENTIAL_QUALIFIERS:
        return QuantifierKind.EXISTS
    raise ValueError(
        f"Unrecognized statutory qualifier {qualifier!r}; add it to the "
        "known table only after confirming its quantifier semantics."
    )


def known_qualifiers() -> dict[str, QuantifierKind]:
    return {q: QuantifierKind.FORALL for q in _UNIVERSAL_QUALIFIERS} | {
        q: QuantifierKind.EXISTS for q in _EXISTENTIAL_QUALIFIERS
    }
