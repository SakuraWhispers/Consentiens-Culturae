# Consentiens-Culturae

A decision-support engine for cultural-affinity screening: three product
concepts, a brief, and evidence from the Qloo API — scored by deterministic
code, explained and critiqued by an LLM within strict limits.

---

## Run it locally (two commands, two windows)

The dev servers do **not** survive between sessions — start them yourself
whenever you want to test. Open two terminals.

**1 · Backend (port 8000)** — from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:serve --factory --port 8000
```

With `.env` loaded automatically via `python-dotenv` (set `LLM_ENABLED=true`
and keys in `.env`). Render still injects env vars directly.

**2 · Frontend (port 3000)** — in a second terminal:

```powershell
cd website; npm run dev
```

Then open <http://localhost:3000>. The frontend talks to the backend at
`http://localhost:8000` (override with `NEXT_PUBLIC_API_BASE_URL`).

Check both are up before testing:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/api/health -UseBasicParsing   # {"status":"ok"}
Invoke-WebRequest http://localhost:3000 -UseBasicParsing              # 200
```

If a page says *"the backend did not answer"*, the backend is not running —
start it again with command 1.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest            # offline suite
.\.venv\Scripts\python.exe -m pytest -m live    # live Qloo calls (needs a key)
cd website; npm run build                       # production build of the site
```

## What it does

1. **Research** — a retrieval plan (three allowlisted Qloo endpoints: search, tags, insights) becomes
   evidence records.
2. **Scoring** — deterministic code turns the evidence into four criterion
   scores, four weights and a hard-constraint gate. No LLM touches a number.
3. **Analysis** — an LLM analyst explains the ranking and cites real
   evidence IDs; a critic challenges the claims; flagged wording is revised.
4. **Sensitivity** — up to 1,000 seeded alternative weightings show how
   stable the ranking is. The same brief always produces the same answer.
5. **Attribute suggester** (`POST /api/attributes/suggest`, LLM mode only) —
   before a run, a cheap assist model proposes attribute values grounded in
   each concept's description. Proposals are SHOW-ONLY: you copy what you
   agree with; nothing is auto-applied and the gate stays deterministic code
   (set `LLM_SUGGESTER_MODEL` / `LLM_SUGGESTER_BASE_URL` to point it at a
   smaller model; defaults fall back to the main one).

## Hard-constraint notes

- A constraint only means something against the attributes you typed for each
  concept. A constraint naming an attribute no concept declares stops the
  brief at submit (HTTP 422 naming the concepts) — no spend, no surprise.
- "Cannot be checked" is never treated as a violation: an unverifiable
  constraint still ranks the concept and the results page says so loudly; a
  genuinely violated constraint still blocks it as INFEASIBLE.

## Honesty rules (see `AGENTS.md`)

- The LLM never writes a score, a rank or a weight.
- Missing data is reported, never invented; fixture data is always labelled.
- Cultural affinity is **not** purchase intent. The report says "Top-ranked
  in X% of tested preference scenarios" — nothing stronger.
- Every limitation of a run is listed in the report and on the results page.
