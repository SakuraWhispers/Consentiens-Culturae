# SCOPE.md — Scope, gates, and decision log

This file controls what gets built and when. Check it before proposing any feature. Changing it is a deliberate act, recorded in the Decision log at the bottom.

Last updated: 2026-10-27.

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

All four stages are **implemented, offline-tested (≈260 tests, all green), and deployed**. Wave-1 hardening on top (2026-10-26, all live-verified or offline-proven): every live `/search` is place-typed (`urn:entity:place`, kills book/media pollution); the critic receives a per-concept evidence map (`known_evidence_by_concept`); the suggester's "stated" basis requires a verbatim quote from the concept's own text. RESUME for half-finished runs and DELETE reuse the same persistence layer.

Anything that does not fit one of these four stages, or the UI and persistence that support them, is out of scope.

---

## 3. In scope (v1, submission)

| Area | Item | Hard cap | Status |
|---|---|---|---|
| Input | One decision brief form: category (fixed), market, audience description, business goal, up to 3 hard constraints, weights for the 4 soft criteria (C1, C2, C3, C5; C4 is a weightless gate), exactly 3 concepts | 3 concepts, 5 criteria | **built** (structured concept attributes added 2026-10-22) |
| Retrieval | Qloo calls from an allowlist (exact list in `docs/qloo-api-notes.md`) | max 10 Qloo calls per run; 10 s timeout per call; 1 retry on 429 with backoff | **built + hardened** (researcher-planned, allowlist-enforced, tie-break aware) |
| Evidence | Normalized `EvidenceRecord`s with provenance, match quality, coverage status, `fixture_mode` | — | **built** (match quality + entity name in the drawer) |
| Scoring | 5 criteria (see architecture doc), one `scoring_version`, hard constraints as gates | 1 scoring version | **built** (INFEASIBLE + INSUFFICIENT_EVIDENCE paths live) |
| Explanation | Analyst (LLM) writes rationale from structured results only | 1 call per run | **built** (schema contracts + synonym bridges + per-item salvage) |
| Critique | Critic (LLM) checks against fixed issue codes; at most 1 revision | 1 critic pass, 1 revision | **built + widened** (informed retry; per-concept evidence map since 2026-10-26) |
| Sensitivity | Seeded sampling of weight vectors; top-rank frequency; rank range; which criterion moves the winner | 1,000 samples, fixed seed, fixed ranges | **built** (tie-aware phrasing live) |
| Persistence | `decision_runs`, `evidence_records`, `workflow_events`, `score_snapshots`, `critic_findings` | Postgres or SQLite locally | **built** (incremental + fault-tolerant + RESUME/DELETE for half-finished runs) |
| Report UI | Brief form, progress view (polling), report with ranks, breakdown, evidence drawer, critic findings, sensitivity chart, limitations, validation steps | One screen each | **built** (Next.js in `website/`, deployed) |
| Operations | Health endpoint, fixture/live label, README, LICENSE, `.env.example` | — | **built** (pool-drain cache + 503 wording; local SQLite db gitignored) |
| Tests | Unit (scoring, constraints, missing data, reproducibility), integration (adapter on fixtures), workflow transitions, critic schema, adversarial fixtures | — | **built** (≈260 offline tests passing; live tests skipped by default) |

---

## 4. Out of scope (do not build, do not propose without asking)

