"""Propositional formulas, the object language the dyadic operators in
system_e.py take as arguments.

Deliberately *not* reusing formal_logic/ast_nodes.py. That AST is
first-order and exists to be compiled into the EPR fragment for Z3; this
one is propositional and exists to be evaluated by enumeration over a
finite world set. Sharing a type between them would mean either
supporting quantifiers here (where they have no meaning — a world either
satisfies an atom or doesn't) or dragging deontic operators into the EPR
compiler, which is exactly the coupling that would put the EPR
decidability guarantee at risk. Two small ASTs are cheaper than one that
has to be careful.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True)
class Top:
    """The tautology. ``O(psi | Top)`` is unconditional obligation."""


@dataclass(frozen=True)
class Bottom:
    """The contradiction. Its extension is empty, which makes any
    obligation conditional on it *vacuous* — see system_e.py."""


@dataclass(frozen=True)
class Atom:
    name: str


@dataclass(frozen=True)
class Not:
    operand: Formula


@dataclass(frozen=True)
class And:
    left: Formula
    right: Formula


@dataclass(frozen=True)
class Or:
    left: Formula
    right: Formula


@dataclass(frozen=True)
class Implies:
    antecedent: Formula
    consequent: Formula


Formula: TypeAlias = Top | Bottom | Atom | Not | And | Or | Implies


def holds_at(formula: Formula, true_atoms: frozenset[str]) -> bool:
    """Whether ``formula`` is true at a world whose true atoms are
    ``true_atoms``. Ordinary classical evaluation — the deontic content
    lives entirely in *which* worlds get consulted (system_e.py), not in
    how a formula is evaluated at one of them."""
    match formula:
        case Top():
            return True
        case Bottom():
            return False
        case Atom(name):
            return name in true_atoms
        case Not(operand):
            return not holds_at(operand, true_atoms)
        case And(left, right):
            return holds_at(left, true_atoms) and holds_at(right, true_atoms)
        case Or(left, right):
            return holds_at(left, true_atoms) or holds_at(right, true_atoms)
        case Implies(antecedent, consequent):
            return (not holds_at(antecedent, true_atoms)) or holds_at(consequent, true_atoms)
    raise TypeError(f"not a Formula: {formula!r}")


def atoms_in(formula: Formula) -> frozenset[str]:
    """Every atom name the formula mentions. Used to catch a formula that
    references an atom no world in the model ever assigns — almost always
    a typo, and one that would otherwise read as "false everywhere" and
    quietly change what's optimal."""
    match formula:
        case Top() | Bottom():
            return frozenset()
        case Atom(name):
            return frozenset({name})
        case Not(operand):
            return atoms_in(operand)
        case And(left, right) | Or(left, right):
            return atoms_in(left) | atoms_in(right)
        case Implies(antecedent, consequent):
            return atoms_in(antecedent) | atoms_in(consequent)
    raise TypeError(f"not a Formula: {formula!r}")
