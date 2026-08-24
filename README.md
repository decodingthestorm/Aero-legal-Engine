# Legal Engine Platform

A legal ingestion, formal verification, and game-theoretic statutory optimization platform.

v1.0.0 marked the completion of the 5-phase build plan below: every subsystem the original spec
called for exists and has a passing test suite. v1.1.0 closes three of the five items that v1.0.0's
Known Limitations honestly flagged as open — startup reindexing, cross-browser E2E coverage, and
load-test hardening (including a graceful-degradation path for genuine solver timeouts) — leaving
two deliberately not done: multi-tenant auth and a liability-disclaimer UI, both scoped and
declined for now (see Known Limitations). This still doesn't mean "battle-tested production
system" — read on for what would still take.

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

  `hydration.py`'s `hydrate_indexes` closes the gap this originally left open: `graph_backend` and
  `vector_backend` are separate settings that still default to in-memory, so even with
  `statute_backend="sql"`, the graph/vector *indexes* used to wake up empty on every restart —
  every durably-recorded statute would be invisible to preemption resolution and semantic search
  until someone re-submitted it. `api/main.py`'s `lifespan` now calls it unconditionally on
  startup (a no-op for the default in-memory statute backend, since `.all()` is always empty on a
  fresh process there). This required a real schema change, not just a lifespan snippet:
  `StatuteDocument.applies_to` didn't exist before — the statute-to-entity association
  `GraphService.add_statute` needs was never durably recorded anywhere to rebuild from.
  `tests/integration/test_statute_persistence.py` now proves the graph/vector state — not just the
  statute record — survives a restart.
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
  already running locally), so `npm run test:e2e` is one command.

  Written without Node.js available to run it, same as the rest of `ui/` — and the first real run
  (by a human, not me) immediately caught a genuine bug: `/simulation/penalty-curve` returned a
  dict keyed by `str(x)` for each sample point, and Python's `str(50.0)` ("50.0") doesn't match
  JavaScript's `String(50)` ("50") for a whole-number value. Every lookup on the frontend silently
  missed, so the penalty curve chart just never rendered — no error, nothing in the console, a
  Python-only unit test couldn't see it because it asserted against Python's own stringification
  and never crossed the language boundary. 15/16 passed on that first run; fixed by changing the
  response to a list of `{x, y}` points instead of a stringified-float-keyed dict (removes the bug
  class, not just this instance); a second independent run then passed 16/16. That's the concrete
  case, not just the abstract argument, for why `ui/`'s one earlier manual pass was never a
  substitute for this suite.

  `playwright.config.ts` now runs all three of Playwright's browser engines (Chromium, Firefox,
  WebKit), and CI's `e2e` job runs them as a matrix — one job per browser, in parallel, with
  independent pass/fail reporting — rather than Chromium alone.

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

**Trying to find where the 480ms budget actually gets tight, empirically**: pushed domain size to
800 with 3 quantified variables (`forall x, y, z` — a formula that would need 512 million naive
ground instantiations) and Z3 still solved it in ~15ms. It isn't doing brute-force grounding for
the EPR fragment; it scales far better than that for every formula shape this system's own
compiler can produce. Even `timeout_ms=0` against a trivial formula still returns a real answer
rather than "unknown" — Z3 checks its own timeout budget too lazily to reliably interrupt anything
this fast. Constructing a genuinely adversarial EPR instance (the fragment is NEXPTIME-complete in
the worst case, so pathological instances do exist) is a research-level exercise, not a load-test
task. `load_tests/locustfile.py` now includes a 300-element-domain task anyway — not to trip the
timeout, but because the SMT-LIB2 response text scales with domain size (one datatype constructor
per element), a distinct and real thing to check under concurrent load; it stayed just as fast
(p50=13ms, max=40ms, 0 failures over 86 requests in a follow-up run).

Since a naturally slow formula proved impractical to construct, the timeout-handling *code path*
(does a genuine Z3 timeout degrade to a clean 400 instead of crashing or hanging other requests) is
covered deterministically instead, by mocking `z3.Solver`'s own `check()`/`reason_unknown()` —
`tests/unit/test_formal_logic.py::TestSolverPoolTimeout` at the solver level,
`tests/unit/test_api.py::test_solver_timeout_degrades_gracefully_and_server_stays_up` at the API
level (asserts the 400 response, then issues an unmocked follow-up request to prove the process
itself is unaffected).

## Known limitations

Read this before treating any of the above as more finished than it is:

- **The Playwright suite has run for real (twice on Chromium, plus whatever CI's next run
  produces across all three browsers) and passed 16/16 both times.** What that does and doesn't
  establish: it's been run by one person on one machine so far — CI's cross-browser matrix hasn't
  executed yet as of this commit (it will on the next push). Treat "the UI has real, cross-browser-
  configured behavioral test coverage, and it already found and fixed one bug" as established;
  treat "this has run in CI, repeatedly, over time" as not yet true.
- **Auth is deliberately minimal.** One hardcoded client_id/client_secret pair
  (`settings.api_client_id`/`api_client_secret`), no user/tenant model, no token revocation, no
  refresh tokens. Fine for a demo gateway; not what you'd want fronting anything real. Swapping in
  PyJWT/passlib for the same single-credential check wouldn't change this — real multi-tenant auth
  needs an actual user/tenant repository and tenant-scoped data isolation, a genuine feature to
  build deliberately, not a drop-in.
- **Load testing has been run a few times, at modest scale, on one machine.** Up to 20 concurrent
  users for 30-45 seconds against every in-memory default backend is real evidence the concurrency
  fix above holds, that typical request latencies stay well inside budget, and that larger response
  payloads (a 300-element domain's SMT-LIB2 text) don't change that — it is not evidence of behavior
  at production scale (hundreds+ concurrent users), under sustained multi-hour load, against the
  Neo4j/Qdrant/Postgres backends instead of the in-memory defaults, or from multiple load-generating
  machines instead of one. Treat this as "the obvious concurrency landmine has been found and
  defused, and the timeout path degrades gracefully," not "this has been capacity-planned."
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
npx playwright install --with-deps            # one-time download: Chromium, Firefox, WebKit
npm run test:e2e                              # headless, runs all three browser projects
npm run test:e2e:ui                           # or Playwright's interactive UI mode
npm run test:e2e -- --project=chromium        # just one browser, for a faster local loop
```

## Phased build plan

1. **Core schemas, formal logic & game theory** — done.
2. **Hybrid knowledge graph & preemption resolver** — done.
3. **Ingestion subsystem & structured parsers (polite crawling)** — done.
4. **State ledger (WAL), Celery workers & FastAPI gateway** — done.
5. **Production infrastructure, Next.js UI & release** — done, with the caveats above.
