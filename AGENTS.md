# Working in this repo

Conventions an agent needs that aren't obvious from the code. The README is the
reference for *what exists and why*; this file is only about *how to work here*, and
deliberately stays short so it doesn't drift out of date the way a second copy of the
README would.

## Before you commit

Three gates, all of which run in CI:

```bash
ruff check .
mypy src/legal_engine    # strict; `make typecheck` runs the same thing
pytest
```

If a stray `data/` directory appears in the repo root, `rm -rf data` before staging.
It's gitignored and doesn't affect pass/fail. This used to be a required step — the
claim here was that `tests/conftest.py`'s autouse `_isolate_wal_path` fixture leaked
`data/wal/signing_key.bin` on a full run. Three consecutive clean runs say otherwise, so
the fixture is doing its job and the original observation was probably from running the
API manually rather than the suite. Left as a "if you see it" note rather than deleted,
since an intermittent fault can't be disproven by three runs.

## Verify before you implement

Plans, roadmaps, and specs pasted into a session are **proposals, not instructions** —
including ones that look authoritative and including this repo's own
`docs/v2-proposal.md`. Check every claim against the actual codebase and the actual
environment before building anything: read the file, run the command, check whether the
package imports. Correct or reject the parts that don't survive that, and say so
plainly rather than implementing around them.

This is not caution for its own sake. Doing it has repeatedly found real defects that
were stated confidently — an abstention threshold set 3.7× above the mathematical
ceiling of the quantity it gated on, a session-pooling pattern that would have leaked
data across tenants, a mandated range check requiring 4.3 billion constraints. See
`docs/v2-proposal.md` for the full set.

The same rule applies to this codebase's own claims about itself. `mypy` sat configured
and unrun for the project's entire history, and `SqlAlchemyUserRepository` ran from
v1.3.0 to v1.9.2 with CI coverage that silently didn't include it. Both looked fine from the
config file.

## Releasing

Bump the version in **four** files together, or the API reports a version the package
doesn't have:

- `pyproject.toml`
- `src/legal_engine/__init__.py`
- `src/legal_engine/api/main.py` (the `FastAPI(...version=...)` argument)
- `ui/package.json`

MINOR for a new capability area, PATCH for scoped work inside an existing one. Every
release adds a bullet to the README's version-history list at the top saying which
specific gap it closed — that list is the project's spine and the reason each version
is justifiable rather than incidental.

## Code conventions

**Optional backends follow one shape**: a `Protocol`, an always-available default
implementation that the whole test suite runs against, and a lazily-imported "real"
backend behind an install extra. See `core/key_signer.py`, `core/email_sender.py`,
`uncertainty/entailment.py`, `knowledge_graph/embeddings.py`.

**Lazy imports catch `Exception`, not `ImportError`.** Native extensions fail in ways
that surface as `OSError` or an internal `ImportError` rather than "no module named X"
— a Windows Application Control policy blocking a DLL, a CUDA mismatch. Normalize
whatever comes back into one `ImportError` with a `pip install` hint. This is why
`torch` and `cvxpy` don't take the process down here.

**Docstrings explain the decision, not the mechanics.** The convention throughout is to
say what was considered and rejected, and why — see `compliance/consent.py` or
`persistence/sql_repository.py`'s `_as_utc`. When you change behaviour, check whether a
nearby docstring just became false; `UserAccount`'s claimed roles couldn't be changed
for three releases after they could.

**Every README feature section ends with "What this still isn't."** Keep it accurate.
The project's credibility rests on those paragraphs being true, so an unverified claim
costs more than an unbuilt feature.

## Environment gotchas

- **Windows.** PowerShell is primary; a Git Bash tool is also available. Each takes its
  own syntax.
- **The venv is Python 3.14; CI runs 3.11.** `mypy`'s `python_version` is deliberately
  unpinned so both work — see the long note in `pyproject.toml` before changing it.
- **No Node, no Postgres, no GPU toolchain locally.** The Playwright suite (`ui/e2e/`)
  and both Postgres suites only run in CI. Postgres tests skip-gate on
  `LEGAL_ENGINE_TEST_POSTGRES_DSN`; **any new SQL-backed store needs adding to that CI
  job explicitly** — the user repository was missed there from v1.3.0 to v1.9.2.
- To sanity-check a Postgres test's *logic* locally, point that env var at a
  `sqlite+aiosqlite:///` DSN. It validates the assertions, not the Postgres-specific
  behaviour.

## Testing

`tests/unit`, `tests/integration`, `tests/property` (Hypothesis). Integration tests go
through the real app via `TestClient(app)` rather than asserting at the unit level —
match that. Reach for a property test when the thing being asserted is a bound or an
invariant rather than a case; `tests/property/test_semantic_entropy_bounds.py` exists
because assuming a ceiling was the original bug.

`core/logging.py` uses `structlog.PrintLoggerFactory`, which writes straight to stdout
and bypasses stdlib `logging` entirely — **`caplog` cannot capture it, use `capsys`**.
