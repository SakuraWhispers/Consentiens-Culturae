# architecture.md — How Consentiens-Culturae is built

This document describes the system as it should be built. Where something is not yet verified, it says so. Keep it current: when a design decision changes, update the relevant section and add a line to the Decision log in `SCOPE.md`.

Status legend: **[decided]** settled, change only with approval. **[proposed]** our current plan, may change after the API spike. **[open]** not yet decided.

Last updated: 2026-10-27.

---

## 1. Shape of the system [decided]

A **modular monolith**: one Python backend process, one database, one frontend. Internal modules are separated by clear function contracts. There are no separate services and no queues.

```
 Browser (frontend)
     │  POST /api/decision-runs, GET .../{id} (polling)
     ▼
 FastAPI app (app/api)
     │
     ▼
 Workflow coordinator (app/workflow)  ← deterministic; owns state, budgets, limits
     │
     ├─► Researcher  (LLM, optional)  → retrieval plan, validated against allowlist
     │        │
     │        ▼
     │   Qloo adapter (app/integrations) → Qloo HTTP API  (or fixture source)
     │        │
     │        ▼
     │   Evidence normalizer (app/services) → EvidenceRecord[]
     │
     ├─► Decision engine (app/services/decision_engine.py)  ← code only, no LLM
     │        │
     │        ▼
     │   ConceptScore[] + ranks
     │
     ├─► Analyst (LLM) → draft explanation (structured input only)
     │
     ├─► Critic (LLM) → CriticFinding[] (structured output)
     │        └─ at most one revision → analyst again → re-validate
     │
     ├─► Final validator (code) → accepts, qualifies, or removes claims
     │
     ├─► Sensitivity engine (app/services/robustness.py) ← code only, seeded
     │
     └─► Persistence (app/services/persistence.py) → Postgres/SQLite
```

The coordinator is the only component that moves a run from one state to the next. Agents return proposals. The coordinator validates them.

---

## 2. Pipeline stages and their contracts [decided]

Each stage has an input, an output, and a rule about what it may not do.

### Stage 1: Evidence retrieval
- **Input:** validated `DecisionBrief` and three `ConceptInput`s.
- **Process:** the researcher (or, if the LLM is disabled, a deterministic planner) produces a retrieval plan. The coordinator checks every planned call against the allowlist in `docs/qloo-api-notes.md`. Calls run through the Qloo adapter.
- **Output:** `EvidenceRecord[]`, plus `unresolved_entities` and `coverage notes`.
- **May not:** invent an entity ID; call an endpoint not on the allowlist; treat a failed call as an empty result; substitute fixture data silently.
- **Limits:** max 10 Qloo calls per run; 10 s timeout per call; one retry on 429 with backoff; a run with a total failure of retrieval ends in `FAILED_RETRYABLE` or `COMPLETED_WITH_LIMITATIONS`, depending on whether any usable evidence exists.

### Stage 2: Normalization
- **Input:** raw Qloo responses (or fixture payloads).
- **Process:** map each response into the internal `EvidenceRecord` schema. Record the original endpoint, redacted query parameters, retrieval timestamp, match quality, and coverage status. Preserve the raw value as JSON.
- **Output:** normalized `EvidenceRecord[]` persisted for the run.
- **May not:** discard a record because it is inconvenient; coerce a missing field to zero; merge two entities without recording an `ENTITY_MATCH_AMBIGUOUS` limitation.

### Stage 3: Deterministic scoring
- **Input:** normalized evidence, the user's weights, hard constraints, `scoring_version`.
- **Process:** compute five criterion scores per concept, a weighted total, hard-constraint status, evidence coverage, and ranks.
- **Output:** `ConceptScore[]` and `CriterionScore[]`, saved as a `score_snapshot`.
- **May not:** call an LLM; use randomness; treat missing evidence as favorable; compare raw values on different scales without a documented normalization.

### Stage 4: Bounded critique and explanation
- **Input:** `ConceptScore[]`, evidence records, analyst output schema.
- **Process:** the analyst drafts an explanation as structured claims, each referencing `evidence_id`s or score fields. The critic checks each claim. The coordinator allows at most one revision.
- **Output:** a validated report with accepted claims, qualified claims, removed claims, and `CriticFinding[]`.
- **May not:** change a number; change a rank; change a weight; invent an evidence ID; introduce a causal claim without a `CAUSAL_OVERCLAIM` check.

