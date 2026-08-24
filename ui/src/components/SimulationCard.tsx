import { useState } from "react";
import { ApiError, PenaltyResponse, computePenalty, computePenaltyCurve } from "@/lib/api";
import { useApiToken } from "@/lib/useApiToken";

// Payoff matrix & penalty curve visualizer — see routes/simulation.py
// (/simulation/penalty, /simulation/penalty-curve). Renders the convex
// penalty curve as a plain inline SVG polyline rather than pulling in a
// charting library, to keep this app's dependency footprint (and thus the
// surface that could go wrong in an environment where `npm install` was
// never actually run to verify it) as small as possible.

interface CurvePoint {
  x: number;
  y: number;
}

export default function SimulationCard() {
  const { token } = useApiToken();

  const [benefit, setBenefit] = useState("1000");
  const [costCompliance, setCostCompliance] = useState("50");
  const [pDetect, setPDetect] = useState("0.3");
  const [penaltyResult, setPenaltyResult] = useState<PenaltyResponse | null>(null);
  const [penaltyError, setPenaltyError] = useState<string | null>(null);
  const [penaltyLoading, setPenaltyLoading] = useState(false);

  const [k, setK] = useState("2");
  const [xLimit, setXLimit] = useState("100");
  const [curvePoints, setCurvePoints] = useState<CurvePoint[]>([]);
  const [curveError, setCurveError] = useState<string | null>(null);
  const [curveLoading, setCurveLoading] = useState(false);

  async function handleComputePenalty() {
    setPenaltyLoading(true);
    setPenaltyError(null);
    try {
      const result = await computePenalty(
        {
          benefit: Number(benefit),
          cost_compliance: Number(costCompliance),
          p_detect: Number(pDetect),
        },
        token ?? undefined
      );
      setPenaltyResult(result);
    } catch (err) {
      setPenaltyError(err instanceof ApiError ? err.detail : String(err));
      setPenaltyResult(null);
    } finally {
      setPenaltyLoading(false);
    }
  }

  async function handleComputeCurve() {
    setCurveLoading(true);
    setCurveError(null);
    try {
      const limit = Number(xLimit);
      const samplePoints = Array.from({ length: 11 }, (_, i) => limit + (i - 5) * 10);
      const result = await computePenaltyCurve(
        { k: Number(k), x_limit: limit, sample_points: samplePoints },
        token ?? undefined
      );
      setCurvePoints([...result].sort((a, b) => a.x - b.x));
    } catch (err) {
      setCurveError(err instanceof ApiError ? err.detail : String(err));
      setCurvePoints([]);
    } finally {
      setCurveLoading(false);
    }
  }

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
      <h2 className="text-base font-semibold text-slate-100">Deterrence Penalty Simulator</h2>
      <p className="mt-1 text-sm text-slate-400">
        Minimum penalty that makes honest compliance a dominant strategy (game_theory/penalty_optimizer.py).
      </p>

      <div className="mt-4 grid grid-cols-3 gap-3 text-sm">
        <Field label="Benefit of evasion" value={benefit} onChange={setBenefit} />
        <Field label="Cost of compliance" value={costCompliance} onChange={setCostCompliance} />
        <Field label="Detection probability" value={pDetect} onChange={setPDetect} step="0.01" />
      </div>
      <button
        className="mt-3 rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
        onClick={handleComputePenalty}
        disabled={penaltyLoading}
        data-testid="compute-penalty-button"
      >
        {penaltyLoading ? "Computing…" : "Compute minimum penalty"}
      </button>

      {penaltyError && (
        <p className="mt-3 text-sm text-red-400" data-testid="penalty-error">
          {penaltyError}
        </p>
      )}
      {penaltyResult && (
        <div
          className="mt-3 rounded border border-slate-800 bg-slate-950/60 p-3 text-sm"
          data-testid="penalty-result"
        >
          <Row label="Deterrence threshold" value={penaltyResult.minimum_deterrent_penalty.toFixed(2)} />
          <Row label="Recommended penalty" value={penaltyResult.recommended_penalty.toFixed(2)} />
          <Row
            label="Compliance is dominant"
            value={penaltyResult.recommended_penalty_is_dominant ? "yes" : "no"}
            highlight={penaltyResult.recommended_penalty_is_dominant}
          />
        </div>
      )}

      <hr className="my-5 border-slate-800" />

      <h3 className="text-sm font-semibold text-slate-100">Convex Penalty Curve</h3>
      <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
        <Field label="Convexity (k)" value={k} onChange={setK} />
        <Field label="Statutory limit (x_limit)" value={xLimit} onChange={setXLimit} />
      </div>
      <button
        className="mt-3 rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
        onClick={handleComputeCurve}
        disabled={curveLoading}
        data-testid="plot-curve-button"
      >
        {curveLoading ? "Computing…" : "Plot curve"}
      </button>
      {curveError && <p className="mt-3 text-sm text-red-400">{curveError}</p>}
      {curvePoints.length > 0 && <PenaltyCurveChart points={curvePoints} />}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  step,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  step?: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-slate-400">{label}</span>
      <input
        type="number"
        step={step ?? "1"}
        className="rounded border border-slate-700 bg-slate-800 px-2 py-1 text-slate-100"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

function Row({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  const testId = `row-value-${label.toLowerCase().replace(/\s+/g, "-")}`;
  return (
    <div className="flex justify-between py-0.5">
      <span className="text-slate-400">{label}</span>
      <span
        className={highlight ? "font-medium text-emerald-400" : "font-medium text-slate-100"}
        data-testid={testId}
      >
        {value}
      </span>
    </div>
  );
}

function PenaltyCurveChart({ points }: { points: CurvePoint[] }) {
  const width = 400;
  const height = 160;
  const padding = 24;

  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = 0;
  const yMax = Math.max(...ys, 1);

  const scaleX = (x: number) => padding + ((x - xMin) / (xMax - xMin || 1)) * (width - 2 * padding);
  const scaleY = (y: number) => height - padding - ((y - yMin) / (yMax - yMin || 1)) * (height - 2 * padding);

  const path = points.map((p) => `${scaleX(p.x)},${scaleY(p.y)}`).join(" ");

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="mt-4 w-full rounded border border-slate-800 bg-slate-950/60"
      data-testid="penalty-curve-chart"
    >
      <polyline points={path} fill="none" stroke="#818cf8" strokeWidth={2} />
      {points.map((p) => (
        <circle key={p.x} cx={scaleX(p.x)} cy={scaleY(p.y)} r={3} fill="#818cf8" />
      ))}
      <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke="#334155" />
      <line x1={padding} y1={padding} x2={padding} y2={height - padding} stroke="#334155" />
    </svg>
  );
}
