# SESSION_LOG.md — rolling session context for CultureFit Decision Engine

Read at the start of every session, alongside AGENTS.md, SCOPE.md, architecture.md, qloo-api-notes.md.
Format: CURRENT STATE at top (always true for right now), then session entries below it, newest first.

Last updated: 2026-10-15 (session 01, second pass)

---

## CURRENT STATE

- **Date now:** 2026-10-15
- **Current gate:** G0 + G1, both dated Oct 16. Status: OPEN.
- **Qloo API key:** requested, NOT yet obtained. All work runs in fixture/offline mode until it arrives.
- **What exists:** offline skeleton, tests passing.
  - `pyproject.toml` (pinned deps; pydantic bumped to 2.12.* for Python 3.14 wheels — only Python on this machine)
  - `app/schemas/`: `brief.py` (DecisionBrief, Weights, HardConstraint), `concept.py`, `scoring.py`
  - `app/services/decision_engine.py`: deterministic scoring, ranks, gates, coverage
  - `app/workflow/`: `states.py`, `transitions.py` (typed state table)
  - `app/config.py`: env-based settings, fixture-mode default, live-mode startup check
  - `scripts/qloo_smoke_test.py`: G1 spike, ready for the key; verified the no-key path
  - `sessions/SESSION_LOG.md` (this file), `.env.example` (placeholders only)
- **Tests:** `pip install -e ".[dev]"` then `pytest` → **25 passed** (live tests: 25 deselected, marked, run manually with a key). Run with `.venv/Scripts/python.exe -m pytest` on this machine.
- **NOT yet verified against live Qloo:** everything. qloo-api-notes.md has zero VERIFIED entries.
- **NOT yet built:** Qloo client/adapter/normalizer (blocked on G1 response shapes), analyst/critic, sensitivity engine, persistence, API routes, frontend (Phase 4).
- **Human decisions so far:** single rolling context file (this one); agent commits only when the human asks; build offline skeleton + smoke test in parallel while key is pending.
- **Open question awaiting human answer:** whether C4 counts in the weighted total when the user lists no hard constraints (see session 01).
- **Next action:** human runs `QLOO_API_KEY=... .venv/Scripts/python.exe scripts/qloo_smoke_test.py --save-fixture tests/fixtures/fixture_search_success.json`, then we record results in qloo-api-notes.md (G1).

Workflow conventions for every session:
1. Append a numbered session entry below (newest first) at end of session.
2. Update CURRENT STATE so it is true after the session.
3. Never log QLOO_API_KEY or any secret here.

---

## Sessions (newest first)

### Session 01 — 2026-10-15 — offline skeleton + smoke test script

- Read all .md files; docs live at repo root (AGENTS.md, SCOPE.md, architecture.md, qloo-api-notes.md, README.md), not in docs/ yet as AGENTS.md layout suggests. Keep or move = human's call.
- Qloo key status: requested, waiting. Chose "both in parallel": offline skeleton + smoke test script.
- Context policy: single rolling file (this file). Commit policy: agent does NOT commit; only when human asks.
- Built: pyproject.toml, app/schemas/, app/services/decision_engine.py (tests first), app/workflow/ (states, transitions, tests), app/config.py, scripts/qloo_smoke_test.py.
- Design decision used to unblock scoring before G1: decision_engine consumes per-concept normalized 0–100 criterion values (None = missing); evidence-to-criterion extraction waits for G1-verified response shapes.
- Open question to human (answer in next session): SCOPE says weights for 5 criteria; architecture §3.2 says C4 is a gate-only when constraints are present. If the user lists NO hard constraints, should C4 be scored/weighted (and how, with no Qloo evidence to define "feasibility"), or dropped from the weighted total with renormalization? Buffy's current implementation answer: C4 always gate-only; when no constraints exist C4 weight is renormalized across C1/C2/C3/C5 and the report discloses it.
