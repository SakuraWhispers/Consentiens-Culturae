# SESSION_LOG.md — rolling session context for Consentiens-Culturae Decision Engine

Read at the start of every session, alongside AGENTS.md, SCOPE.md, architecture.md, qloo-api-notes.md.
Format: CURRENT STATE at top (always true for right now), then session entries below it, newest first.

Last updated: 2026-10-17 (session 13; OpenRouter wired, UI deferred to post-phase Vercel page)

---

## CURRENT STATE (2026-10-17, session 13)

- **Gates:** G0 done · G1 PASSED (live) · G2 PASSED (human sign-off) · G3 open (paths built; live LLM test pending key) · G4 open (engine + wiring built; non-render acceptance checks ran locally; *render* and gate sign-off pending UI).
- **Suite:** 85 passed, 0 failed, offline.
- **New this session:**
  - `LLM_BASE_URL` env var wired: `config.py` (default OpenAI URL, trailing slash normalized), `llm_client.complete_json(base_url=...)`, all four agent wrappers take `base_url`. OpenRouter free-tier switch = set `LLM_BASE_URL=https://openrouter.ai/api/v1` + an OpenRouter model id in `.env` — no code change. 5 new client tests (default URL, custom URL, slash normalization, 401, unusable output). Provider switch itself DEFERRED until the human brings a key.
  - Minimal report UI DEFERRED by human decision: will be built later as a full Vercel-deployable page with user-supplied exact input requirements, after the last phase. Until then no static UI work.
  - G4 non-render acceptance checks RAN (fixture-mode pipeline via API): sampler runs end-to-end (1000 scenarios, seeded); two identical briefs → byte-identical sensitivity block; weight-change flip demonstrable at engine level (unit tests) but NOT on fixture pipeline evidence (FixtureSource serves one search file per concept → A/C evidence-identical, A always first — explainable no-change). G4 gate stays OPEN (render part pending).
- **Still left (unchanged):**
  1. Live LLM test (needs LLM key in `.env`; OpenRouter supported — human chooses provider) → then G3 sign-off.
  2. Minimal report UI — DEFERRED (see above); the handoff §20 Level-B "UI" item is now post-phase work.
  3. Differentiated fixture evidence (optional but wanted for a meaningful sensitivity demo: today A/C tie-break makes the fixture demo static).
  4. 3-way evaluation (Level C, design only).
  5. Post-C extras, ALL parked: weight sandbox, run history, recompute endpoint (each needs explicit move-in).
  6. G5 deployment (backend + host choice; Vercel page for frontend later), G6 freeze (README/LICENSE/demo script), submission.
- **How to run:** `.venv\Scripts\python.exe -m pytest -q` (85 tests, offline). Live: keys in gitignored `.env`, never in chat. Recorded fixtures in gitignored `tests/fixtures/recorded/`.
- **Known issues:** one orphan Neon run row at ROBUSTNESS_ANALYSIS (harmless); fixture A/C evidence-identical (above); test engines not always disposed in ad-hoc scripts (irrelevant to repo code).

