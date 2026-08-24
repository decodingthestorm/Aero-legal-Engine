"""Proves SolverPool is safe under real concurrent use.

This is the regression test for a genuine bug: the pre-fix version of
solver_pool.py built every Z3 object on Z3's implicit default/global
context. Every existing unit test used pool_size=1 (sequential), so it
never exercised true concurrency and never caught this. Running the API
under real concurrent HTTP load with the default pool_size=4 reliably
reproduced z3.Z3Exception("not a valid ast") and outright native
access-violation crashes within seconds — Z3's default context genuinely
isn't safe to touch from multiple threads at once. See solver_pool.py's
module docstring for the fix (one z3.Context() per check() call).

This test drives many concurrent SolverPool.check() calls directly via a
thread pool — the same concurrency shape a busy API sees, without needing
a running server or an HTTP load-testing tool to prove it.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from legal_engine.formal_logic.ast_nodes import And, Atom, Constant, Implies, Not, Variable
from legal_engine.formal_logic.epr_compiler import compile_epr_formula
from legal_engine.formal_logic.solver_pool import SolverPool

_DOMAIN = tuple(f"actor_{i}" for i in range(8))


def _satisfiable_formula():
    return compile_epr_formula(
        exists_vars=(),
        forall_vars=("x",),
        matrix=Implies(
            Atom("Owns", (Variable("x"),)),
            Atom("Reports", (Variable("x"),)),
        ),
        domain=_DOMAIN,
    )


def _unsatisfiable_formula():
    matrix = And(
        (
            Implies(Atom("Owns", (Variable("x"),)), Atom("Reports", (Variable("x"),))),
            Atom("Owns", (Constant("actor_0"),)),
            Not(Atom("Reports", (Constant("actor_0"),))),
        )
    )
    return compile_epr_formula(exists_vars=(), forall_vars=("x",), matrix=matrix, domain=_DOMAIN)


def test_many_concurrent_checks_do_not_crash_or_corrupt_results():
    pool = SolverPool(pool_size=4, timeout_ms=2000, memory_limit_mb=512)
    sat_formula = _satisfiable_formula()
    unsat_formula = _unsatisfiable_formula()

    # Interleave both formulas across many concurrent calls: if contexts
    # were ever shared/corrupted across threads, this is exactly the shape
    # that would flip a result to the wrong verdict (or crash the process).
    jobs = [sat_formula if i % 2 == 0 else unsat_formula for i in range(60)]

    results = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(pool.check, formula) for formula in jobs]
        for future in as_completed(futures):
            results.append(future.result())  # re-raises if check() raised (e.g. a Z3Exception)

    assert len(results) == 60


def test_concurrent_checks_return_correct_verdicts_per_formula():
    pool = SolverPool(pool_size=4, timeout_ms=2000, memory_limit_mb=512)
    sat_formula = _satisfiable_formula()
    unsat_formula = _unsatisfiable_formula()

    jobs = [sat_formula if i % 2 == 0 else unsat_formula for i in range(40)]

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(pool.check, formula): formula for formula in jobs}
        for future in as_completed(futures):
            formula = futures[future]
            result = future.result()
            expected_satisfiable = formula is sat_formula
            assert result.satisfiable == expected_satisfiable, (
                "a concurrent check returned the wrong verdict for its own formula - "
                "exactly the kind of cross-thread state corruption a shared Z3 "
                "context produces"
            )
