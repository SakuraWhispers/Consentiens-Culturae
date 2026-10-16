# SCOPE.md — Scope, gates, and decision log

This file controls what gets built and when. Check it before proposing any feature. Changing it is a deliberate act, recorded in the Decision log at the bottom.

Last updated: 2026-10-15.

---

## 1. Product in one paragraph

Consentiens-Culturae helps a small consumer brand compare three competing product concepts for a defined audience and market. It retrieves cultural-affinity evidence from the Qloo API, scores the concepts with transparent deterministic code, has a bounded AI analyst and critic review the explanation, and shows whether the ranking holds when the user's priorities change. It is an early concept-screening aid. It is not a sales forecast and does not replace consumer research.

**Demo category (fixed):** stationery and creative accessories.
**Target user:** a founder or small team at an independent consumer brand with limited research budget.

---

## 2. The pipeline (the only pipeline)

1. **Evidence retrieval**: brief → entity resolution → allowlisted Qloo calls → normalized evidence records with provenance.
2. **Deterministic scoring**: evidence + user weights + hard constraints → scores, ranks, coverage. Code only.
3. **Bounded critique**: analyst drafts an explanation from structured results; critic checks it; at most one revision.
4. **Sensitivity analysis**: seeded sampling of valid weight vectors → top-rank frequency and rank stability.

Anything that does not fit one of these four stages, or the UI and persistence that support them, is out of scope.

---

## 3. In scope (v1, submission)

| Area | Item | Hard cap |
|---|---|---|
| Input | One decision brief form: category (fixed), market, audience description, business goal, up to 3 hard constraints, weights for the 4 soft criteria (C1, C2, C3, C5; C4 is a weightless gate), exactly 3 concepts | 3 concepts, 5 criteria |
| Retrieval | Qloo calls from an allowlist (exact list in `docs/qloo-api-notes.md`) | max 10 Qloo calls per run; 10 s timeout per call; 1 retry on 429 with backoff |
| Evidence | Normalized `EvidenceRecord`s with provenance, match quality, coverage status, `fixture_mode` | — |
| Scoring | 5 criteria (see architecture doc), one `scoring_version`, hard constraints as gates | 1 scoring version |
| Explanation | Analyst (LLM) writes rationale from structured results only | 1 call per run |
| Critique | Critic (LLM) checks against fixed issue codes; at most 1 revision | 1 critic pass, 1 revision |
| Sensitivity | Seeded sampling of weight vectors; top-rank frequency; rank range; which criterion moves the winner | 1,000 samples, fixed seed, fixed ranges |
| Persistence | `decision_runs`, `evidence_records`, `workflow_events`, `score_snapshots`, `critic_findings` | Postgres or SQLite locally |
| Report UI | Brief form, progress view (polling), report with ranks, breakdown, evidence drawer, critic findings, sensitivity chart, limitations, validation steps | One screen each |
| Operations | Health endpoint, fixture/live label, README, LICENSE, `.env.example` | — |
| Tests | Unit (scoring, constraints, missing data, reproducibility), integration (adapter on fixtures), workflow transitions, critic schema, adversarial fixtures | — |

---

## 4. Out of scope (do not build, do not propose without asking)

- Authentication, user accounts, billing, teams, sharing permissions
- Run history and browsing past reports (optional; only if Phase 4 is done early and the human approves)
- The optional `POST /api/decision-runs/{id}/recompute` endpoint (the frontend may recompute client-side only if the human approves)
- LangGraph or any workflow framework
- Message queues, Redis, Kafka, Kubernetes, microservices, separate agent services
- Vector databases, RAG over documents, custom or fine-tuned models
- More than one category, or any category other than stationery and creative accessories
- Demographic (age, gender) affinity as a scored input
- Any output that describes a score as a probability, chance of success, likelihood of purchase, sales, revenue, or market size
- Any claim that the system is more accurate than Zappi, Kantar, Qualtrics, or WGSN
- Market-size or TAM estimates
- Auto-generated marketing copy for the brand's products
- A general-purpose chat interface
- Branding, logo, or domain work before the core path works
- Real-time animations, confidence gauges, or decorative charts
- Model-generated SQL, model-chosen URLs, or model-executed code

---

## 5. Gates (dated)

Dates are Eastern Daylight Time unless stated. Each gate has an acceptance check. A gate is passed only when the check is run and recorded, not when it "should work."