- **Date now:** 2026-10-16
- **Current gate:** G2 PASSED (human sign-off; SCOPE.md gate line + decision log updated). G3 agent roles and critic due Oct 22 — agent paths built behind injectable hooks (session 10); live LLM test pending key.
- **LLM provider (agent pick, human delegated):** OpenAI `gpt-4o-mini` via `LLM_API_KEY` (`LLM_MODEL` override); httpx-only client, JSON-object mode, temp 0. Default OFF (`LLM_ENABLED=false`); missing key with flag on fails at startup check. Alternative: Gemini Flash (needs small client change) if human prefers Google.
- **Richer claim schema (human chose richer):** base fields + `confidence` (high/medium/low) + `audience_context` (≤280 chars, non-scored labeled note only). Critic + validator updated for both.
- **Level B vs C (human pasted handoff wording):** Level B = core + ONE API endpoint + minimal report UI, stable by Oct 19; exit = user submits 3 concepts → reproducible ranking with limitations, no agents required. Level C = B + agentic/analytical behavior (coordinator, 3 roles, ≤1 revision + fallback, sensitivity, 3-way evaluation), no new infrastructure. Cut C before shipping broken B.
- **Scope impact:** our G2 passed on coordinator-report JSON, but Level B still misses the API endpoint + minimal UI — both move INTO the Oct 19 window. API routes were previously "after coordinator"; now next.
- **Earlier agent-drafted extras renamed post-C (all parked):** weight sandbox (SCOPE-conditional), run history (out-of-scope), recompute endpoint (optional/out). Not scoped until B stable and C lands.
- **Level C features:** human notes possible post-G2 differentiation work "if time permits" — meaning not yet defined; must ask what Level C is before scoping anything.
- **Qloo API key:** RECEIVED and VERIFIED live (45-char key, placeholder replaced in local `.env` by human; values never logged). First spike run with placeholder 401'd as expected; second run with real key authenticated.
- **QLOO_BASE_URL:** new env var (default `https://hackathon.api.qloo.com`), wired in `app/config.py` + `.env.example` + smoke script. `.env` scaffolded from example (placeholders, gitignored, not staged).
- **LangGraph decision (human, session 04):** asked to add; agent researched (Devpost rules + 2026 framework consensus) and recommended KEEP custom coordinator — pipeline is linear, framework pays off only with branching/checkpointing/fan-out/HITL we don't need. Human asked for research response; no SCOPE change, no dependency added. Custom `states.py/transitions.py` stays.
- **Demographics decision (human, session 04):** non-scored context ONLY (hard rule 10 + SCOPE out-of-scope for scored use retained). No code yet; renders as labeled context, never enters weights.
- **G2 progress (session 07):** `qloo_client.py` (HTTP-only, retry policy, 8 MockTransport tests), `criterion_extraction.py` (single formulas C1–C5 + read-only diagnostics, 2 tests), `coordinator.py` (full state walk, template claims, deterministic critic, report + persistence), `LiveEvidenceSource` in adapter (allowlist + call counter). Defect caught by tests: evidence IDs not run-scoped → UNIQUE violation on run 2; fixed by run-scoping before claims cite them. Suite 48 → **60 passed**. Neon fixture slice: winner A, B INFEASIBLE (gate works), A/C tie broken deterministically, 1 limitation (G4 deferral), 0 critic findings. Live confirm PENDING brief approval (~7 calls).
- **NOT yet built (G2 remainder):** live-confirm run on Neon, then G2 acceptance sign-off.
- **Next actions (in order):** 1) brief approval → live confirm on Neon 2) G2 sign-off + SCOPE gate line 3) sensitivity robustness.py (G4) 4) API routes 5) G3 agent wrappers.

## Sessions (newest first)

### Session 13 — 2026-10-17 — OpenRouter wiring + UI deferral + G4 partial check

- Human answers: OpenRouter support wired NOW (switch deferred until a key exists); minimal report UI DEFERRED entirely — human wants a full Vercel-deployable page with their own exact input requirements, built after the last phase.
- `tests/unit/test_llm_client.py` (5 tests) first → `llm_client.complete_json(base_url=...)`, configs `llm_base_url` (`LLM_BASE_URL`, default OpenAI, slash-normalized), wrappers take `base_url`, `.env.example` documents the OpenRouter switch. Suite 80 → **85 passed**.
- G4 non-render acceptance checks ran through the real API path (temp script): sampler end-to-end ✓, cross-run determinism ✓, engine-level weight-flip ✓ (unit tests), fixture-pipeline flip ✗ (one search fixture per concept → A/C evidence-identical; explainable no-change). Gate stays OPEN; render component pending UI.
- Candidate follow-up flagged, needs human approval before any build: differentiated fixture evidence so the fixture demo can show a real weight-driven flip.

### Session 12 — 2026-10-16 — G4 sensitivity built, wired, day closed with handoff

- `app/services/robustness.py` (tests first, 6 tests): box sampling ±0.20 around user weights, hard cap 1000, fixed seed 20261016; top-rank frequency with the fixed permitted phrasing; rank ranges; pivotal criterion by max deviation on flips; gates enforced per replay (infeasible never wins); 3-vector named fallback. Zero LLM tokens, zero Qloo calls (replays frozen evidence).
- Coordinator: `ROBUSTNESS_ANALYSIS` now runs real analysis into `report["sensitivity"`; "deferred to G4" limitation removed. Displaces nothing; no new dependency.
- Suite: 74 → **80 passed**. CURRENT STATE rewritten as handoff (built vs left, run commands, known issues) for the next human.
- `git status` check + commit left to human (agent never commits).

### Session 11 — 2026-10-16 — Level B API built (tests first)