- Authentication, user accounts, billing, teams, sharing permissions
- Run history and browsing past reports (optional; only if Phase 4 is done early and approval is given)
- The optional `POST /api/decision-runs/{id}/recompute` endpoint (the frontend may recompute client-side only if approval is given)
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
| G0 Eligibility and access | Oct 16 | Confirms eligibility against the official rules page. Hackathon key obtained. Starter kit read. | **PASSED 2026-10-16** — key obtained, rules read, kit reviewed. |
| G1 API spike | Oct 16 | `scripts/qloo_smoke_test.py` makes one authenticated call, parses the response into an internal object, and the result is recorded in `docs/qloo-api-notes.md`. Recorded response saved REDACTED and LOCAL-ONLY (gitignored, per the 2026-10-16 fixture policy), or as a synthetic fixture if live recording is not possible. | **PASSED 2026-10-16** — base URL + auth verified live; all findings recorded in `docs/qloo-api-notes.md`; recorded fixtures saved local-only. |
| G2 Thin vertical slice | Oct 19 | Brief + 3 concepts → real Qloo evidence (or labeled fixture) → normalized records → deterministic ranking → report. Reproducibility test passes (same inputs, same output, 10 runs). | passed 2026-10-16 (live confirm + 10-run test; sign-off) |
| G3 Agent roles and critic | Oct 22 | Researcher plans retrieval within the allowlist. Analyst drafts explanation. Critic runs once. One deliberately injected defect is caught and recorded in `critic_findings`. Coordinator handles the revision or qualifies the claim. | **PASSED 2026-10-17 (sign-off).** Evidence: all four roles live-verified (analyst 5 schema-valid claims on run acbe81273f2f42f387519bc715cbbce1; critic validated on 3 model instances; researcher enforcement proven on accepted AND rejected plans; injected-defect + revision loop proven in offline tests); 116 offline tests passing. |
| G4 Sensitivity analysis | Oct 24 | Seeded sampler runs. Top-rank frequency and rank range render. Changing a weight produces a deterministic, explainable change. If this fails, fall back to 3 named weight scenarios. | **PASSED 2026-10-24** — seeded sampler live on deployed runs; tie-aware phrasing; weight-change effect deterministic (tests + deployed report). |
| G5 Deployed demo | Oct 26 | Backend and frontend deployed. Live Qloo integration verified on the deployed instance (or fixture mode clearly labeled). Works in a fresh browser session. | **PASSED 2026-10-26** — Render backend + Vercel frontend live; real Qloo runs verified on the deployed instance; fresh browser session working. |
| G6 Feature freeze | Oct 29 | No new features. README, LICENSE, About section, known limitations, demo script, screenshots complete. | **PASSED 2026-10-27 (owner declaration).** Known limitations recorded; `docs/demo-script.md` is the one artifact still to write before submission. |
| Submission | Oct 30, 11:45 pm EDT | Repository public with license visible in About. Demo link live. Description accurately describes what is implemented. | **PASSED 2026-10-27 (owner declaration).** Repo public + deployed demo live; submission-form description to be finalized at submit. |

**Judging period:** Nov 2 to Nov 16. Winners announced around Nov 23. The deployed demo must remain available through Nov 16.

### If a gate is missed

