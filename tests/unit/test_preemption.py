"""Unit coverage for statutory conflict resolution.

The doctrinal ordering tests are the ones that matter: lex superior is
lexically first, so a *general federal* statute beats a *specific
municipal* one even though lex specialis alone would say the opposite;
and specialis is applied before posterior, so an earlier-but-narrower
statute beats a later general one. Both are cases where a plausible
misimplementation still passes every other test in this file.
"""

from __future__ import annotations

from datetime import UTC, datetime

from legal_engine.core.models import JurisdictionTier, SourceType, StatuteDocument
from legal_engine.knowledge_graph.graph_service import NetworkXGraphService
from legal_engine.knowledge_graph.preemption import (
    ResolutionPrinciple,
    resolve_preemption_for_entity,
)

ENTITY = "commercial-trucks"


def _statute(
    citation: str,
    applies_to: list[str],
    tier: JurisdictionTier = JurisdictionTier.MUNICIPAL,
    year: int | None = None,
) -> StatuteDocument:
    return StatuteDocument(
        source_type=SourceType.MUNICIPAL_CODE,
        jurisdiction_tier=tier,
        citation=citation,
        title=f"Ordinance {citation}",
        text="No person shall...",
        applies_to=applies_to,
        effective_date=datetime(year, 1, 1, tzinfo=UTC) if year is not None else None,
    )


def _resolve(*statutes: StatuteDocument, entity: str = ENTITY):
    graph = NetworkXGraphService()
    for statute in statutes:
        graph.add_statute(statute, applies_to=statute.applies_to)
    return resolve_preemption_for_entity(graph, entity)


class TestTrivialCases:
    def test_no_statutes_is_not_a_conflict(self):
        result = _resolve()
        assert result.governing is None
        assert result.requires_review is False
        assert result.resolved_by is None

    def test_a_single_statute_governs_by_default(self):
        only = _statute("Sec. 1", [ENTITY])
        result = _resolve(only)
        assert result.governing.citation == "Sec. 1"
        assert result.resolved_by is ResolutionPrinciple.SOLE_STATUTE
        assert result.preempted == []


class TestLexSuperior:
    def test_higher_authority_governs(self):
        federal = _statute("42 U.S.C. 1", [ENTITY], tier=JurisdictionTier.FEDERAL)
        municipal = _statute("Sec. 9", [ENTITY], tier=JurisdictionTier.MUNICIPAL)

        result = _resolve(federal, municipal)

        assert result.governing.citation == "42 U.S.C. 1"
        assert result.resolved_by is ResolutionPrinciple.LEX_SUPERIOR
        assert [s.citation for s in result.preempted] == ["Sec. 9"]

    def test_hierarchy_beats_specificity(self):
        """The ordering test. A federal statute covering a broad class
        outranks a municipal one written for exactly this entity —
        specialis never gets consulted, because superior already decided."""
        broad_federal = _statute(
            "42 U.S.C. 1", [ENTITY, "passenger-cars", "motorcycles"], tier=JurisdictionTier.FEDERAL
        )
        narrow_municipal = _statute("Sec. 9", [ENTITY], tier=JurisdictionTier.MUNICIPAL)

        result = _resolve(broad_federal, narrow_municipal)

        assert result.governing.citation == "42 U.S.C. 1"
        assert result.resolved_by is ResolutionPrinciple.LEX_SUPERIOR


class TestLexSpecialis:
    def test_narrower_scope_governs(self):
        narrow = _statute("Sec. 1", [ENTITY])
        broad = _statute("Sec. 2", [ENTITY, "passenger-cars", "motorcycles"])

        result = _resolve(narrow, broad)

        assert result.governing.citation == "Sec. 1"
        assert result.resolved_by is ResolutionPrinciple.LEX_SPECIALIS

    def test_order_of_registration_does_not_matter(self):
        narrow = _statute("Sec. 1", [ENTITY])
        broad = _statute("Sec. 2", [ENTITY, "passenger-cars"])

        assert _resolve(narrow, broad).governing.citation == "Sec. 1"
        assert _resolve(broad, narrow).governing.citation == "Sec. 1"

    def test_merely_overlapping_scopes_do_not_resolve(self):
        """Neither scope contains the other, so there is no specificity
        relation to apply — this is the under-decide-and-defer behaviour
        the applies_to proxy is documented to have."""
        left = _statute("Sec. 1", [ENTITY, "passenger-cars"])
        right = _statute("Sec. 2", [ENTITY, "motorcycles"])

        result = _resolve(left, right)

        assert result.requires_review is True
        assert result.governing is None
        assert result.resolved_by is None
        assert {s.citation for s in result.unresolved_candidates} == {"Sec. 1", "Sec. 2"}


class TestLexPosterior:
    def test_later_statute_governs_when_scopes_are_identical(self):
        older = _statute("Sec. 1", [ENTITY], year=2019)
        newer = _statute("Sec. 2", [ENTITY], year=2024)

        result = _resolve(older, newer)

        assert result.governing.citation == "Sec. 2"
        assert result.resolved_by is ResolutionPrinciple.LEX_POSTERIOR

    def test_identical_dates_do_not_resolve(self):
        left = _statute("Sec. 1", [ENTITY], year=2024)
        right = _statute("Sec. 2", [ENTITY], year=2024)

        assert _resolve(left, right).requires_review is True

    def test_a_missing_date_does_not_resolve(self):
        """An undated statute isn't "older" — it's unknown. Treating
        absence as an early date would invent a supersession."""
        dated = _statute("Sec. 1", [ENTITY], year=2024)
        undated = _statute("Sec. 2", [ENTITY], year=None)

        result = _resolve(dated, undated)

        assert result.requires_review is True
        assert result.resolved_by is None

    def test_both_undated_does_not_resolve(self):
        assert _resolve(
            _statute("Sec. 1", [ENTITY]), _statute("Sec. 2", [ENTITY])
        ).requires_review is True

    def test_a_later_statute_with_a_different_scope_does_not_supersede(self):
        """Lex posterior requires identical scopes. A newer statute about
        partly different subject matter sits alongside the old one rather
        than replacing it."""
        older = _statute("Sec. 1", [ENTITY, "passenger-cars"], year=2019)
        newer = _statute("Sec. 2", [ENTITY, "motorcycles"], year=2024)

        assert _resolve(older, newer).requires_review is True