- New: `app/api/` (health + POST/GET decision-runs, thin over coordinator) and `app/main.py` (`create_app` factory; `serve()` for `uvicorn --factory`; import-safe, no network at import). Mode selects source: fixture → FixtureSource, live → LiveEvidenceSource + stationery tag.
- Test caught: `RunDeps` as pydantic model rejects Protocol fields — plain holder class instead. 4 API tests (health, ranking report, 422 on 2 concepts, GET bundle + 404). Suite: 70 → **74 passed**.
- It displaces nothing (API/UI rows). Net scope change: none. No new dependency (fastapi already pinned).
- Per human order: sensitivity (G4) next, minimal UI last.

### Session 10 — 2026-10-16 — G3 agent paths built (hooks, revision loop, fallbacks)

- New: `app/agents/` (`schemas.py` RetrievalPlan/RichClaim/AnalysisDraft/CriticOutput + closed issue codes; `researcher.py` allowlist/budget validator + deterministic fallback; `prompts.py` with data-not-instructions clauses; `llm_client.py` httpx-only JSON client; `analyst.py` four LLM wrappers; `__init__.py`). Config: `LLM_ENABLED/PROVIDER/MODEL/TIMEOUT` + startup check; `.env.example` updated.
- Coordinator: injectable `researcher_fn/analyst_fn/critic_fn/revise_fn` (retry-once → deterministic fallback + limitation each); revision capped at 1 with deterministic re-check; `revision_count` persisted; template claims upgraded to rich shape.
- Defects caught by tests: (1) fully-rejected agent plan → empty evidence → scoring crash; fixed with deterministic-plan fallback + `FAILED_TERMINAL` guard when zero usable values (legal from NORMALIZING). (2) pydantic schema rejects off-allowlist/over-budget before code validators — kept as defense in depth, tests assert both layers.
- Suite: 61 → **70 passed**. Live LLM test pending key (flag stays off; suite offline).
- It displaces nothing (agent-role rows). Net scope change: none. No new dependency (httpx only).

### Session 09 — 2026-10-16 — G2 signed off, G3 kickoff questions

- Human passed G2 ("G2 pass for now") with a note: Level C features later if time permits (undefined — asked back). SCOPE.md G2 row → passed + decision-log line appended (header preserved after a mis-edit that dropped it; repaired and verified).
- G3 questions sent (provider/model, researcher scope, schema reuse, revision caps, injected-defect pick, LLM flag, Level C meaning). Build starts on answers.
- Suite untouched this session (61 passed last run).

### Session 08 — 2026-10-16 — G2 LIVE CONFIRM passed on real Qloo evidence

- Live run defects, both fixed and test-locked: (1) per-concept insights calls used identical params → same 20 entities ×3, duplicate scoped IDs → Neon UNIQUE violation mid-run (40 real records retrieved, persist failed); fixed with ONE shared insights call + concept-scoped IDs. (2) Added `test_shared_market_evidence_gets_concept_scoped_ids` (stub shared payload → all persisted IDs unique). Suite: 60 → **61 passed**.
- Live confirm (approved brief, Neon, 4 calls: 3 search + 1 shared insights): `COMPLETED_WITH_LIMITATIONS`, `fixture_mode=False`, winner **C (73.8) > A (67.5)**, B `INFEASIBLE` (gate works on live path), 40 hits/concept, 2 limitations (1 partial-coverage entity + G4 deferral), 0 critic findings. Live evidence differentiates concepts (fixture path tied at 60.0).
- G2 ACCEPTANCE MET: brief + 3 concepts → real Qloo evidence → normalized records → deterministic ranking → persisted report; 10-run reproducibility green on fixtures. One orphan run row (interrupted persist) sits at ROBUSTNESS_ANALYSIS on Neon — harmless, superseded.
- G2 sign-off remaining: SCOPE.md gate line (needs human gate-pass confirmation per AGENTS.md §9).

### Session 07 — 2026-10-16 — G2 core built: client, extraction, coordinator, reproducibility

- Tests-first: `tests/integration/test_qloo_client.py` (8: auth/429/5xx/timeout/non-JSON, retry counts), `tests/unit/test_criterion_extraction.py` (2: formula values + empty/error edges), `tests/workflow/test_coordinator.py` (2: fixture run ranks/gate/report/persistence; 10-run identical ranks + totals).
- New modules: `app/integrations/qloo_client.py`, `app/services/criterion_extraction.py`, `app/workflow/coordinator.py`, `LiveEvidenceSource` in `qloo_adapter.py`. Each displaces nothing (retrieval/scoring/workflow rows); no new dependencies.
- Fixture-run caveat: FixtureSource serves the same search file per concept, so A/C tied at 60.0 (tie-break by concept_id); live evidence differentiates fully. Labeled fixture mode throughout.
- Decision choices section started in this file (running list, newest first).

