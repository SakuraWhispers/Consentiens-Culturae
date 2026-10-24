// Typed client for the FastAPI backend. The base URL is configurable so a
// deployed frontend can point at a hosted backend (dev default localhost).
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface HardConstraint {
  attribute: string;
  value: string;
}

export interface ConceptInput {
  concept_id: string;
  name: string;
  description: string;
  attributes: Record<string, string>;
}

/** A run id in the exact shape the API accepts (32 lowercase hex chars). */
export function newRunId(): string {
  const raw =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random()}`;
  return raw.replace(/[^a-f0-9]/gi, "").toLowerCase().padEnd(32, "0").slice(0, 32);
}

export interface BriefPayload {
  market: string;
  audience_description: string;
  business_goal: string;
  constraints: HardConstraint[];
  weights: { c1: number; c2: number; c3: number; c5: number };
  concepts: ConceptInput[];
}

// Report types mirror app/workflow/coordinator.py's report dict 1:1.
export interface CriterionScore {
  criterion: string;
  value: number | null;
  weight_applied: number | null;
}

export interface ConceptRank {
  concept_id: string;
  rank: number | null;
  status: string; // RANKED | INFEASIBLE | ...
  weighted_total: number | null;
  coverage: number | null;
  /** Why the concept is not ranked (hard-constraint or coverage gate). */
  reason?: string | null;
  /** A constraint that could NOT be checked (missing attribute) never blocks
   *  (2026-10-23): the concept ranks and this notice explains it. */
  constraint_notice?: string | null;
  criterion_scores: CriterionScore[];
  diagnostics: Record<string, unknown>;
}

export interface Claim {
  claim_id: string;
  concept_id: string;
  claim_type: string;
  strength: string;
  confidence: string;
  text: string;
  evidence_ids: string[];
  score_fields: string[];
  audience_context: string | null;
  qualified?: boolean;
}

export interface CriticFinding {
  issue_code: string;
  severity: string;
  affected_concept_id: string;
  affected_claim_id: string;
  evidence_ids: string[];
  explanation: string;
  suggested_action: string;
  /** "llm" (the LLM critic) or "rules" (the deterministic rule checks). */
  source?: string;
}

export interface Sensitivity {
  method: string;
  seed: number | null;
  scenarios_tested: number;
  base_winner: string | null;
  top_rank_frequency: Record<string, number>;
  statements: Record<string, string>;
  /** How often each concept was level with another (not a clear winner). */
  tie_frequency?: Record<string, number>;
  tie_statements?: Record<string, string>;
  tie_scenarios?: number;
  tie_scenario_fraction?: number;
  rank_range: Record<string, unknown> | Record<string, [number, number]>;
  pivotal_criterion: string | null;
  scoring_version: string;
}

/** What the researcher did and found. */
export interface ResearchBlock {
  mode: "agent" | "deterministic" | "resumed";
  calls: Array<{
    endpoint: string;
    params: Record<string, string>;
    owner: string | null;
  }>;
  evidence: {
    total: number;
    available: number;
    per_concept: Record<string, { available: number; total: number }>;
  };
  qloo_calls: number;
}

/** A tie between the leading concepts (they are level, not ranked apart). */
export interface TieBlock {
  detected: boolean;
  concepts: string[];
  spread: number | null;
  threshold: number;
  top_total?: number;
}

export interface StageTiming {
  stage: string;
  seconds: number;
}

/**
 * What the tie-break did when the leaders ended level: extra Qloo calls for
 * the tied concepts, the totals recomputed, and (if still level) a focused
 * LLM comparison. 2026-10-22, Batch 2.
 */
export interface TiebreakBlock {
  detected: boolean;
  concepts: string[];
  extra_calls: number;
  new_entities: number;
  known_entities_skipped: number;
  before: Record<string, number>;
  after: Record<string, number>;
  resolved: boolean;
  comparison: Claim[];
  note: string;
}

/**
 * The verbose report in words (2026-10-22, Batch 3): written by the reporter
 * model (number-guarded) or by the deterministic template when the model may
 * not or cannot write.
 */
export interface VerboseBlock {
  prose: string;
  llm_written: boolean;
  attempts: number;
  template_fallback: boolean;
  template_reason: string | null;
  note: string;
}

export interface Report {
  run_id: string;
  state: string;
  scoring_version: string;
  workflow_version: string;
  fixture_mode: boolean;
  fixture_banner: string | null;
  winner: string | null;
  ranks: ConceptRank[];
  formulas: Record<string, string>;
  claims: Claim[];
  critic_findings: CriticFinding[];
  limitations: string[];
  explanation_template: boolean;
  llm_written: boolean;
  analyst: { llm_written: boolean; revision_count: number };
  critic: {
    llm_written: boolean;
    findings_count: number;
    llm_findings: number;
    rule_findings: number;
    /** The scope of the critique, so "0 findings" reads as "it ran". */
    claims_reviewed: number;
    /** The critique, per concept (2026-10-24): drawbacks per concept plus
     *  the winning-concept note. Present in reports from this version on. */
    concept_notes?: {
      notes: Record<string, string>;
      winner_note: string;
      llm_written: boolean;
      template_used?: boolean;
      template_reason?: string | null;
    };
    evidence_records_available: number;
    issue_codes: string[];
  };
  research: ResearchBlock;
  tie: TieBlock;
  tiebreak?: TiebreakBlock;
  verbose?: VerboseBlock;
  stages?: StageTiming[];
  sensitivity: Sensitivity;
  disclaimer: string;
}

export interface RunBundle {
  run: {
    run_id: string;
    state: string;
    input_json: BriefPayload & { category: string };
    final_report_json: Report;
    scoring_version: string;
    workflow_version: string;
    revision_count: number;
  };
  evidence: Array<{
    evidence_id: string;
    qloo_entity_id: string | null;
    entity_name?: string | null;
    entity_subtype?: string | null;
    popularity?: number | null;
    tags?: string[];
    match_quality: string;
    coverage_status: string;
    endpoint_or_operation: string;
    query_params_redacted: Record<string, string>;
    source: string;
    fixture_mode: boolean;
    limitations?: string[];
  }>;
  scores: Array<{ concept_id: string; score_json: Record<string, unknown> }>;
  events: Array<{
    sequence_number: number;
    state: string;
    event_type: string;
    detail?: Record<string, unknown>;
  }>;
  critic: CriticFinding[];
}

export async function fetchHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/health`, { cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  }
}

