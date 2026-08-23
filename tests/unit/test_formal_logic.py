import pytest

from legal_engine.core.exceptions import NotEPRFragmentError
from legal_engine.formal_logic.ast_nodes import And, Atom, Constant, Implies, Not, Variable
from legal_engine.formal_logic.disambiguator import QuantifierKind, classify_qualifier
from legal_engine.formal_logic.epr_compiler import compile_epr_formula
from legal_engine.formal_logic.smt_generator import generate_smt_lib2
from legal_engine.formal_logic.solver_pool import SolverPool

DOMAIN = ("alice", "bob")


def _ownership_implies_reporting():
    """forall x. Owns(x) -> Reports(x)"""
    matrix = Implies(
        Atom("Owns", (Variable("x"),)),
        Atom("Reports", (Variable("x"),)),
    )
    return compile_epr_formula(
        exists_vars=(),
        forall_vars=("x",),
        matrix=matrix,
        domain=DOMAIN,
    )


class TestDisambiguator:
    def test_universal_qualifiers(self):
        assert classify_qualifier("any") == QuantifierKind.FORALL
        assert classify_qualifier("Every") == QuantifierKind.FORALL

    def test_existential_qualifiers(self):
        assert classify_qualifier("some") == QuantifierKind.EXISTS

    def test_unknown_qualifier_raises(self):
        with pytest.raises(ValueError):
            classify_qualifier("purportedly")


class TestEPRCompiler:
    def test_compiles_valid_formula(self):
        formula = _ownership_implies_reporting()
        assert formula.predicate_arities == {"Owns": 1, "Reports": 1}

    def test_rejects_empty_domain(self):
        with pytest.raises(NotEPRFragmentError):
            compile_epr_formula(
                exists_vars=(),
                forall_vars=("x",),
                matrix=Atom("Owns", (Variable("x"),)),
                domain=(),
            )

    def test_rejects_unbound_variable(self):
        with pytest.raises(NotEPRFragmentError, match="unbound"):
            compile_epr_formula(
                exists_vars=(),
                forall_vars=("x",),
                matrix=Atom("Owns", (Variable("y"),)),
                domain=DOMAIN,
            )

    def test_rejects_inconsistent_predicate_arity(self):
        matrix = And(
            (
                Atom("Owns", (Variable("x"),)),
                Atom("Owns", (Variable("x"), Constant("alice"))),
            )
        )
        with pytest.raises(NotEPRFragmentError, match="inconsistent arities"):
            compile_epr_formula(
                exists_vars=(), forall_vars=("x",), matrix=matrix, domain=DOMAIN
            )

    def test_rejects_constant_outside_domain(self):
        matrix = Atom("Owns", (Constant("charlie"),))
        with pytest.raises(NotEPRFragmentError, match="not a member of the domain"):
            compile_epr_formula(exists_vars=(), forall_vars=(), matrix=matrix, domain=DOMAIN)

    def test_rejects_variable_in_both_exists_and_forall(self):
        with pytest.raises(NotEPRFragmentError, match="both"):
            compile_epr_formula(
                exists_vars=("x",),
                forall_vars=("x",),
                matrix=Atom("Owns", (Variable("x"),)),
                domain=DOMAIN,
            )


class TestSMTGenerator:
    def test_generates_datatype_and_predicate_declarations(self):
        formula = _ownership_implies_reporting()
        smt = generate_smt_lib2(formula)
        assert "(declare-datatypes () ((Individual (alice) (bob))))" in smt
        assert "(declare-fun Owns (Individual) Bool)" in smt
        assert "(declare-fun Reports (Individual) Bool)" in smt
        assert "(check-sat)" in smt
        assert "(forall ((x Individual))" in smt


class TestSolverPool:
    def test_unconstrained_implication_is_satisfiable(self):
        formula = _ownership_implies_reporting()
        pool = SolverPool(pool_size=1, timeout_ms=5000, memory_limit_mb=512)
        result = pool.check(formula)
        assert result.satisfiable is True
        assert result.timed_out is False

    def test_contradiction_is_unsatisfiable(self):
        """forall x. Owns(x) -> Reports(x)  AND  Owns(alice)  AND  NOT Reports(alice)"""
        base = Implies(
            Atom("Owns", (Variable("x"),)),
            Atom("Reports", (Variable("x"),)),
        )
        contradiction = And(
            (
                base,
                Atom("Owns", (Constant("alice"),)),
                Not(Atom("Reports", (Constant("alice"),))),
            )
        )
        formula = compile_epr_formula(
            exists_vars=(), forall_vars=("x",), matrix=contradiction, domain=DOMAIN
        )
        pool = SolverPool(pool_size=1, timeout_ms=5000, memory_limit_mb=512)
        result = pool.check(formula)
        assert result.satisfiable is False
        assert result.unsat_core  # non-empty: the tracked assertion is in the core

    def test_exists_witness_is_satisfiable(self):
        formula = compile_epr_formula(
            exists_vars=("x",),
            forall_vars=(),
            matrix=Atom("Owns", (Variable("x"),)),
            domain=DOMAIN,
        )
        pool = SolverPool(pool_size=1, timeout_ms=5000, memory_limit_mb=512)
        result = pool.check(formula)
        assert result.satisfiable is True
        assert result.counterexample is not None
