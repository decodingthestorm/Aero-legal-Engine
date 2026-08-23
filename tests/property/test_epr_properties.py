"""Property-based tests for the EPR compiler's structural guarantees.

These generate many small, well-formed and deliberately-broken clause
specifications and check that compile_epr_formula accepts exactly the
well-formed ones and rejects every broken one with NotEPRFragmentError.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from legal_engine.core.exceptions import NotEPRFragmentError
from legal_engine.formal_logic.ast_nodes import Atom, Constant, Variable
from legal_engine.formal_logic.epr_compiler import compile_epr_formula
from legal_engine.formal_logic.smt_generator import generate_smt_lib2

_identifier = st.from_regex(r"[A-Za-z][A-Za-z0-9_]{0,8}", fullmatch=True)
_domains = st.lists(_identifier, min_size=1, max_size=6, unique=True)


@given(domain=_domains, predicate=_identifier, var=_identifier)
def test_well_formed_unary_forall_always_compiles(domain, predicate, var):
    formula = compile_epr_formula(
        exists_vars=(),
        forall_vars=(var,),
        matrix=Atom(predicate, (Variable(var),)),
        domain=tuple(domain),
    )
    assert formula.domain == tuple(domain)
    assert formula.predicate_arities == {predicate: 1}


@given(domain=_domains, predicate=_identifier, var=_identifier, other_var=_identifier)
def test_unbound_variable_always_rejected(domain, predicate, var, other_var):
    if var == other_var:
        return  # not the case we're testing
    with pytest.raises(NotEPRFragmentError):
        compile_epr_formula(
            exists_vars=(),
            forall_vars=(var,),
            matrix=Atom(predicate, (Variable(other_var),)),
            domain=tuple(domain),
        )


@given(domain=_domains, predicate=_identifier, const_name=_identifier)
def test_constant_outside_domain_always_rejected(domain, predicate, const_name):
    if const_name in domain:
        return  # not the case we're testing: constant happens to be in-domain
    with pytest.raises(NotEPRFragmentError):
        compile_epr_formula(
            exists_vars=(),
            forall_vars=(),
            matrix=Atom(predicate, (Constant(const_name),)),
            domain=tuple(domain),
        )


@given(domain=_domains, predicate=_identifier, var=_identifier)
def test_compiled_formula_always_renders_valid_smt_skeleton(domain, predicate, var):
    formula = compile_epr_formula(
        exists_vars=(),
        forall_vars=(var,),
        matrix=Atom(predicate, (Variable(var),)),
        domain=tuple(domain),
    )
    smt = generate_smt_lib2(formula)
    assert smt.startswith("(declare-datatypes")
    assert smt.rstrip().endswith("(get-model)")
    assert "(check-sat)" in smt
