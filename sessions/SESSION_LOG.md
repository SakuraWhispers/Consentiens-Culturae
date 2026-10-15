# SESSION_LOG.md — rolling session context for CultureFit Decision Engine

Read at the start of every session, alongside AGENTS.md, SCOPE.md, architecture.md, qloo-api-notes.md.
Format: CURRENT STATE at top (always true for right now), then session entries below it, newest first.

Last updated: 2026-10-15 (end of session 02)

---

## CURRENT STATE

- **Date now:** 2026-10-15
- **Current gate:** G0 + G1, both dated Oct 16 (tomorrow). Status: OPEN.
- **Qloo API key:** requested, NOT yet in our hands. All work runs in fixture/offline mode until it arrives.
- **Database:** Neon approved (decision log line added to SCOPE.md 2026-10-15). Human is doing the Neon signup themselves; connection string (pooled) goes into their local `.env` as DATABASE_URL - NOT quoted in chat or this file. Local default remains SQLite. `psycopg[binary]==3.2.*` added to pyproject (comment included) and installed (3.2.13).
- **What exists:** offline skeleton, tests passing.
  - `pyproject.toml`: pinned deps; pydantic 2.12.* (Python 3.14 is the only local Python); psycopg 3.2.* added
  - `app/schemas/`: `brief.py` (DecisionBrief, Weights WITHOUT c4 + extra="forbid", HardConstraint), `concept.py`, `scoring.py`
  - `app/services/decision_engine.py`: deterministic scoring, ranks, gates, coverage; rejects any C4 key in scoring input (no hidden input)
  - `app/workflow/`: `states.py`, `transitions.py` (typed state table) + `tests/workflow/`
  - `app/config.py`: env-based settings, fixture-mode default, live-mode startup check
  - `scripts/qloo_smoke_test.py`: G1 spike, ready for the key; no-key path verified (exit 2, clean message)
  - `sessions/SESSION_LOG.md` (this file), `.env.example` (placeholders only)
- **Tests:** `pip install -e ".[dev]"` then `pytest` → **28 passed, 0 failed** (live tests marked and deselected; run manually with a key). Runner: `.venv/Scripts/python.exe -m pytest`.
- **C4 decision (2026-10-15, human-approved, IMPLEMENTED):** C4 has NO weight. Weights = 4 soft criteria (C1, C2, C3, C5), sum 1; C4 is a pass/fail gate shown in the report; a payload carrying c4 is rejected at the schema gate. Docs pending from HUMAN: SCOPE.md section 3 wording change, architecture.md section 3.2 rewrite (replace "gate-or-score" sentence), section 3.3 kept-distinct note, C4 decision-log line.
- **NOT yet verified live:** Qloo (all of it; qloo-api-notes.md has zero VERIFIED entries) and the Neon connection (URL not yet delivered).
- **NOT yet built:** persistence (`app/services/persistence.py` - next up), Qloo client/adapter/normalizer (mappings blocked on G1 shapes; client scaffold possible but stays uncallable), sensitivity engine (robustness.py - can finish offline, G4 closable offline), analyst/critic + prompts (need LLM_API_KEY - separate from Qloo key; human has NOT answered whether one exists), API routes, coordinator, frontend (Phase 4 - do NOT start before backend path works).
- **Offline-vs-key map (agreed with human):** persistence → coordinator+fixture-mode run path (G2 fixture path) → sensitivity (G4) can all close without a Qloo key. Evidence normalizer mappings and recorded fixtures wait for G1. Frontend starts only after backend path works (Phase 4).
- **Deployment shape (agreed):** one FastAPI process serving API + static frontend (same origin, no CORS), Neon Postgres via DATABASE_URL, env vars APP_MODE/ QLOO_API_KEY/ LLM_API_KEY on the host; hosting choice researched at G5 prep, must stay up through Nov 16. Frontend choice: small Vite app only if the report view outgrows plain JS; static-served-by-FastAPI is the lean.
- **Human decisions recorded:** rolling context file (this file); agent commits only when asked; C4 weight removal; Neon for hosting Postgres; human does Neon signup themselves (5-step guide given: console.neon.tech signup → create project `culturefit` → copy POOLED connection string → put DATABASE_URL in local .env themselves, not in chat → tell agent it's set).
- **Next actions (in order):** 1) human: Neon `DATABASE_URL` into `.env`, then Buffy builds persistence.py (SQLite-tested first, Neon connection check) — serves persistence row, prep for G2. 2) human: Qloo key → runs `QLOO_API_KEY=... .venv/Scripts/python.exe scripts/qloo_smoke_test.py --save-fixture tests/fixtures/fixture_search_success.json` → Buffy records VERIFIED entries in qloo-api-notes.md (G1, due Oct 16). 3) human: answer LLM_API_KEY question (analyst/critic depend on it). 4) Buffy can start parallel: sensitivity engine + robustness.py with tests (G4, offline).

