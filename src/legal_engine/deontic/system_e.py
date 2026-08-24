"""Åqvist System E dyadic deontic logic, evaluated over finite preference
models.

## The semantics

A model is a finite set of worlds `W`, a betterness relation `⪰` on it
(`w1 ⪰ w2` reading "w1 is at least as good as w2"), and a valuation
saying which atoms hold where. For a proposition φ:

    Opt(φ) = { w ∈ W : w ⊨ φ and ∀w' ∈ W (w' ⊨ φ → w ⪰ w') }

    O(ψ | φ)  ⟺  ∀w ∈ Opt(φ): w ⊨ ψ
    P(ψ | φ)  ⟺  ∃w ∈ Opt(φ): w ⊨ ψ        (= ¬O(¬ψ | φ))
    F(ψ | φ)  ⟺  O(¬ψ | φ)

The whole point is that obligation is evaluated only at the *best*
antecedent-worlds. That's what lets a secondary obligation govern the
case where a primary one has already been violated, without the two
colliding — which is what defeats the contrary-to-duty paradoxes that
break Standard Deontic Logic. `tests/unit/test_system_e.py` runs
Chisholm's Paradox and Forrester's gentle-murder paradox through this and
checks no contradiction is derivable.

## What this is, and what it is not

This is **finite-model evaluation**, not theorem proving. Every operator
above is decided by enumerating `W`, so results are exact and always
terminate, and complexity is polynomial in `|W|`. What it cannot do is
tell you a formula is valid across *all* models: it answers "does this
hold in the model you gave me," not "is this a theorem of E."

That distinction matters here because the obvious alternative — the
LogiKEy shallow embedding of System E in Isabelle/HOL — is genuinely more
powerful and genuinely weaker in a different way: HOL is undecidable,
so `sledgehammer` can simply not return. Neither is strictly better, and
this codebase already stakes a decidability claim on
`formal_logic/`'s EPR fragment; adding an undecidable engine and calling
it a strengthening would misrepresent both. Nothing here touches the EPR
compiler.

## Model conditions

`⪰` is validated at construction as reflexive, transitive, and total —
System E's frame conditions. Totalness is the one that matters most and
is the easiest to get wrong by hand, which is why `from_ranking` exists:
it builds the relation from tiers of equally-good worlds so the
conditions hold by construction.

Limitedness — every satisfiable φ has a non-empty `Opt(φ)` — comes free
on finite models. A non-empty finite set under a total preorder always
has maximal elements, so the axiom Åqvist needs in the general case is a
theorem here. That is a real benefit of restricting to finite models,
not a gap being papered over.

## On detecting dilemmas

An earlier specification proposed halting whenever `⪰` "yields equal
optimality over conflicting norm worlds" — i.e. on *ties*. That fires
during ordinary operation: totalness makes ties ubiquitous and `Opt(φ)`
is almost always a multi-world set, so a gate on ties halts on nearly
every evaluation.

A tie is not a dilemma. The dilemma is when the optimal worlds *disagree
about ψ*, leaving neither `O(ψ|φ)` nor `O(¬ψ|φ)` true — the norm simply
fails to determine the question. `Verdict.is_dilemma` tests that, and
`tests/unit/test_system_e.py` pins the difference with a model whose
optimal set is a tie yet determines ψ perfectly well.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from legal_engine.core.exceptions import LegalEngineError
from legal_engine.deontic.formulas import Formula, Not, atoms_in, holds_at


class PreferenceModelError(LegalEngineError):
    """The supplied worlds, betterness relation, or valuation don't form
    a System E model."""


@dataclass(frozen=True)
class Verdict:
    """Everything the dyadic operators say about one (ψ, φ) pair, in one
    object, so a caller deciding whether to act never has to re-derive
    ``Opt(φ)`` or reason about which combination of booleans means what.

    ``is_vacuous`` and ``is_dilemma`` are mutually exclusive and both
    worth surfacing. Vacuity means ``Opt(φ)`` is empty (φ is
    unsatisfiable in this model), which makes *every* obligation
    conditional on φ true, including an obligation and its negation —
    classically correct and practically a red flag. A dilemma means the
    optimal worlds genuinely disagree about ψ."""

    obligation: bool
    permission: bool
    prohibition: bool
    optimal_worlds: frozenset[str]
    is_vacuous: bool
    is_dilemma: bool


@dataclass(frozen=True)
class PreferenceModel:
    worlds: frozenset[str]
    betterness: frozenset[tuple[str, str]]
    valuation: Mapping[str, frozenset[str]]

    def __post_init__(self) -> None:
        if not self.worlds:
            raise PreferenceModelError("a preference model needs at least one world")

        missing = set(self.worlds) - set(self.valuation)
        if missing:
            raise PreferenceModelError(f"no valuation for world(s): {sorted(missing)}")
        unknown = set(self.valuation) - set(self.worlds)
        if unknown:
            raise PreferenceModelError(f"valuation names unknown world(s): {sorted(unknown)}")

        for left, right in self.betterness:
            if left not in self.worlds or right not in self.worlds:
                raise PreferenceModelError(
                    f"betterness pair ({left!r}, {right!r}) names a world not in the model"
                )

        for world in self.worlds:
            if (world, world) not in self.betterness:
                raise PreferenceModelError(f"betterness is not reflexive: {world!r} is not >= itself")

        for a in self.worlds:
            for b in self.worlds:
                if (a, b) not in self.betterness and (b, a) not in self.betterness:
                    raise PreferenceModelError(
                        f"betterness is not total: {a!r} and {b!r} are incomparable"
                    )

        for a, b in self.betterness:
            for c in self.worlds:
                if (b, c) in self.betterness and (a, c) not in self.betterness:
                    raise PreferenceModelError(
                        f"betterness is not transitive: {a!r} >= {b!r} >= {c!r} but not {a!r} >= {c!r}"
                    )

    @classmethod
    def from_ranking(
        cls, tiers: Sequence[Iterable[str]], valuation: Mapping[str, Iterable[str]]
    ) -> PreferenceModel:
        """Builds a model from tiers of worlds, best first. Worlds sharing
        a tier are equally good, which is how a tie gets expressed.

        This is the constructor to reach for: it produces a relation that
        satisfies reflexivity, transitivity, and totalness by
        construction, rather than asking a caller to write out |W|²
        pairs and hope. The explicit constructor stays available for a
        relation that genuinely isn't rank-shaped."""
        ranked: dict[str, int] = {}
        for index, tier in enumerate(tiers):
            for world in tier:
                if world in ranked:
                    raise PreferenceModelError(f"world {world!r} appears in more than one tier")
                ranked[world] = index
        if not ranked:
            raise PreferenceModelError("a preference model needs at least one world")

        betterness = frozenset(
            (a, b) for a in ranked for b in ranked if ranked[a] <= ranked[b]
        )
        return cls(
            worlds=frozenset(ranked),
            betterness=betterness,
            valuation={w: frozenset(atoms) for w, atoms in valuation.items()},
        )

    @property
    def known_atoms(self) -> frozenset[str]:
        return frozenset().union(*self.valuation.values()) if self.valuation else frozenset()

    def _check_atoms(self, *formulas: Formula) -> None:
        referenced = frozenset().union(*(atoms_in(f) for f in formulas)) if formulas else frozenset()
        unknown = referenced - self.known_atoms
        if unknown:
            raise PreferenceModelError(
                f"formula references atom(s) no world assigns: {sorted(unknown)}. "
                "An atom that is false everywhere silently changes which worlds are "
                "optimal, so this is rejected rather than evaluated."
            )

    def extension(self, formula: Formula) -> frozenset[str]:
        """The worlds where ``formula`` is true."""
        self._check_atoms(formula)
        return frozenset(w for w in self.worlds if holds_at(formula, self.valuation[w]))

    def optimal(self, condition: Formula) -> frozenset[str]:
        """``Opt(φ)``: the best worlds satisfying ``condition``. Empty
        exactly when the condition is unsatisfiable in this model (see
        the module docstring on limitedness)."""
        extension = self.extension(condition)
        return frozenset(
            w for w in extension if all((w, other) in self.betterness for other in extension)
        )

    def obligation(self, obligated: Formula, condition: Formula) -> bool:
        """``O(ψ | φ)``. Vacuously true when ``Opt(φ)`` is empty — use
        ``evaluate`` if that distinction matters, which it usually
        does."""
        # Both formulas, not just the condition: an unknown atom in the
        # obligated position is false at every optimal world, which would
        # silently return False rather than flag the typo.
        self._check_atoms(obligated, condition)
        return all(holds_at(obligated, self.valuation[w]) for w in self.optimal(condition))

    def permission(self, permitted: Formula, condition: Formula) -> bool:
        """``P(ψ | φ) = ¬O(¬ψ | φ)``: some optimal world allows ψ."""
        return not self.obligation(Not(permitted), condition)

    def prohibition(self, forbidden: Formula, condition: Formula) -> bool:
        """``F(ψ | φ) = O(¬ψ | φ)``."""
        return self.obligation(Not(forbidden), condition)

    def evaluate(self, subject: Formula, condition: Formula) -> Verdict:
        self._check_atoms(subject, condition)
        optimal = self.optimal(condition)
        obligation = all(holds_at(subject, self.valuation[w]) for w in optimal)
        prohibition = all(not holds_at(subject, self.valuation[w]) for w in optimal)
        return Verdict(
            obligation=obligation,
            permission=not prohibition,
            prohibition=prohibition,
            optimal_worlds=optimal,
            is_vacuous=not optimal,
            # A tie is not a dilemma: what makes one is the optimal
            # worlds disagreeing about the subject, so neither it nor its
            # negation is obligatory. Vacuity makes both true, which is a
            # different failure and is reported as such.
            is_dilemma=bool(optimal) and not obligation and not prohibition,
        )