### Stage 5: Sensitivity analysis
- **Input:** user weights, weight ranges, hard constraints, evidence, `scoring_version`, seed.
- **Process:** sample up to 1,000 valid weight vectors with a fixed seed. Exclude vectors that break a hard constraint or a weight bound. Recompute ranks for each vector using the same decision engine code.
- **Output:** top-rank frequency per concept, rank range per concept, which criterion most often changes the winner, sampling metadata (method, seed, count, bounds).
- **May not:** be labeled as a probability of success. Use only: "Top-ranked in X% of tested preference scenarios."

---

## 3. Scoring model [proposed — finalize after G1]

Five criteria. Each returns a value on a 0–100 scale with a documented method. Criteria that cannot be computed from verified data are dropped or marked as user-judged; they are not invented.

| # | Criterion | What it measures | Source | Status |
|---|---|---|---|---|
| C1 | Cultural affinity alignment | How strongly the concept's cultural references match Qloo affinity signals for the chosen audience-and-market entities | Qloo evidence | proposed; depends on G1 |
| C2 | Differentiation | How distinct the concept's attributes and references are from the other two concepts | Concept inputs + Qloo overlap | proposed |
| C3 | Market-context relevance | How much verified evidence supports the concept's references in the chosen market | Qloo evidence + match quality | proposed |
| C4 | Constraint feasibility | Whether the concept meets the user's explicit hard constraints (price band, product type, etc.) | User input | proposed; this is a gate, see §3.2 |
| C5 | Evidence coverage | Share of the concept's claims backed by `available` evidence | Evidence coverage status | proposed |

