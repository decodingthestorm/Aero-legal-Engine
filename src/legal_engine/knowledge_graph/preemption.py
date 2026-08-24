"""Statutory conflict resolution: which of several statutes governs an
entity, and by which principle.

Three maxims, applied in lexical order. Each one only sees the conflicts
the ones before it could not decide:

1. **Lex superior** — higher authority wins. The statute at the
   numerically lowest ``JurisdictionTier`` (core/models.py — treaty=0,
   federal=1, state=2, county=3, municipal=4) governs. This is Article VI
   and it is *first*, so a general federal statute beats a specific
   municipal one even though lex specialis alone would say otherwise.
2. **Lex specialis** — the narrower rule wins. A statute's scope is the
   set of entities it is linked to in the graph, so A defeats B when
   ``scope(A)`` is a strict subset of ``scope(B)``.
3. **Lex posterior** — the later rule wins, *only where the scopes are
   identical*. That restriction is the doctrine, not a simplification: a
   later statute governing different subject matter doesn't supersede an
   earlier one, it sits alongside it.

Specialis before posterior follows *lex posterior generalis non derogat
legi priori speciali* — a later general law does not derogate from an
earlier special law. That is a jurisprudential choice with real backing
rather than a mathematical necessity, and reordering these two would be a
defensible (if different) reading.

The handoff between 2 and 3 falls out of the scope relation rather than
needing a rule of its own: if one scope is strictly narrower, specialis
decides; if the scopes are equal, specialis is silent (neither is
narrower) and posterior decides; if the scopes merely overlap, both are
silent and the conflict stays unresolved.

## What the specificity proxy can and cannot see

Scope is approximated by the entity ids a statute is linked to in the
graph (``GraphService.entities_for_statute``, *not* the ``applies_to``
field on the document — see ``_scopes`` for why those can differ). That
makes lex specialis computable from data already present, and it is
*sound*: a strict subset really is a narrower scope of application.

It is not *complete*. Two statutes can both apply to
``{commercial-trucks}`` while one governs, by its text, only those
carrying hazardous materials. Nothing in the entity model represents
that, so this reports "no specificity relation" where a lawyer sees an
obvious one. The error runs in the safe direction — it under-decides and
falls through to human review rather than confidently picking a winner —
which is the right bias for something whose job is to surface conflicts,
but it does mean an unresolved result is weak evidence that no
specificity relation exists.

``PreemptionResult.resolved_by`` exists for the same reason: a result
that says "X governs" without saying *why* isn't auditable, and a
resolution resting on this proxy deserves less weight than one resting on
Article VI.

## What this module still doesn't do

It resolves *which statute wins* once a candidate conflict set is known.
Deciding whether statutes tied to the same entity actually textually
contradict each other is out of scope — that's a job for formal_logic/
(verify both statutes' compiled clauses are jointly UNSAT) or for
vector_service.py similarity search to surface as a candidate. Grouping
by "applies to the same entity" is a coarse, sound filter: statutes that
don't share a subject can't conflict, but sharing a subject doesn't by
itself prove they do.

Nothing here reaches into deontic/. A lex specialis exception is
structurally a default refined by an exception, which is what System E
models — but that is a resemblance between layers, not a dependency.
This module decides which statute governs; deontic/ decides what is
obligatory given a condition. Wiring them together would couple two
independent modules with no caller needing the result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import UUID

from legal_engine.core.models import JurisdictionTier, StatuteDocument
from legal_engine.knowledge_graph.graph_service import GraphService


class ResolutionPrinciple(str, Enum):
    """Which maxim decided a conflict. Carried on every resolved result so
    a caller can weigh the answer — an Article VI resolution is a fact
    about the hierarchy, while a lex specialis one rests on the
    ``applies_to`` proxy described in this module's docstring."""

    SOLE_STATUTE = "sole_statute"
    LEX_SUPERIOR = "lex_superior"
    LEX_SPECIALIS = "lex_specialis"
    LEX_POSTERIOR = "lex_posterior"


@dataclass
class PreemptionResult:
    """``unresolved_candidates`` holds the statutes that survived every
    principle without one winning. They are deliberately *not* reported as
    ``preempted`` — nothing preempted them; the question is open. Before
    this field existed the review branch discarded them entirely, which
    left a reviewer knowing a conflict existed but not among what."""

    entity_id: str
    governing: StatuteDocument | None
    preempted: list[StatuteDocument]
    requires_review: bool
    conflicting_tier: JurisdictionTier | None = None
    resolved_by: ResolutionPrinciple | None = None
    unresolved_candidates: list[StatuteDocument] = field(default_factory=list)


Scopes = dict[UUID, frozenset[str]]


def _scopes(graph: GraphService, statutes: list[StatuteDocument]) -> Scopes:
    """Scope comes from the *graph*, not from ``StatuteDocument.applies_to``.

    ``GraphService.add_statute`` takes ``applies_to`` as a separate
    argument and never reconciles it with the field on the document, so
    the two can legitimately disagree — and the candidate set here was
    produced by ``statutes_for_entity``, which walks the edges. Measuring
    specificity against the field while selecting candidates by the edges
    would compare two different relations. The failure mode is quiet:
    documents whose field is empty all look equal-scoped, so every
    conflict would collapse to lex posterior or to review.
    """
    return {statute.id: frozenset(graph.entities_for_statute(statute.id)) for statute in statutes}


