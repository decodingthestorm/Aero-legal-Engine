// Typed client for the FastAPI gateway (see ../../../src/legal_engine/api/).
// Every type here mirrors a real Pydantic request/response model — kept in
// sync by hand since there's no shared schema generation step yet.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  detail: string;
  correlationId: string | null;

  constructor(status: number, detail: string, correlationId: string | null) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.correlationId = correlationId;
  }
}

async function apiFetch<T>(path: string, options: RequestInit = {}, token?: string): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });

  if (!response.ok) {
    // api/middleware.py's error handler shape for our domain exceptions;
    // FastAPI's own validation errors (422) have a different {detail: [...]}
    // shape, so fall back gracefully if `detail` isn't a plain string.
    let detail = response.statusText;
    let correlationId: string | null = response.headers.get("X-Correlation-ID");
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
      correlationId = body.correlation_id ?? correlationId;
    } catch {
      // response body wasn't JSON; keep the statusText fallback
    }
    throw new ApiError(response.status, detail, correlationId);
  }

  return response.json() as Promise<T>;
}

// ---- /health ----

export interface HealthResponse {
  status: string;
}

export function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health");
}

// ---- /auth ----

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in_minutes: number;
}

export function issueToken(clientId: string, clientSecret: string): Promise<TokenResponse> {
  return apiFetch<TokenResponse>("/auth/token", {
    method: "POST",
    body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
  });
}

// ---- /verification ----

export type TermSchema = { kind: "constant"; name: string } | { kind: "variable"; name: string };

export type FormulaSchema =
  | { kind: "atom"; predicate: string; args: TermSchema[] }
  | { kind: "not"; operand: FormulaSchema }
  | { kind: "and"; operands: FormulaSchema[] }
  | { kind: "or"; operands: FormulaSchema[] }
  | { kind: "implies"; antecedent: FormulaSchema; consequent: FormulaSchema };

export interface VerifyClauseRequest {
  exists_vars: string[];
  forall_vars: string[];
  matrix: FormulaSchema;
  domain: string[];
}

export interface ProofResult {
  satisfiable: boolean;
  unsat_core: string[];
  counterexample: Record<string, string> | null;
  elapsed_ms: number;
  timed_out: boolean;
}

export interface VerifyClauseResponse {
  proof_result: ProofResult;
  smt_lib2: string;
}

export function verifyClause(
  request: VerifyClauseRequest,
  token?: string
): Promise<VerifyClauseResponse> {
  return apiFetch<VerifyClauseResponse>(
    "/verification/verify",
    { method: "POST", body: JSON.stringify(request) },
    token
  );
}

// ---- /simulation ----

export interface PenaltyRequest {
  benefit: number;
  cost_compliance: number;
  p_detect: number;
}

export interface PenaltyResponse {
  minimum_deterrent_penalty: number;
  recommended_penalty: number;
  recommended_penalty_is_dominant: boolean;
}

export function computePenalty(request: PenaltyRequest, token?: string): Promise<PenaltyResponse> {
  return apiFetch<PenaltyResponse>("/simulation/penalty", { method: "POST", body: JSON.stringify(request) }, token);
}

export interface PenaltyCurveRequest {
  k: number;
  x_limit: number;
  disgorgement?: number;
  sample_points: number[];
}

export function computePenaltyCurve(
  request: PenaltyCurveRequest,
  token?: string
): Promise<Record<string, number>> {
  return apiFetch<Record<string, number>>(
    "/simulation/penalty-curve",
    { method: "POST", body: JSON.stringify(request) },
    token
  );
}

// ---- /graph ----

export type SourceType =
  | "municipal_code"
  | "state_statute"
  | "federal_code"
  | "international_treaty"
  | "judicial_precedent";

// Mirrors core.models.JurisdictionTier: lower value = higher precedence.
export enum JurisdictionTier {
  INTERNATIONAL_TREATY = 0,
  FEDERAL = 1,
  STATE = 2,
  COUNTY = 3,
  MUNICIPAL = 4,
}

export interface AddStatuteRequest {
  source_type: SourceType;
  jurisdiction_tier: JurisdictionTier;
  citation: string;
  title: string;
  text: string;
  applies_to: string[];
}

export interface AddStatuteResponse {
  id: string;
  citation: string;
}

export function addStatute(request: AddStatuteRequest, token?: string): Promise<AddStatuteResponse> {
  return apiFetch<AddStatuteResponse>("/graph/statutes", { method: "POST", body: JSON.stringify(request) }, token);
}

export interface PreemptionResponse {
  entity_id: string;
  governing_citation: string | null;
  preempted_citations: string[];
  requires_review: boolean;
  conflicting_tier: JurisdictionTier | null;
}

export function getPreemption(entityId: string, token?: string): Promise<PreemptionResponse> {
  return apiFetch<PreemptionResponse>(`/graph/preemption/${encodeURIComponent(entityId)}`, {}, token);
}

export interface SearchMatch {
  citation: string;
  distance: number;
  is_match: boolean;
}

export function searchStatutes(queryText: string, topK = 5, token?: string): Promise<SearchMatch[]> {
  return apiFetch<SearchMatch[]>(
    "/graph/search",
    { method: "POST", body: JSON.stringify({ query_text: queryText, top_k: topK }) },
    token
  );
}
