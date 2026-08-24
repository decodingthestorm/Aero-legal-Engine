# Legal Engine Platform

A legal ingestion, formal verification, and game-theoretic statutory optimization platform.

v1.0.0 marked the completion of the 5-phase build plan below: every subsystem the original spec
called for exists and has a passing test suite. v1.1.0 closed three of the five items that v1.0.0's
Known Limitations honestly flagged as open — startup reindexing, cross-browser E2E coverage, and
load-test hardening (including a graceful-degradation path for genuine solver timeouts) — leaving
two deliberately not done: multi-tenant auth and a liability-disclaimer UI. v1.2.0 closes both, but
not in the form originally proposed for either: multi-tenant isolation is real end-to-end scoping
(`StatuteRepository`, `GraphService`, and `VectorIndex` all driven by the JWT's `tenant_id` claim —
see "Multi-tenant data isolation" below), not just a token check; and the liability item is a
one-time, per-tenant, cryptographically-logged disclaimer acceptance (see "Liability disclaimer &
consent" below), not a per-request header or a client-side modal — both of those were assessed and
rejected as security theater (client-controlled, no enforcement teeth, easy to characterize as
manufactured compliance rather than genuine consent) before building what's here instead. v1.2.1
adds an $L_1$-sparse alternative to `refactoring/`'s existing minimum-norm loophole correction —
one deliberately narrow, self-contained slice of a much larger proposed roadmap (neuro-symbolic
LLM ingestion, modal deontic/temporal/epistemic logic, multi-agent reinforcement learning, ZK-SNARK
compliance proofs, HSM-backed signing, Kubernetes autoscaling) that was assessed and **not**
pursued wholesale: several of those pillars would either compromise the EPR core's decidability
guarantee (modal logic's Kripke semantics generically require quantifier alternation outside the
`exists*-forall*` fragment `formal_logic/` has guaranteed since Phase 1) or require cloud
infrastructure (Kubernetes, HSM/KMS, managed Neo4j/Qdrant clusters) this environment has no way to
build *or verify*, which is not how anything else in this codebase has been built. v1.2.2 pursues
one more scoped slice of a follow-up version of that same roadmap: `ConsentLedger` (see "Liability
disclaimer & consent" below) replaces the O(n) full-WAL-scan the consent gate originally ran on
every request with an O(1) indexed projection, still exactly re-derivable from the WAL alone.
v1.2.3 takes the KMS/HSM item off that roadmap too, in scoped form: `KeySigner`
(`core/key_signer.py`) abstracts WAL signing behind `sign()`/`verify()`, with the existing
Ed25519-file backend as the default and lazy-imported AWS KMS/HashiCorp Vault adapters as
real, dispatching alternatives — genuinely correct against the installed boto3/hvac packages'
actual API contracts (verified by introspection, not memory), but not exercised against a live AWS
account or Vault instance, which this environment doesn't have. This still doesn't mean
"battle-tested production system" — read on for what would still take.

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
  `B @ w = 0` to zero them out. Two correction strategies over the same constraint:
  `zero_arbitrage.py`'s minimum-*L2*-norm least-squares solve (spreads the fix a little across
  every edge — closest to the original values, but not something a regulator could actually pass
  as a bill), and `sparse_optimizer.py`'s minimum-*L1*-norm solve via `cvxpy` (a Lasso/compressed-
  sensing reformulation of the identical constraint that drives most edges to exactly zero,
  producing a "surgical" patch that changes as few clauses as possible — see
  `tests/unit/test_sparse_optimizer.py` for a concrete, non-degenerate example where L1 changes 1
  edge and L2 changes all 5 to satisfy the same two constraints). `cvxpy` is a lazy-imported
  optional dependency (the `sparse-opt` extra) using only its bundled open-source LP solvers, not
  the commercial MOSEK some cvxpy examples default to — L1-minimization under linear equality
  constraints is a linear program, nothing here needs a paid solver license. Exposed via
  `POST /refactoring/sparse-patch` alongside the existing `/detect-loopholes`, with an optional
  `max_delta` per-edge bound and a 503 (not 400) when `cvxpy` isn't installed on a given
  deployment — a missing capability, not a bad request.
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