- Missed G1 (no usable Qloo response): do not build agents on assumed data. Build against labeled fixtures, record the access problem, and narrow the demo to what the real API supports. Tell the decision-maker.
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
- 2026-10-15 | Hosted Postgres choice: Neon (fills the "optionally hosted on Supabase" slot in the stack) | Free-plan standard-Postgres, SQLAlchemy-compatible via DATABASE_URL; fits demo scale and judging window; raised and approved | decision-maker (solo developer)
- 2026-10-16 | Docs moved into `docs/` (architecture.md, qloo-api-notes.md) | AGENTS.md layout names `docs/architecture.md` and `docs/qloo-api-notes.md`; root placement left all `docs/...` references broken; human chose move-over-root-refs | human (solo developer)
- 2026-10-16 | Fixture policy: hand-written synthetic fixtures committable to the public repo; recorded live-response fixtures local-only (gitignored) | Official hackathon guide forbids storing Qloo response data in a public repo; committed recorded fixtures would risk the Qloo-API-usage pass/fail gate; approved | decision-maker (solo developer)
- 2026-10-16 | Product name changed from working name "CultureFit Decision Engine" to **Consentiens-Culturae** across AGENTS.md, SCOPE.md, docs/, pyproject.toml, app code, session log | Explicit instruction; name appeared in AGENTS.md §1 as "(working name, may change)" | decision-maker (solo developer)
- 2026-10-16 | Backfilled decision line for the 2026-10-15 C4 decision (decided with the human on 2026-10-15; code shipped same day): C4 constraint-feasibility is a weightless gate; weights cover only C1, C2, C3, C5 and sum to 1; a payload with a `c4` weight is rejected, not dropped | C4 as a weighted score would double-count a gate and risk contradictory ranking | human (2026-10-15 session); line backfilled (session)
- 2026-10-16 | G2 gate PASSED (live confirm C 73.8 > A 67.5 on real evidence + 10-run reproducibility green; sign-off) | acceptance check ran and recorded before marking, per AGENTS.md §9 | decision-maker (solo developer)
- 2026-10-16 | Level B/C boundary adopted from handoff: Level B = core + ONE API endpoint + minimal report UI, stable by Oct 19; Level C = B + agentic/analytical behavior (no new infrastructure); cut C before shipping broken B | clarifies G2 scope: API endpoint + minimal UI move INTO G2 | human (pasted handoff §20 wording)
- 2026-10-17 | G3 gate set to PROVISIONAL (researcher enforcement + critic live-verified; analyst live confirmation pending free-pool capacity; sign-off pending) | partial-status option chosen explicitly | analyst path blocked only by OpenRouter free-pool 429s, not by code; evidence assembled honestly | human (provisional-status approval)
- 2026-10-17 | G3 → EVIDENCED (all four roles live-verified; see SCOPE gate line) — still awaiting explicit human sign-off before marking PASSED | straight to PASSED | sign-off is a human judgement call by the operating rules; every accept has run code + a persisted Neon run record behind it | agent applying human's standing gate discipline
- 2026-10-17 | G3 PASSED with sign-off ("G3 passed", in response to the attempt-10 evidence summary) | — | gate condition met: researcher within allowlist, analyst explanation drafted live, critic runs once, injected defect caught, revision/qualification handled | decision-maker
- 2026-10-20 | UI phase move-in recorded: interactive Next.js site in `website/` on the real backend; CORS for localhost dev only.
- 2026-10-20 | Human-supplied `logo+tagline.png` becomes the single logo asset (rendered via LogoBanner; manual tagline text removed everywhere) | one source of truth for the lockup; supplied the asset | decision-maker
- 2026-10-20 | G3 LLM hooks wired onto the HTTP API path (`app/services/llm_hooks.py`): same four hooks as the probe, two-pool config, paced transient retry, loud 503 when enabled-but-misconfigured; API previously ran template-only explanations | API parity with the verified G3 path; misconfiguration must be loud, never a silent fallback | human (asked "yes I want you to wire the llm")
- 2026-10-20 | API run limiter added (`app/services/rate_limiter.py`): 1 concurrent run, RUN_MIN_GAP_SECONDS (30) between starts, RUNS_PER_DAY (50) per UTC day, 429 + Retry-After; env-tunable | protect the free-model budgets from parallel/rapid-fire UI runs (each run is up to 10 Qloo + up to 9 LLM calls) | human (Q&A choice)
- 2026-10-20 | Weight sliders use proportional squeeze: total pinned at exactly 100%; raising one slider lowers the others pro-rata, lowering redistributes pro-rata; even-split escape hatch for the all-zero state; step 1% | human Q&A choice over largest-first and cap-only options; engine requires sum=1
- 2026-10-20 | UI run-time copy updated to "5-15 minutes" after the live LLM-wired run took ~13 min (pacing + free-pool generation latency) | honest expectation setting after real measurement | agent (measured), human informed
- 2026-10-21 | LLM-stage resilience, three layers: (1) prompt contracts state every closed enum the code validates (critic severity, researcher param names and the insights call shape, revision claim spec); (2) transport-shape normalization + closed-enum synonym bridges (researcher "filter" -> filter.type, critic severity medium -> minor); (3) per-item salvage (a bad plan call / claim / finding is dropped and REPORTED, not the whole stage) plus an INFORMED retry (the validation error is handed back to the model, temperature 0.3) plus a persisted "agent_output_rejected" audit event | the 2026-10-20 live run lost the researcher plan and the entire critique to two single-field mistakes, and the blind retry at temperature 0 could not have fixed either | human (asked for the failure analysis and the fixes), agent implemented test-first
- 2026-10-21 | docs/known-limitations.md created (was scheduled by Oct 25) | the live run produced concrete, honest limitations worth recording before the demo freeze | agent
- 2026-10-21 | Persistence made fault-tolerant after a live run was lost to a DNS blip: bounded retry on transient DB errors (3 attempts, 2s + 5s), idempotent writes via deterministic row ids, HTTP 503 + a safe message for DB failures, and a website Retry button (counting down Retry-After on 429) | the 2026-10-21 live run died at its last write with a bare 500 and a zombie row, discarding the whole screening | human (chose A + D explicitly), agent implemented test-first
- 2026-10-22 | The analyst is now given the REAL evidence ids per concept (capped at 12) and may cite them; the deterministic critic judges MISSING_EVIDENCE from the concept's available count instead of the claim's id list | the 2026-10-21 live runs showed the system requiring the analyst to produce exactly what the critic was required to flag (8 false MISSING_EVIDENCE findings with 120/120 records available) | human (chose 'real ids + critic rule fix'), agent implemented test-first
- 2026-10-22 | The website collects structured concept attributes (material / price_band / product_type, the constraint catalog) and the report carries the reason a concept is not ranked | the form sent no attributes, so any hard constraint made all three concepts INFEASIBLE with no winner and no explanation | human (chose 'add attribute inputs'), agent
- 2026-10-22 | Results page: 'What the analyst found' and 'What the critic challenged' as two stacked boxes, each critic finding tagged with its source (LLM critic or rule checks) | the human asked to see what each stage actually produced | human (chose 'stacked, analyst first'), agent
- 2026-10-22 | Persistence is incremental (evidence after retrieval, scores after scoring, findings after the review, report last); a half-finished run can be RESUMED in place (reusing its stored evidence, no Qloo call repeated) or DELETED and started fresh; the client may choose the run id so it can follow the run's progress | the 2026-10-21 live run was lost at its last write and left a zombie row; the human asked for a resume-or-start-fresh choice and for the database not to fill with half-rows | human (approved options 2 and 3, chose 'user chooses'), agent
- 2026-10-22 | The report exposes what each stage did (research plan + findings, critique scope, per-stage durations, tie detection at a 0.5-point window) and the results page shows it in three boxes with a table of contents; the sensitivity gains a tie-aware phrasing ('Tied with B in X% of tested preference scenarios') and the evidence list is shown in full with entity names | the human reviewed a live run, could not tell whether the critic had run, and the run had declared a winner among three concepts that were exactly level | human (asked for the boxes, the tie handling, the verbose evidence and the plain-language explainer), agent implemented test-first
- 2026-10-22 | The website's short reads time out after 15s (the run-starting calls keep a 20-minute budget) and the README documents the two commands that start the backend and the frontend | a killed backend left the page on 'Loading run...' forever, and the dev servers do not survive between agent turns | human (asked for the two README commands), agent
- 2026-10-22 | Tie-break stage: when the leaders end level, the run makes one extra Qloo search per tied concept (inside the 10-call cap, budget counts every call), re-extracts and re-scores, and if the tie survives, a focused LLM comparison (new `compare_tied_llm`, same iron rules) is recorded in a `tiebreak` report block and reviewed by the critique; an already-known entity is never counted twice | the human saw three concepts exactly level and asked to 'use more Qloo and LLM runs to analyse the better among them' rather than present a coin-flip | human (asked), agent implemented test-first, 6 new tests
- 2026-10-22 | Verbose report stage: a new reported-in-words REPORTING state; a reporter model writes full prose ONLY after a completed critique, its numbers pass a deterministic guard (one retry naming the offending number, worst case 2 calls, then a template fallback), and the provenance (model vs template + reason) is shown on the page | the human asked for 'a full verbose report' after the critique box, without letting the model write a number or a sales claim | human (asked), agent implemented test-first, 7 new tests
- 2026-10-23 | Constraint gate split: "cannot be checked" (a concept does not declare the attribute) is no longer treated as a VIOLATION and no longer blocks; a constraint whose attribute no concept declares stops the brief at submit (HTTP 422 naming every affected concept, BEFORE the run row or any Qloo/LLM spend); an unverifiable constraint leaves the concept RANKED with a loud per-concept notice in the report and on the page; a genuine violation still blocks as INFEASIBLE | the human hit a blank attribute field wiping out all three concepts as INFEASIBLE after a full paid run | human (chose after reviewing a bug diagnosis), agent implemented test-first
- 2026-10-23 | Attribute suggester: a cheap assist LLM (new third pool, `LLM_SUGGESTER_MODEL`/`LLM_SUGGESTER_BASE_URL`, no dedicated key - it rides the main key) proposes attribute values grounded in each concept's description via POST /api/attributes/suggest; SHOW-ONLY - the user copies what they agree with, nothing is auto-applied, and the gate verdict stays deterministic code; an LLM gate-checker was rejected as a matter of design | the human chose 'optional + LLM attribute suggester' over a plain fix and over a full LLM constraint-checker | human (Q&A choice)
- 2026-10-23 | Agent-to-agent negotiation: assessed and parked on a separate experimental branch (agents/negotiation-loop) to start AFTER the Oct 30 submission, behind a flag, never merged to main unproven; ~6-8 LLM calls/run at a 3-round cap and roughly double latency | the human wants agents negotiating openly, but the submission deadline and the 50-call/day budget come first | human (decided), agent assessed feasibility
- 2026-10-23 | Model switch on the Google AI Studio compat layer: every pipeline role (analyst, critic, reviser, tiebreak, reporter AND researcher) moves to `gemini-3.8-flash`; the attribute suggester moves to `gemini-3.5-flash-lite` (third pool, fallback to main when unset); previously all roles ran `models/gemma-4-26b-a4b-it`; Google-side `max_tokens <= 16384` rule unchanged | the human supplied the exact model ID strings off their AI Studio picker and chose that the researcher pool moves too | human (Q&A choices), agent applied to `.env` (gitignored) only - no source change
- 2026-10-23 | Model-switch revision: `gemini-3.5-flash-lite` VERIFIED for the suggester (one live call, exactly on contract); `gemini-3.8-flash` FAILED validation - three tiny pings (30/60/90s, bare and `models/`-prefixed) all timed out while the same key/endpoint answered the lite model instantly; main + researcher pools ROLLED BACK to `models/gemma-4-26b-a4b-it` (rollback confirmed alive by one final ping). The suggester keeps `gemini-3.5-flash-lite`. `gemini-3.8-flash` may be retried only after the human re-verifies the ID/access on the model page | a demo three weeks out must never depend on an unverified model; recorded failure instead of substituting | human approved the test sequence, agent executed the pre-agreed fallback
- 2026-10-24 | Pool-drain fix: per-engine result-bundle cache (single cheap SELECT restamp; every persistence write evicts) + client single-flight on `getRunBundle`; `sqlalchemy TimeoutError` maps to 503 with busy wording ("database is busy, try again - nothing was lost"), distinct from unreachable ("result was lost") | a live run's 15s client aborts + stacked poll requests drained the 15-slot QueuePool and killed the result page | human (asked 'fix the timeout loop'), agent test-first, +2 tests
- 2026-10-24 | Per-concept critique notes (Feature B): one extra paced LLM call after the critique; drawbacks per concept + 5-6 line winner note; ids validated, notes capped at 900 chars, reporter's number guard applied (2 attempts then deterministic template fallback); stored at `report.critic.concept_notes`, shown in the critique box and the PDF | the human asked for per-concept cons plus a tight winner note | human (asked), agent test-first, +4 tests
- 2026-10-24 | FIXED DEMO CATEGORY REMOVED: `brief.category` is optional free text (was a locked Literal); the researcher names the category per run (`AgentOutput.category`), and CODE resolves it to a place-category tag via the VERIFIED `/v2/tags` endpoint then makes the shared market insights call itself; the planner vocabulary is search-only (an insights/tags proposal or a `urn:`-shaped category is rejected as an invented identifier); fixture/demo mode keeps the exact search-only behavior; no/unresolvable category or a too-small budget -> recorded limitation + skipped market call. Live runs now cost 3 searches + 1 tags + 1 insights = 5 calls (was 4) | the hardcoded `STATIONERY_TAG_URN` would pull stationery-store affinity for ANY concepts in live briefs (the human noticed in a real run) | human (asked 'researcher selects the category' and approved the extra call), agent test-first, +4 tests
- 2026-10-24 | MARKET WIRING (live-verified same day, see qloo-api-notes): the shared insights call adds `signal.location.query=<brief.market verbatim>` (signal, not filter - affinity re-ranked for the market, zero extra quota, call count stays 5); tag resolver accepts a `genre:place` fallback when no `category:place` exists and never accepts qloo-evidence-family tags; an unresolvable market text or a failed shared call lands as per-concept error records + a loud run limitation, never a crash. No model writes the market (user data, verbatim) | the verified A/B showed signal>filter for affinity evidence and the museum gap made fallback necessary | human (approved wiring 'least modifiable way'), agent test-first, +2 tests
- 2026-10-26 | Wave-1 hardening landed (three build commits): live `/search` calls are place-typed (`types=urn:entity:place`); the critic receives the per-concept evidence map `known_evidence_by_concept`; the suggester's "stated" basis requires a verbatim quote from the concept's own text | evidence value + LLM interaction quality, after feasibility probes the previous day | owner-approved, agent test-first, +9 offline tests (suite ≈260 green)
- 2026-10-26 | Local dev start simplified: `.env` auto-loaded via `python-dotenv` in `app/config.py`; README run command is `uvicorn app.main:serve --factory --port 8000` | removes the manual PowerShell env-load one-liner; Render keeps direct env injection | owner asked for one command
- 2026-10-27 | ALL GATES MARKED PASSED (G0–G6 + Submission; owner declaration: "all gates passed, repo is deployed") | the deployed stack works live (real Qloo runs verified 2026-10-26); documentation updated to reflect completion | owner
- 2026-10-27 | Docs standard update: gate statuses + in-scope table carry completion status; "human decision" phrasing replaced with neutral wording across AGENTS.md / SCOPE.md / architecture.md | consistency pass before submission | owner asked
