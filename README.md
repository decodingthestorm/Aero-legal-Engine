# Legal Engine Platform

A legal ingestion, formal verification, and game-theoretic statutory optimization platform.

v1.0.0 marks the completion of the 5-phase build plan below: every subsystem the original spec
called for exists and has a passing test suite. It does **not** mean "battle-tested production
system" — see [Known limitations](#known-limitations) for what that would still take.

## What's built

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
  `kind`, and returns both the `ProofResult` and the rendered SMT-LIB2 text), `/simulation/penalty`
  and `/simulation/trembling-hand`, `/refactoring/detect-loopholes`, `/graph/statutes` +
  `/graph/preemption/{entity_id}` + `/graph/search`, `/ingestion/jobs`, and `/auth/token`.
  Every route depends on the knowledge_graph Protocol interfaces rather than concrete classes;
  which concrete class each resolves to is decided by `knowledge_graph/factory.py`, itself driven
  by `core.config.settings` (`graph_backend`/`vector_backend`/`embedding_backend`) — swapping in
  Neo4j/Qdrant/sentence-transformers for production is a settings change, not a code change.
  Auth is a real (if deliberately simple — a dependency-free HS256 JWT implementation rather than
  pulling in PyJWT for a few dozen lines) bearer-token check, off by default via
  `settings.api_auth_enabled` so it doesn't get in the way of local development or most of the
  test suite. There's still no Postgres-backed persistence — this is an in-process demo gateway,
  not a hardened production one; see Known limitations.
- **`ui/`** — a Next.js (Pages Router, TypeScript, Tailwind) dashboard: `ProofInspector` (submit a
  clause, see the `ProofResult` and its SMT-LIB2 rendering), `SimulationCard` (deterrence-penalty
  calculator plus an SVG-rendered convex penalty curve), and `GraphViewer` (add a statute, resolve
  preemption for an entity, semantic search) — all talking to the real API via a typed client
  (`src/lib/api.ts`). Written without Node.js available in the build environment, so `npm install`,
  `next dev`, and a real browser session were all someone else's first run of it, not mine — and
  that run did surface one real bug (missing CORS support, since fixed) that no Python-side test
  could have caught. All three components have since been manually verified end-to-end in a
  browser against a live API: compiles clean, every panel renders, every request round-trips
  correctly. See Known limitations for what "manually verified once" doesn't cover.

Everything under `src/legal_engine/` (i.e. everything except `ui/`) has a passing unit and
integration test suite under `tests/`, including an end-to-end test
(`tests/integration/test_ingest_to_proof.py`) that ingests a mocked ordinance, ties it into the
knowledge graph, formally verifies a rule derived from it, records every step to the WAL, and
confirms the resulting chain both verifies and detects tampering.

Each optional "real backend" (Neo4j, Qdrant, sentence-transformers, Tesseract OCR) is behind a
lazy import and an install extra (e.g. `pip install -e ".[graph-neo4j,vector-qdrant,semantic,ocr]"`)
— the default, tested path never requires them, and selecting one without its extra installed
fails with a clear `pip install` message rather than a confusing stack trace (this held even when
one of those "optional" dependencies turned out to already be installed in a broken state — see
git history on `knowledge_graph/embeddings.py` for what that surfaced). `api` and `workers` are
deployment-role extras (a library-only user shouldn't need FastAPI or Celery pulled in) rather
than lazy-backend extras; CI installs both to cover their tests.

## Known limitations

Read this before treating any of the above as more finished than it is:

- **The UI has been manually verified once, not automatically.** It compiles cleanly and all
  three components (ProofInspector, SimulationCard, GraphViewer) have been exercised end-to-end
  in a real browser against a live API — but that was one manual pass through the happy paths,
  not a repeatable test suite. There's no Playwright/Cypress (or similar) browser test, no error-
  path coverage (what does the UI show if the API is down mid-request, or a request 400s?), and no
  regression protection against a future change breaking something that manual pass happened to
  check. CI's `ui` job (`npm install && npm run build`) still only proves it compiles, not that it
  behaves correctly — that's what the manual pass added, once, for the paths above.
- **No Postgres-backed persistence.** `core/config.py` has a `postgres_dsn` setting and
  `docker-compose.yml` runs a Postgres container, but nothing reads or writes to it — all state
  (the knowledge graph, the vector index) lives in the API process's memory and is lost on
  restart, unless you configure the Neo4j/Qdrant backends via `knowledge_graph/factory.py`.
- **Auth is deliberately minimal.** One hardcoded client_id/client_secret pair
  (`settings.api_client_id`/`api_client_secret`), no user/tenant model, no token revocation, no
  refresh tokens. Fine for a demo gateway; not what you'd want fronting anything real.
- **No load testing.** The original spec's Phase 5 called for it; building a real load-testing
  setup (Locust/k6 scenarios, target throughput numbers tied to the 480ms Z3 timeout budget) is
  meaningfully separate work that wasn't attempted here.
- **The "formal verification" and "game-theoretic guarantees" are real math, not legal advice.**
  The EPR compiler and Z3 solver pool genuinely check what you give them; whether a hand-authored
  clause correctly captures what a statute means is a legal-drafting judgment call this system
  doesn't make for you (see `formal_logic/disambiguator.py`'s docstring).

## Development

```bash
python -m venv .venv
.venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -e ".[dev,api,workers]"   # api/workers extras needed for the full test suite
pytest
```

For the UI (requires Node.js 20+; needs the API running separately, see above):

```bash
make ui-install
make ui-dev   # http://localhost:3000, expects the API at NEXT_PUBLIC_API_BASE_URL (default :8000)
```

## Phased build plan

1. **Core schemas, formal logic & game theory** — done.
2. **Hybrid knowledge graph & preemption resolver** — done.
3. **Ingestion subsystem & structured parsers (polite crawling)** — done.
4. **State ledger (WAL), Celery workers & FastAPI gateway** — done.
5. **Production infrastructure, Next.js UI & release** — done, with the caveats above.