def _defeats(
    left: StatuteDocument, right: StatuteDocument, scopes: Scopes
) -> ResolutionPrinciple | None:
    """Whether ``left`` beats ``right`` by specialis or posterior, and by
    which. Returns None when neither applies — the two are incomparable.

    This is a strict partial order, which is what makes the undefeated-set
    computation below well defined: strict subset is irreflexive and
    transitive, and the date comparison only ever operates inside a class
    of equal-scope statutes, so no cycle can form across the two rules.
    """
    left_scope, right_scope = scopes[left.id], scopes[right.id]

    if left_scope < right_scope:
        return ResolutionPrinciple.LEX_SPECIALIS

    # Lex posterior needs both dates to compare. An undated statute isn't
    # "older" — it's unknown, and guessing would silently invent a
    # supersession that may not exist.
    if (
        left_scope == right_scope
        and left.effective_date is not None
        and right.effective_date is not None
        and left.effective_date > right.effective_date
    ):
        return ResolutionPrinciple.LEX_POSTERIOR

    return None


def _resolve_same_tier(
    candidates: list[StatuteDocument], scopes: Scopes
) -> tuple[StatuteDocument | None, ResolutionPrinciple | None]:
    """Applies specialis then posterior to statutes that tied on tier.

    Works by finding the candidates that nothing else defeats. Exactly one
    survivor means the conflict is resolved; more than one means the
    survivors are mutually incomparable (overlapping scopes, or equal
    scopes with equal or missing dates) and a human has to look.
    """
    def rivals(statute: StatuteDocument) -> list[StatuteDocument]:
        return [other for other in candidates if other.id != statute.id]

    # "Undefeated" is about surviving, not about winning. A statute whose
    # scope merely overlaps every rival defeats nothing and is defeated by
    # nothing — it is still a live candidate, and treating "defeats
    # something" as the test would drop it and hand the conflict to
    # whichever statute happened to beat a *different* rival.
    undefeated = [
        candidate
        for candidate in candidates
        if all(_defeats(other, candidate, scopes) is None for other in rivals(candidate))
    ]

    if len(undefeated) != 1:
        return None, None

    winner = undefeated[0]
    principles = {_defeats(winner, other, scopes) for other in rivals(winner)}

    # Specialis is reported in preference to posterior when the winner
    # beats different rivals by different maxims — it's the stronger claim
    # and the one applied first.
    if ResolutionPrinciple.LEX_SPECIALIS in principles:
        return winner, ResolutionPrinciple.LEX_SPECIALIS
    if ResolutionPrinciple.LEX_POSTERIOR in principles:
        return winner, ResolutionPrinciple.LEX_POSTERIOR

    # A unique survivor that defeated nothing shouldn't be reachable — the
    # rivals would have been undefeated too. Fall through to review rather
    # than report a resolution with no principle behind it.
    return None, None


def resolve_preemption_for_entity(graph: GraphService, entity_id: str) -> PreemptionResult:
    statutes = graph.statutes_for_entity(entity_id)

    if not statutes:
        return PreemptionResult(
            entity_id=entity_id, governing=None, preempted=[], requires_review=False
        )

    if len(statutes) == 1:
        return PreemptionResult(
            entity_id=entity_id,
            governing=statutes[0],
            preempted=[],
            requires_review=False,
            resolved_by=ResolutionPrinciple.SOLE_STATUTE,
        )

    min_tier = min(s.jurisdiction_tier for s in statutes)
    candidates = [s for s in statutes if s.jurisdiction_tier == min_tier]

    if len(candidates) == 1:
        governing: StatuteDocument | None = candidates[0]
        principle: ResolutionPrinciple | None = ResolutionPrinciple.LEX_SUPERIOR
    else:
        governing, principle = _resolve_same_tier(candidates, _scopes(graph, candidates))

    if governing is None:
        return PreemptionResult(
            entity_id=entity_id,
            governing=None,
            preempted=[],
            requires_review=True,
            conflicting_tier=min_tier,
            unresolved_candidates=candidates,
        )

    preempted = [s for s in statutes if s.id != governing.id]
    for subordinate in preempted:
        graph.add_preemption_edge(governing.id, subordinate.id)

    return PreemptionResult(
        entity_id=entity_id,
        governing=governing,
        preempted=preempted,
        requires_review=False,
        resolved_by=principle,
    )


def resolve_all(graph: GraphService) -> list[PreemptionResult]:
    return [resolve_preemption_for_entity(graph, entity_id) for entity_id in graph.all_entity_ids()]


def truncate_preempted_text(statute: StatuteDocument, reason: str = "preempted") -> StatuteDocument:
    """Return a copy of `statute` with its operative text truncated, marking
    it preempted so it doesn't reach formal_logic/ verification as if it
    were still live law. The original document is left untouched — this is
    a view for downstream consumers, not a mutation of ingested history."""
    return statute.model_copy(update={"text": f"[{reason.upper()}] {statute.citation} superseded."})