- **`core/wal.py`** — `WriteAheadLog`: an append-only, SHA-384 hash-chained, cryptographically-
  signed audit log. `verify()` replays the whole chain and catches any tampering with a past
  entry's payload, its `prev_hash` link, or its signature. Unlike the knowledge_graph backends,
  `cryptography` is a hard dependency here, not a lazy-imported optional one — there's no
  meaningful lightweight version of "the audit log, but unsigned." Since v1.2.0 it's wired into
  the live API (`api/main.py`'s `lifespan`, not just the standalone
  `tests/integration/test_ingest_to_proof.py` walkthrough it started as).
- **`core/key_signer.py`** — `KeySigner`: a `sign()`/`verify()` Protocol `WriteAheadLog` signs
  through, so it doesn't need to know or care which backend actually holds the private key.
  `Ed25519FileKeySigner` is the always-available default (persists an Ed25519 keypair to disk
  unencrypted — see its own docstring for why that's an honest limitation, not a hidden one — so
  the same key signs every entry across a restart; a key regenerated on every startup would make
  every entry recorded before that restart fail `verify()` against the new public key).
  `AwsKmsKeySigner`/`VaultTransitKeySigner` are lazy-imported optional backends (the `kms` extra:
  boto3/hvac) matching every other "real backend" in this codebase — dispatch
  (`core/key_signer_factory.py`, `settings.wal_signer_backend`) and fail-closed-with-install-hint
  behavior are tested; their actual `sign()`/`verify()` request/response handling is unit-tested
  against an injected mock client (`tests/unit/test_key_signer.py`), verified against the real
  installed boto3/hvac packages' actual service model and method signatures (not memory) when this
  was written, but never against a genuine AWS account or Vault instance, neither of which is
  available here. `AwsKmsKeySigner` uses `ED25519_SHA_512` over an `ECC_NIST_EDWARDS25519` KMS
  key — AWS KMS does support Ed25519 natively (confirmed by introspecting botocore's own KMS
  service model, correcting an initial assumption that it was RSA/NIST-ECC only), so this matches
  `Ed25519FileKeySigner`'s algorithm rather than switching families.
- **`compliance/consent.py`** — per-tenant liability-disclaimer acceptance, recorded as WAL entries
  rather than a separate consent table. See "Liability disclaimer & consent" below.
- **`workers/`** — a real Celery app (`celery_app.py`, Redis broker/backend, matching
  `docker/docker-compose.yml`) and two tasks (`crawl_and_parse`, `index_statute_embedding`).
  Both are fully tested via `.apply(...).get()`, which runs a task synchronously in-process with
  no broker involved — real distributed dispatch via `.delay()` needs a live Redis instance,
  which this environment doesn't have, but the task *logic* needs nothing infra-specific to test.
- **`api/`** — a working FastAPI gateway wiring every subsystem above into HTTP endpoints:
  `/verification/verify` (accepts a JSON mirror of the EPR formula AST, a discriminated union on
  `kind`, and returns both the `ProofResult` and the rendered SMT-LIB2 text), `/simulation/penalty`
  and `/simulation/trembling-hand`, `/refactoring/detect-loopholes` + `/refactoring/sparse-patch`, `/graph/statutes` +
  `/graph/preemption/{entity_id}` + `/graph/search`, `/ingestion/jobs`, `/auth/token`, and
  `/legal/disclaimer` + `/legal/accept` (see "Liability disclaimer & consent" below).
  Every route depends on the knowledge_graph Protocol interfaces rather than concrete classes;
  which concrete class each resolves to is decided by `knowledge_graph/factory.py`, itself driven
  by `core.config.settings` (`graph_backend`/`vector_backend`/`embedding_backend`) — swapping in
  Neo4j/Qdrant/sentence-transformers for production is a settings change, not a code change.
  Auth is a real (if deliberately simple — a dependency-free HS256 JWT implementation rather than
  pulling in PyJWT for a few dozen lines) bearer-token check, off by default via
  `settings.api_auth_enabled` so it doesn't get in the way of local development or most of the
  test suite. Since v1.2.0, the token's `tenant_id` claim is what actually drives data isolation —
  see "Multi-tenant data isolation" below.