| Gate | Date | Acceptance check | Status |
|---|---|---|---|
| G0 Eligibility and access | Oct 16 | Human confirms eligibility against the official rules page. Hackathon key obtained. Starter kit read. | open |
| G1 API spike | Oct 16 | `scripts/qloo_smoke_test.py` makes one authenticated call, parses the response into an internal object, and the result is recorded in `docs/qloo-api-notes.md`. Recorded response saved REDACTED and LOCAL-ONLY (gitignored, per the 2026-10-16 fixture policy), or as a synthetic fixture if live recording is not possible. | open |
| G2 Thin vertical slice | Oct 19 | Brief + 3 concepts → real Qloo evidence (or labeled fixture) → normalized records → deterministic ranking → report. Reproducibility test passes (same inputs, same output, 10 runs). | passed 2026-10-16 (live confirm + 10-run test; human sign-off) |
| G3 Agent roles and critic | Oct 22 | Researcher plans retrieval within the allowlist. Analyst drafts explanation. Critic runs once. One deliberately injected defect is caught and recorded in `critic_findings`. Coordinator handles the revision or qualifies the claim. | open |
| G4 Sensitivity analysis | Oct 24 | Seeded sampler runs. Top-rank frequency and rank range render. Changing a weight produces a deterministic, explainable change. If this fails, fall back to 3 named weight scenarios. | open |
| G5 Deployed demo | Oct 26 | Backend and frontend deployed. Live Qloo integration verified on the deployed instance (or fixture mode clearly labeled). Works in a fresh browser session. | open |
| G6 Feature freeze | Oct 29 | No new features. README, LICENSE, About section, known limitations, demo script, screenshots complete. | open |
| Submission | Oct 30, 11:45 pm EDT | Repository public with license visible in About. Demo link live. Description accurately describes what is implemented. | open |

**Judging period:** Nov 2 to Nov 16. Winners announced around Nov 23. The deployed demo must remain available through Nov 16.

### If a gate is missed

- Missed G1 (no usable Qloo response): do not build agents on assumed data. Build against labeled fixtures, record the access problem, and narrow the demo to what the real API supports. Tell the human.
- Missed G2: cut optional Level-C features. Ship the deterministic core.
- Missed G3: ship the coordinator with a critic that runs but is limited to deterministic checks (constraint violations, missing evidence, score mismatch). Report it honestly.
- Missed G4: ship the named-scenario version.
- Missed G5: a fixture-mode deployment labeled as fixture mode is acceptable. Do not hide it.

### Cut order (when time runs short)

1. Valid, working Qloo integration (or an honest fixture fallback)
2. Coherent workflow and UI
3. Deterministic scoring with visible evidence
4. Bounded critic
5. Sensitivity analysis (named-scenario fallback allowed)
6. Everything else, including history, animation, and extra metrics

---

## 6. Displacement rule

Every new item must name what it displaces. Write it in the reply like this:

> Adding X. It displaces Y from the in-scope table. Net scope change: none.

If an item displaces nothing and is not on the in-scope table, it is out of scope. Stop and ask.

---

## 7. Evaluation scope (what must be measured, and what we will not claim)

Measured on a fixed set of 6 synthetic-but-realistic briefs with controlled fixtures:

- Baseline A: LLM-only ranking
- Baseline B: Qloo evidence + deterministic scoring (no critic, no sensitivity)
- Candidate C: full pipeline

Metrics: evidence traceability, unsupported-claim count, score-explanation consistency, hard-constraint violations, missing-data disclosure, reproducibility, critic precision and recall on injected defects, latency, Qloo and LLM call counts.

**Rule:** report what was measured. If Candidate C does not beat Baseline B on a metric, say so. Do not claim superiority without a recorded result.

---

## 8. Decision log

Append-only. Newest entries at the bottom. Format: `YYYY-MM-DD | what changed | why | approved by`

- 2026-10-15 | Initial scope written from handoff v1.0 | Establish gates and out-of-scope list before coding | human (solo developer)
- 2026-10-15 | Hosted Postgres choice: Neon (fills the "optionally hosted on Supabase" slot in the stack) | Free-plan standard-Postgres, SQLAlchemy-compatible via DATABASE_URL; fits demo scale and judging window; human raised and approved | human (solo developer)
- 2026-10-16 | Docs moved into `docs/` (architecture.md, qloo-api-notes.md) | AGENTS.md layout names `docs/architecture.md` and `docs/qloo-api-notes.md`; root placement left all `docs/...` references broken; human chose move-over-root-refs | human (solo developer)
- 2026-10-16 | Fixture policy: hand-written synthetic fixtures committable to the public repo; recorded live-response fixtures local-only (gitignored) | Official hackathon guide forbids storing Qloo response data in a public repo; committed recorded fixtures would risk the Qloo-API-usage pass/fail gate; human approved | human (solo developer)
- 2026-10-16 | Product name changed from working name "CultureFit Decision Engine" to **Consentiens-Culturae** across AGENTS.md, SCOPE.md, docs/, pyproject.toml, app code, session log | Human owner's explicit instruction in session; name appeared in AGENTS.md §1 as "(working name, may change)" | human (solo developer)
- 2026-10-16 | Backfilled decision line for the 2026-10-15 C4 decision (decided with the human on 2026-10-15; code shipped same day): C4 constraint-feasibility is a weightless gate; weights cover only C1, C2, C3, C5 and sum to 1; a payload with a `c4` weight is rejected, not dropped | C4 as a weighted score would double-count a gate and risk contradictory ranking | human (2026-10-15 session); line backfilled (session)
- 2026-10-16 | G2 gate PASSED (live confirm C 73.8 > A 67.5 on real evidence + 10-run reproducibility green; human sign-off in session) | acceptance check ran and recorded before marking, per AGENTS.md §9 | human (solo developer)
- 2026-10-16 | Level B/C boundary adopted from handoff: Level B = core + ONE API endpoint + minimal report UI, stable by Oct 19; Level C = B + agentic/analytical behavior (no new infrastructure); cut C before shipping broken B | clarifies G2 scope: API endpoint + minimal UI move INTO G2 | human (pasted handoff §20 wording)
