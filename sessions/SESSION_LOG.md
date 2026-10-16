# SESSION_LOG.md — rolling session context for Consentiens-Culturae Decision Engine

Read at the start of every session, alongside AGENTS.md, SCOPE.md, architecture.md, qloo-api-notes.md.
Format: CURRENT STATE at top (always true for right now), then session entries below it, newest first.

Last updated: 2026-10-16 (session 06; sessions 04–05 logged below)

---

## CURRENT STATE

- **Date now:** 2026-10-16
- **Current gate:** G1 PASSED live 2026-10-16 (hackathon URL + X-Api-Key VERIFIED; /search, /v2/tags, /v2/insights all 200). G2 thin vertical slice due Oct 19 — STARTED this session (normalizer live-shape fix done; persistence + coordinator path remain).
- **Qloo API key:** RECEIVED and VERIFIED live (45-char key, placeholder replaced in local `.env` by human; values never logged). First spike run with placeholder 401'd as expected; second run with real key authenticated.
- **QLOO_BASE_URL:** new env var (default `https://hackathon.api.qloo.com`), wired in `app/config.py` + `.env.example` + smoke script. `.env` scaffolded from example (placeholders, gitignored, not staged).
- **LangGraph decision (human, session 04):** asked to add; agent researched (Devpost rules + 2026 framework consensus) and recommended KEEP custom coordinator — pipeline is linear, framework pays off only with branching/checkpointing/fan-out/HITL we don't need. Human asked for research response; no SCOPE change, no dependency added. Custom `states.py/transitions.py` stays.
- **Demographics decision (human, session 04):** non-scored context ONLY (hard rule 10 + SCOPE out-of-scope for scored use retained). No code yet; renders as labeled context, never enters weights.
- **G2 progress (session 05):** normalizer accepts LIVE shapes (`results` list for /search; `results.entities` for insights; top-level popularity + `properties` fallback; tag `id/tag_id/value`; `subtype` + `types[0]` fallback; `/v2/tags` lookup refused as non-evidence). New synthetic fixture `fixture_search_live_shape.json` + 3 tests. Suite 42 → **45 passed**.
- **NOT yet built (G2 remainder):** persistence.py, qloo_client.py (shapes now VERIFIED — unblocked), coordinator run path (brief → evidence → ranking → run record), reproducibility test (10 runs), API routes, frontend.
- **Next actions (in order):** 1) coordinator fixture-mode run path end-to-end (persistence DONE) 2) reproducibility test 3) qloo_client.py live adapter 4) sensitivity robustness.py 5) API routes after coordinator works.

## Sessions (newest first)

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

---

## Sessions (newest first)

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
