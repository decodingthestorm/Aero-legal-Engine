# Legal Engine Platform

A legal ingestion, formal verification, and game-theoretic statutory optimization platform.

## What's built so far (Phases 1-4)

- **`core/`** — shared Pydantic v2 models (statutes, jurisdiction tiers, actors, payoff
  matrices, proof results, WAL entries), settings, exceptions, structured logging.
- **`formal_logic/`** — compiles clauses into the decidable EPR (Bernays-Schoenfinkel-Ramsey)
  fragment, renders them as SMT-LIB2, and checks satisfiability via a bounded-concurrency Z3
  solver pool with timeout/memory limits.
- **`game_theory/`** — derives the minimum penalty that makes honest compliance a dominant
  strategy, strictly-convex penalty curves, Individual Rationality / Incentive Compatibility
  checks, and a numeric Trembling Hand Perfect Equilibrium check.
- **`refactoring/`** — builds statutory/tax dependency graphs, finds negative-weight loophole
  cycles (Tarjan SCC + Johnson simple-cycle enumeration), and solves the cycle-basis system
  `B @ w = 0` to zero them out with a minimum-norm correction.
- **`knowledge_graph/`** — a statute/entity graph (`GraphService`, NetworkX-backed by default,
  Neo4j-backed implementation included but untested here), text embeddings (`Embedder`,
  deterministic hashing-based by default, real all-MiniLM-L6-v2 wrapper included but not
  exercised here), a cosine-distance vector index (`VectorIndex`, in-memory by default,
  Qdrant-backed implementation included but untested here), and `preemption.py`, which resolves
  Article VI Supremacy Clause conflicts between statutes tied to the same entity.
- **`ingestion/`** — `rate_limiter.py`'s `PoliteFetcher` (robots.txt compliance, per-host rate
  limiting, exponential backoff honoring `Retry-After`) plus three structured parsers
  (`parsers/municipal.py` for ordinance HTML with embedded GIS boundaries,
  `parsers/federal.py` for Federal Register/CFR XML with delta diffing against previously-known
  statutes, `parsers/treaty.py` for multilingual treaty XML with choice-of-law and territorial
  boundary extraction) and `crawler_manager.py`, which dispatches fetched URLs to the parser
  matching their source type. `ocr.py` defines the scanned-PDF OCR interface with a real
  Tesseract-backed implementation, lazily imported and not exercised here (needs the Tesseract
  and poppler system binaries).

  **Deliberate deviation from the original spec**: this replaces the spec's TLS-fingerprint-
  impersonation `anti_blocking.py` with honest, well-behaved crawling — a truthful User-Agent,
  robots.txt compliance, conservative concurrency/delay, and standard retry/backoff — since
  there's no legitimate need for anti-detection tooling against public government statute
  sources.

  Each parser works against a documented, simplified subset of its real-world XML/HTML schema
  (e.g. eCFR/Federal Register XML is a much larger DTD than what's parsed here) rather than a
  scraper tuned to one specific publisher's current markup, which would break on the next
  redesign anyway.

- **`core/wal.py`** — `WriteAheadLog`: an append-only, SHA-384 hash-chained, Ed25519-signed
  audit log. `verify()` replays the whole chain and catches any tampering with a past entry's
  payload, its `prev_hash` link, or its signature. Unlike the knowledge_graph backends,
  `cryptography` is a hard dependency here, not a lazy-imported optional one — there's no
  meaningful lightweight version of "the audit log, but unsigned."
- **`workers/`** — a real Celery app (`celery_app.py`, Redis broker/backend, matching
  `docker/docker-compose.yml`) and two tasks (`crawl_and_parse`, `index_statute_embedding`).
  Both are fully tested via `.apply(...).get()`, which runs a task synchronously in-process with
  no broker involved — real distributed dispatch via `.delay()` needs a live Redis instance,
  which this environment doesn't have, but the task *logic* needs nothing infra-specific to test.
- **`api/`** — a working FastAPI gateway wiring every subsystem above into HTTP endpoints:
  `/verification/verify` (accepts a JSON mirror of the EPR formula AST, a discriminated union on
  `kind`), `/simulation/penalty` and `/simulation/trembling-hand`, `/refactoring/detect-loopholes`,
  `/graph/statutes` + `/graph/preemption/{entity_id}` + `/graph/search`, and `/ingestion/jobs`.
  Every route depends on the knowledge_graph Protocol interfaces rather than concrete classes, so
  swapping in the Neo4j/Qdrant/sentence-transformers backends for production is a one-line change
  in `main.py`'s `lifespan`, not a change to any route. There's no Postgres/JWT auth wired up yet
  — this is an in-process demo gateway, not a hardened production one.

Everything above has a passing unit and integration test suite under `tests/`, including an
end-to-end test (`tests/integration/test_ingest_to_proof.py`) that ingests a mocked ordinance,
ties it into the knowledge graph, formally verifies a rule derived from it, records every step to
the WAL, and confirms the resulting chain both verifies and detects tampering.

Each optional "real backend" (Neo4j, Qdrant, sentence-transformers, Tesseract OCR) is behind a
lazy import and an install extra (e.g. `pip install -e ".[graph-neo4j,vector-qdrant,semantic,ocr]"`)
— the default, tested path never requires them. `api` and `workers` are deployment-role extras
(a library-only user shouldn't need FastAPI or Celery pulled in) rather than lazy-backend extras;
CI installs both to cover their tests.

## Not yet implemented

`ui/` (Next.js dashboard) and the Kubernetes/CI release pipeline are scaffolded (directory
structure + stub components) but not built out yet — see the phased plan below. Also still
missing: real Postgres-backed persistence, JWT auth on the API, and a settings-driven factory for
swapping the in-memory knowledge_graph backends for their Neo4j/Qdrant/sentence-transformers
counterparts at deploy time (the classes exist; nothing wires them up yet based on environment).

## Development

```bash
python -m venv .venv
.venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -e ".[dev,api,workers]"   # api/workers extras needed for the full test suite
pytest
```

## Phased build plan

1. **Core schemas, formal logic & game theory** — done.
2. **Hybrid knowledge graph & preemption resolver** — done.
3. **Ingestion subsystem & structured parsers (polite crawling)** — done.
4. **State ledger (WAL), Celery workers & FastAPI gateway** — done.
5. Production infrastructure, Next.js UI & release.
