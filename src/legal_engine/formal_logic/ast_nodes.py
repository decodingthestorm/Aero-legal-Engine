"""AST node schemas for the EPR (Bernays-Schoenfinkel-Ramsey) logic fragment.

The node set deliberately has no "function application" node — only
``Constant`` and ``Variable`` terms exist. That is what makes "no function
symbols of arity > 0" a structural guarantee rather than a rule the compiler
has to police after the fact.

Quantifiers are not embedded in ``Formula`` either: they only appear once,
at the top of an ``EPRFormula``, as ``exists_vars`` followed by
``forall_vars``. This makes prenex-normal-form with strict
exists*-then-forall* ordering structural too. The classic EPR
decidability result depends on exactly this shape.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass


class Term(ABC):
    """A term in the EPR fragment: either a constant or a bound/free variable."""


@dataclass(frozen=True)
class Constant(Term):
    name: str


@dataclass(frozen=True)
class Variable(Term):
    name: str


class Formula(ABC):
    """A quantifier-free formula over predicates applied to terms."""


@dataclass(frozen=True)
class Atom(Formula):
    predicate: str
    args: tuple[Term, ...]


@dataclass(frozen=True)
class Not(Formula):
    operand: Formula


@dataclass(frozen=True)
class And(Formula):
    operands: tuple[Formula, ...]


@dataclass(frozen=True)
class Or(Formula):
    operands: tuple[Formula, ...]


@dataclass(frozen=True)
class Implies(Formula):
    antecedent: Formula
    consequent: Formula


@dataclass(frozen=True)
class EPRFormula:
    """A formula in Bernays-Schoenfinkel-Ramsey prenex normal form.

    ``exists_vars[0] ... exists_vars[m] forall_vars[0] ... forall_vars[n] . matrix``

    ``domain`` is the finite set of individual constants the quantifiers range
    over — EPR decidability requires this to be finite.
    """

    exists_vars: tuple[str, ...]
    forall_vars: tuple[str, ...]
    matrix: Formula
    domain: tuple[str, ...]
    predicate_arities: dict[str, int]


def free_variables(formula: Formula) -> set[str]:
    """Collect variable names referenced anywhere inside a quantifier-free formula."""
    match formula:
        case Atom(_, args):
            return {arg.name for arg in args if isinstance(arg, Variable)}
        case Not(operand):
            return free_variables(operand)
        case And(operands) | Or(operands):
            result: set[str] = set()
            for op in operands:
                result |= free_variables(op)
            return result
        case Implies(antecedent, consequent):
            return free_variables(antecedent) | free_variables(consequent)
        case _:
            raise TypeError(f"Unknown formula node: {formula!r}")