Workflow conventions for every session:
1. Append a numbered session entry below (newest first) at end of session.
2. Update CURRENT STATE so it is true after the session.
3. Never log QLOO_API_KEY or any secret here.

---

## Sessions (newest first)

### Session 02 — 2026-10-15 — C4 removal implemented + Neon approved + frontend/deploy plan

- Human re-asserted C4 decision and confirmed: no hidden input, simpler sensitivity space, consistent gate rule. Notes the edge case: renormalization made effective weights depend on whether constraints exist.
- Implemented (tests first): `Weights` lost the `c4` field AND forbids extra fields; `decision_engine._validate_inputs` now rejects any C4 key with an explicit error (previously it silently ignored numeric C4 - the exact hidden-input pattern the human vetoed). Suite: 25 → **28 passed**.
- Answered human's "how far without the key": full offline map (persistence, fixture-mode coordinator path, G4 sensitivity, G2 fixture path, LLM-dependent critic caveat).
- Neon researched via service catalog (score 92); approved by human; decision-log line added to SCOPE.md (Supabase slot → Neon). `psycopg[binary]==3.2.*` added to pyproject with comment, installed, suite still green.
- Human chose to run the Neon signup themselves (5-step guide provided; pooled connection string into local .env, no secrets in chat). Waiting sign: "it's in .env".
- Explained SQLAlchemy role and the frontend/deployment plan (Phase 4 only; one FastAPI process serves static frontend; hosting researched at G5 prep).
- Open items carried: Neon URL; Qloo key (G1 due Oct 16); LLM_API_KEY question unanswered; human's doc edits for SCOPE/architecture (C4 wording, §3.3 keep-distinct note).

### Session 01 — 2026-10-15 — offline skeleton + smoke test script

- Read all .md files; docs live at repo root (AGENTS.md, SCOPE.md, architecture.md, qloo-api-notes.md, README.md), not in docs/ yet as AGENTS.md layout suggests. Keep or move = human's call.
- Qloo key status: requested, waiting. Chose "both in parallel": offline skeleton + smoke test script.
- Context policy: single rolling file (this file). Commit policy: agent does NOT commit; only when human asks.
- Built: pyproject.toml, app/schemas/, app/services/decision_engine.py (tests first), app/workflow/ (states, transitions, tests), app/config.py, scripts/qloo_smoke_test.py.
- Design decision used to unblock scoring before G1: decision_engine consumes per-concept normalized 0–100 criterion values (None = missing); evidence-to-criterion extraction waits for G1-verified response shapes.
- Open question to human (answer in next session): SCOPE says weights for 5 criteria; architecture §3.2 says C4 is a gate-only when constraints are present. If the user lists NO hard constraints, should C4 be scored/weighted (and how, with no Qloo evidence to define "feasibility"), or dropped from the weighted total with renormalization? Buffy's current implementation answer: C4 always gate-only; when no constraints exist C4 weight is renormalized across C1/C2/C3/C5 and the report discloses it.