/** An error the API returned, with the status code the UI reacts to. */
export class ApiError extends Error {
  status: number;
  retryAfterSeconds: number | null;

  constructor(status: number, message: string, retryAfterSeconds: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }

  /** True when running the same brief again could plausibly succeed. */
  get retryable(): boolean {
    return this.status === 429 || this.status === 503 || this.status >= 500;
  }
}

/** One proposed attribute: the user decides what (if anything) to copy into
 *  the form, and the constraint gate itself stays deterministic code. */
export interface AttributeSuggestion {
  attribute: string;
  value: string;
  basis: "stated" | "inferred";
  quote: string;
}

export interface ConceptSuggestion {
  concept_id: string;
  attributes: AttributeSuggestion[];
}

/** POST /attributes/suggest (2026-10-23): SHOW-ONLY proposals grounded in the
 *  concept's own description. Nothing here is written into the brief. */
export async function suggestAttributes(
  concept: { concept_id: string; name: string; description: string },
  targetAttributes: string[]
): Promise<ConceptSuggestion[]> {
  const res = await fetchWithTimeout(
    `${API_BASE}/api/attributes/suggest`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        concepts: [concept],
        target_attributes: targetAttributes,
      }),
    },
    60 * 1000
  );
  if (!res.ok) {
    const detail = await res
      .json()
      .then((j) => j?.detail)
      .catch(() => null);
    throw new ApiError(
      res.status,
      typeof detail === "string" ? detail : `backend returned ${res.status}`
    );
  }
  const body = (await res.json()) as { suggestions: ConceptSuggestion[] };
  return body.suggestions;
}

