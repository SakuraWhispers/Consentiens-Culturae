# AGENTS.md — Operating manual for AI coding agents

This file is read at the start of every session. It is the short, binding summary. The longer documents it points to are in `SCOPE.md`, `docs/architecture.md`, and `docs/qloo-api-notes.md`. If this file and another document disagree, stop and ask which one is current. Do not pick one silently.

Last updated: 2026-10-15. Owner: solo developer. Change this header when you edit the file.

---

## 1. What we are building

**Consentiens-Culturae Decision Engine** (working name, may change). A decision-support web app for a small consumer brand. The user enters a decision brief, a target audience and market, and exactly three competing product concepts. The app retrieves cultural-affinity evidence from the Qloo API, scores the concepts with deterministic code, has an LLM explain and critique the result within strict limits, and runs a sensitivity analysis on the user's weights.

**Pipeline (the only pipeline):**

evidence retrieval → deterministic scoring → bounded critique → sensitivity analysis

**It is not:** a sales forecaster, a general chatbot, a market-demand predictor, a multi-agent network, or a replacement for consumer research. Cultural affinity is not purchase intent. Never write copy that implies otherwise.

Scope, gates, and the out-of-scope list live in `SCOPE.md`. Check it before proposing any feature.

---

## 2. Hard rules (never break these)

1. **Never fabricate Qloo data.** No invented entity IDs, affinity values, demographics, citations, or response fields. If a call fails, record the failure. Do not substitute plausible-looking numbers.
2. **Never let the LLM write a score.** Numeric scores, ranks, and weights come only from `decision_engine` code. LLM output is a proposal, validated by code.
3. **Never let the LLM change weights, hard constraints, or evidence records.** Weights change only through an explicit user action.
4. **Never log, print, commit, or embed secrets.** The Qloo key lives in an environment variable (`QLOO_API_KEY`). It must never appear in source, tests, fixtures, logs, frontend code, screenshots, or the demo video. Never write a real `.env` file into the repository.
5. **Fixture data must be labeled.** Any response that did not come from a live Qloo call carries `fixture_mode=true` and is shown as fixture/demo data in the UI and report. The deployed demo never presents fixtures as live Qloo output.
6. **Never make network calls outside the allowlist.** The only external calls are to the Qloo adapter and to the configured LLM provider. No arbitrary URLs chosen by a model. No model-generated SQL. No model-generated code executed.
7. **Never add an out-of-scope item** from `SCOPE.md` without explicit approval. If a task seems to require one, stop and ask.
8. **Never claim a feature works until you have run it.** Report what you ran and what the result was.
9. **Never claim commercial validity.** Do not write "predicts sales," "probability of success," "validated demand," or any equivalent. "Top-ranked in X% of tested preference scenarios" is the permitted phrasing for sensitivity output.
10. **Do not use demographic affinity (age or gender) as a primary score input.** It is a stereotyping risk. If it appears at all, it is a labeled, non-scored context field.

---

## 3. Session start protocol

At the start of every session, before writing any code:

1. Read this file, then `SCOPE.md`, then `docs/architecture.md`.
2. Read `docs/qloo-api-notes.md` if you are touching anything in `app/integrations/` or `app/services/evidence_normalizer.py`.
3. State back, in 3 to 5 lines:
   - the current gate and its date (from `SCOPE.md`),
   - what the task is,
   - which in-scope item it belongs to,
   - which out-of-scope items are relevant, if any.
4. If you cannot state the current gate, the context has not loaded. Stop and ask to paste `SCOPE.md`.

---

## 4. Working rules

### Small steps
- One logical change per commit. Run the test suite after each change.
- Prefer editing an existing module over creating a new one.
- Do not create empty folders or placeholder files "for later." They invite scope creep.

### Before adding anything
- Name what it displaces. If it displaces nothing on the in-scope list, it does not go in. Say this explicitly in your reply.
- If it adds a dependency, add it to `pyproject.toml` with a one-line comment explaining why, and say so in your reply. The dependency list is kept deliberately small.