### Session 06 — 2026-10-16 — Neon verified + persistence built (tests first)

- Human pasted Neon URL into local `.env` (value never printed; only scheme/length/pooled-flag checked). Advice given beforehand: pooled URL for runtime, unpooled aside for migrations; `postgresql://` verbatim, driver prefix handled in code.
- Safe probe via project `.venv` (pinned SQLAlchemy 2.0.54 + psycopg 3.2.13; system python lacks them — all future runs use `.venv`): CONNECT OK, `PostgreSQL 18.6`, pooled. `init_db` created all 5 tables on Neon (`decision_runs, evidence_records, workflow_events, score_snapshots, critic_findings`).
- Built `app/services/persistence.py` (tests first in `tests/integration/test_persistence.py`: prefix handling, full run lifecycle roundtrip, empty-input rejection). SQLAlchemy 2.0, JSON columns, `create_all` v1, secret-free by construction (params arrive redacted). Suite: 45 → **48 passed, 0 failed** (venv python).
- It displaces nothing (persistence row). Net scope change: none. No new dependency.
- `git status`: only intended files (`evidence_normalizer.py`, `SESSION_LOG.md`, new fixture, 2 test/module files); `.env` + `recorded/` ignored.
- **Official docs fetched 2026-10-16 (all three):** base URL `https://hackathon.api.qloo.com` ONLY; `X-Api-Key` header; `/v2/insights` is GET with `filter.type` REQUIRED; supported entity types listed (brand/place/artist/...); `/recs` FORBIDDEN; invalid params are SILENTLY IGNORED (200 + empty entities can mean bad params OR no-match); full response returned (no field filtering); caching server-side OK no time limit; **Qloo response data must NOT go in a public repo**; keys active through end of judging. All recorded as DOCS-VERIFIED in `docs/qloo-api-notes.md` (§0 defines the label; live confirmation at G1 still required).
- **GitHub starter kit:** NOT accessible from this host (github.com fetch blocked); web-search description only (CLI + MCP starter kit + separate OpenAPI-spec repo). Human to clone locally when possible; recorded as UNVERIFIED in the notes.
- **What changed 2026-10-16 (session 03):**
  - `docs/` folder created; `architecture.md` and `qloo-api-notes.md` moved there via `git mv`; ALL cross-references updated (app docstrings, SCOPE, notes). Human-approved.
  - **Product renamed Consentiens-Culturae** (human's explicit instruction) across AGENTS.md, SCOPE.md, docs/, pyproject.toml (`consentiens-culturae`), app code, session log; egg-info regenerated; suite stayed green.
  - **Fixture policy (human-approved):** hand-written synthetic fixtures committable; recorded live responses local-only under gitignored `tests/fixtures/recorded/`. G1 acceptance wording in SCOPE.md updated accordingly.
  - `docs/qloo-api-notes.md`: DOCS-VERIFIED section 0/§1/§2/§3/§4/§6/§7/§9/§10 updates: base URL, auth header, insights GET-only, filter.type, entity-type list, /search-vs-insights division, silent-ignore rule, no-match shape, response fields, caching rules, public-repo restriction, quota/keys lifetime; verification-log lines appended for all three doc pages.
  - `scripts/qloo_smoke_test.py`: insights probes now use `filter.type=urn:entity:brand|place` (term omitted); header docs state X-Api-Key, GET-only and the wrong-base-URL-401 check.
  - **Evidence layer built (G2 fixture path):** `app/schemas/evidence.py` (EvidenceRecord + stable_evidence_id + make_error_record; SourceKind/CoverageStatus/MatchQuality/ErrorCode); `app/integrations/` new (dir) with `qloo_adapter.py` (QlooPayload, EvidenceSource protocol, FixtureSource reading ONLY approved synthetic fixtures, synthetic loader REFUSES `recorded`-source files); `app/services/evidence_normalizer.py` (normalize_response: documented-field extraction, exact/partial/ambiguous match quality, partial/missing/error coverage, limitations for every missing documented field; error mapping per notes §5). Schemas re-exported from `app/schemas/__init__.py`.
  - Synthetic fixtures created (all labeled `_meta.source=hand-written`, "NO real Qloo data" in the note): `fixture_search_synthetic_success.json`, `fixture_adv_missing_fields.json`, `fixture_adv_no_match.json`, `fixture_adv_malformed.json`.
  - `tests/integration/test_evidence_normalizer.py`: 14 tests (fixture-envelope rules incl. recorded-refusal, success mapping, stable ids, missing-field partial+ambiguous, no-match, malformed, itemwise bad entities, popularity range, FixtureSource end-to-end).
  - `SCOPE.md` decision log: docs-move line, fixture-policy line, rename line, backfilled C4 line (approved 2026-10-15 by human, implemented same day). SCOPE §3 Input row reworded (weights for 4 soft criteria; C4 weightless gate). `docs/architecture.md` §3.2 rewritten from "gate-or-score" to gate-only.
  - LLM decision (human, this session): build deterministic-first; NO LLM key exists yet; agent wrappers wire-up later behind a flag.
- **Tests:** `pytest` → **42 passed, 0 failed** (28 previous + 14 integration).
- **Human decisions recorded:** docs→docs/ move; synthetic-committable fixture policy; rename to Consentiens-Culturae; deterministic-first LLM posture; recorded-fixture location `tests/fixtures/recorded/` (gitignored).
- **Open items carried from session 02:** Neon DATABASE_URL (human side); Qloo key (G1 today's date — follow up); LLM_API_KEY (now decided: wait; deterministic-first).
- **NOT yet built:** persistence.py, qloo_client.py (awaits G1 VERIFIED shapes), coordinator run path with fixture source, sensitivity robustness.py, analyst/critic/prompt wrappers, API routes, frontend.
- **Next actions (in order):** 1) persistence.py with SQLite-first tests (G2 prep, offline) 2) coordinator fixture-mode run path end-to-end (brief → fixture evidence → normalized records → deterministic ranking → run record) 3) on key arrival: G1 smoke test (Buffy runs it) + VERIFIED fixture saved into tests/fixtures/recorded/ + notes updated 4) sensitivity engine (robustness.py, offline, G4) 5) API routes after coordinator works.

