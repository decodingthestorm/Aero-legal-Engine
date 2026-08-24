import { useState } from "react";
import {
  ApiError,
  JurisdictionTier,
  PreemptionResponse,
  SearchMatch,
  SourceType,
  addStatute,
  getPreemption,
  searchStatutes,
} from "@/lib/api";
import { useApiToken } from "@/lib/useApiToken";

// Interactive preemption graph visualizer — see knowledge_graph/
// graph_service.py, preemption.py, and vector_service.py. Rendered as
// structured panels (add / resolve / search) rather than a node-link
// diagram: drawing the underlying NetworkX graph would need a "list every
// statute and edge" endpoint that doesn't exist yet, and pulling in a
// graph-drawing library (Cytoscape.js, per the original spec) adds a
// dependency this pass can't verify actually installs cleanly. What's
// here talks to the real API and exercises the real preemption logic.

const SOURCE_TYPES: SourceType[] = [
  "municipal_code",
  "state_statute",
  "federal_code",
  "international_treaty",
  "judicial_precedent",
];

const TIERS: { label: string; value: JurisdictionTier }[] = [
  { label: "International Treaty", value: JurisdictionTier.INTERNATIONAL_TREATY },
  { label: "Federal", value: JurisdictionTier.FEDERAL },
  { label: "State", value: JurisdictionTier.STATE },
  { label: "County", value: JurisdictionTier.COUNTY },
  { label: "Municipal", value: JurisdictionTier.MUNICIPAL },
];

export default function GraphViewer() {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <AddStatutePanel />
      <PreemptionPanel />
      <SearchPanel />
    </div>
  );
}

function AddStatutePanel() {
  const { token } = useApiToken();
  const [sourceType, setSourceType] = useState<SourceType>("municipal_code");
  const [tier, setTier] = useState<JurisdictionTier>(JurisdictionTier.MUNICIPAL);
  const [citation, setCitation] = useState("Sec. 12.04.030");
  const [title, setTitle] = useState("Short-term rental permits");
  const [text, setText] = useState("No person shall operate a short-term rental without a permit.");
  const [appliesTo, setAppliesTo] = useState("short_term_rental_regulation");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit() {
    setLoading(true);
    setError(null);
    setStatus(null);
    try {
      const response = await addStatute(
        {
          source_type: sourceType,
          jurisdiction_tier: tier,
          citation,
          title,
          text,
          applies_to: appliesTo
            .split(",")
            .map((v) => v.trim())
            .filter(Boolean),
        },
        token ?? undefined
      );
      setStatus(`Added ${response.citation} (id ${response.id.slice(0, 8)}…)`);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
      <h2 className="text-base font-semibold text-slate-100">Add a Statute</h2>
      <div className="mt-3 space-y-3 text-sm">
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-slate-400">Source type</span>
            <select
              className="rounded border border-slate-700 bg-slate-800 px-2 py-1"
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value as SourceType)}
            >
              {SOURCE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-slate-400">Jurisdiction tier</span>
            <select
              className="rounded border border-slate-700 bg-slate-800 px-2 py-1"
              value={tier}
              onChange={(e) => setTier(Number(e.target.value) as JurisdictionTier)}
            >
              {TIERS.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <TextField label="Citation" value={citation} onChange={setCitation} />
        <TextField label="Title" value={title} onChange={setTitle} />
        <label className="flex flex-col gap-1">
          <span className="text-xs text-slate-400">Text</span>
          <textarea
            className="h-20 rounded border border-slate-700 bg-slate-800 p-2"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </label>
        <TextField label="Applies to (entity ids, csv)" value={appliesTo} onChange={setAppliesTo} />
      </div>
      <button
        className="mt-3 rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
        onClick={handleSubmit}
        disabled={loading}
      >
        {loading ? "Adding…" : "Add statute"}
      </button>
      {status && <p className="mt-2 text-sm text-emerald-400">{status}</p>}
      {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
    </div>
  );
}

function PreemptionPanel() {
  const { token } = useApiToken();
  const [entityId, setEntityId] = useState("short_term_rental_regulation");
  const [result, setResult] = useState<PreemptionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleLookup() {
    setLoading(true);
    setError(null);
    try {
      setResult(await getPreemption(entityId, token ?? undefined));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
      <h2 className="text-base font-semibold text-slate-100">Resolve Preemption</h2>
      <p className="mt-1 text-sm text-slate-400">
        Article VI Supremacy Clause resolution for statutes tied to an entity (knowledge_graph/preemption.py).
      </p>
      <div className="mt-3 flex gap-2">
        <input
          className="flex-1 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-sm"
          value={entityId}
          onChange={(e) => setEntityId(e.target.value)}
          placeholder="entity id"
        />
        <button
          className="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
          onClick={handleLookup}
          disabled={loading}
        >
          {loading ? "Looking up…" : "Resolve"}
        </button>
      </div>
      {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
      {result && (
        <div className="mt-3 rounded border border-slate-800 bg-slate-950/60 p-3 text-sm">
          {result.requires_review ? (
            <p className="text-amber-400">
              Requires human review: multiple statutes at the same tier conflict
              {result.conflicting_tier !== null &&
                ` (${TIERS.find((t) => t.value === result.conflicting_tier)?.label ?? result.conflicting_tier})`}
              .
            </p>
          ) : result.governing_citation ? (
            <>
              <p>
                Governing: <span className="font-medium text-emerald-400">{result.governing_citation}</span>
              </p>
              {result.preempted_citations.length > 0 && (
                <p className="mt-1 text-slate-400">Preempts: {result.preempted_citations.join(", ")}</p>
              )}
            </>
          ) : (
            <p className="text-slate-400">No statutes are tied to this entity.</p>
          )}
        </div>
      )}
    </div>
  );
}

function SearchPanel() {
  const { token } = useApiToken();
  const [queryText, setQueryText] = useState("short-term rental permit");
  const [matches, setMatches] = useState<SearchMatch[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSearch() {
    setLoading(true);
    setError(null);
    try {
      setMatches(await searchStatutes(queryText, 5, token ?? undefined));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
      setMatches(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-5 lg:col-span-2">
      <h2 className="text-base font-semibold text-slate-100">Semantic Search</h2>
      <p className="mt-1 text-sm text-slate-400">
        Cosine-distance search over statute text embeddings (knowledge_graph/vector_service.py).
      </p>
      <div className="mt-3 flex gap-2">
        <input
          className="flex-1 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-sm"
          value={queryText}
          onChange={(e) => setQueryText(e.target.value)}
        />
        <button
          className="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
          onClick={handleSearch}
          disabled={loading}
        >
          {loading ? "Searching…" : "Search"}
        </button>
      </div>
      {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
      {matches && (
        <ul className="mt-3 divide-y divide-slate-800 text-sm">
          {matches.length === 0 && <li className="py-2 text-slate-400">No statutes indexed yet.</li>}
          {matches.map((m) => (
            <li key={m.citation} className="flex items-center justify-between py-2">
              <span>{m.citation}</span>
              <span className={`text-xs ${m.is_match ? "text-emerald-400" : "text-slate-500"}`}>
                distance {m.distance.toFixed(3)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-slate-400">{label}</span>
      <input
        className="rounded border border-slate-700 bg-slate-800 px-2 py-1"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