### 3.1 Normalization
- Each raw measure is mapped to 0–100 using a documented, versioned function (for example, min–max over the run's three concepts, or a fixed scale for coverage ratios).
- The normalization method is recorded in the `CriterionScore` record.
- Min–max over three concepts can make a small difference look large. This is a known limitation and must appear in the report when it applies.

### 3.2 Hard constraints vs. soft weights
- **Hard constraints** are gates. A concept that violates one is marked `INFEASIBLE` with the reason. It stays visible in the report and cannot be ranked first.
- **Soft criteria** (C1, C2, C3, C5) contribute to the weighted total.
- C4 is a gate only (decision 2026-10-15; implemented in `app/schemas/brief.py` and the decision engine): constraint feasibility never enters the weighted total. Weights cover only the four soft criteria C1, C2, C3, C5 and must sum to 1; a payload that carries a `c4` weight is rejected at the schema gate, not silently discarded.

### 3.3 Weighted total
`Score(c) = Σ w_j · s_j(c)` with `Σ w_j = 1`, `w_j ≥ 0`, and each `s_j(c)` in 0–100.

- If a criterion's evidence is missing for a concept, `s_j(c)` is `null`, not zero. The total is computed over available criteria with the reweighted sum, and the report shows the reduced coverage. If coverage falls below a threshold set in `config.py`, the concept is shown as `INSUFFICIENT_EVIDENCE` rather than ranked.
- Ties are broken by a fixed rule (higher C1, then higher C5, then concept_id lexicographic) and the tie is displayed.

### 3.4 Reproducibility
Same brief, same evidence snapshot, same `scoring_version`, same weights → same scores and ranks. This is a required test (G2).

---

## 4. Workflow state machine [decided]

States:

```
CREATED
  → VALIDATING_INPUT
  → RETRIEVING_EVIDENCE
  → NORMALIZING_EVIDENCE
  → SCORING
  → DRAFTING_EXPLANATION
  → CRITIC_REVIEW
  → REVISING            (only if CRITIC_REVIEW returned a fixable finding and revision_count < 1)
  → FINAL_VALIDATION
  → ROBUSTNESS_ANALYSIS
  → COMPLETED
  → COMPLETED_WITH_LIMITATIONS   (evidence was partial or missing; report says so)
  → FAILED_RETRYABLE             (e.g. Qloo timeout; run can be resumed)
  → FAILED_TERMINAL              (e.g. invalid input; cannot proceed)
```

Rules:
- Every transition has a precondition checked in `transitions.py`. An illegal transition raises an error and is logged.
- Each state records `started_at`, `ended_at`, and `outcome` in `workflow_events`.
- `COMPLETED` is set only after `FINAL_VALIDATION` and persistence both succeed.
- A failed Qloo request never produces an `EvidenceRecord` marked `available`. It produces `coverage_status=error` with the error code.
- The run is retrievable by `run_id` at any point. The frontend polls.
- Idempotency: a repeated POST with the same `Idempotency-Key` header returns the existing run instead of starting a new one. (Optional; implement only if time allows. Mark as cut if not done by G3.)

---

## 5. Agent roles (three logical roles, one model is acceptable) [decided]

These are logical boundaries with separate prompts and output schemas. They may run on the same LLM. They are not separate services.

### Researcher
- **Job:** turn the brief and concepts into a retrieval plan: which entities to resolve, which allowlisted calls to make, which terms to search.
- **Output schema:** `RetrievalPlan` (list of planned calls, each with endpoint name from the allowlist and parameters drawn from the brief).
- **Validation:** the coordinator rejects any call whose endpoint is not on the allowlist, any parameter not in the schema, and any plan longer than the call budget.
- **Fallback:** a deterministic planner built from the brief's fields, used when the LLM is disabled or fails.

### Analyst
- **Job:** write the explanation for each concept from the structured score breakdown and evidence.
- **Input:** `ConceptScore[]`, `CriterionScore[]`, `EvidenceRecord[]` (summaries with IDs), limitations, the user's weights.
- **Output schema:** `AnalysisDraft` = list of `Claim` objects. Each `Claim` has `text`, `claim_type` (observation | interpretation | recommendation), `evidence_ids[]`, `score_fields[]`, and `strength` (strong | moderate | weak).
- **Rules:** may not write numbers that are not in the input; may not state a rank that differs from the computed rank; must mark interpretations as interpretations.

### Critic
- **Job:** check each `Claim` against its cited evidence and the computed results.
- **Issue codes (fixed list):** `UNSUPPORTED_CLAIM`, `CLAIM_STRENGTH_EXCEEDS_EVIDENCE`, `MISSING_EVIDENCE`, `ENTITY_MATCH_AMBIGUOUS`, `CONSTRAINT_VIOLATION`, `SCORE_MISMATCH`, `CAUSAL_OVERCLAIM`, `CULTURAL_STEREOTYPE_RISK`, `INCOMPARABLE_DATA`, `CONTRADICTORY_RATIONALE`.
- **Output schema:** `CriticFinding[]` with `issue_code`, `severity`, `affected_concept_id`, `affected_claim_id`, `evidence_ids`, `explanation`, `suggested_action` (`remove` | `qualify` | `revise_wording`).
- **Rules:** cannot edit evidence, scores, weights, or constraints. Its findings are proposals. The validator applies only the allowed actions.

### Coordinator (code, not an agent)
- Controls state, budgets, retries, timeouts, revision count (max 1), schema validation of every agent output, and persistence.
- If an agent output fails schema validation, the coordinator retries once, then falls back to the deterministic template for that section and records a limitation.

---

## 6. Deterministic fallbacks [decided]

The app must produce a usable report with the LLM disabled. This is both a reliability requirement and a test case.

- Researcher → deterministic planner.
- Analyst → template text built from the score breakdown ("Concept A ranks first on C1 and C5; C3 is missing for this concept.").
- Critic → deterministic checks only: constraint violations, missing evidence, score mismatch against the computed rank, claims with no `evidence_ids`.

The report labels which sections were LLM-written and which were template-written.

---

## 7. Data model [proposed — refine after G1]

Tables (minimum, JSON columns allowed):

- `decision_runs`: run_id (UUID), created_at, updated_at, state, input_json, final_report_json, error_code, error_message_safe, scoring_version, workflow_version, revision_count
- `evidence_records`: evidence_id (UUID), run_id (FK), source, qloo_entity_id, endpoint_or_operation, query_params_redacted_json, evidence_json, retrieved_at, match_quality, coverage_status, fixture_mode
- `workflow_events`: event_id, run_id, sequence_number, state, event_type, safe_payload_json, created_at
- `score_snapshots`: score_id, run_id, concept_id, score_json, scoring_version, created_at
- `critic_findings`: finding_id, run_id, finding_json, created_at

Rules:
- Never store the API key or any header value.
- Redact query parameters before storing.
- Do not store full raw Qloo payloads beyond what reproducibility needs. Check Qloo's terms (see `docs/qloo-api-notes.md`) before deciding how much raw data to keep.
- Migrations: use simple SQL or SQLAlchemy `create_all` for v1. Do not build a migration framework.

---

## 8. Qloo adapter boundary [decided]

- `integrations/qloo_client.py`: HTTP only. Builds requests, sends them with httpx, applies timeouts and the retry policy, returns a typed response or a typed error. Knows nothing about decisions.
- `integrations/qloo_adapter.py`: maps Qloo response shapes to internal schemas. This is the only module that knows Qloo's field names. If Qloo changes a field, only this file changes.
- A `FixtureSource` implements the same interface and reads from `tests/fixtures/` (or a bundled fixture directory in demo mode). Its output sets `fixture_mode=true`.
- The exact endpoints, parameters, and response fields are **unverified** until recorded in `docs/qloo-api-notes.md`.

Error mapping (required):

| Condition | Internal code | Evidence record |
|---|---|---|
| 401 / 403 | `QLOO_AUTH_FAILED` | none created; run limitation |
| 429 | `QLOO_RATE_LIMITED` | retry once with backoff; if still failing, error record |
| timeout | `QLOO_TIMEOUT` | error record |
| malformed JSON | `QLOO_MALFORMED_RESPONSE` | error record with raw length, not raw body |
| empty result | `QLOO_NO_MATCH` | record with `coverage_status=missing`, not a negative signal |
| unexpected field | logged as warning | normalized if known; ignored otherwise |

---

## 9. Security and configuration [decided]

- Settings come from environment variables via `config.py`. Required: `QLOO_API_KEY` (live mode only), `LLM_API_KEY` (if LLM enabled), `DATABASE_URL`, `APP_MODE` (`fixture` | `live`).
- `APP_MODE=fixture` is the default. The UI shows a banner: "Demo mode: fixture data, not live Qloo output."
- `APP_MODE=live` with a missing key fails at startup with a clear message, not at request time.
- Request body limits and field length limits are enforced by Pydantic models.
- Logs include `run_id` and state names. They never include request bodies, headers, or keys.
- The LLM receives only structured data and the user's text, which is treated as data, not instructions. Prompts state this explicitly.

---

## 10. Frontend [proposed — Phase 4]

Four views, no more:

1. **Brief**: form with category (fixed), market, audience, goal, constraints, weights, three concept cards. A visible note: "Early screening aid. Not a demand forecast."
2. **Progress**: polls `GET /api/decision-runs/{id}`. Shows persisted state names in plain language. Shows the fixture banner when applicable.
3. **Report**: ranked concept cards, criterion breakdown, hard-constraint status, coverage, critic findings and what was revised, sensitivity chart, "what would change the ranking," missing evidence, validation steps, evidence drawer.
4. **Weight sandbox**: client-side recalculation using the same scoring logic (ported or shared), with a clear "recalculate" action. Default ranking shown for comparison. If client-side scoring diverges from server scoring in tests, the server result wins and the sandbox is labeled as approximate.

Design rules: one primary action per view; no confidence gauges; limitations visible in the report body, not in a footer.

---

## 11. Testing layers [decided]

| Layer | What | Where | Runs |
|---|---|---|---|
| Unit | weight normalization, scoring, constraints, missing data, tie-break, reproducibility | `tests/unit/` | always |
| Integration | Qloo adapter against fixtures, including all error mappings | `tests/integration/` | always |
| Workflow | state transitions, illegal transitions, revision limit, fallback paths | `tests/workflow/` | always |
| Schema | critic and analyst output validation, including malformed outputs | `tests/unit/` | always |
| Adversarial | no match, ambiguous match, conflicting evidence, missing criterion, overclaim, score mismatch, constraint violation, timeout, 429, malformed, ranking flip under weights | `tests/fixtures/` + `tests/workflow/` | always |
| Live | real Qloo calls | `tests/live/` | manual only: `pytest -m live` |

Adversarial fixtures must each be labeled in their filename, for example `fixture_adv_ambiguous_match.json`.

---

## 12. Known architectural risks

| Risk | Mitigation | Owner doc |
|---|---|---|
| Qloo endpoints differ from the notes | G1 spike; adapter isolates change | `qloo-api-notes.md` |
| Hackathon key limits endpoints or quota | Fixture mode; narrow demo to what works | `SCOPE.md` §5 |
| LLM output fails schema validation | Retry once, then template fallback | §5, §6 |
| Min–max normalization over three concepts exaggerates small gaps | Disclose in report; show raw values | §3.1 |
| Sensitivity results over-read as probability | Fixed label wording; test that the label string appears | §2 Stage 5 |
| Weight sandbox diverges from server scoring | Shared logic or server authority | §10 |
| Scope creep | `SCOPE.md` displacement rule | `SCOPE.md` §6 |