- **Database (unchanged):** Neon approved. Human doing Neon signup themselves; pooled connection string goes into local `.env` as DATABASE_URL - NOT quoted in chat or this file. Local default remains SQLite. `psycopg[binary]==3.2.*` installed (3.2.13).
- **What exists:** offline skeleton + evidence layer, tests passing.
  - `pyproject.toml`: pinned deps; pydantic 2.12.* (Python 3.14 is the only local Python); psycopg 3.2.* added; project renamed `consentiens-culturae`
  - `app/schemas/`: `brief.py` (DecisionBrief, Weights WITHOUT c4 + extra="forbid", HardConstraint), `concept.py`, `scoring.py`, `evidence.py` (EvidenceRecord, stable_evidence_id, make_error_record) + package re-exports
  - `app/services/`: `decision_engine.py` (deterministic scoring, ranks, gates, coverage; rejects any C4 key), `evidence_normalizer.py` (normalize_response with error mapping)
  - `app/integrations/`: `qloo_adapter.py` (QlooPayload, EvidenceSource protocol, FixtureSource for synthetic fixtures only; refuses `recorded` fixtures)
  - `tests/fixtures/`: 4 labeled synthetic fixtures + `recorded/` dir (gitignored, reserved)
  - `app/workflow/`: `states.py`, `transitions.py` (typed state table) + `tests/workflow/`
  - `app/config.py`: env-based settings, fixture-mode default, live-mode startup check

