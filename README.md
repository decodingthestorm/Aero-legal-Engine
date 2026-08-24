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
  test suite.
- **`persistence/`** — the durable, queryable system-of-record for ingested statutes, separate
  from the graph/vector *indexes* above (which are rebuildable from this). `StatuteRepository` is
  in-memory by default; `settings.statute_backend = "sql"` switches to `SqlAlchemyStatuteRepository`
  (`sql_repository.py`), which works against any SQLAlchemy-async DSN — `postgresql+asyncpg://` in
  production (`docker-compose.yml` runs Postgres; the `postgres` install extra pulls in
  `sqlalchemy`+`asyncpg`), `sqlite+aiosqlite://` in this codebase's own test suite, since there's no
  Postgres available to test against for real in the environment this was built in.
  `tests/integration/test_statute_persistence.py` proves durability through the real API lifespan
  (add a statute, tear the app down, bring a fresh instance up pointed at the same SQLite file, read
  it back), and `tests/integration/test_postgres_repository.py` runs the same repository against a
  genuine Postgres — skipped locally, but for real under CI's `postgres` job (a real
  `services: postgres:` container), the same "can't verify locally, so make CI do it for real"
  pattern the `ui` job uses for the dashboard.
- **`ui/`** — a Next.js (Pages Router, TypeScript, Tailwind) dashboard: `ProofInspector` (submit a
  clause, see the `ProofResult` and its SMT-LIB2 rendering), `SimulationCard` (deterrence-penalty
  calculator plus an SVG-rendered convex penalty curve), and `GraphViewer` (add a statute, resolve
  preemption for an entity, semantic search) — all talking to the real API via a typed client
  (`src/lib/api.ts`). Written without Node.js available in the build environment, so `npm install`,
  `next dev`, and a real browser session were all someone else's first run of it, not mine — and
  that run did surface one real bug (missing CORS support, since fixed) that no Python-side test
  could have caught.
- **`ui/e2e/`** — Playwright tests covering all three components against a real, live API: the
  happy paths (verify a satisfiable/unsatisfiable clause, compute a penalty and plot its curve, add
  a statute and resolve its preemption, semantic search) *and* the error paths that were missing
  before (`error-handling.spec.ts` — API unreachable, a request 500s, a request 400s — using route
  interception to simulate real failures without needing to control the live server's lifecycle
  mid-test). `playwright.config.ts` starts both the UI and the API itself (or reuses them if
  already running locally), so `npm run test:e2e` is one command. Written the same way as `ui/`
  itself — no Node.js available to run it while writing it — so it's unverified in the same sense;
  see Known limitations.

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

## Load testing

`load_tests/locustfile.py` (Locust — pure Python, no Docker/Node/binary tooling needed) drives a
realistic mix of traffic against a running API, weighted toward `/verification/verify` since it's
the one endpoint that routes through native code (the Z3 solver) rather than pure Python/NetworkX.

```bash
make run-api                                    # in one terminal
pip install -e ".[load-test]" && make load-test  # in another — opens the Locust web UI
```

or headless, e.g. 20 users ramping at 5/s for 45s:

```bash
locust -f load_tests/locustfile.py --host http://localhost:8000 --headless -u 20 -r 5 -t 45s
```

**Running this for the first time found a real, serious bug**: `formal_logic/solver_pool.py`
built every Z3 object on Z3's implicit default/global context, which Z3's own documentation says
plainly isn't safe to use concurrently across threads. It wasn't theoretical — 20 concurrent users
against the default `settings.z3_pool_size=4` reliably produced `z3.Z3Exception: 'not a valid ast'`
and outright native access-violation crashes that took the whole server process down within
seconds. Every existing unit test for `SolverPool` used `pool_size=1` (sequential), so nothing in
the test suite had ever exercised true concurrent Z3 use before something actually sent it
concurrent load. Fixed by giving every `check()` call its own `z3.Context()` — full isolation per
concurrent solve, which is what Z3's Python API guidance for multi-threaded use actually calls for
(see the module docstring for the detailed writeup, and
`tests/unit/test_solver_pool_concurrency.py` for the regression test: many concurrent `check()`
calls via a real thread pool, driven directly rather than through HTTP, so it doesn't need a
running server to catch a regression here again).

