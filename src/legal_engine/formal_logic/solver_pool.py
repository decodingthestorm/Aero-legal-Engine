"""Bounded-concurrency Z3 solver pool with hard timeout and memory limits.

Builds Z3 objects directly from an ``EPRFormula`` (rather than re-parsing the
SMT-LIB2 text from smt_generator.py) so that each top-level conjunct of the
matrix can be asserted with ``assert_and_track``, which is what makes
``solver.unsat_core()`` return something useful instead of an opaque blob.

On sandboxing: this pool enforces Z3's own ``timeout`` and
``memory_max_size`` parameters, which stop a single check from running away
inside the process. That is process-internal resource control, not OS-level
sandboxing (no seccomp/cgroup/namespace isolation happens here) — real
isolation between tenants should come from running workers in the
resource-limited containers defined under docker/ and k8s/, not from this
module alone. Documenting that boundary honestly beats calling this
"sandboxed" and having it mean less than the name implies.
"""

from __future__ import annotations

import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass

import z3

from legal_engine.core.exceptions import SolverTimeoutError
from legal_engine.core.models import ProofResult
from legal_engine.formal_logic.ast_nodes import (
    And,
    Atom,
    Constant,
    EPRFormula,
    Formula,
    Implies,
    Not,
    Or,
    Term,
    Variable,
)


@dataclass
class _Z3Context:
    sort: z3.SortRef
    constants: dict[str, z3.ExprRef]
    predicates: dict[str, z3.FuncDeclRef]


def _build_context(formula: EPRFormula) -> _Z3Context:
    # Z3's default context registers enum sort names globally, so reusing a
    # fixed name (e.g. "Individual") across successive checks in the same
    # process raises "enumeration sort name is already declared". Each check
    # gets its own throwaway sort.
    sort_name = f"Individual_{uuid.uuid4().hex[:12]}"
    sort, domain_consts = z3.EnumSort(  # type: ignore[misc]
        sort_name, list(formula.domain)
    )
    constants = {name: const for name, const in zip(formula.domain, domain_consts)}
    predicates: dict[str, z3.FuncDeclRef] = {}
    for predicate, arity in formula.predicate_arities.items():
        predicates[predicate] = z3.Function(predicate, *([sort] * arity), z3.BoolSort())
    return _Z3Context(sort=sort, constants=constants, predicates=predicates)


def _term_to_z3(term: Term, ctx: _Z3Context, bound: dict[str, z3.ExprRef]) -> z3.ExprRef:
    if isinstance(term, Constant):
        return ctx.constants[term.name]
    if isinstance(term, Variable):
        return bound[term.name]
    raise TypeError(f"Unknown term node: {term!r}")


def _formula_to_z3(formula: Formula, ctx: _Z3Context, bound: dict[str, z3.ExprRef]) -> z3.BoolRef:
    match formula:
        case Atom(predicate, args):
            z3_args = [_term_to_z3(a, ctx, bound) for a in args]
            return ctx.predicates[predicate](*z3_args)
        case Not(operand):
            return z3.Not(_formula_to_z3(operand, ctx, bound))
        case And(operands):
            return z3.And(*[_formula_to_z3(op, ctx, bound) for op in operands])
        case Or(operands):
            return z3.Or(*[_formula_to_z3(op, ctx, bound) for op in operands])
        case Implies(antecedent, consequent):
            return z3.Implies(
                _formula_to_z3(antecedent, ctx, bound), _formula_to_z3(consequent, ctx, bound)
            )
        case _:
            raise TypeError(f"Unknown formula node: {formula!r}")


class SolverPool:
    """A bounded-concurrency pool of Z3 solver invocations.

    Not a literal object pool of reusable ``z3.Solver`` instances — each
    ``check()`` call constructs a fresh solver, since Z3 solvers are cheap to
    create and reusing one across unrelated formulas risks leaking learned
    clauses/assumptions between callers. "Pool" here means bounded
    concurrency: at most ``pool_size`` checks run at once.
    """

    def __init__(self, pool_size: int = 4, timeout_ms: int = 480, memory_limit_mb: int = 512):
        self._semaphore = threading.Semaphore(pool_size)
        self._timeout_ms = timeout_ms
        self._memory_limit_mb = memory_limit_mb

    @contextmanager
    def _slot(self):
        self._semaphore.acquire()
        try:
            yield
        finally:
            self._semaphore.release()

    def check(self, formula: EPRFormula) -> ProofResult:
        with self._slot():
            z3.set_param("memory_max_size", self._memory_limit_mb)

            ctx = _build_context(formula)
            solver = z3.Solver()
            solver.set("timeout", self._timeout_ms)

            bound: dict[str, z3.ExprRef] = dict(ctx.constants)
            for var in formula.exists_vars:
                bound[var] = z3.Const(var, ctx.sort)
            for var in formula.forall_vars:
                bound[var] = z3.Const(var, ctx.sort)

            body = _formula_to_z3(formula.matrix, ctx, bound)
            if formula.forall_vars:
                body = z3.ForAll([bound[v] for v in formula.forall_vars], body)
            if formula.exists_vars:
                body = z3.Exists([bound[v] for v in formula.exists_vars], body)

            track_label = "goal"
            solver.assert_and_track(body, track_label)

            start = time.perf_counter()
            result = solver.check()
            elapsed_ms = (time.perf_counter() - start) * 1000

            if result == z3.unsat:
                core = [str(c) for c in solver.unsat_core()]
                return ProofResult(satisfiable=False, unsat_core=core, elapsed_ms=elapsed_ms)

            if result == z3.sat:
                model = solver.model()
                counterexample = {str(d): str(model[d]) for d in model.decls()}
                return ProofResult(
                    satisfiable=True, counterexample=counterexample, elapsed_ms=elapsed_ms
                )

            # z3.unknown: either the hard timeout tripped or the memory cap was hit.
            reason = solver.reason_unknown()
            if "timeout" in reason.lower() or "canceled" in reason.lower():
                raise SolverTimeoutError(
                    f"Z3 did not reach a verdict within {self._timeout_ms}ms: {reason}"
                )
            return ProofResult(satisfiable=False, elapsed_ms=elapsed_ms, timed_out=True)
