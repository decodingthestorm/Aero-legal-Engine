"""Formal logic verification endpoints.

Accepts a JSON mirror of the EPR formula AST (ast_nodes.py) — a
discriminated union on ``kind`` mirroring Constant/Variable/Atom/Not/And/
Or/Implies — compiles it via epr_compiler.compile_epr_formula (which
enforces the EPR decidability constraints and raises NotEPRFragmentError,
mapped to a 400 by api/middleware.py, on any violation), checks it via the
shared SolverPool, and also renders it as SMT-LIB2 text (smt_generator.py)
so a caller — namely ui/'s ProofInspector, "SMT-LIB2 AST & Z3 result
inspector" — has something to actually inspect alongside the verdict.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from legal_engine.api.dependencies import SolverPoolDep
from legal_engine.core.models import ProofResult
from legal_engine.formal_logic import ast_nodes
from legal_engine.formal_logic.epr_compiler import compile_epr_formula
from legal_engine.formal_logic.smt_generator import generate_smt_lib2

router = APIRouter()


class ConstantSchema(BaseModel):
    kind: Literal["constant"] = "constant"
    name: str


class VariableSchema(BaseModel):
    kind: Literal["variable"] = "variable"
    name: str


TermSchema = Annotated[ConstantSchema | VariableSchema, Field(discriminator="kind")]


class AtomSchema(BaseModel):
    kind: Literal["atom"] = "atom"
    predicate: str
    args: list[TermSchema] = Field(default_factory=list)


class NotSchema(BaseModel):
    kind: Literal["not"] = "not"
    operand: FormulaSchema


class AndSchema(BaseModel):
    kind: Literal["and"] = "and"
    operands: list[FormulaSchema]


class OrSchema(BaseModel):
    kind: Literal["or"] = "or"
    operands: list[FormulaSchema]


class ImpliesSchema(BaseModel):
    kind: Literal["implies"] = "implies"
    antecedent: FormulaSchema
    consequent: FormulaSchema


FormulaSchema = Annotated[
    AtomSchema | NotSchema | AndSchema | OrSchema | ImpliesSchema, Field(discriminator="kind")
]

NotSchema.model_rebuild()
AndSchema.model_rebuild()
OrSchema.model_rebuild()
ImpliesSchema.model_rebuild()


def _term_from_schema(schema: ConstantSchema | VariableSchema) -> ast_nodes.Term:
    if isinstance(schema, ConstantSchema):
        return ast_nodes.Constant(schema.name)
    return ast_nodes.Variable(schema.name)


def _formula_from_schema(schema: BaseModel) -> ast_nodes.Formula:
    if isinstance(schema, AtomSchema):
        return ast_nodes.Atom(schema.predicate, tuple(_term_from_schema(a) for a in schema.args))
    if isinstance(schema, NotSchema):
        return ast_nodes.Not(_formula_from_schema(schema.operand))
    if isinstance(schema, AndSchema):
        return ast_nodes.And(tuple(_formula_from_schema(op) for op in schema.operands))
    if isinstance(schema, OrSchema):
        return ast_nodes.Or(tuple(_formula_from_schema(op) for op in schema.operands))
    if isinstance(schema, ImpliesSchema):
        return ast_nodes.Implies(
            _formula_from_schema(schema.antecedent), _formula_from_schema(schema.consequent)
        )
    raise TypeError(f"Unknown formula schema node: {schema!r}")


class VerifyClauseRequest(BaseModel):
    exists_vars: list[str] = Field(default_factory=list)
    forall_vars: list[str] = Field(default_factory=list)
    matrix: FormulaSchema
    domain: list[str]


class VerifyClauseResponse(BaseModel):
    proof_result: ProofResult
    smt_lib2: str


@router.post("/verify", response_model=VerifyClauseResponse)
async def verify_clause(request: VerifyClauseRequest, solver_pool: SolverPoolDep) -> VerifyClauseResponse:
    matrix = _formula_from_schema(request.matrix)
    formula = compile_epr_formula(
        exists_vars=tuple(request.exists_vars),
        forall_vars=tuple(request.forall_vars),
        matrix=matrix,
        domain=tuple(request.domain),
    )
    smt_lib2 = generate_smt_lib2(formula)
    # SolverPool.check is a blocking (threading-based) call that can take up
    # to the configured Z3 timeout; run it off the event loop so one slow
    # verification doesn't stall every other in-flight request.
    proof_result = await run_in_threadpool(solver_pool.check, formula)
    return VerifyClauseResponse(proof_result=proof_result, smt_lib2=smt_lib2)