class TestPrincipleOrdering:
    def test_specialis_beats_posterior(self):
        """lex posterior generalis non derogat legi priori speciali — a
        later general law does not derogate from an earlier special one.
        The naive "newest wins" implementation fails exactly here."""
        earlier_narrow = _statute("Sec. 1", [ENTITY], year=2019)
        later_broad = _statute("Sec. 2", [ENTITY, "passenger-cars"], year=2024)

        result = _resolve(earlier_narrow, later_broad)

        assert result.governing.citation == "Sec. 1"
        assert result.resolved_by is ResolutionPrinciple.LEX_SPECIALIS

    def test_specialis_is_reported_when_a_winner_uses_both(self):
        winner = _statute("Sec. 1", [ENTITY], year=2024)
        by_posterior = _statute("Sec. 2", [ENTITY], year=2019)
        by_specialis = _statute("Sec. 3", [ENTITY, "passenger-cars"], year=2030)

        result = _resolve(winner, by_posterior, by_specialis)

        assert result.governing.citation == "Sec. 1"
        assert result.resolved_by is ResolutionPrinciple.LEX_SPECIALIS


class TestMultipleCandidates:
    def test_a_specificity_chain_resolves_to_the_narrowest(self):
        narrowest = _statute("Sec. 1", [ENTITY])
        middle = _statute("Sec. 2", [ENTITY, "passenger-cars"])
        broadest = _statute("Sec. 3", [ENTITY, "passenger-cars", "motorcycles"])

        result = _resolve(broadest, middle, narrowest)

        assert result.governing.citation == "Sec. 1"
        assert result.resolved_by is ResolutionPrinciple.LEX_SPECIALIS
        assert {s.citation for s in result.preempted} == {"Sec. 2", "Sec. 3"}

    def test_an_undefeated_rival_blocks_resolution(self):
        """The bug this guards. 'Sec. 1' defeats 'Sec. 3' by specialis, so
        a naive implementation reports Sec. 1 as the winner — but 'Sec. 2'
        is comparable to neither of them (its scope is a subset of neither
        and a superset of neither), so it survives too. Two undefeated
        candidates means the conflict is open, and picking the one that
        happened to beat a *different* rival would silently resolve it.

        Note the scopes have to be built carefully to get this: an earlier
        draft of this test used {trucks} vs {trucks, motorcycles}, which is
        a strict subset, so Sec. 1 legitimately defeated it."""
        narrow = _statute("Sec. 1", [ENTITY, "trailers"])
        incomparable = _statute("Sec. 2", [ENTITY, "motorcycles"])
        broad = _statute("Sec. 3", [ENTITY, "trailers", "passenger-cars"])

        result = _resolve(narrow, incomparable, broad)

        assert result.requires_review is True
        assert result.governing is None
        assert {s.citation for s in result.unresolved_candidates} == {"Sec. 1", "Sec. 2", "Sec. 3"}

    def test_three_way_tie_requires_review(self):
        result = _resolve(
            _statute("Sec. 1", [ENTITY], year=2024),
            _statute("Sec. 2", [ENTITY], year=2024),
            _statute("Sec. 3", [ENTITY], year=2024),
        )
        assert result.requires_review is True

    def test_lower_tier_statutes_are_preempted_not_treated_as_rivals(self):
        """Tier filtering happens first, so a municipal statute never
        blocks a conflict between two federal ones."""
        federal_narrow = _statute("42 U.S.C. 1", [ENTITY], tier=JurisdictionTier.FEDERAL)
        federal_broad = _statute(
            "42 U.S.C. 2", [ENTITY, "passenger-cars"], tier=JurisdictionTier.FEDERAL
        )
        municipal = _statute("Sec. 9", [ENTITY], tier=JurisdictionTier.MUNICIPAL)

        result = _resolve(federal_narrow, federal_broad, municipal)

        assert result.governing.citation == "42 U.S.C. 1"
        assert result.resolved_by is ResolutionPrinciple.LEX_SPECIALIS
        assert {s.citation for s in result.preempted} == {"42 U.S.C. 2", "Sec. 9"}


class TestReviewResults:
    def test_unresolved_candidates_are_not_reported_as_preempted(self):
        """Nothing preempted them — the question is open. Reporting them
        as preempted would claim a resolution that didn't happen."""
        result = _resolve(
            _statute("Sec. 1", [ENTITY, "passenger-cars"]),
            _statute("Sec. 2", [ENTITY, "motorcycles"]),
        )

        assert result.preempted == []
        assert len(result.unresolved_candidates) == 2

    def test_resolved_results_carry_no_unresolved_candidates(self):
        result = _resolve(_statute("Sec. 1", [ENTITY]), _statute("Sec. 2", [ENTITY, "cars"]))
        assert result.unresolved_candidates == []

    def test_conflicting_tier_is_reported_on_review(self):
        result = _resolve(
            _statute("Sec. 1", [ENTITY, "a"], tier=JurisdictionTier.STATE),
            _statute("Sec. 2", [ENTITY, "b"], tier=JurisdictionTier.STATE),
        )
        assert result.conflicting_tier is JurisdictionTier.STATE