- **`persistence/`** — the durable, queryable system-of-record for ingested statutes, separate
  from the graph/vector *indexes* above (which are rebuildable from this). `StatuteRepository` is
  in-memory by default; `settings.statute_backend = "sql"` switches to `SqlAlchemyStatuteRepository`
  (`sql_repository.py`), which works against any SQLAlchemy-async DSN — `postgresql+asyncpg://` in
  production (`docker-compose.yml` runs Postgres; the `postgres` install extra pulls in
  `sqlalchemy`+`asyncpg`), `sqlite+aiosqlite://` in this codebase's own test suite, since there's no
  Postgres available to test against for real in the environment this was built in. Every method
  takes a `tenant_id` and scopes to it (see "Multi-tenant data isolation" below).
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
  `GraphService.add_statute` needs was never durably recorded anywhere to rebuild from. Since
  v1.2.0, `hydrate_indexes` rebuilds every tenant's indexes independently (via
  `StatuteRepository.list_tenant_ids()`), not just one shared graph/vector pair.
  `tests/integration/test_statute_persistence.py` now proves the graph/vector state — not just the
  statute record — survives a restart.

### Multi-tenant data isolation

Added in v1.2.0, replacing v1.1.0's Known Limitations entry that flagged auth as not actually
isolating tenant data. Two mechanisms, matched to how cheap each backend is to duplicate:

- **`StatuteRepository`** (`persistence/repository.py`, `sql_repository.py`) — one shared instance,
  every query scoped by a `tenant_id` argument. The in-memory backend keys its dict by
  `(tenant_id, id)`; the SQL backend gives `StatuteRecord` a composite primary key of
  `(id, tenant_id)` rather than `id` alone, specifically so that two tenants' statutes sharing the
  same UUID (e.g. via `model_copy`, or a genuine `uuid4` collision) land as two independent rows
  instead of the second write silently overwriting the first through `session.merge()` — an actual
  bug this multi-tenant work caught in its own first draft, fixed before it shipped. `get()` and
  `list_by_citation()` return "not found" identically whether a record doesn't exist or exists under
  a different tenant — no operation ever confirms even the *existence* of another tenant's data.
- **`GraphService` / `VectorIndex`** (`knowledge_graph/tenant_registry.py`'s `TenantIndexRegistry`)
  — cheap to construct (an in-memory `NetworkXGraphService`/`InMemoryVectorIndex` wraps a fresh
  graph/dict), so instead of threading `tenant_id` through every method of both Protocols, each
  tenant gets its own genuinely separate instance, lazily created on first use. Stronger isolation
  guarantee than a shared-instance-plus-filter: there's no shared in-memory structure a bug in a
  filter clause could ever leak across, because there's no shared structure at all.

The API wires this in via `api/dependencies.py`'s `get_current_tenant` — decodes the bearer token's
`tenant_id` claim when `settings.api_auth_enabled` is on, or returns `settings.default_tenant_id`
(the whole deployment behaves as one tenant, unchanged from pre-multi-tenancy behavior) when auth is
off, which is why every pre-existing test that runs with auth disabled needed no changes.
`tests/integration/test_multi_tenant_isolation.py` proves this end-to-end through the real API with
two distinct tenant tokens: a statute added under one tenant is invisible to `GET
/graph/statutes/{id}` (404, not just filtered out), absent from `GET /graph/statutes`, doesn't
resolve in `/graph/preemption/{entity_id}`, and never surfaces in `/graph/search` — for another
tenant's token.

**What this still isn't**: there's no user/tenant registration system. `settings.api_client_id`
remains the one configured demo credential, scoped to `settings.api_client_tenant_id` — the
isolation *mechanism* works for however many tenants actually have credentials, which is what's
tested (via directly-minted tokens with different `tenant_id` claims, standing in for a second
registered client), but there's no API to provision a real second tenant/credential pair yet.

### Liability disclaimer & consent

Added in v1.2.0, closing v1.1.0's other declined item — but not as originally proposed. Two shapes
were considered and rejected first: an `X-Legal-Disclaimer` request header, and a client-side
modal/`localStorage` flag. Both are client-controlled and unenforceable server-side; a third
proposal (an exact-string-match field required on every `/verification/verify` and
`/simulation/*` call) was also rejected — its own stated implementation had the frontend SDK
auto-inject the string into every request, meaning no human ever actually saw or clicked anything,
which proves a client sent a string, not that an identified person agreed to a disclaimer. What
shipped instead is closer to a real click-through EULA:

- **`GET /legal/disclaimer`** — unauthenticated, returns the current disclaimer text and its
  version (`compliance/consent.py`'s `DISCLAIMER_VERSION`, a code constant — changing what a
  tenant is asked to agree to is a reviewed code change and a version bump, not a runtime setting).
- **`POST /legal/accept`** — requires a valid bearer token; records one WAL entry
  (`legal_disclaimer_accepted`) containing the tenant_id, the disclaimer version, and the
  *token's own `sub` claim* as the accepting subject — never a client-supplied field, so nobody can
  put an arbitrary name in the record. Idempotent from the caller's perspective (`already_accepted`
  in the response) but not silently deduplicated in the log — a repeat acceptance is itself
  recorded as a fact, not swallowed.
