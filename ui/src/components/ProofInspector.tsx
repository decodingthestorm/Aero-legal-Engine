import { useState } from "react";
import { ApiError, VerifyClauseResponse, verifyClause } from "@/lib/api";
import { useApiToken } from "@/lib/useApiToken";

// SMT-LIB2 AST & Z3 result inspector — see routes/verification.py's
// /verification/verify, which compiles a submitted EPR clause
// (formal_logic/epr_compiler.py), renders it as SMT-LIB2
// (formal_logic/smt_generator.py), and checks it with the shared Z3
// solver pool. The "matrix" field is authored as raw JSON here rather
// than through a formula-building UI — the discriminated-union AST shape
// (constant/variable terms; atom/not/and/or/implies formulas) is exactly
// what formal_logic/ast_nodes.py defines, and a dedicated visual builder
// for it is a bigger piece of UI than this pass is scoped for.

const EXAMPLES: Record<string, { existsVars: string; forallVars: string; domain: string; matrix: string }> = {
  "Satisfiable: ownership implies reporting": {
    existsVars: "",
    forallVars: "x",
    domain: "alice, bob",
    matrix: JSON.stringify(
      {
        kind: "implies",
        antecedent: { kind: "atom", predicate: "Owns", args: [{ kind: "variable", name: "x" }] },
        consequent: { kind: "atom", predicate: "Reports", args: [{ kind: "variable", name: "x" }] },
      },
      null,
      2
    ),
  },
  "Unsatisfiable: alice owns but never reports": {
    existsVars: "",
    forallVars: "x",
    domain: "alice, bob",
    matrix: JSON.stringify(
      {
        kind: "and",
        operands: [
          {
            kind: "implies",
            antecedent: { kind: "atom", predicate: "Owns", args: [{ kind: "variable", name: "x" }] },
            consequent: { kind: "atom", predicate: "Reports", args: [{ kind: "variable", name: "x" }] },
          },
          { kind: "atom", predicate: "Owns", args: [{ kind: "constant", name: "alice" }] },
          {
            kind: "not",
            operand: { kind: "atom", predicate: "Reports", args: [{ kind: "constant", name: "alice" }] },
          },
        ],
      },
      null,
      2
    ),
  },
};

function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
}

export default function ProofInspector() {
  const { token } = useApiToken();
  const firstExample = Object.values(EXAMPLES)[0];

  const [existsVars, setExistsVars] = useState(firstExample.existsVars);
  const [forallVars, setForallVars] = useState(firstExample.forallVars);
  const [domain, setDomain] = useState(firstExample.domain);
  const [matrixJson, setMatrixJson] = useState(firstExample.matrix);

  const [result, setResult] = useState<VerifyClauseResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function loadExample(name: string) {
    const example = EXAMPLES[name];
    setExistsVars(example.existsVars);
    setForallVars(example.forallVars);
    setDomain(example.domain);
    setMatrixJson(example.matrix);
    setResult(null);
    setError(null);
  }

  async function handleVerify() {
    setLoading(true);
    setError(null);
    try {
      const matrix = JSON.parse(matrixJson);
      const response = await verifyClause(
        {
          exists_vars: splitCsv(existsVars),
          forall_vars: splitCsv(forallVars),
          domain: splitCsv(domain),
          matrix,
        },
        token ?? undefined
      );
      setResult(response);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else if (err instanceof SyntaxError) {
        setError(`Matrix is not valid JSON: ${err.message}`);
      } else {
        setError(String(err));
      }
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
      <h2 className="text-base font-semibold text-slate-100">Formal Logic Proof Inspector</h2>
      <p className="mt-1 text-sm text-slate-400">
        Compiles a clause into the decidable EPR fragment and checks it with Z3 (formal_logic/).
      </p>

      <div className="mt-4 flex flex-wrap gap-2 text-xs">
        {Object.keys(EXAMPLES).map((name) => (
          <button
            key={name}
            className="rounded border border-slate-700 bg-slate-800 px-2 py-1 hover:bg-slate-700"
            onClick={() => loadExample(name)}
          >
            {name}
          </button>
        ))}
      </div>

      <div className="mt-4 grid grid-cols-3 gap-3 text-sm">
        <TextField label="exists_vars (csv)" value={existsVars} onChange={setExistsVars} />
        <TextField label="forall_vars (csv)" value={forallVars} onChange={setForallVars} />
        <TextField label="domain (csv)" value={domain} onChange={setDomain} />
      </div>

      <label className="mt-3 flex flex-col gap-1 text-sm">
        <span className="text-xs text-slate-400">matrix (JSON — see formal_logic/ast_nodes.py)</span>
        <textarea
          className="h-40 rounded border border-slate-700 bg-slate-800 p-2 font-mono text-xs text-slate-100"
          value={matrixJson}
          onChange={(e) => setMatrixJson(e.target.value)}
          data-testid="matrix-textarea"
        />
      </label>

      <button
        className="mt-3 rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
        onClick={handleVerify}
        disabled={loading}
        data-testid="verify-button"
      >
        {loading ? "Verifying…" : "Verify clause"}
      </button>

      {error && (
        <p className="mt-3 whitespace-pre-wrap text-sm text-red-400" data-testid="verify-error">
          {error}
        </p>
      )}

      {result && (
        <div className="mt-4 space-y-3" data-testid="verify-result">
          <div
            className={`rounded border p-3 text-sm ${
              result.proof_result.satisfiable
                ? "border-emerald-800 bg-emerald-950/40"
                : "border-amber-800 bg-amber-950/40"
            }`}
          >
            <p className="font-medium">
              {result.proof_result.satisfiable ? "SATISFIABLE" : "UNSATISFIABLE"}
              {result.proof_result.timed_out && " (timed out)"}
            </p>
            <p className="mt-1 text-xs text-slate-400">{result.proof_result.elapsed_ms.toFixed(2)} ms</p>
            {result.proof_result.counterexample && (
              <pre className="mt-2 overflow-x-auto text-xs text-slate-300">
                {JSON.stringify(result.proof_result.counterexample, null, 2)}
              </pre>
            )}
            {result.proof_result.unsat_core.length > 0 && (
              <p className="mt-2 text-xs text-slate-300">
                Unsat core: {result.proof_result.unsat_core.join(", ")}
              </p>
            )}
          </div>

          <details className="rounded border border-slate-800 bg-slate-950/60 p-3 text-xs" open>
            <summary className="cursor-pointer text-slate-300">SMT-LIB2</summary>
            <pre className="mt-2 overflow-x-auto text-slate-400">{result.smt_lib2}</pre>
          </details>
        </div>
      )}
    </div>
  );
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-slate-400">{label}</span>
      <input
        className="rounded border border-slate-700 bg-slate-800 px-2 py-1 text-slate-100"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