After the fix, the same 20-user / 45-second run against a live API: **1,901 requests, 0 failures**,
`/verification/verify` (the heaviest endpoint) at p50=10ms / p99=18ms / max=40ms — comfortably
inside the 480ms Z3 timeout budget (`settings.z3_timeout_ms`) even under concurrent load. This was
run once, on one machine, at a modest scale (20 concurrent users) — see Known limitations for what
that does and doesn't prove.

## Known limitations

Read this before treating any of the above as more finished than it is:

- **The UI has been manually verified once by a human; the Playwright suite that's meant to
  replace that has not been run by anyone yet.** `ui/e2e/` was written the same way the rest of the
  UI was — without Node.js available to run it — so while it's written carefully against real,
  known-working selectors (`data-testid` attributes added to the components specifically for this)
  and the actual API contracts, it has never actually executed. CI's new `e2e` job runs it for real
  on every push going forward, but as of this writing that hasn't happened yet either. Until one of
  those runs (CI's or a local `npm run test:e2e`) actually completes, "there's an automated browser
  test suite" is a claim about what was written, not about what's been proven to pass.
- **The graph/vector indexes still don't persist, even with `statute_backend = "sql"`.**
  `persistence/` gives you a durable record of every statute ingested — but `graph_backend` and
  `vector_backend` are separate settings that still default to in-memory, and switching them to
  Neo4j/Qdrant is what actually makes preemption resolution and semantic search survive a restart
  too. Nothing currently rebuilds the graph/vector indexes from the statute repository on startup
  if you mix a persistent statute backend with in-memory indexes — that gap (an explicit
  reindex-on-startup step) hasn't been closed.
- **Auth is deliberately minimal.** One hardcoded client_id/client_secret pair
  (`settings.api_client_id`/`api_client_secret`), no user/tenant model, no token revocation, no
  refresh tokens. Fine for a demo gateway; not what you'd want fronting anything real.
- **Load testing has been run once, at modest scale, on one machine.** 20 concurrent users for 45
  seconds against every in-memory default backend is real evidence the concurrency fix above holds
  and that typical request latencies stay well inside budget — it is not evidence of behavior at
  production scale (hundreds+ concurrent users), under sustained multi-hour load, against the
  Neo4j/Qdrant/Postgres backends instead of the in-memory defaults, or from multiple load-generating
  machines instead of one. It also didn't push `/verification/verify` with deliberately larger
  domains or deeper formulas to find where the 480ms budget actually gets tight — the formula used
  (an 8-element domain, one quantifier) solves in single-digit milliseconds, nowhere near the
  timeout. Treat this as "the obvious concurrency landmine has been found and defused," not "this
  has been capacity-planned."
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

`tests/integration/test_postgres_repository.py` skips itself unless `LEGAL_ENGINE_TEST_POSTGRES_DSN`
is set (and needs the `postgres` extra installed) — it's what CI's `postgres` job runs against a
real Postgres service container; there's nothing to configure for the rest of the suite, which
tests the same repository against SQLite instead.

For the UI (requires Node.js 20+; needs the API running separately, see above):

```bash
make ui-install
make ui-dev   # http://localhost:3000, expects the API at NEXT_PUBLIC_API_BASE_URL (default :8000)
```

For the Playwright E2E suite (`ui/e2e/`) — starts both the UI and the API itself, or reuses them
if you already have both running from the commands above:

```bash
cd ui
npx playwright install --with-deps chromium   # one-time browser download
npm run test:e2e                              # headless
npm run test:e2e:ui                           # or Playwright's interactive UI mode
```

## Phased build plan

1. **Core schemas, formal logic & game theory** — done.
2. **Hybrid knowledge graph & preemption resolver** — done.
3. **Ingestion subsystem & structured parsers (polite crawling)** — done.
4. **State ledger (WAL), Celery workers & FastAPI gateway** — done.
5. **Production infrastructure, Next.js UI & release** — done, with the caveats above.
