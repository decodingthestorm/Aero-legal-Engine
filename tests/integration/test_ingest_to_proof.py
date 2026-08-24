"""End-to-end: fetch and parse a municipal ordinance, tie it into the
knowledge graph, compile and formally verify a rule derived from it, and
record every step in the cryptographic WAL — then verify the whole chain.

This is the seam Phase 4 was actually meant to prove out: ingestion,
knowledge_graph, formal_logic, and core.wal all wired together, not each
tested in isolation (which the unit suites already do).
"""

from __future__ import annotations

import httpx
import pytest

from legal_engine.core.exceptions import WALIntegrityError
from legal_engine.core.models import SourceType
from legal_engine.core.wal import WriteAheadLog, generate_signing_key
from legal_engine.formal_logic.ast_nodes import And, Atom, Constant, Implies, Not, Variable
from legal_engine.formal_logic.epr_compiler import compile_epr_formula
from legal_engine.formal_logic.solver_pool import SolverPool
from legal_engine.ingestion.crawler_manager import IngestionJob, run_ingestion_jobs
from legal_engine.ingestion.rate_limiter import PoliteFetcher
from legal_engine.knowledge_graph.graph_service import NetworkXGraphService

pytestmark = pytest.mark.asyncio

_ORDINANCE_HTML = """
<article class="ordinance" data-citation="Sec. 12.04.030" data-title="STR Permits">
  <div class="ordinance-text">No person shall operate a short-term rental without a permit.</div>
</article>
"""


async def test_ingest_verify_and_record_to_wal():
    wal = WriteAheadLog(generate_signing_key())

    # 1. Ingest: fetch (mocked network) and parse the ordinance.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_ORDINANCE_HTML)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = PoliteFetcher(client=client, min_delay_seconds=0, respect_robots_txt=False)

    job = IngestionJob(url="https://example.gov/code/12.04.030", source_type=SourceType.MUNICIPAL_CODE)
    [statute] = await run_ingestion_jobs([job], fetcher)
    await fetcher.aclose()

    wal.append("statute_ingested", {"citation": statute.citation, "source_url": statute.source_url})

    # 2. Tie the statute into the knowledge graph, bound to a regulated entity.
    graph = NetworkXGraphService()
    entity_id = "short_term_rental_operators"
    graph.add_statute(statute, applies_to=[entity_id])
    assert [s.citation for s in graph.statutes_for_entity(entity_id)] == [statute.citation]

    # 3. Compile a formal rule derived from the ordinance's text
    #    ("no person shall operate without a permit") and verify it's
    #    internally consistent, then verify a violating scenario is UNSAT.
    consistent_formula = compile_epr_formula(
        exists_vars=(),
        forall_vars=("x",),
        matrix=Implies(
            Atom("Operates", (Variable("x"),)),
            Atom("HasPermit", (Variable("x"),)),
        ),
        domain=("landlord_a", "landlord_b"),
    )
    solver_pool = SolverPool(pool_size=1, timeout_ms=5000, memory_limit_mb=512)
    consistent_result = solver_pool.check(consistent_formula)
    assert consistent_result.satisfiable is True

    wal.append(
        "clause_verified",
        {"citation": statute.citation, "satisfiable": consistent_result.satisfiable},
    )

    violation_formula = compile_epr_formula(
        exists_vars=(),
        forall_vars=("x",),
        matrix=And(
            (
                Implies(Atom("Operates", (Variable("x"),)), Atom("HasPermit", (Variable("x"),))),
                Atom("Operates", (Constant("landlord_a"),)),
                Not(Atom("HasPermit", (Constant("landlord_a"),))),
            )
        ),
        domain=("landlord_a", "landlord_b"),
    )
    violation_result = solver_pool.check(violation_formula)
    assert violation_result.satisfiable is False  # an unpermitted operator directly contradicts the rule

    wal.append(
        "clause_verified",
        {"citation": statute.citation, "satisfiable": violation_result.satisfiable},
    )

    # 4. The WAL should now hold a tamper-evident record of every step.
    entries = wal.entries()
    assert [e.event_type for e in entries] == ["statute_ingested", "clause_verified", "clause_verified"]
    wal.verify()  # raises WALIntegrityError on any break — should not raise here

    # And tampering with any recorded step should be caught.
    entries[0].payload["citation"] = "forged citation"
    with pytest.raises(WALIntegrityError, match="payload_hash"):
        wal.verify()
