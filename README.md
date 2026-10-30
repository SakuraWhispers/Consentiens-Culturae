# Consentiens Culturae

*Cultura ducit, ratio iudicat.* Culture guides, reason judges.

Consentiens Culturae is an early concept-screening tool for small consumer brands. You describe a market and an audience, enter three competing product concepts, and set how much each criterion matters to you. The app retrieves cultural-affinity evidence from the Qloo API, scores the concepts with deterministic code, has an LLM explain and critique the result within strict limits, and re-runs the ranking across sampled weightings to show whether it holds when your priorities shift.

It is an early screening aid. It is not a sales forecast, does not estimate market size, and does not replace consumer research. Cultural affinity is not purchase intent.

**Live demo:** https://consentiens-culturae-beta.vercel.app
**Backend:** https://consentiens-culturae.onrender.com

---

## What is built

- Evidence retrieval from the Qloo API through three allowlisted endpoints (search, tags, insights), with a cap of 10 calls per run.
- Deterministic scoring: four weighted criteria (C1 cultural affinity, C2 differentiation, C3 market context, C5 evidence coverage) and a hard-constraint gate (C4). No LLM sets a score, rank, or weight.
- An LLM analyst that explains the result from structured data, and a critic that checks the explanation. Both have deterministic fallbacks, and the report says which sections were written by a model and which by template.
- Sensitivity analysis: up to 1,000 seeded alternative weightings, reported as "Top-ranked in X% of tested preference scenarios."
- A Next.js interface for entering the brief and reading the report, including an evidence drawer and a list of limitations.
- An offline test suite (262 tests, no network or keys needed).

Not built, and out of scope (see [SCOPE.md](SCOPE.md) : accounts, run history, chat, vector search or RAG over documents, demographic scoring, sales or market-size estimates.

## Demo mode and live mode

- `APP_MODE=fixture` (default): runs offline on labelled synthetic fixtures. Every report and banner says "Demo mode: fixture data, not live Qloo output."
- `APP_MODE=live`: makes real Qloo calls with `QLOO_API_KEY` (a hackathon key, used against `https://hackathon.api.qloo.com`).

A report is labelled by the data it actually used, not by the mode you intended.

---

## Run it locally

You need Python 3.11 or newer and Node.js 20.9 or newer (required by Next.js 16).

**Setup (once)**

```bash
python -m venv .venv
# Windows:            .\.venv\Scripts\activate
# macOS / Linux:      source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # Windows: copy .env.example .env
```

Edit `.env` to add any keys you have. The file is gitignored; never commit it.

**Terminal 1: backend (port 8000)**

```powershell
# Windows
.\.venv\Scripts\python.exe -m uvicorn app.main:serve --factory --port 8000
```

```bash
# macOS / Linux
.venv/bin/python -m uvicorn app.main:serve --factory --port 8000
```

The backend loads `.env` automatically. Hosted environments inject variables directly and take precedence.

**Terminal 2: website (port 3000)**

```bash
cd website
npm ci
npm run dev
```

Open http://localhost:3000. The website calls the backend at `http://localhost:8000` unless `NEXT_PUBLIC_API_BASE_URL` is set.

**Check both are running**

```bash
curl http://127.0.0.1:8000/api/health      # returns a status of ok
curl -I http://localhost:3000              # 200
```

If the page says the backend did not answer, start terminal 1 again.

---

## Configuration

The full list is in [.env.example](.env.example). The main settings:

| Variable | Purpose | Default |
|---|---|---|
| `APP_MODE` | `fixture` (offline demo) or `live` (real Qloo calls) | `fixture` |
| `QLOO_API_KEY` | Qloo hackathon key. Required in live mode. | none |
| `QLOO_BASE_URL` | Qloo base URL. The hackathon key works only with the hackathon host. | `https://hackathon.api.qloo.com` |
| `QLOO_TIMEOUT_SECONDS` | Timeout per Qloo call | `10` |
| `QLOO_MAX_CALLS_PER_RUN` | Qloo call cap per run | `10` |
| `DATABASE_URL` | Database. SQLite locally, Postgres when hosted. | `sqlite:///./consentiens_culturae.db` |
| `LLM_ENABLED` | Turns the LLM roles on. Off uses deterministic fallbacks only. | `false` |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY` | LLM pool for the analyst and critic | see `.env.example` |
| `CORS_ORIGINS` | Comma-separated origins allowed to call the API | `http://localhost:3000` |
| `RUN_MIN_GAP_SECONDS`, `RUNS_PER_DAY` | Run limiter that protects free model quotas | `30`, `50` |
| `NEXT_PUBLIC_API_BASE_URL` | Website: backend URL | `http://localhost:8000` |

---

## Tests

```bash
pytest                       # offline suite: 262 tests, no network or keys
cd website && npm run lint   # website lint
cd website && npm run build  # production build (needs network for Google Fonts)
```

`pytest -m live` currently selects no tests. Live Qloo checks are run by hand with `scripts/qloo_smoke_test.py` and recorded in [docs/qloo-api-notes.md](docs/qloo-api-notes.md).

---

## How a run works

1. **Research.** An LLM proposes a retrieval plan. Code checks every call against the allowlist and the call budget. If the plan is rejected, a deterministic plan runs instead.
2. **Scoring.** Deterministic code turns evidence into criterion scores, applies weights and the hard-constraint gate, and ranks the concepts. Ties are shown as ties.
3. **Analysis.** The analyst explains the ranking and cites real evidence IDs. The critic checks each claim against the evidence. Flagged claims are qualified or removed, with at most one revision.
4. **Sensitivity.** Up to 1,000 seeded weightings are tested. The same brief always gives the same result.

Every limitation of a run appears in the report. See [docs/known-limitations.md](docs/known-limitations.md).

## Honesty rules (see [AGENTS.md](AGENTS.md))

- The LLM never writes a score, a rank, or a weight.
- Missing data is reported as missing, never filled in with zero or a guess.
- Fixture data is always labelled.
- Cultural affinity is not purchase intent. The sensitivity result is worded "Top-ranked in X% of tested preference scenarios" and nothing stronger.

## Qloo data and licence

- Qloo response data is not stored in this public repository. Hand-written synthetic fixtures are committed. Recorded live responses stay local in `tests/fixtures/recorded/`, which is gitignored.
- Use your own hackathon key. Never commit `.env` or any key.
- Licensed under the Apache License 2.0. See [LICENSE](LICENSE).

## Documentation

- [SCOPE.md](SCOPE.md): scope, gates, and decision log
- [AGENTS.md](AGENTS.md): rules for AI coding agents
- [docs/architecture.md](docs/architecture.md): how the system is built
- [docs/qloo-api-notes.md](docs/qloo-api-notes.md): what is verified about the Qloo API, and how
- [docs/known-limitations.md](docs/known-limitations.md): what the system does not do
