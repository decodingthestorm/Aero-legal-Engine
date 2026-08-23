# Legal Engine Platform

A legal ingestion, formal verification, and game-theoretic statutory optimization platform.

## What's built so far (Phases 1-2)

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

Everything above has a passing unit and integration test suite under `tests/`.

Each optional "real backend" (Neo4j, Qdrant, sentence-transformers) is behind a lazy import and
an install extra (`pip install -e ".[graph-neo4j,vector-qdrant,semantic]"`) — the default,
tested path never requires them.

## Not yet implemented

`ingestion/`, `api/`, `workers/`, `ui/`, Docker/k8s deployment, and the WAL are scaffolded
(directory structure + stub modules) but not built out yet — see the phased plan below.

One deliberate deviation from the original spec: ingestion is planned as a polite, rate-limited
crawler (respects `robots.txt`, conservative concurrency, honest User-Agent, standard
retry/backoff) rather than the TLS-fingerprint-impersonation ("anti-blocking") approach
originally specified, to avoid building active anti-detection tooling.

## Development

```bash
python -m venv .venv
.venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
pytest
```

## Phased build plan

1. **Core schemas, formal logic & game theory** — done.
2. **Hybrid knowledge graph & preemption resolver** — done.
3. Ingestion subsystem & structured parsers (polite crawling).
4. State ledger (WAL), Celery workers & FastAPI gateway.
5. Production infrastructure, Next.js UI & release.
