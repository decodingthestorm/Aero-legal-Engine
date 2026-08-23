"""Compiles clause specifications into decidable EPR (Bernays-Schoenfinkel-Ramsey) formulas.

Three structural guarantees are checked before a formula is accepted:

1. Prenex normal form, exists* then forall* — enforced by ``EPRFormula``'s
   shape (see ast_nodes.py); we additionally reject empty variable lists that
   would make ordering meaningless is not required, so nothing to check here.
2. No function symbols of arity > 0 — enforced structurally: ``Term`` has no
   function-application node, only ``Constant``/``Variable``.
3. Finite domain of discourse — checked explicitly below, since ``domain``
   is a plain tuple and nothing stops a caller from passing one that isn't
   actually bounded at the call site.

On top of the three EPR conditions, we check well-formedness that a
classical FOL compiler would also need: every free variable in the matrix is
bound by a quantifier, and every predicate is applied with a consistent
arity throughout the formula.
"""

from __future__ import annotations

from legal_engine.core.exceptions import NotEPRFragmentError
from legal_engine.formal_logic.ast_nodes import (
    And,
    Atom,
    Constant,
    EPRFormula,
    Formula,
    Implies,
    Not,
    Or,
    free_variables,
)

_MAX_DOMAIN_SIZE = 10_000
"""Hard ceiling on |domain| so a caller can't accidentally pass something
effectively unbounded (e.g. a generator materialized into a huge list) and
still call it 'finite'. EPR is decidable for any finite domain in principle,
but solver runtime grows with domain size, and the whole point of the EPR
fragment here is sub-second (480ms) verification."""


def _collect_predicate_arities(formula: Formula, arities: dict[str, int]) -> None:
    match formula:
        case Atom(predicate, args):
            arity = len(args)
            if predicate in arities and arities[predicate] != arity:
                raise NotEPRFragmentError(
                    f"Predicate {predicate!r} used with inconsistent arities "
                    f"({arities[predicate]} and {arity})"
                )
            arities[predicate] = arity
        case Not(operand):
            _collect_predicate_arities(operand, arities)
        case And(operands) | Or(operands):
            for op in operands:
                _collect_predicate_arities(op, arities)
        case Implies(antecedent, consequent):
            _collect_predicate_arities(antecedent, arities)
            _collect_predicate_arities(consequent, arities)
        case _:
            raise NotEPRFragmentError(f"Unknown formula node: {formula!r}")


def compile_epr_formula(
    exists_vars: tuple[str, ...],
    forall_vars: tuple[str, ...],
    matrix: Formula,
    domain: tuple[str, ...],
) -> EPRFormula:
    """Validate and assemble an EPRFormula. Raises NotEPRFragmentError on any violation."""

    if not domain:
        raise NotEPRFragmentError("Domain of discourse must be non-empty to guarantee decidability")
    if len(domain) > _MAX_DOMAIN_SIZE:
        raise NotEPRFragmentError(
            f"Domain of size {len(domain)} exceeds the {_MAX_DOMAIN_SIZE}-element "
            "ceiling for sub-second EPR verification"
        )
    if len(set(domain)) != len(domain):
        raise NotEPRFragmentError("Domain constants must be distinct")

    bound_vars = set(exists_vars) | set(forall_vars)
    if len(bound_vars) != len(exists_vars) + len(forall_vars):
        raise NotEPRFragmentError("A variable name appears in both exists_vars and forall_vars")

    free = free_variables(matrix)
    unbound = free - bound_vars
    if unbound:
        raise NotEPRFragmentError(f"Matrix references unbound variable(s): {sorted(unbound)}")

    arities: dict[str, int] = {}
    _collect_predicate_arities(matrix, arities)

    domain_set = set(domain)
    _check_constants_in_domain(matrix, domain_set)

    return EPRFormula(
        exists_vars=exists_vars,
        forall_vars=forall_vars,
        matrix=matrix,
        domain=domain,
        predicate_arities=arities,
    )


def _check_constants_in_domain(formula: Formula, domain_set: set[str]) -> None:
    match formula:
        case Atom(_, args):
            for arg in args:
                if isinstance(arg, Constant) and arg.name not in domain_set:
                    raise NotEPRFragmentError(
                        f"Constant {arg.name!r} is not a member of the domain of discourse"
                    )
        case Not(operand):
            _check_constants_in_domain(operand, domain_set)
        case And(operands) | Or(operands):
            for op in operands:
                _check_constants_in_domain(op, domain_set)
        case Implies(antecedent, consequent):
            _check_constants_in_domain(antecedent, domain_set)
            _check_constants_in_domain(consequent, domain_set)
