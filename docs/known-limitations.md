# Known limitations — Consentiens-Culturae Decision Engine

Honest record of what this system does NOT do, and where the live behaviour
still falls short. Written 2026-10-21 after the first live run through the
website API path.

## What the product is not

- **Not a demand forecast.** Cultural affinity is not purchase intent. The
  report says "Top-ranked in X% of tested preference scenarios" and nothing
  stronger. No output may state or imply probability of success, predicted
  sales, or validated demand.
- **Not a research replacement.** It screens three concepts against evidence
  retrieved from Qloo and records what the evidence does and does not support.
- **Not autonomous.** The scores, ranks, weights and constraint verdicts are
  computed by `app/services/decision_engine.py`. The LLM only explains and
  critiques; it never writes a number, a rank, or a weight.

## Live-path limitations (observed, not hypothetical)

1. **The LLM stages can fail, and the pipeline degrades honestly.** When an
   agent output fails validation, the deterministic path takes over and the
   report names it in `limitations` (e.g. "critic LLM output invalid twice …
   deterministic checks used"). A report with a template explanation is
   marked `explanation_template: true` and the UI shows a badge.
2. **A single bad item used to kill a whole stage.** Fixed on 2026-10-21:
   invalid claims, findings and planned calls are now dropped individually
   and reported, instead of discarding the entire output. See
   `app/agents/researcher.py` (`validate_call`, `salvage_calls`) and the
   coordinator's `_salvage_claims` / `_salvage_findings`.
3. **Retries are informed, not blind.** A retry now carries the validation
   error back to the model (and a non-zero temperature). A blind retry of an
   identical prompt at temperature 0 reproduces the same invalid output and
   wastes a call — this is what happened in the first live API run.
4. **The researcher plan is not reliable enough to be trusted blindly.** The
   LLM planner produces the right SHAPE only sometimes (it wrote a param named
   `filter` instead of `filter.type`). The code enforces the allowlist, the
   verified `filter.type` value and the call budget on every call, and the
   deterministic planner (one search per concept + one shared insights call)
   is the guaranteed path. The agent plan is an optimisation, not a
   dependency.
5. **Run time is long: 5–15 minutes for a live run with LLM explanations.**
   The free model pools generate slowly at the token budgets we need. The API
   therefore limits concurrency (one run at a time, `RUN_MIN_GAP_SECONDS`,
   `RUNS_PER_DAY`) and returns 429 with `Retry-After` rather than queueing
   work it cannot serve.
6. **Free-pool rate limits (429) are normal** and are retried once after a
   70-second pause. They are not provider outages and they do not consume the
   daily quota, but they do extend the run.
7. **The critique is thin by design.** The deterministic critic checks three
   things (unknown evidence IDs, missing evidence, causal phrasing). It is a
   floor, not a review.
8. **Search-to-concept attribution is a name match.** A search whose query
   contains exactly one concept name is attributed to that concept; anything
   else is treated as shared market evidence. Ambiguity is reported as
   `ENTITY_MATCH_AMBIGUOUS` where the normalizer detects it.

## Data and evidence limitations

- **Qloo insights evidence is place-level only.** The docs-verified
  `filter.type` is `urn:entity:place`; other values return rows that do not
  score, so the code refuses them (see `docs/qloo-api-notes.md`).
- **Coverage varies by market and concept.** Concepts with no usable match
  get no evidence; their status is reported, never imputed.
- **Demographics are never scored.** Where demographic affinity appears it is
  a labelled, non-scored context note, for stereotyping-risk reasons.
- **One shared insights call per run** covers the market-level criterion for
  all three concepts (identical parameters, one quota unit instead of three).
  It is attached to every concept, which is semantically honest for a
  market-level criterion, but it does mean C3 is identical across concepts.
- **Reproducibility is per scoring version.** `scoring_version` and
  `workflow_version` are recorded on every run; changing a formula requires a
  new version string.

## Demo and deployment limitations

- **Fixture data is labelled everywhere.** `fixture_mode` is on the run, in
  the report, and in the UI banner. The deployed demo must never present
  fixtures as live Qloo output.
- **The website is not deployed yet** (as of 2026-10-21). It runs locally
  against a locally hosted backend; `NEXT_PUBLIC_API_BASE_URL` points it at a
  hosted backend when that exists.
- **No progress streaming.** `POST /api/decision-runs` is synchronous, so a
  15-minute run holds one request open. There is no run list and no polling
  UI yet; the run id is only known after the response returns.
