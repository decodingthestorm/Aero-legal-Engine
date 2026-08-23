"""Renders a compiled EPRFormula as SMT-LIB2 source text.

This is deliberately a pure text renderer, independent of solver_pool.py's
Z3-object-based solving path. Two reasons to keep them separate:

1. Provenance/audit — the WAL (core/wal.py) and the UI's ProofInspector
   component want the literal SMT-LIB2 text that was reasoned about, not a
   re-serialization of whatever Z3 happened to build internally.
2. solver_pool.py needs assert-and-track handles per sub-clause to extract a
   useful unsat core; round-tripping through parsed SMT-LIB2 text would lose
   that structure. So it builds Z3 objects directly from the same
   EPRFormula this module renders text from — both are compiled from one
   source of truth.

The finite domain of discourse is encoded as a single-sort SMT-LIB2 datatype
with one nullary constructor per domain element. Datatype semantics give us
finiteness and distinctness of domain elements for free.
"""

from __future__ import annotations

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

_SORT_NAME = "Individual"


def _term_to_smt(term: Term) -> str:
    if isinstance(term, (Constant, Variable)):
        return term.name
    raise TypeError(f"Unknown term node: {term!r}")


def _formula_to_smt(formula: Formula) -> str:
    match formula:
        case Atom(predicate, args):
            if not args:
                return predicate
            rendered_args = " ".join(_term_to_smt(a) for a in args)
            return f"({predicate} {rendered_args})"
        case Not(operand):
            return f"(not {_formula_to_smt(operand)})"
        case And(operands):
            rendered = " ".join(_formula_to_smt(op) for op in operands)
            return f"(and {rendered})"
        case Or(operands):
            rendered = " ".join(_formula_to_smt(op) for op in operands)
            return f"(or {rendered})"
        case Implies(antecedent, consequent):
            return f"(=> {_formula_to_smt(antecedent)} {_formula_to_smt(consequent)})"
        case _:
            raise TypeError(f"Unknown formula node: {formula!r}")


def generate_smt_lib2(formula: EPRFormula) -> str:
    lines: list[str] = []

    domain_ctors = " ".join(f"({name})" for name in formula.domain)
    lines.append(f"(declare-datatypes () (({_SORT_NAME} {domain_ctors})))")

    for predicate, arity in sorted(formula.predicate_arities.items()):
        arg_sorts = " ".join([_SORT_NAME] * arity)
        lines.append(f"(declare-fun {predicate} ({arg_sorts}) Bool)")

    matrix_smt = _formula_to_smt(formula.matrix)

    body = matrix_smt
    if formula.forall_vars:
        binders = " ".join(f"({v} {_SORT_NAME})" for v in formula.forall_vars)
        body = f"(forall ({binders}) {body})"
    if formula.exists_vars:
        binders = " ".join(f"({v} {_SORT_NAME})" for v in formula.exists_vars)
        body = f"(exists ({binders}) {body})"

    lines.append(f"(assert {body})")
    lines.append("(check-sat)")
    lines.append("(get-model)")

    return "\n".join(lines)