/** POST /decision-runs returns {run_id, state, report, persisted} (coordinator). */
export interface RunResponse {
  run_id: string;
  state: string;
  report: Report | null;
  persisted: string;
}

export async function postRun(
  brief: BriefPayload,
  runId?: string
): Promise<RunResponse> {
  const res = await fetchWithTimeout(
    `${API_BASE}/api/decision-runs`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(runId ? { ...brief, run_id: runId } : brief),
    },
    RUN_TIMEOUT_MS
  );
  if (!res.ok) {
    const detail = await res
      .json()
      .then((j) => j?.detail)
      .catch(() => null);
    const message =
      typeof detail === "string" ? detail : `backend returned ${res.status}`;
    // Retry-After is only readable because the API exposes it via CORS.
    const rawRetry = res.headers.get("Retry-After");
    const seconds = rawRetry ? Number(rawRetry) : NaN;
    throw new ApiError(
      res.status,
      message,
      Number.isFinite(seconds) ? seconds : null
    );
  }
  return res.json();
}

/** Continue a half-finished run in place, reusing its stored evidence. */
export async function resumeRun(runId: string): Promise<RunResponse> {
  const res = await fetchWithTimeout(
    `${API_BASE}/api/decision-runs/${runId}/resume`,
    { method: "POST" },
    RUN_TIMEOUT_MS
  );
  if (!res.ok) {
    const detail = await res
      .json()
      .then((j) => j?.detail)
      .catch(() => null);
    const message =
      typeof detail === "string" ? detail : `backend returned ${res.status}`;
    const rawRetry = res.headers.get("Retry-After");
    const seconds = rawRetry ? Number(rawRetry) : NaN;
    throw new ApiError(
      res.status,
      message,
      Number.isFinite(seconds) ? seconds : null
    );
  }
  return res.json();
}

/** Delete a run and its rows (the "start fresh" cleanup). */
export async function deleteRun(runId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/decision-runs/${runId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const detail = await res
      .json()
      .then((j) => j?.detail)
      .catch(() => null);
    throw new ApiError(
      res.status,
      typeof detail === "string" ? detail : `backend returned ${res.status}`
    );
  }
}

/** A request that never answers must not hang the page forever (2026-10-22:
 *  the backend was killed mid-request and the page sat on "Loading run…"). */
const FETCH_TIMEOUT_MS = 15000;
/** A run takes minutes (5–15 live), so the run-starting calls wait much
 *  longer before giving up. */
const RUN_TIMEOUT_MS = 20 * 60 * 1000;

async function fetchWithTimeout(
  url: string,
  init?: RequestInit,
  timeoutMs: number = FETCH_TIMEOUT_MS
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(
        504,
        timeoutMs >= RUN_TIMEOUT_MS
          ? "The run did not finish within 20 minutes. The backend may have stopped — check that it is running, then resume or start fresh."
          : "The backend did not answer within 15 seconds. It may not be running — start it and try again."
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

// One shared in-flight request per run id: every tab/poller refreshing the
// same run joins ONE backend request instead of stacking them - each stacked
// request holds a database connection for its full duration, which is what
// drained the pool (2026-10-24). Also healed by the server bundle cache.
const bundleInFlight = new Map<string, Promise<RunBundle>>();

export function getRunBundle(runId: string): Promise<RunBundle> {
  const existing = bundleInFlight.get(runId);
  if (existing) return existing;
  const request = fetchRunBundle(runId).finally(() => bundleInFlight.delete(runId));
  bundleInFlight.set(runId, request);
  return request;
}

async function fetchRunBundle(runId: string): Promise<RunBundle> {
  const res = await fetchWithTimeout(`${API_BASE}/api/decision-runs/${runId}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(res.status === 404 ? "unknown run" : `backend returned ${res.status}`);
  }
  return res.json();
}