### Testing
- Write or update the test first where practical. The scoring tests exist before the scoring code.
- Tests must run offline. Live Qloo calls are marked and skipped by default (`pytest -m live`, run manually).
- Fixtures live in `tests/fixtures/` and are named with the prefix `fixture_`. Each fixture file has a header comment saying it is a redacted, hand-labeled sample.

### Changing these documents
- These docs are living documents. Update them when a decision changes, not after the fact.
- When you change a decision, add a dated line to the **Decision log** at the bottom of `SCOPE.md` (date, what changed, why, who approved). Do not edit history.
- Never edit a verified fact in `docs/qloo-api-notes.md` without a new dated entry showing the new verification.

### When uncertain
- Ask one specific question with two concrete options and a recommendation. Do not ask open-ended questions when a sensible default exists.
- If the Qloo API behaves differently from the notes, stop building on the assumption and record the discrepancy in `docs/qloo-api-notes.md`.

---

## 5. Tech stack (fixed unless a change is approved)

- Python 3.11+
- FastAPI (HTTP), Pydantic v2 (contracts), httpx (async HTTP client)
- PostgreSQL, optionally hosted on Supabase; SQLAlchemy for persistence
- pytest for tests
- One simple frontend (framework choice made in Phase 4; do not start it before the backend path works)
- A typed state machine for workflow. **Do not add LangGraph** unless approved in `SCOPE.md`.

Do not add: microservices, message queues, Kubernetes, vector databases, custom model training, a RAG pipeline, or per-agent services.

---

## 6. Repository layout (guide, not mandate)

```
README.md              setup, run, test, demo-vs-live explanation
AGENTS.md              this file
SCOPE.md               scope, out-of-scope list, gates, decision log
LICENSE                MIT or Apache-2.0
.env.example           placeholder values only
.gitignore             must include .env
pyproject.toml         pinned dependencies, pytest config
app/
  main.py              FastAPI app
  config.py            env-based settings (no secrets in code)
  api/                 routes_runs.py, routes_health.py
  schemas/             Pydantic models (brief, concept, evidence, scoring, critic, run)
  integrations/        qloo_client.py (HTTP only), qloo_adapter.py (maps to internal schema)
  services/            evidence_normalizer.py, decision_engine.py, robustness.py,
                       report_builder.py, persistence.py
  workflow/            coordinator.py (deterministic), states.py, transitions.py
  agents/              researcher.py, analyst.py, critic.py, prompts.py
frontend/              built in Phase 4
tests/
  unit/                scoring, normalization, constraints, missing data
  integration/         Qloo adapter against fixtures
  workflow/            state transitions, critic output schema
  fixtures/            fixture_*.json, labeled as fixtures
docs/
  architecture.md
  qloo-api-notes.md
  known-limitations.md   (start by Oct 25)
  demo-script.md         (start by Oct 25)
scripts/
  qloo_smoke_test.py   the API spike; run manually with a real key
```

The `app/agents/` folder contains thin prompt-and-schema wrappers, not separate services. Keep them that way.

---

## 7. Commands

These are placeholders until the project skeleton exists. Replace them when `pyproject.toml` is created, and keep this section accurate.

```
# install (fill in once pyproject.toml exists)
pip install -e ".[dev]"

# tests, offline (default)
pytest

# live Qloo tests (manual, needs QLOO_API_KEY in the environment)
pytest -m live

# run the API locally
uvicorn app.main:app --reload

# API spike (manual)
python scripts/qloo_smoke_test.py
```

---

## 8. Reporting back

End each work session with:

- what changed (files, one line each),
- what you ran and the result (test counts, any failures),
- what is still unverified,
- the next step, and which gate it serves.

Do not describe effort. Describe outcomes. If something is broken, say so in the first line.

---

## 9. Things the agent must never do without asking

- Add an out-of-scope feature.
- Change the product name, target market, or demo category.
- Add a dependency not on the approved list in `pyproject.toml`.
- Call a live Qloo endpoint that is not recorded in `docs/qloo-api-notes.md` as verified.
- Remove or weaken a hard rule in this file.
- Commit anything under `.env`, or anything containing a key-shaped string.
- Mark a gate as passed without running its acceptance check.