- **Offline-vs-key map (agreed with human, updated 2026-10-16):** persistence → coordinator+fixture-mode run path (G2 fixture path) → sensitivity (G4) can all close without a Qloo key. Evidence NORMALIZER is now built; recorded evidence fixtures + qloo_client wait for G1. Frontend starts only after backend path works (Phase 4).
- **Deployment shape (agreed):** one FastAPI process serving API + static frontend (same origin, no CORS), Neon Postgres via DATABASE_URL, env vars APP_MODE/ QLOO_API_KEY/ LLM_API_KEY on the host; hosting choice researched at G5 prep, must stay up through Nov 16. Frontend choice: small Vite app only if the report view outgrows plain JS; static-served-by-FastAPI is the lean.
- **Policy retained from session 02:** agent commits only when asked; rolling context file (this file); C4 weight removal; Neon for hosting Postgres; human does Neon signup themselves (5-step guide given: console.neon.tech signup → create project `consentiens-culturae` (created 2026-10-15 under the old working name `culturefit`) → copy POOLED connection string → put DATABASE_URL in local .env themselves, not in chat → tell agent it's set).

Workflow conventions for every session:
1. Append a numbered session entry below (newest first) at end of session.
2. Update CURRENT STATE so it is true after the session.
3. Never log QLOO_API_KEY or any secret here.
4. Log every user-facing choice in Decision choices at the end of this file (date | decision | alternatives | why | approved by).

### Session 05 — 2026-10-16 — G2 started: normalizer live-shape fix (tests first)

- G1 follow-through: live spike showed our normalizer expected the DOCS shape (`results.entities`, `properties.popularity`, `tags[].id`) but live `/search` returns a `results` LIST with top-level `popularity`, `tag_id`/`value` tags, `types[]` plural. Wrote `tests/fixtures/fixture_search_live_shape.json` (hand-written, synthetic, labeled) + 3 tests first — 4 failures, all the expected gaps (fixture had `//` comments → invalid JSON; top-level popularity/tag_id unhandled; tags-lookup message).
- Fixed `app/services/evidence_normalizer.py`: accepts `results` list (search) + `results.entities` (insights); popularity top-level with `properties` fallback; tag `id/tag_id/value`; `subtype` with `types[0]` fallback; `results.tags` lookup refused as non-evidence with a named error. Suite: 42 → **45 passed, 0 failed**.
- It displaces nothing on the in-scope table (evidence normalization row). Net scope change: none. No new dependency.
- Still to build for G2: persistence.py, coordinator run path, reproducibility test, qloo_client.py (now unblocked — shapes VERIFIED), API routes.

### Session 04 — 2026-10-16 — G1 passed live: key verified, shapes recorded, LangGraph/demographics decided

- Human provided server URL + real key in local `.env` (placeholder replaced by human; agent never printed/stored values — only lengths/shapes). First spike with placeholder 401'd (`API keys mismatch`) on all 8 probes; second run authenticated: hackathon base URL VERIFIED.
- Live results: `/search?query=` 200 ×4 (20 hits each); `/v2/tags?filter.query=` 200 (`urn:tag:category:place:stationery_store`); insights `place + filter.tags` 200 (20 entities); insights `brand + same tag` 200 with 0 entities (genuine no-match); 1 timeout on `signal.interests.tags`. 3 redacted fixtures saved to gitignored `tests/fixtures/recorded/`.
- `docs/qloo-api-notes.md`: 3 endpoint rows DOCS-VERIFIED → VERIFIED; behavior facts rewritten (explicit 400/401 shapes, top-level popularity, `tag_id`, `types[]`, rank-order + popularity instead of affinity score, no-match vs error); 3 verification-log lines; 6 open questions answered. `app/config.py` + `.env.example` + smoke script gained `QLOO_BASE_URL`.
- Human decisions: LangGraph — agent researched and recommended keep-custom-coordinator (linear pipeline; framework pays off only with branching/checkpointing/fan-out); no SCOPE change, no dep added. Demographics — non-scored context only (hard rule 10 retained). Starter kit — not needed for G1.
- Suite stayed **42 passed**. Commit policy: agent does not commit; human commits when ready.

### Session 03 — 2026-10-16 — docs fetched & verified, dotfile/policy cleanup, evidence layer built

- Fetched all three official Qloo doc pages in full (the developer guide that robots-blocked us on Oct 15 fetched fine). Recorded everything as DOCS-VERIFIED in `docs/qloo-api-notes.md` with a new §0 label scheme (VERIFIED = real call; DOCS-VERIFIED = official-docs-sourced; UNVERIFIED = lead). Copy-paste trap discovered: the onboarding examples use `staging.api.qloo.com` — a hackathon key must use `hackathon.api.qloo.com` (401 otherwise).
- Flags to human: starter-kit repo not reachable from this host (network-restricted; human to clone later); Qloo's no-public-repo-data rule conflicts with committing recorded fixtures.
- Human decisions this session: docs → `docs/` (git mv + reference updates); rename CultureFit → **Consentiens-Culturae** everywhere (AGENTS.md, SCOPE.md, docs/, pyproject, code, session log; egg-info regenerated); fixture policy = synthetic committable + recorded local-only in gitignored `tests/fixtures/recorded/`; LLM posture = deterministic-first (no LLM key); next step = notes + smoke test then G2 fixture-path prep.
- `scripts/qloo_smoke_test.py` updated to the documented shape: insights probes with `filter.type=urn:entity:brand|place`, GET-only/X-Api-Key comments, accidental-`recs`-call guard by omission. Verified offline path (clean exit 2 with key message).
- Evidence layer built (G2 fixture path): `app/schemas/evidence.py`, `app/integrations/qloo_adapter.py` (FixtureSource; refuses `recorded` fixtures; requires `_meta` labels), `app/services/evidence_normalizer.py` (`normalize_response`: exact/partial/ambiguous match quality, partial/missing/error coverage, per-field limitations on every missing documented field, error mapping per notes §5). Four labeled synthetic fixtures; `tests/integration/test_evidence_normalizer.py` = 14 tests.
- Test-drive catching real defects: first normalizer version had a bogus `source="entity-sourced"` literal (violating SourceKind) and a helper that could return None — caught on read-back, rewritten cleanly; then the suite caught a missed limitation for missing `entity_id`/`name` fields — normalizer fixed, suite green.
- Tidbrook-decision sync: SCOPE §3 Input-row reworded (weights = 4 soft criteria; C4 weightless gate), `docs/architecture.md` §3.2 rewritten gate-only, backfilled decision-log line (C4 approved 2026-10-15 by human).
- Built this session: docs/ move, rename, `.gitignore` fixture rule, evidence schema + adapter + normalizer, 4 synthetic fixtures, 14 integration tests, doc syncs, SESSION_LOG updates.
- Suite: 28 → **42 passed, 0 failed**. Verified `pytest` offline default still holds (no live markers introduced).
- Wait-for-human: Qloo key (G1 runs same-day once it lands; smoke test ready), Neon DATABASE_URL, local clone of starter kit.

### Session 02 — 2026-10-15 — C4 removal implemented + Neon approved + frontend/deploy plan

- Human re-asserted C4 decision and confirmed: no hidden input, simpler sensitivity space, consistent gate rule. Notes the edge case: renormalization made effective weights depend on whether constraints exist.
- Implemented (tests first): `Weights` lost the `c4` field AND forbids extra fields; `decision_engine._validate_inputs` now rejects any C4 key with an explicit error (previously it silently ignored numeric C4 - the exact hidden-input pattern the human vetoed). Suite: 25 → **28 passed**.
- Answered human's "how far without the key": full offline map (persistence, fixture-mode coordinator path, G4 sensitivity, G2 fixture path, LLM-dependent critic caveat).
- Neon researched via service catalog (score 92); approved by human; decision-log line added to SCOPE.md (Supabase slot → Neon). `psycopg[binary]==3.2.*` added to pyproject with comment, installed, suite still green.
- Human chose to run the Neon signup themselves (5-step guide provided; pooled connection string into local .env, no secrets in chat). Waiting sign: "it's in .env".
- Explained SQLAlchemy role and the frontend/deployment plan (Phase 4 only; one FastAPI process serves static frontend; hosting researched at G5 prep).
- Open items carried: Neon URL; Qloo key (G1 due Oct 16); LLM_API_KEY question unanswered; human's doc edits for SCOPE/architecture (C4 wording, §3.3 keep-distinct note).

### Session 01 — 2026-10-15 — offline skeleton + smoke test script

- Read all .md files; docs lived at repo root at that time (AGENTS.md, SCOPE.md, architecture.md, qloo-api-notes.md, README.md), not in docs/ yet as AGENTS.md layout suggests. Moved into docs/ on 2026-10-16 (session 03, human-approved).
- Qloo key status: requested, waiting. Chose "both in parallel": offline skeleton + smoke test script.
- Context policy: single rolling file (this file). Commit policy: agent does NOT commit; only when human asks.
- Built: pyproject.toml, app/schemas/, app/services/decision_engine.py (tests first), app/workflow/ (states, transitions, tests), app/config.py, scripts/qloo_smoke_test.py.

- Design decision used to unblock scoring before G1: decision_engine consumes per-concept normalized 0–100 criterion values (None = missing); evidence-to-criterion extraction waits for G1-verified response shapes.
- Open question to human (answer in next session): SCOPE says weights for 5 criteria; architecture §3.2 says C4 is a gate-only when constraints are present. If the user lists NO hard constraints, should C4 be scored/weighted (and how, with no Qloo evidence to define "feasibility"), or dropped from the weighted total with renormalization? Buffy's current implementation answer: C4 always gate-only; when no constraints exist C4 weight is renormalized across C1/C2/C3/C5 and the report discloses it.

---

## Decision choices (running list; newest first)

- 2026-10-16 | ONE shared insights call per run (market evidence attached to all concepts) | per-concept insights calls | identical params ×3 wasted quota and produced duplicate evidence IDs; C3 is market-level so sharing is semantically honest | agent (live-run defect), human approved brief
- 2026-10-16 | Evidence IDs scoped by run + concept | run-only scope | shared payloads collided on the PK within one run | agent (live-run defect)
- 2026-10-16 | G2 runs persist to Neon (not SQLite) | SQLite local was recommended | durable hosted runs prove the deployed path early; network cost accepted | human
- 2026-10-16 | G2 scope = coordinator + report JSON (no API routes, no UI today) | include-API / include-UI options | keep today's finish inside G2 acceptance (ranking + report + reproducibility) | human
- 2026-10-16 | G2 evidence = fixture first, then one live confirm | live-only / fixture-only | deterministic build + 10-run test free, then real-path proof for ~7 quota calls | human
- 2026-10-16 | G2 demo brief = agent-drafted stationery set, human approves before live run | human-supplied brief | unblocks code build while brief approval gates only the live run | human
- 2026-10-16 | C2/C3 formula switcher + custom formulas DEFERRED (out of scope) | dropdown + freeform entry | breaks single-version cap + reproducibility; server-side custom formulas = code-execution hole | agent proposed, human to confirm
- 2026-10-16 | Three C1 variants as cards REJECTED; one C1 (mean popularity) + rank/hit-count diagnostics | three live variants | SCOPE one-version cap + 10-run reproducibility fail with competing C1s | agent proposed, human to confirm
- 2026-10-16 | Demographics = non-scored context only | scored demographic input | hard rule 10 + stereotyping risk + SCOPE out-of-scope | human
- 2026-10-16 | Keep custom coordinator, no LangGraph | LangGraph wrapper / full graph | linear pipeline; framework pays off only with branching/checkpointing/fan-out we lack | agent proposed, human asked for research
- 2026-10-16 | `QLOO_BASE_URL` env var (hackathon default) | keep hardcoded | base URL is config, not code; wrong-URL 401 trap documented | human
- 2026-10-16 | Fixture policy: synthetic committable, recorded local-only | commit redacted recordings | Qloo terms forbid response data in public repo | human
- 2026-10-15 | Neon for hosted Postgres | Supabase slot in stack | free-tier standard Postgres, SQLAlchemy-compatible | human
- 2026-10-15 | C4 = weightless gate, `c4` weight rejected | C4 as fifth weight | gate double-counted as score; hidden-input risk | human
- 2026-10-16 | G2 gate PASSED | hold open | acceptance evidence (live confirm + 10-run test) ran and recorded; human signed off | human
- 2026-10-16 | G3 started via questions-first (no assumptions) | start building directly | researcher/analyst/critic need provider, scope, schema, budget answers first | human
- 2026-10-16 | Empty-evidence runs → FAILED_TERMINAL (legal from NORMALIZING) + rejected-plan → deterministic fallback | crash / silent empty | scoring code cannot rank zero values; terminal-with-reason is the honest state | agent (test-caught defect)
- 2026-10-16 | Deterministic critic also checks causal phrasing (CAUSAL_OVERCLAIM) | LLM-only causal check | injected-overclaim acceptance must hold even on the fallback path | agent
- 2026-10-16 | Level B/C boundary from handoff recorded; API endpoint + minimal UI moved into Oct-19 window | keep prior G2 scope | handoff §20 exit gate requires them; cut C before broken B | human
- 2026-10-16 | Level B closure order: API first, sensitivity (G4) next, UI last | API→UI / UI→API | sampler output feeds the UI chart; UI risk accepted near Oct 19 | human
- 2026-10-16 | G3 answers: provider = agent picks (OPENAI_API_KEY); researcher LLM-plans/code-enforces; analyst RICHER schema; critic 1 pass + 1 revision with injected CAUSAL_OVERCLAIM; LLM flag-gated default-off; Level C = agent drafts candidate set | alternatives per question | unblock G3 build without assumptions | human
- 2026-10-17 | LLM base URL made configurable (`LLM_BASE_URL`, default OpenAI; OpenRouter free tier = URL + model id only) — support NOW, provider switch DEFERRED until human brings a key | switch now / defer entirely / full live test now | one env var now removes rebuild risk later; no key needed to wire | human
- 2026-10-17 | Minimal report UI DEFERRED: to be built later as a full Vercel-deployable page with human-supplied exact input requirements, after the last phase | single page / two pages / build now | human's explicit direction (overrides the static-page plan and the UI-last order) | human
