# Legal Engine Platform

A legal ingestion, formal verification, and game-theoretic statutory optimization platform.

v1.0.0 marked the completion of the 5-phase build plan below: every subsystem the original spec
called for exists and has a passing test suite. Every version since has closed one specific,
honestly-flagged gap from the version before it — never a rewrite, always additive:

- **v1.1.0** — closed 3 of v1.0.0's 5 Known Limitations: startup reindexing, cross-browser E2E
  coverage, and load-test hardening (a graceful-degradation path for genuine solver timeouts).
- **v1.2.0** — closed the other 2, but not as originally proposed for either. Multi-tenant auth:
  real end-to-end scoping (`StatuteRepository`/`GraphService`/`VectorIndex` all driven by the JWT's
  `tenant_id` claim — see "Multi-tenant data isolation" below), not just a token check. Liability
  disclaimer: a one-time, per-tenant, cryptographically-logged acceptance (see "Liability
  disclaimer & consent" below), not a per-request header or client-side modal — both rejected as
  security theater (client-controlled, no enforcement teeth, easy to characterize as manufactured
  compliance rather than genuine consent) before building what's here instead.
- **v1.2.1** — an $L_1$-sparse alternative to `refactoring/`'s minimum-norm loophole correction. One
  deliberately narrow slice of a much larger proposed roadmap (neuro-symbolic LLM ingestion, modal
  deontic/temporal/epistemic logic, MARL, ZK-SNARKs, HSM signing, Kubernetes autoscaling) assessed
  and **not** pursued wholesale: several pillars would either compromise the EPR core's decidability
  guarantee (modal logic's Kripke semantics generically need quantifier alternation outside the
  `exists*-forall*` fragment `formal_logic/` has guaranteed since Phase 1) or need cloud
  infrastructure this environment has no way to build *or verify*.
- **v1.2.2** — `ConsentLedger` replaces the consent gate's O(n) full-WAL-scan with an O(1) indexed
  projection, still exactly re-derivable from the WAL alone.
- **v1.2.3** — `KeySigner` (`core/key_signer.py`) abstracts WAL signing behind `sign()`/`verify()`;
  the existing Ed25519-file backend is the default, lazy-imported AWS KMS/HashiCorp Vault adapters
  are real, dispatching alternatives, genuinely correct against the installed boto3/hvac packages'
  actual API contracts (verified by introspection, not memory) but not exercised against a live AWS
  account or Vault instance.
- **v1.3.0** — `POST /auth/register`: real, self-service user/tenant registration (see "User
  accounts, tokens & revocation" below), closing "no user/tenant registration system to provision a
  second real credential."
- **v1.4.0** — token revocation and refresh-token rotation (`compliance/token_ledger.py`,
  `POST /auth/refresh` + `POST /auth/revoke`), closing the two gaps v1.3.0 deliberately left open.
- **v1.4.1** — refresh-token reuse now revokes the whole session (`family_id`, shared by every
  token issued in one login and carried through every rotation), not just the one reused token —
  closing the gap where a victim's already-rotated access token would otherwise stay valid even
  after their refresh token was clearly stolen and reused.
- **v1.5.0** — `UserAccount.role` (`"owner"`/`"member"`) plus `POST /auth/invite` +
  `POST /accept-invite`, closing "no inviting a second user into an existing tenant" and "no
  roles/permissions" together: the natural minimal role model here is exactly what an invite system
  needs to gate on (only an owner can invite).
- **v1.6.0** — `core/email_sender.py`'s `EmailSender` (`LoggingEmailSender` default,
  `SmtpEmailSender` real dispatch, stdlib-only, no install extra) plus `POST
  /auth/request-password-reset` + `POST /auth/reset-password` + `POST /auth/verify-email`, closing
  the last two gaps: "no password reset" and "no email verification flow." The Known Limitations
  bullet this whole thread traces back to is now empty of the four items it originally named — the
  smaller sub-gaps that closing them surfaced (session-wide reset invalidation, tenant member
  management) are what the next two versions close.
- **v1.6.1** — `TokenLedger.revoke_all_sessions_for_subject`: `POST /auth/reset-password` now kills
  *every* active session for that user, not just the one reset token — the "assume this account may
  be compromised" property a password reset is supposed to have.
- **v1.7.0** — tenant member management: `GET /auth/members` (list), `POST
  /auth/members/{email}/role` (owner-only role change), `DELETE /auth/members/{email}` (owner-only
  removal, reusing v1.6.1's session-cascade so a removed member's live sessions die immediately).
  Both role-change and removal reject the change that would leave a tenant with zero owners (409).
  Closes "no way to change a role or remove a member after the fact, no listing who's in a tenant."
- **v1.8.0** — `POST /legal/revoke` (owner-only): a tenant can withdraw its liability-disclaimer
  acceptance, immediately re-blocking `/verification`/`/simulation` via the existing
  `require_consent` gate with no other wiring needed. Closes "no way to revoke or amend an
  acceptance once recorded."
- **v1.9.0** — `uncertainty/`: a semantic-entropy abstention gate for stochastic model output, the
  one node of a proposed v2.0 spec that was both genuinely buildable here and genuinely broken as
  specified — its threshold (8.5) sat 3.7× above the mathematical ceiling of the quantity it gated
  on (log(10) = 2.3026 nats), so it could never fire. The gate now rejects an unfireable threshold
  at construction. See "Semantic entropy abstention gate" below.

- **v1.9.1** — `mypy --strict` now passes on all 72 source files and runs in CI. It had been
  configured in `pyproject.toml` since the start and never once executed, so nothing it claimed to
  enforce was actually enforced — the same shape of problem as v1.9.0's unfireable threshold, one
  layer up. Turning it on surfaced 53 errors. Most were missing annotations, but three were real
  defects: `sql_repository.py` reconstructed a `GeoBoundary` after checking only one of its four
  bounds for NULL (a partial row would have failed pydantic validation pointing at the model rather
  than the bad row); `federal.py` guarded `<TEXT>` as possibly-`None` on one line and called
  `.strip()` on it unguarded three lines later; and `municipal.py` passed BeautifulSoup attribute
  values straight to `float()` without accounting for multi-valued attributes returning a list.

- **v1.9.2** — `SqlAlchemyUserRepository` now runs against a real Postgres in CI. It had been
  SQLite-only since v1.3.0 — `test_postgres_repository.py` covered statutes and nothing else — so
  `list_by_tenant`/`remove`, which back member management, had never touched the database they'd
  run against in production. Writing the suite surfaced a round-trip bug neither backend was
  catching: `created_at`/`ingested_at` went in UTC-aware and came back **naive**, because SQLite has
  no native timestamp type and Postgres' `TIMESTAMP WITHOUT TIME ZONE` discards the offset. Nothing
  asserted on either field, so nothing noticed. Fixed at the domain boundary (`_as_utc`).

- **v1.10.0** — `core/timestamper.py`: RFC 3161 trusted timestamping, closing the gap that every
  timestamp here was **self-asserted**. The WAL signs its own clock, which proves the chain is
  intact but nothing about *when* to anyone who doesn't already trust the host. `anchor()`
  timestamps the head hash, attesting the whole log in one token. Second of the v2.0 proposal's
  nodes to ship, and the only one of its infrastructure items that closed a real gap rather than
  restating a solved one.

- **v1.11.0** — the v2.0 proposal's last two buildable nodes, each correcting one of its defects by
  construction. `deontic/` evaluates Åqvist System E over finite preference models and survives
  Chisholm's Paradox and Forrester's gentle-murder paradox — and distinguishes a *tie* among optimal
  worlds (ordinary, and what the spec's `ABS_02` would have halted on) from a real dilemma, where
  the optimal worlds disagree. `game_theory/hjb.py` solves the regulator's Hamilton-Jacobi-Bellman
  equation by finite differences, checked against the closed-form Riccati solution the spec's own
  "linear-quadratic" claim implies — resolving its demand for LQ structure *and* viscosity solutions
  by making the closed form the solver's test oracle rather than its competitor.

- **v1.12.0** — statutory conflict resolution beyond Article VI. `preemption.py` used to give up
  whenever two statutes tied at the same `JurisdictionTier`, which is correct for the Supremacy
  Clause but leaves the commonest real conflict unresolved. It now applies **lex specialis** (the
  narrower rule wins) and then **lex posterior** (the later rule wins, only where scopes are
  identical), reports *which* maxim decided via `resolved_by`, and names the statutes still in
  contention via `unresolved_candidates`. Prompted by a research plan whose defeasibility track
  correctly identified this gap.

- **v1.13.0** — three gaps that had all been documented rather than fixed. A deployment now
  **refuses to start** on the placeholder secrets this repo ships with (`core/startup_checks.py`) —
  previously "plaintext secret defaults" sat under Known limitations, which made it an acknowledged
  risk rather than a prevented one, and an acknowledged risk still ships.
  `settings.require_email_verification` makes `UserAccount.email_verified` gate something for the
  first time. And `ConsentLedger`'s startup replay is now measured instead of disclaimed: linear at
  ~0.6us/entry, with memory rather than time as the real ceiling.

- **v1.14.0** — the first step on Layer 0 (ingestion): `obligations/`, a structured representation
  for regulatory provisions plus **express-preemption analysis**, built against the verbatim text of
  Fla. Stat. § 509.032(7)(b) fetched from the Florida Senate. That one provision reserves *three*
  subjects to the state (prohibition, duration, frequency), spares anything adopted on or before
  June 1 2011, and carves out property-valuation rules — so a city night cap is void, the same
  city's parking rule is untouched, an identical cap adopted in 2010 survives, and an undated one
  cannot be decided at all. Tier-based reasoning gets three of those four wrong.

- **v1.15.0** — `obligations/extraction.py` closes the loop: ordinance **prose** now reaches a
  preemption verdict. `KeywordObligationExtractor` is the deterministic default;
  `LlmObligationExtractor` is the real backend and fails closed, since no model is wired in here.
  The design point isn't accuracy — it's that a provision the extractor can't classify **surfaces**
  rather than vanishing, because a missed obligation reports an ordinance as not regulating
  something it does regulate.

None of this means "battle-tested production system" — read on for what would still take.

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
- **`core/timestamper.py`** — `Timestamper`: RFC 3161 trusted timestamping, closing the gap that
  every timestamp in this system is otherwise **self-asserted**. The WAL stamps its own clock and
  signs it, which makes the log tamper-*evident* but proves nothing about *when* to anyone who
  doesn't already trust the host — someone who controls the machine can backdate it and produce a
  perfectly valid chain. A Time-Stamp Authority signs "I saw this digest at this time," which is a
  different claim from "this host wrote this." `anchor()` timestamps the WAL's *head hash* rather
  than each entry: entry N's hash transitively commits to every entry before it, so one token
  attests the whole log, and per-entry stamping would put a network round trip on every write and
  make the WAL unavailable whenever the TSA is. See "Trusted timestamping" below for what it
  verifies and what it deliberately doesn't.
- **`compliance/consent.py`** — per-tenant liability-disclaimer acceptance, recorded as WAL entries
  rather than a separate consent table. See "Liability disclaimer & consent" below.
- **`deontic/`** — dyadic deontic logic (Åqvist System E) over finite preference models:
  conditional obligation `O(ψ|φ)` evaluated at the *best* φ-worlds, which is what lets a secondary
  obligation govern an already-violated primary one without the two colliding. Decidable by
  enumeration, deliberately separate from `formal_logic/`'s EPR compiler. See "Deontic reasoning"
  below.
- **`game_theory/hjb.py`** — the regulator's continuous-time control problem: choose enforcement
  intensity against a drifting, noisy compliance gap. A finite-difference HJB solver plus the exact
  Riccati solution it's validated against. See "Regulatory control" below.
- **`uncertainty/`** — semantic entropy over bidirectional-entailment clusters, as an abstention
  gate for stochastic (LLM) output: sample the same question N times, group the samples by
  *meaning* rather than by string, and take the Shannon entropy of that distribution. Consistent
  answers score 0; mutually incompatible ones approach the ceiling. See "Semantic entropy
  abstention gate" below — including why the ceiling is the load-bearing detail.
- **`workers/`** — a real Celery app (`celery_app.py`, Redis broker/backend, matching
  `docker/docker-compose.yml`) and two tasks (`crawl_and_parse`, `index_statute_embedding`).
  Both are fully tested via `.apply(...).get()`, which runs a task synchronously in-process with
  no broker involved — real distributed dispatch via `.delay()` needs a live Redis instance,
  which this environment doesn't have, but the task *logic* needs nothing infra-specific to test.
- **`api/`** — a working FastAPI gateway wiring every subsystem above into HTTP endpoints:
  `/verification/verify` (accepts a JSON mirror of the EPR formula AST, a discriminated union on
  `kind`, and returns both the `ProofResult` and the rendered SMT-LIB2 text), `/simulation/penalty`
  and `/simulation/trembling-hand`, `/refactoring/detect-loopholes` + `/refactoring/sparse-patch`, `/graph/statutes` +
  `/graph/preemption/{entity_id}` + `/graph/search`, `/ingestion/jobs`, `/auth/token` +
  `/auth/register` + `/auth/invite` + `/auth/accept-invite` + `/auth/refresh` + `/auth/revoke` +
  `/auth/request-password-reset` + `/auth/reset-password` + `/auth/verify-email` (see "User
  accounts, tokens & revocation" below), and `/legal/disclaimer` + `/legal/accept` (see "Liability
  disclaimer & consent" below).
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

**What this still isn't**: as of v1.3.0 there *is* a real registration path (`POST /auth/register`
— see "User accounts, tokens & revocation" below) provisioning genuine, independent tenants — this section's
isolation guarantee is no longer only exercised via directly-minted tokens standing in for a second
registered client, `tests/integration/test_registration_flow.py` proves it through real registration
end-to-end. What's still missing: inviting a *second* user into a tenant that already has one (every
tenant has exactly one user for now), and any notion of roles/permissions within a tenant.

### User accounts, tokens & revocation

**Registration & login**, added in v1.3.0, closing the "no way to provision a real second
tenant/credential pair" gap the previous section used to flag. Self-service, not admin-gated:
`POST /auth/register` requires no existing credential, matching how most SaaS trial signup works.

- **`POST /auth/register`** — `{email, password}`. Always provisions a *brand-new* tenant (a
  generated `tenant_id`) plus its first `UserAccount` — this is "start your own workspace," not
  "join an existing one." Rejects a duplicate email with 409, an obviously-malformed email or a
  password under 8 characters with 422. Returns the new `tenant_id` plus an access+refresh token
  pair immediately (standard "logged in right after signup" UX).
- **`POST /auth/token`** — kept backward-compatible: the demo credential
  (`settings.api_client_id`/`api_client_secret`) still works unconditionally, so zero-config local
  dev and every pre-existing test stay unaffected. It now *also* checks the real user registry —
  `client_id` doubling as a registered email, `client_secret` as the password — so real accounts log
  in through the same endpoint rather than a separate one.
- **`persistence/user_repository.py`** — `UserRepository`, in-memory by default,
  `settings.user_backend = "sql"` for the same SQLAlchemy-backed durability
  `persistence/repository.py`/`sql_repository.py` already give `StatuteRepository` (same file, same
  DSN, a second table). Deliberately *not* tenant-scoped the way `StatuteRepository` is: email is
  globally unique, because `POST /auth/token`'s login flow only has an email + password to go on,
  not a tenant_id yet — resolving "which account does this email belong to" has to be a global
  lookup. That's a property of the login credential itself, not a breach of the data-isolation
  guarantee above, which is about tenant *data*, not the login system's own account lookup.
- **`api/security.py`**'s `hash_password`/`verify_password` — `hashlib.pbkdf2_hmac` (600,000
  iterations, OWASP's current minimum, a random salt per password, constant-time comparison via
  `hmac.compare_digest`), the same "correct use of a standard-library primitive" philosophy this
  file already applies to its hand-rolled HS256 JWT signing.