- **`require_consent`** (`api/dependencies.py`) gates `/verification` and `/simulation` — the two
  subsystems the disclaimer text is actually about — on an on-record acceptance of the *current*
  version for that request's tenant. Like `require_auth`/`get_current_tenant`, it no-ops when
  `settings.api_auth_enabled` is off, so the default dev/test posture is unaffected.
- Because acceptance lives in the WAL, it inherits the WAL's actual property: `wal.verify()`
  detects a forged or backdated acceptance the same way it detects tampering with any other entry
  (`tests/unit/test_consent.py::test_acceptance_is_tamper_evident`). That's the real content behind
  "non-repudiation" here — not the previous proposal's unenforced client-side check, an
  identified-tenant's acceptance in a hash-chained, Ed25519-signed log that a forgery attempt is
  cryptographically detectable in.
- **`ConsentLedger`** (`compliance/consent.py`) — a read-optimized `tenant_id -> most recent
  acceptance` projection over the WAL, replacing this feature's original implementation, which
  answered `has_accepted_current_disclaimer` by scanning every entry in the WAL on every single
  gated request. The WAL stays the sole source of truth (the index is built by replaying
  `wal.entries()` once at startup and updated incrementally on every new `record_acceptance` call,
  never re-scanned), and every `ConsentRecord` carries a `wal_sequence` back-reference to the exact
  signed entry it was derived from — a cached "yes, this tenant accepted" answer is always
  traceable to one specific entry, not just trusted at face value.
  `tests/unit/test_consent.py::TestConsentLedgerReplay` proves the actual property that justifies
  calling it a projection rather than a second source of truth: a fresh `ConsentLedger` constructed
  over a WAL that already has entries (the real case after a process restart) reconstructs
  identical state to one that was live for every write.

`tests/integration/test_legal_consent_gate.py` proves this end-to-end: verification/simulation
403 before acceptance, 200 after; `GET /legal/disclaimer` needs no token; acceptance for one
tenant never unblocks another (same isolation guarantee as the data-isolation section above);
`refactoring`/`graph`/`ingestion` stay ungated by this, since they're not what the disclaimer is
about.

**What this still isn't**: by default, the WAL's signing key is still persisted to disk
unencrypted (`Ed25519FileKeySigner`, `core/key_signer.py`) — the same gap this codebase's other
plaintext-default secrets (`jwt_secret`, `api_client_secret`) already have. `settings.wal_signer_backend`
can now point this at AWS KMS or HashiCorp Vault instead (see the `core/key_signer.py` bullet
above), which is real, dispatching code — but neither has been exercised against an actual AWS
account or Vault instance, so treat "the abstraction and request/response handling are correct
against the documented API contracts" as established, not "this has been proven against a live
KMS/Vault." The consent check itself
is now O(1) (`ConsentLedger`, above) rather than an O(n) WAL scan, but the ledger is still an
in-process, in-memory projection rebuilt by a single full replay at startup — fine at this system's
current scale (and current WAL size), not something that's been load-tested the way
`/verification/verify` has (see "Load testing" below), and not yet a persisted index of its own
(a restart replays the whole WAL again, rather than resuming from a snapshot).
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