**Token revocation & refresh rotation**, added in v1.4.0, closing the two gaps the registration work
deliberately left open. Every issued token carries a `jti` (unique per token — `sub` alone only
identifies the *user*, not which specific token to revoke), a `token_type` claim, and (since v1.4.1)
a `family_id` shared by every token issued from one login.

- **`compliance/token_ledger.py`**'s `TokenLedger` — the same WAL-backed-projection pattern
  `ConsentLedger` already proved out: the WAL is the sole source of truth, this is an O(1) index
  over it (`is_revoked(jti)`, `is_family_revoked(family_id)`, `redeem_refresh_token(jti)`), exactly
  re-derivable by replaying `wal.entries()` from scratch
  (`tests/unit/test_token_ledger.py::TestTokenLedgerReplay` proves it, same shape as
  `ConsentLedger`'s own replay test). No separate "was this jti ever issued" tracking — the JWT
  signature itself is that proof; nothing downstream needs to query it.
- **`POST /auth/refresh`** — `{refresh_token}`. Redeems a still-valid, not-yet-used refresh token
  for a new access+refresh pair (rotation: the old refresh token is spent the instant it's used, and
  the new pair carries the *same* `family_id` forward). An access token presented here, or a refresh
  token presented as a regular bearer token elsewhere, is rejected either way (`token_type` is
  checked in both directions).
- **`POST /auth/revoke`** — `{token}`. Possession of the token (access *or* refresh) is the
  authorization to revoke it — matches ordinary "logout" semantics, no separate auth check needed.
  A revoked access token is rejected immediately on its very next use, not just once it naturally
  expires (`api/dependencies.py`'s `_decode_bearer_token`, shared by `require_auth`/
  `get_current_tenant`, checks `TokenLedger.is_revoked` on every request when auth is enabled).
- **Reuse of a spent refresh token now revokes the whole session (v1.4.1), not just that one
  attempt.** A single jti's revocation was never enough on its own: if an attacker steals a refresh
  token and redeems it, the *victim* still holds the access token from their own legitimate rotation
  right before the theft — jti-revocation alone leaves that token valid until it naturally expires.
  `redeem_refresh_token` detecting reuse now calls `revoke_family(family_id)`, which
  `_decode_bearer_token` checks on every request — the sibling access token stops working
  immediately too, not just the reused refresh token. A normal multi-step refresh chain (always
  using only the newest token, completely ordinary client behavior) never triggers this — only an
  actual second use of an already-spent token does.

`tests/integration/test_registration_flow.py` proves registration end-to-end: a registered
account's token works on a protected route, a duplicate email is rejected, a registered user logs
in via the same `/auth/token` the demo credential uses, two separate registrations get two tenants
fully isolated from each other (reusing the exact guarantee "Multi-tenant data isolation" above
proves for directly-minted tokens — this proves it holds for tokens obtained the real way).
`tests/integration/test_token_lifecycle.py` proves revocation and rotation end-to-end, including the
actual cascade: refresh once, reuse the *old* refresh token (simulating theft), then confirm the
*new* access token from the legitimate rotation — never itself revoked or reused — is now rejected
too; a normal 3-step refresh chain that never reuses anything is confirmed to never falsely trigger
this; none of it leaks across two different users' sessions.

**Roles & tenant invites**, added in v1.5.0, closing "no inviting a second user into an existing
tenant" and "no roles/permissions" together — the natural minimal role model here (`UserAccount.
role`, `"owner"`/`"member"`) is exactly what an invite system needs to gate on, so building them
separately would have meant inventing a role system with nothing real to check it against, or an
invite system with no notion of who's allowed to send one.

- `POST /auth/register`'s user is always `"owner"` — they *are* the one who created the tenant.
- **`POST /auth/invite`** (owner-only, 403 otherwise) — `{email}`. 409s if the email is already
  registered. Issues an invite token (`token_type="invite"`, `settings.
  invite_token_expires_days` — a week by default) scoped to the *inviter's own tenant* — this is
  what actually lets someone join an *existing* tenant, unlike `POST /auth/register`, which always
  creates a brand-new one.
- **`POST /auth/accept-invite`** — `{invite_token, password}`. Creates the `UserAccount` (role
  `"member"`, same `tenant_id` the invite was scoped to) and revokes the invite token's `jti` via
  the *same* `TokenLedger.revoke` `POST /revoke` already uses — no second single-use mechanism
  built, since an already-accepted invite is functionally identical to a revoked one. Issues a
  normal access+refresh pair so the new member is logged in immediately.

`tests/integration/test_invite_flow.py` proves this end-to-end: an invitee lands in the *same*
tenant as the owner (not a new one) and can see/act on that tenant's data through the existing
isolation machinery; a member's own invite attempt is rejected (403); inviting an already-registered
email is rejected (409); accepting the same invite token twice is rejected (401, reusing
`TokenLedger`'s existing single-use guarantee); an access token presented at `/accept-invite` is
rejected the same way a refresh token is rejected elsewhere (`token_type` checked).

**What this still isn't**, as of v1.5.0: there's no way to change a role or remove a member after
the fact, and no listing who's in a tenant — closed below in "Tenant member management."

**Password reset & email verification**, added in v1.6.0, closing the last two gaps. Every token
this module hands to an email address (invite, password reset, and registration's verification
token) is now both sent through a real `EmailSender` *and* returned directly in the API response —
a real deployment would only do the former, but returning it too keeps every one of these flows
directly testable and usable without a real inbox, the same reasoning invites already established.

- **`core/email_sender.py`**'s `EmailSender` — matches `core/key_signer.py`'s Protocol-plus-
  default-plus-lazy-real-backend shape almost exactly, but it's a stateless dispatch service, not a
  WAL-backed trust ledger, which is why it lives in `core/` rather than `compliance/` alongside
  `ConsentLedger`/`TokenLedger`. `LoggingEmailSender` is the default, always-available backend
  (logs instead of sending). `SmtpEmailSender` is real dispatching code — `smtplib` +
  `email.message`, both stdlib, so unlike the AWS KMS/Vault `KeySigner` backends there's *no
  install extra needed at all* — but like them, it's unverified against a live server in this
  environment; a real connection failure there is left to propagate as a real error, not silently
  swallowed. `settings.email_backend` (`"logging"`/`"smtp"`) selects it, mirroring
  `wal_signer_backend`'s dispatch exactly (`core/email_sender_factory.py`).
- **`POST /auth/request-password-reset`** — `{email}`. Always 200s and never reveals whether the
  email is registered (`reset_token` is only present in the response when the account actually
  exists) — a real anti-enumeration property, not an oversight.
- **`POST /auth/reset-password`** — `{reset_token, new_password}`. Single-use (same `TokenLedger.
  revoke` reuse as invite tokens) and, since v1.6.1, revokes **every other active session** for that
  user too (`TokenLedger.revoke_all_sessions_for_subject`) — a password reset is exactly the "assume
  this account may have been compromised" moment a session-wide invalidation exists for, not just
  the one reset token. This needed a new index `TokenLedger` didn't have before: `record_session_
  started` tracks which `family_id`s belong to which subject (only on a fresh login — a
  `/auth/refresh` rotation continues the same session, not a new one to track), so
  `revoke_all_sessions_for_subject` has something real to revoke.
- **`POST /auth/verify-email`** — `{verify_token}` (issued alongside every token pair at `POST
  /auth/register`). Sets `UserAccount.email_verified`. Not single-use via `TokenLedger` the way
  invite/reset tokens are — verifying an already-verified email twice with the same token is a
  harmless no-op, not a security-relevant reuse, since `email_verified` itself is the durable
  record. Still not *enforced* anywhere — no route currently checks it — so treat it as real,
  queryable state rather than a functioning access gate.

`tests/integration/test_password_reset_and_verification.py` proves this end-to-end: requesting a
reset for an unregistered email still 200s with no token (the enumeration check); a reset actually
changes the password (the old one is rejected at `/auth/token`, the new one works); reusing a reset
token twice is rejected; registration's verify token flips `email_verified` and a second use is a
harmless no-op; **logging in twice (two independent sessions), then resetting the password, rejects
both old access tokens immediately** — not just the reset token — and never touches a different
user's session.

**What this still isn't**: `SmtpEmailSender` is real, dispatching code, unverified against a live
mail server; `email_verified` is tracked but not enforced anywhere.

**Tenant member management**, added in v1.7.0, closing the "no way to change a role or remove a
member after the fact, no listing who's in a tenant" gap this section flagged above. All three
routes operate strictly within the caller's own `tenant_id` (from the bearer token, same as every
other tenant-scoped route) — a `{email}` path parameter naming an account in a *different* tenant is
rejected with 404, not 403, so the endpoint never confirms whether that email exists anywhere else.

- **`GET /auth/members`** — any authenticated member of a tenant (not owner-gated: seeing your own
  team's roster isn't a privileged action). Returns `email`, `role`, `email_verified`, `created_at`
  for every member — never `password_hash`.
- **`POST /auth/members/{email}/role`** — owner-only (403 otherwise). `{role: "owner"|"member"}`.
  404 if the target isn't in the caller's own tenant. Demoting the tenant's *last* remaining owner to
  `"member"` is rejected with 409 — the one real invariant this feature has to protect, since a
  tenant with zero owners could never again change a role or remove a member itself.
- **`DELETE /auth/members/{email}`** — owner-only (403 otherwise), same 404/409-last-owner
  protection as role change. Also calls `TokenLedger.revoke_all_sessions_for_subject` (the same
  mechanism v1.6.1 built for password reset) — a removed member's already-issued access tokens stop
  working on their very next request, not just their ability to log in again.
- Both `_require_owner` and the last-owner check (`_would_leave_tenant_without_an_owner`) are shared
  helpers now used by `/auth/invite` too — extracted rather than writing a third near-duplicate
  owner-check inline.

`tests/integration/test_member_management.py` proves this end-to-end: an owner sees both themselves
and an invited member on the roster; a plain member can list but not change anything; promoting a
member to owner and demoting the original owner actually swaps who can manage the tenant afterward;
demoting or removing the tenant's last owner is rejected (409); a member removed mid-session has
their live access token rejected on the very next request, not just future logins.

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

**Acceptance revocation**, added in v1.8.0, closing "no way to revoke or amend an acceptance once
recorded" — e.g. the person who accepted is no longer with the organization, or a tenant otherwise
wants to withdraw its acceptance.

- **`POST /legal/revoke`** — owner-only (`{"role": "member"}` callers get 403), via the same
  `require_owner` dependency (`api/dependencies.py`) the member-management routes use — deciding
  who's an authorized signer for a tenant is exactly the same question either way, so this reuses
  that check rather than inventing a second one. Appends a `legal_disclaimer_revoked` WAL entry
  (never mutates or deletes the original acceptance entry — this is still an append-only log) and
  clears that tenant from `ConsentLedger`'s projection in the same call.
- No token-level cascade needed the way member removal needed one: `require_consent`
  (`api/dependencies.py`) already re-checks `has_accepted_current_disclaimer` fresh on every
  `/verification`/`/simulation` request, so a revocation blocks further calls immediately — the
  *same* still-valid access token that worked a moment before is rejected on its very next request,
  with nothing about the token itself having changed.
- A later `POST /legal/accept` re-establishes acceptance from scratch — revocation isn't a
  one-way door for the tenant, only for that specific acceptance record.

`tests/integration/test_consent_revocation.py` proves this end-to-end: an owner accepts, uses
`/verification` successfully, revokes, and is blocked again (403) on the same token with no new
token issued or revoked; re-accepting unblocks it again; a non-owner can't revoke (403), and their
rejected attempt leaves the tenant's existing acceptance untouched; revocation for one tenant never
affects another.

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
current scale — replay is now measured as linear at ~0.6us/entry
(`tests/unit/test_consent_scale.py`), with memory rather than time as the real ceiling — not
something that's been load-tested the way
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

### Structured obligations and express preemption

Added in v1.14.0 (`obligations/`). The first real attack on Layer 0 — the gap between statutory
prose and something a solver can reason over.

**The worked example is a real statute.** Fla. Stat. § 509.032(7)(b), fetched verbatim from the
Florida Senate:

> A local law, ordinance, or regulation may not prohibit vacation rentals or regulate the duration
> or frequency of rental of vacation rentals. This paragraph does not apply to any local law,
> ordinance, or regulation adopted on or before June 1, 2011.

Three features stacked in two sentences, each of which flattening into `if/else` destroys:

- **Scope.** It reserves *prohibition, duration, frequency* — and nothing else. A Florida city's
  night cap is void; the same city's parking requirement is untouched. Both are municipal, both
  concern short-term rentals, both sit below the state. **Tier cannot tell them apart.** That's why
  `SubjectMatter` exists.
- **Defeasibility.** The grandfather clause is an exception attached to the rule, keyed on the
  *adoption* date of the ordinance being tested. `adopted_date` is deliberately separate from
  `effective_date`: an ordinance passed in May 2011 that took effect in 2012 is grandfathered on the
  text as written, and conflating the two would decide real cases wrongly.
- **Containment.** A Florida statute reaches Florida's subdivisions. Nothing in the tier ordering
  says so — an Arizona city ordinance is also "municipal" and also "below state". `Obligation`
  carries a `jurisdiction_path` rather than a name because a bare name cannot express reach, and
  the bug is silent: the engine would confidently void ordinances in states the statute has never
  touched.

Outcomes are reported distinctly rather than as a boolean: `PREEMPTED`, `NOT_IN_SCOPE`,
`GRANDFATHERED`, `EXEMPTED`, `OUTSIDE_JURISDICTION`, `NOT_SUBORDINATE`, `UNDETERMINED`. A
grandfathered rule and an out-of-scope rule both survive, for different reasons, and a lawyer needs
to know which — the first is vulnerable to amendment in a way the second isn't.

**`UNDETERMINED` is the important one.** An ordinance with no adoption date, tested against a rule
with a grandfather cutoff, cannot be decided — and the engine says so, naming the missing fact,
rather than guessing in either direction. `survives` deliberately returns `False` for it, so a
caller checking one boolean can't read an unresolved question as a clean bill of health.

Only **express** preemption is modelled — where a statute says so in terms. Field and conflict
preemption require judgment about legislative intent and can't be decided from a taxonomy;
claiming otherwise would be exactly the overreach this codebase keeps refusing.

**What this still isn't**: extraction is not automated. The corpus is hand-encoded, so this proves
the *representation and the doctrine*, not that text can be read into it — which is the actual
Layer 0 problem and remains open. The statute is verbatim and sourced; the municipal ordinances are
**illustrative, not quoted**, because Municode disallows this crawler in robots.txt
(`User-agent: ClaudeBot` / `Disallow: /`). And none of it is legal advice.

### Reading prose into obligations

Added in v1.15.0 (`obligations/extraction.py`). With this, raw ordinance text reaches a preemption
verdict end to end:

```
"No dwelling unit may be rented as a vacation rental for more
 than 90 nights in any calendar year. Adopted March 12, 2019."
        ↓  KeywordObligationExtractor
 prohibition · {frequency} · adopted 2019-03-12
        ↓  express_preemption.analyze
 PREEMPTED — "regulates frequency, which Fla. Stat. § 509.032(7)(b)
 reserves to Florida, and it was adopted 2019-03-12, after the
 2011-06-01 cutoff."
```

All five outcomes are reachable from prose: preempted, grandfathered, out-of-scope, undetermined,
and wrong-state.

**The design point is not accuracy.** It's that `ExtractionResult` separates three things —
provisions classified, provisions recognised as **normative but unclassifiable**, and text with no
normative force. The middle category is why the module exists. If an extractor reads a night cap
and silently produces nothing, downstream analysis concludes the ordinance has no frequency rule
and reports the city as compliant. A wrong subject is visible; an absent one is not. So a result
carrying any unclassified provision is **incomplete**, and `is_complete` says so.

**Two bugs worth recording**, both found by running it rather than reading it:

- `\bno \w+ may\b` admits exactly one word between "No" and the modal. "No **dwelling unit** may
  be rented for more than 90 nights" is two — so it fell through to the permissive branch and a cap
  was classified as a **permission**. A modality error inverts the provision, which is strictly
  worse than any subject-matter mistake.
- The adoption-date pattern lacked `re.IGNORECASE`, and real ordinances write "Adopted March 12,
  2019" with a capital A. The date was silently missed, quietly downgrading a decidable
  grandfathering question to `UNDETERMINED`.

**A distinction the extractor has to make**: a night cap is a `FREQUENCY` rule expressed
prohibitively — subject `frequency`, modality `prohibition`. Only an *unqualified* ban is a
`PROHIBITION` **subject**. Conflating them would make every cap look like an outright ban, and the
two are preempted for different reasons.

**On the abstention gate**: `sample_and_gate` reuses `SemanticEntropyGate` over canonical
structural forms, clustering by exact match rather than entailment — these are structured records,
so two extractions either describe the same subjects and modalities or they don't. It detects an
*unstable* extractor. It cannot detect a confidently wrong one: a deterministic extractor is
perfectly self-consistent and may be perfectly wrong, scoring zero entropy every time.
Self-consistency is not correctness.

**What this still isn't**: keyword matching over surface forms, tuned to one narrow domain whose
vocabulary is small and repetitive. It will miss unusually phrased provisions — which is why they
surface as unclassified rather than as silence. `LlmObligationExtractor` carries the schema and the
parsing path, and has never made a call.

### Statutory conflict resolution

Extended in v1.12.0 (`knowledge_graph/preemption.py`). Three maxims in lexical order, each seeing
only what the ones before it couldn't decide:

1. **Lex superior** — higher authority wins, by `JurisdictionTier`. This is Article VI, and it is
   *first*: a general federal statute beats a specific municipal one even though lex specialis
   alone would say the opposite.
2. **Lex specialis** — the narrower rule wins. A defeats B when `scope(A)` is a strict subset of
   `scope(B)`.
3. **Lex posterior** — the later rule wins, **only where scopes are identical**. That restriction
   is the doctrine, not a shortcut: a newer statute about partly different subject matter sits
   alongside the old one rather than replacing it.

The handoff between 2 and 3 falls out of the scope relation instead of needing a rule of its own —
strictly narrower means specialis decides, equal means specialis is silent and posterior decides,
merely overlapping means both are silent and it stays unresolved. Ordering specialis before
posterior follows *lex posterior generalis non derogat legi priori speciali*; it's a jurisprudential
choice with real backing, not a mathematical necessity, and the module says so.

For three or more candidates the winner is the unique **undefeated** statute. "Undefeated" is about
surviving, not winning: a statute whose scope merely overlaps every rival defeats nothing and is
defeated by nothing, and it still blocks resolution. Testing "defeats something" instead would hand
the conflict to whichever statute happened to beat a *different* rival — that was a real bug in the
first draft, and `test_an_undefeated_rival_blocks_resolution` exists because of it.

`resolved_by` is on every result because a system that says "X governs" without saying *why* isn't
auditable — and the three maxims don't carry equal weight here. A `lex_superior` answer is a fact
about the jurisdictional hierarchy; a `lex_specialis` one rests on a proxy.

**About that proxy.** Scope is the set of entities a statute is linked to *in the graph*. That's
sound — a strict subset really is a narrower scope of application — but not complete: two statutes
can both apply to `{commercial-trucks}` while one governs, by its text, only those carrying
hazardous materials. Nothing in the entity model represents that, so this reports "no specificity
relation" where a lawyer sees an obvious one. The error runs toward **under-deciding and deferring
to review**, which is the right bias for a tool whose job is surfacing conflicts — but an
unresolved result is weak evidence that no specificity relation exists.

Scope comes from `GraphService.entities_for_statute` (added in this version) rather than from
`StatuteDocument.applies_to`. Those can legitimately disagree: `add_statute` takes `applies_to` as a
separate argument and never reconciles it with the field, and the candidate set comes from walking
the edges. Reading the field while selecting by edges compares two different relations, and fails
quietly — documents with an empty field all look equal-scoped, collapsing every conflict to
posterior or to review. The existing integration suite contained exactly that divergence, which is
how it was caught.

**What this still isn't**: it decides which statute wins once a candidate set is known. Whether two
statutes tied to the same entity actually contradict each other is a separate question — that's
`formal_logic/` (are their compiled clauses jointly UNSAT) or vector similarity surfacing a
candidate. Nothing here reaches into `deontic/`: a lex specialis exception is structurally a default
refined by an exception, which is what System E models, but that's a resemblance between layers, not
a dependency, and wiring them would couple two independent modules with no caller needing it.

### Refusing to start insecurely

Added in v1.13.0 (`core/startup_checks.py`). `jwt_secret` and `api_client_secret` both ship as
`"change-me-in-production"`, which is the right default for a repo you can clone and run — and
means a deployment that never set them signs every token with a value published in this
repository's source. Anyone who can read GitHub could mint a valid token for any subject and
tenant.

Nothing checked this. It was listed under Known limitations, which made it *acknowledged* rather
than *prevented*, and an acknowledged risk still ships.

- Outside a recognised development environment (`development`, `dev`, `local`, `test`, `testing`),
  startup **raises** on a placeholder or too-short secret. Every other guard here fails closed —
  `KeySigner`, `EmailSender`, `SemanticEntropyGate` — and a warning would be the same shape of
  mistake this project has now found three times: something that reads as a control and isn't one.
  A log line at startup gets scrolled past exactly once.
- Keyed on `environment` rather than `api_auth_enabled`, because "auth disabled in production" is
  itself a misconfiguration, not grounds for an exemption. Any unfamiliar environment name is
  treated as a deployment: erring toward refusing to boot costs seconds to fix, and the failure it
  prevents is not recoverable at all.
- The minimum length isn't arbitrary — RFC 7518 §3.2 requires an HS256 key at least as long as the
  hash output, so 32 characters is the standard's floor.
- All problems are reported at once, since one restart per problem is a miserable way to discover
  there were two.

Development is exempt, so the zero-config path and the whole test suite are unaffected.

### Email verification enforcement

Added in v1.13.0. `UserAccount.email_verified` was written by `POST /auth/verify-email` and
displayed by `GET /auth/members` from the day it was added, and gated nothing at all.
`settings.require_email_verification` turns on `require_verified_email` across every protected
router.

**Off by default**, deliberately: enabling it retroactively locks out every account registered
before it, which has to be a deliberate choice rather than a surprise on upgrade.

Three things must keep working when it's on, and each has a test:

- **The demo credential**, which has no `UserAccount` at all — it predates registration and is
  checked directly by `POST /auth/token`. Requiring a flag it can never carry would break the
  zero-config path for no security gain.
- **`POST /auth/verify-email`**, or the gate would deadlock the route that clears it.
- **Password reset**, or anyone who lost access before verifying would be stranded — unable to
  verify without the account and unable to reset without verifying.

The whole `/auth` router is outside the gate for those reasons. The check reads the account on each
request rather than anything baked into the token, so verifying unblocks an existing session
without re-login.

### Deontic reasoning

Added in v1.11.0 (`deontic/`). Standard Deontic Logic breaks on *contrary-to-duty* obligations —
what you ought to do given that you've already failed to do what you ought. Both classic
counterexamples derive outright contradictions in SDL, and both are the natural shape of a
compliance question, which is why this matters here rather than being a curiosity.

Conditional obligation is evaluated at the **best** antecedent-worlds:

```
Opt(φ) = { w ∈ W : w ⊨ φ and ∀w' ∈ W (w' ⊨ φ → w ⪰ w') }
O(ψ | φ)  ⟺  ∀w ∈ Opt(φ): w ⊨ ψ
```

- **Chisholm's Paradox** — Jones ought to help his neighbours; if he goes he ought to tell them; if
  he doesn't go he ought not tell them; he doesn't go. All four hold simultaneously here, and no
  contradiction is derivable, because the three obligations are evaluated at three *different*
  optimal sets rather than collapsing into one.
- **Forrester's gentle murder** — Smith ought not murder; if he murders he ought to do it gently;
  "gently" entails "murders." SDL detaches an obligation *to murder*. Blocked here:
  `O(gently | murders)` is evaluated at the best murder-worlds, which are not the best worlds.

**A tie is not a dilemma.** The source specification proposed halting whenever the betterness
relation "yields equal optimality over conflicting norm worlds" — i.e. on ties. System E requires
totalness of `⪰`, so ties are ubiquitous and `Opt(φ)` is almost always a multi-world set; that gate
would fire during ordinary operation. What actually indicates a dilemma is the optimal worlds
*disagreeing about ψ*, leaving neither `O(ψ|φ)` nor `O(¬ψ|φ)` true. `Verdict.is_dilemma` tests
that, and there's a test with a genuine tie that determines its subject perfectly well.

Vacuity is reported separately: when `Opt(φ)` is empty, *every* obligation conditional on φ holds,
including a proposition and its negation — classically correct, practically a red flag, and a
different condition from a dilemma.

**What this still isn't**: finite-model *evaluation*, not theorem proving. It answers "does this
hold in the model you gave me," not "is this a theorem of E." The obvious alternative — the LogiKEy
shallow embedding in Isabelle/HOL — is more powerful and weaker in a different way, since HOL is
undecidable and `sledgehammer` can simply not return. This codebase already stakes a decidability
claim on `formal_logic/`'s EPR fragment; presenting an undecidable engine as a strengthening would
misrepresent both, and nothing here touches the EPR compiler. Limitedness — every satisfiable φ
having a non-empty `Opt(φ)` — comes free on finite models, so the axiom Åqvist needs in general is
a theorem here.

### Regulatory control

Added in v1.11.0 (`game_theory/hjb.py`). A regulator watches a compliance gap `x` and picks an
enforcement intensity `u`; the gap drifts and gets shocked, `dx = (a·x + b·u) dt + σ dW`, and the
regulator trades the harm of non-compliance (`q·x²`) against the cost of enforcement (`r·u²`).
Auditing isn't free, and a regulator that ignores that will over-enforce.

**The spec defect this resolves.** It mandated linear-quadratic structure *and* a "unique viscosity
solution" by implicit finite differences. Those pull opposite ways: viscosity solutions are the
machinery for when the value function *isn't* smooth, but if the problem is genuinely LQ then `V`
is a smooth quadratic, the HJB collapses to a Riccati ODE, and you can write the answer down.

The resolution isn't to pick one — it's that they stand in a different relationship than the spec
supposed. The finite-difference sweep is the general tool; the LQ closed form is its **test
oracle**. `solve_hjb` knows nothing about the quadratic structure and discretises the equation as
written; `riccati_solution` computes the exact answer independently; the tests check they agree
*and* that the error falls at the second-order rate central differences should give. Agreement to a
tolerance can be luck on one grid — a sign error or mis-centred stencil usually still converges,
just at first order — so the rate is the check that's hard to fake.

**It refuses σ = 0** rather than returning `NaN`. With no diffusion the equation is pure advection,
and forward-Euler with central differences is *unconditionally* unstable there — no time step
helps. Upwinding would fix stability at the cost of dropping to first order, which would also cost
the convergence-rate check. The deterministic case has an exact solution anyway, and the error says
so.

**What this still isn't**: no jump term (the spec's compensated Poisson measure would make this a
partial integro-differential equation and leave no closed form to validate against), one state
dimension, and **not a Stackelberg game**. The spec described a leader-follower equilibrium and
asserted it reduces to a single control problem "via exact first-order potential game conditions";
Stackelberg games don't generically admit that reduction and the structure justifying one was never
established. What's solved here is the single-agent control problem honestly, not a two-player
equilibrium relabelled.

### Trusted timestamping

Added in v1.10.0 (`core/timestamper.py`), the one infrastructure item from the v2.0 proposal that
closed a gap this codebase genuinely had rather than restating something already solved.

**The gap.** `WriteAheadLog.append` stamps `datetime.now(UTC)` from the host's own clock, signs it,
and chains it. That is tamper-*evidence*: you can't alter an entry without breaking the chain. It
is not *time* evidence. Someone who controls the machine can set the clock back and produce a chain
that verifies perfectly. Every timestamp in the system was self-asserted.

- **`LocalTimestamper`** is the default and is deliberately **not** trusted timestamping — it reads
  the local clock and returns `source="local"`. That field is on the token rather than in a
  docstring on purpose: a caller cannot accidentally treat a local stamp as third-party
  attestation, and the distinction survives being persisted or displayed. It exists so the
  anchoring path is exercisable offline, the role `LoggingEmailSender` plays for email.
- **`Rfc3161Timestamper`** is real TSP dispatch behind the `tsp` extra (pyasn1 — pure Python, no
  native extensions, so unlike the sentence-transformers and cvxpy families it's also in `dev` and
  its encoding/parsing run in the normal suite).
- **`anchor(wal, timestamper)`** timestamps the head hash. One token attests the entire log,
  because the chain already commits backwards. It's a free function rather than a `WriteAheadLog`
  method: the WAL holds together with no notion of trusted time, and anchoring is something done
  *to* a WAL by whoever has a TSA configured.

**What it verifies**: response status, that the returned nonce equals the one sent (anti-replay —
without it a recorded response could be replayed against any later request), that the returned
message imprint equals the digest submitted (the TSA stamped *our* data, not something else), and
that the hash algorithm matches. Every mismatch raises; it fails closed.

**What it does not verify — and won't**: the TSA's signature over the token, or its certificate
chain. This isn't a to-do. `cryptography` 50.x exposes no CMS/PKCS#7 *verification* API at all
(checked by introspection, not assumed — only decrypt and certificate loading), and hand-rolling
CMS signature validation is exactly the category of security code that shouldn't be hand-rolled.
So the full DER token is retained on the returned `TimestampToken` and verification is an explicit
separate step against a real trust store:

```bash
openssl ts -verify -in token.tsr -data anchored.bin -CAfile tsa-ca.pem
```

Read a `source="tsa"` token as *"a TSA granted this and the nonce and imprint round-tripped,"* not
as *"cryptographically verified."*

`tests/unit/test_timestamper.py` exercises this against genuine DER rather than a mock standing in
for it — unlike the KMS/Vault signers, where the wire format belongs to AWS and Vault, TSP's
structures *are* the standard, so the tests assemble a real `TimeStampResp` (CMS `SignedData`
wrapping a context-tagged `TSTInfo`) and the client parses actual bytes. Every rejection path has a
test: rejected status, replayed nonce, substituted digest, wrong hash algorithm, missing token,
wrong content type, and garbage.

**What this still isn't**: never exercised against a live TSA — same honesty category as the
KMS/Vault signers. `anchor()` is a library call with no scheduler behind it; nothing anchors
periodically on its own, and choosing an anchoring cadence is a real operational decision this
doesn't make for you.

### Semantic entropy abstention gate

Added in v1.9.0 (`uncertainty/`). The premise (Kuhn et al.; Farquhar et al., *Nature* 2024): to
tell a confident model from a confabulating one, sample the same question N times and measure
whether the samples agree about *meaning* rather than about wording. Group them into clusters by
bidirectional entailment, then take the Shannon entropy of the cluster distribution. One meaning
repeated N times is entropy 0. N incompatible meanings is the maximum. Above a threshold, the
honest response is to abstain rather than return whichever sample came first.

This was built from a v2.0 spec whose version of the gate could never fire, and the correction is
the interesting part:

**The ceiling is the load-bearing detail.** Entropy over a partition of exactly N samples is
bounded by log(N), attained only when every sample forms its own cluster. For the usual N=10 that
ceiling is **log(10) = 2.3026 nats** (3.3219 bits). The source spec set the abstention threshold at
**8.5** — roughly 3.7× above a bound nobody re-derived while reading it. Nothing about that
misconfiguration is noisy: no exception, no log line, every input simply passes, and the abstention
path stays permanently unreachable while still appearing present in the design document. A gate
that always passes is strictly worse than no gate, because it's credited as a safety control.

So the threshold is validated against `max_entropy(n_samples)` at **construction**, not at call
time, and `SemanticEntropyGate` refuses to build:

```
ValueError: entropy_threshold=8.5 cannot fire for n_samples=10: semantic entropy over 10
generations is bounded by log(10) = 2.3026 nats, so the gate would pass every input and its
abstention path would be unreachable. Choose a threshold in [0.0, 2.3026).
```

`uncertainty/factory.py` deliberately does no clamping — a bad threshold in settings propagates as
this error rather than being quietly repaired into range, since silently repairing it restores the
exact failure mode the check exists to catch. `evaluate()` likewise requires exactly `n_samples`
generations: accepting fewer would lower the ceiling without re-checking the threshold against it,
which is the side door back to an unfireable gate after `__init__` closed the front one.

- **`EntailmentModel`** (`uncertainty/entailment.py`) — same Protocol-plus-always-available-
  default-plus-lazy-real-backend shape as `Embedder`/`KeySigner`/`EmailSender`.
  `LexicalEntailmentModel` is the default: deterministic token-containment scoring, no ML
  dependencies, so the whole suite runs against it. It is explicitly *not* a semantic model — it
  reads "the contract is void" and "the agreement is invalid" as unrelated. That error runs in the
  safe direction: under-clustering splits one meaning across several clusters, which *raises*
  measured entropy and makes the gate abstain more readily than a real NLI model would. A
  hallucination gate that errs toward abstention fails safe; one that errs toward passing does not.
  `CrossEncoderEntailmentModel` lazy-imports a real NLI cross-encoder behind the `semantic` extra
  and fails closed with an install hint here, since torch's native extensions don't load in this
  environment.
- **Negation is the one thing the lexical default gets exactly right**, and it's the property worth
  protecting: "the clause is enforceable" and "the clause is not enforceable" differ by a token
  containment scoring sees, so they never merge. No stopword filtering is applied anywhere in that
  module specifically to keep this true — dropping "not" as a stopword would collapse an answer
  with its own negation and report confident agreement exactly where the model contradicted itself.
- **Clustering is greedy first-match against each cluster's representative**, not a transitive
  closure over all pairs. Bidirectional entailment isn't empirically transitive, so a closure can
  chain a→b→c while a and c are plainly different answers, silently merging meanings and
  under-reporting entropy.
- **Default threshold is 1.0 nats**, just under log(3) = 1.0986: a dominant answer with a couple of
  strays passes (8/1/1 scores 0.639, 9/1 scores 0.325, an even 5/5 split scores 0.693), while a
  genuine three-way disagreement fires (4/3/3 scores 1.089).

`tests/property/test_semantic_entropy_bounds.py` proves the 0 ≤ H ≤ log(N) bound generatively over
arbitrary partitions rather than the handful of shapes the unit tests enumerate — worth proving
rather than assuming, given that assuming a ceiling 3.7× too high is the defect being corrected.
It also proves clustering always returns a true partition of its input, which is what makes cluster
sizes a valid probability distribution to take entropy over.

**What this still isn't**: a library primitive with no caller wired to it. There is no LLM anywhere
in this codebase — no constrained-decoding extraction path exists for it to gate, and inventing one
that can't actually run here would be worse than leaving the seam honest. The `cross_encoder`
backend has never been exercised against a real checkpoint, and its `entailment_label_index` is
checkpoint-specific: pointing it at the wrong index would not raise, it would score contradiction
as entailment and drive measured entropy toward zero. Threshold calibration is reasoned from the
cluster arithmetic above, not tuned against a labelled legal corpus.

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

- **The Playwright suite now runs in CI across all three browsers, and passes.** For most of this
  project's history that was aspirational: the workflow existed but had never executed (see the CI
  bullet below). Chromium, Firefox and WebKit all pass as of the first real run. What's still true:
  this is a handful of runs, not a record over time, and the suite covers the three dashboard
  components rather than the whole surface.
- **Every gap this section originally named is closed now; a handful of smaller, honestly-scoped
  ones remain.** As of v1.2.0, `StatuteRepository`/`GraphService`/`VectorIndex` are genuinely
  tenant-scoped end to end; as of v1.3.0, `POST /auth/register` provisions genuine, independent
  tenant/credential pairs; as of v1.4.0, a leaked or stolen access token can actually be revoked
  (not just wait out its `settings.jwt_expires_minutes` expiry), and refresh tokens are genuinely
  redeemable, single-use, rotating; as of v1.4.1, reusing a spent refresh token revokes the whole
  session, not just that one token; as of v1.5.0, an owner can invite a real second user into their
  *existing* tenant, with a real (if minimal) role distinction gating who's allowed to; as of
  v1.6.0, password reset and email verification are real, working flows, sent through a real
  (if here-unverified) `EmailSender`; as of v1.6.1, a password reset kills every other active
  session for that user, not just the reset token itself; as of v1.7.0, an owner can list, promote,
  demote, or remove a tenant's members, with a removal killing that member's live sessions
  immediately (see "User accounts, tokens & revocation" above for all eight) — none of that
  aspirational. As of v1.13.0, `email_verified` actually gates
  something — `settings.require_email_verification` turns on a check across every protected router,
  off by default because enabling it retroactively locks out accounts registered before it. What's
  still missing: `SmtpEmailSender` has never been exercised against a real mail server, so the
  verification email that gate depends on is dispatched by code that has never delivered one.
- **The liability-disclaimer consent record is real (tamper-evident, tied to a server-verified
  token subject, tenant-scoped, and — since `ConsentLedger` — an O(1) indexed lookup rather than a
  WAL scan) but its supporting infrastructure is still minimal.** The WAL's signing key is a
  plaintext file on disk by default (`Ed25519FileKeySigner`) — `settings.wal_signer_backend` can
  point this at AWS KMS or Vault instead (`core/key_signer.py`), real dispatching code, but neither
  path has been exercised against an actual AWS account or Vault instance. As of v1.8.0, an owner
  can revoke an acceptance (`POST /legal/revoke` — "the tenant's authorized signer changed" flow),
  which is itself just another appended, tamper-evident WAL entry, not a mutation of the original
  one — append-only is still the point. `ConsentLedger` itself is an in-process index rebuilt by a
  full WAL replay at every startup, not a persisted index of its own. That used to be flagged as
  "untested at any real scale"; as of v1.13.0 it's measured rather than assumed
  (`tests/unit/test_consent_scale.py`). Both replay and the disk load that precedes it are linear —
  roughly 0.6 and 3.9 microseconds per entry — so a million-entry log costs about five seconds of
  startup. **The real ceiling is memory, not time**: at ~546 bytes per entry that same log is
  ~550 MB resident, because `WriteAheadLog` holds every entry in a list. Nothing addresses that
  yet. See "Liability disclaimer & consent" above for what it does establish.
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

`tests/integration/test_postgres_repository.py` and `test_postgres_user_repository.py` skip
themselves unless `LEGAL_ENGINE_TEST_POSTGRES_DSN` is set (and need the `postgres` extra installed)
— they're what CI's `postgres` job runs against a real Postgres service container; there's nothing
to configure for the rest of the suite, which tests the same repositories against SQLite instead.
Any future SQL-backed store should get an entry in that job too: the user repository was added in
v1.3.0 and went uncovered there until v1.9.2, running against SQLite alone the whole time.

[`AGENTS.md`](AGENTS.md) covers the conventions that aren't obvious from the code — the release
ritual, the optional-backend pattern, the environment gotchas, and the rule that pasted plans get
verified against the codebase before anything is built. [`docs/v2-proposal.md`](docs/v2-proposal.md)
is the review of a proposed v2.0 architecture: one node of it shipped (the semantic-entropy gate),
three remain buildable, two can't be built here, and six defects are documented — including an
abstention threshold that could never fire and a pooling pattern that would have leaked data across
tenants. It's a record of what was assessed, not a plan of record.

CI runs six jobs — lint/type-check/tests, Postgres integration, the UI build, and Playwright
across Chromium, Firefox and WebKit. Worth knowing the history: the workflow existed from the start
and **had never once executed**, because its trigger named `branches: [main]` while the branch is
`master`. Twelve releases shipped against a pipeline that was never a gate. The first real run
failed immediately (asyncpg rejects timezone-aware datetimes bound to naive timestamp columns — see
v1.9.2 and the `_as_utc`/`timezone=True` note in `persistence/sql_repository.py`), which is a fair
summary of what "configured but unverified" is worth.

Three gates run in CI and should be run locally before a commit:

```bash
ruff check .
mypy src/legal_engine   # strict mode, src only
pytest
```

`mypy` deliberately does **not** pin `python_version` in `pyproject.toml`, unlike ruff's
`target-version = "py311"`. Pinning it to 3.11 makes mypy unrunnable on any newer local
interpreter: numpy ≥ 2.5 requires Python ≥ 3.12 and its stubs use PEP 695 `type` statements, which
are a *syntax* error under a 3.11 target — and a stub syntax error aborts the whole run before a
single first-party file is checked (`ignore_errors` and `follow_imports = "skip"` were both tried;
neither suppresses it). Unpinned, each environment targets its own interpreter and both work: CI
installs a 3.11-era numpy under 3.11 and checks against 3.11, which is the run that gates merges.
Strict mode is enforced on `src/` only — the test suite leans on pytest fixtures and monkeypatching
that strict mode would fight without catching anything real.

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