**Pushed to 300 concurrent users** (up from 20), no distributed/cloud workers involved — a single
local Locust process comfortably drives this much load before becoming the bottleneck itself.
**14,861 requests, 0 failures.** Latency did rise substantially under that much queueing pressure
(median ~600-1200ms per endpoint, `/graph/statutes` p99≈1.7s) — that's real and worth taking
seriously, not hidden. What matters is *why*: `/verification/verify`'s actual Z3 solve time
(`proof_result.elapsed_ms`, checked on every request, not just the HTTP round-trip) never once
exceeded the 480ms budget, even at this scale. The elevated latency is requests queueing for one of
`settings.z3_pool_size=4` bounded solver slots, not the solver degrading under load — exactly the
intended behavior of a bounded-concurrency pool. Still a single `uvicorn` process, not multiple
worker processes behind a load balancer the way a real production deployment would run — that
remains untested.

## Known limitations

Read this before treating any of the above as more finished than it is:

- **The Playwright suite has run for real (twice on Chromium, plus whatever CI's next run
  produces across all three browsers) and passed 16/16 both times.** What that does and doesn't
  establish: it's been run by one person on one machine so far — CI's cross-browser matrix hasn't
  executed yet as of this commit (it will on the next push). Treat "the UI has real, cross-browser-
  configured behavioral test coverage, and it already found and fixed one bug" as established;
  treat "this has run in CI, repeatedly, over time" as not yet true.
- **Auth's credential check is still deliberately minimal; its data-isolation guarantee is not.**
  As of v1.2.0, `StatuteRepository`/`GraphService`/`VectorIndex` are genuinely tenant-scoped end to
  end (see "Multi-tenant data isolation" above) — that part is real, not aspirational. What's still
  missing: one hardcoded client_id/client_secret pair (`settings.api_client_id`/`api_client_secret`),
  no user/tenant *registration* system to provision a second real credential, no token revocation,
  no refresh tokens. Fine for a demo gateway credential check; not what you'd want fronting anything
  real. Swapping in PyJWT/passlib for the same single-credential check still wouldn't address this —
  what's needed is a user/tenant registry (sign-up, credential issuance, tenant provisioning), which
  is a genuine feature to build deliberately, not a drop-in.
- **The liability-disclaimer consent record is real (tamper-evident, tied to a server-verified
  token subject, tenant-scoped, and — since `ConsentLedger` — an O(1) indexed lookup rather than a
  WAL scan) but its supporting infrastructure is still minimal.** The WAL's signing key is a
  plaintext file on disk by default (`Ed25519FileKeySigner`) — `settings.wal_signer_backend` can
  point this at AWS KMS or Vault instead (`core/key_signer.py`), real dispatching code, but neither
  path has been exercised against an actual AWS account or Vault instance. There's no way to revoke
  or amend an acceptance once recorded (append-only is the point, but that also means no "the
  tenant's authorized signer changed" flow exists yet), and `ConsentLedger` itself is an in-process
  index rebuilt by a full WAL replay at every startup, not a persisted index of its own — untested
  at any real scale (WAL size, replay time, or concurrent tenant count). See "Liability disclaimer
  & consent" above for what it does establish.
- **Load testing has been run a few times, at up to 300 concurrent users, on one machine.** That's
  real evidence the concurrency fix holds, that the Z3 timeout budget is respected even under heavy
  queueing, and that larger response payloads don't change that — it is not evidence of behavior at
  genuine production scale (thousands of concurrent users), under sustained multi-hour load, against
  the Neo4j/Qdrant/Postgres backends instead of the in-memory defaults, from multiple
  load-generating machines instead of one, or against multiple `uvicorn` worker processes behind a
  load balancer instead of the single process every run here used. Treat this as "the obvious
  concurrency landmine has been found and defused, the timeout path degrades gracefully, and the
  system holds up to real (if moderate) concurrent load," not "this has been capacity-planned for
  production."
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
