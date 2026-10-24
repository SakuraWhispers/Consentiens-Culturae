# Live G3 probe: ONE OpenRouter call per agent step against live Qloo evidence.
# Run manually with keys in .env or the environment:
#   .venv\Scripts\python.exe scripts\llm_live_probe.py
#
# Budget contract (human-approved): retries allowed on failure (coordinator's
# built-in retry-once), so worst case is 8 OpenRouter calls of the 50/day
# (2 per hook: researcher, analyst, critic, optional revision). Typical case 3-4.
# No OpenRouter attribution headers are sent anywhere (stay off leaderboards).
#
# Secrets: .env is read but only key PRESENCE flags are printed — never values.

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def load_env(path: Path) -> None:
    if not path.exists():
        print(f"[env] no {path.name} found; using environment only")
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name and value and name not in os.environ:
            os.environ[name] = value


def main() -> int:
    load_env(REPO / ".env")

    qloo_key = os.environ.get("QLOO_API_KEY")
    database_url = os.environ.get("DATABASE_URL")
    print("[env] QLOO_API_KEY set:", bool(qloo_key))
    print("[env] GEMINI_API_KEY set:", bool(os.environ.get("GEMINI_API_KEY")))
    print("[env] OpenRouter key set:",
          bool(os.environ.get("LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY")))
    print("[env] DATABASE_URL set:", bool(database_url))
    if not (qloo_key and database_url):
        print("Missing QLOO_API_KEY/DATABASE_URL. Fill .env and rerun. Exiting.")
        return 2

    from app.config import Settings, llm_api_key
    from app.integrations.qloo_adapter import LiveEvidenceSource
    from app.integrations.qloo_client import QlooClient
    from app.schemas.brief import DecisionBrief
    from app.services.persistence import get_engine, init_db
    from app.workflow.coordinator import run_decision
    from app.agents.llm_client import AgentLLMError

    settings = Settings.from_env()

    # Two pools: MAIN (analyst+critic; llm_model/llm_base_url/llm_api_key per
    # provider) and RESEARCHER (llm_researcher_model on its own base URL/key,
    # defaulting to the OpenRouter chain). researcher base defaults to main;
    # when main is not OpenRouter the .env must set LLM_RESEARCHER_BASE_URL.
    main_key = llm_api_key(settings.llm_provider)
    researcher_key = settings.researcher_api_key()
    base_url = settings.llm_base_url
    researcher_base = settings.researcher_base_url()
    on_google = "generativelanguage" in base_url
    on_openrouter = "openrouter" in researcher_base
    gemma = settings.llm_model
    nemotron = settings.llm_researcher_model or gemma
    # Reasoning-heavy calls routinely exceed the 30s default; Google's gemma-4
    # emits its <thought> block INTO the stream before the answer, and a live
    # analyst attempt was still generating at the old 180s ceiling → 300s.
    timeout = max(settings.llm_timeout_seconds, 300.0)
    print(f"[llm] researcher: {nemotron} @ {researcher_base.split('//', 1)[-1]}")
    print(f"[llm] analyst/critic: {gemma} @ {base_url.split('//', 1)[-1]}"
          + (" (Google AI Studio)" if on_google else ""))
    if researcher_key is None or main_key is None:
        print("[llm] MISSING: researcher key" if researcher_key is None else "",
              "[llm] MISSING: main key" if main_key is None else "")
        print("Fill .env and rerun. Exiting.")
        return 2

    # "Max reasoning" per verified model capabilities:
    # - OpenRouter Nemotron supports a direct reasoning token budget (effort
    #   high is NOT in its list), so give it an explicit large budget.
    # - OpenRouter Gemma: effort "max" (~95% of max_tokens) would return no
    #   JSON, so effort high + max_tokens 24000 is the max USABLE reasoning.
    # - Google AI Studio (OpenAI-compat): the `reasoning` field is an
    #   OpenRouter concept — omitted entirely there; JSON mode is requested
    #   via response_format and if the compat layer rejects anything the
    #   surfaced error bodies will show it.
    if on_openrouter:
        researcher_gen = {"max_tokens": 32768, "reasoning": {"max_tokens": 16384}}
    elif "generativelanguage" in researcher_base:
        # Bisected for Google 26b: budgets above 16384 hit HTTP 500 on the
        # compat layer; 16384 verified 200 + clean parse (diag5).
        researcher_gen = {"max_tokens": 16384}
    else:
        researcher_gen = {"max_tokens": 32768}
    if on_google:
        # Bisected live (diag5): max_tokens 24000 → HTTP 500 on this model;
        # 16384 (and 8192) verified 200 + clean parse. 31b's json path 500s at
        # any tested budget today, so the main pool id is the 26b.
        main_gen = {"max_tokens": 16384}
        print("[llm] google main pool: `reasoning` omitted (OpenRouter-only param)")
    elif "openrouter" in base_url:
        main_gen = {"max_tokens": 24000, "reasoning": {"effort": "high"}}
    else:
        main_gen = {"max_tokens": 24000}

    brief = DecisionBrief(
        market="US, online and indie bookstores",
        audience_description="Design-conscious note-takers aged 18-35",
        business_goal="Pick one of three concepts for a limited holiday run",
        constraints=[{"attribute": "material", "value": "recycled"}],
        weights={"c1": 0.35, "c2": 0.20, "c3": 0.25, "c5": 0.20},
        concepts=[
            {"concept_id": "A", "name": "Mock Studio Notebooks",
             "description": "Recycled notebook", "attributes": {"material": "recycled", "price_band": "under-25", "product_type": "stationery"}},
            {"concept_id": "B", "name": "Mock Luxury Pen",
             "description": "Over-budget pen", "attributes": {"material": "virgin-plastic", "price_band": "over-100", "product_type": "stationery"}},
            {"concept_id": "C", "name": "Mock Desk Organizer",
             "description": "Fiber organizer", "attributes": {"material": "recycled", "price_band": "under-25", "product_type": "stationery"}},
        ],
    )

    llm_attempts: dict[str, int] = {"researcher": 0, "analyst": 0, "critic": 0, "revise": 0}
    hard_cap = 9  # researcher <=2, analyst/critic/revise <=3 each (paced retry + coordinator retry-once)

    def guard(step: str) -> None:
        llm_attempts[step] += 1
        total = sum(llm_attempts.values())
        if total > hard_cap:
            raise AgentLLMError(
                f"budget guard tripped: {total} LLM attempts attempted, cap {hard_cap}"
            )

    def pace(step: str, call):
        """Run one hook call; on provider 429s/5xx wait once and retry once.

        Free-model 429s are provider-pool capacity (verified: they do not
        consume the key's daily counter); instant retries just re-429. Google's
        OpenAI-compat layer intermittently returns 500 INTERNAL / 503
        UNAVAILABLE under burst load — same treatment: wait, then retry.
        The coordinator's own retry-once then still applies after a second
        failure, so no failure path is silencer-narrowed.
        """
        import time

        transient_markers = ("rate limited", "HTTP 5", "UNAVAILABLE", "Internal error")
        for attempt in (1, 2):
            guard(step)
            try:
                if attempt == 2:
                    print(f"[llm] {step}: waiting 70s before paced retry (provider error)...")
                    time.sleep(70)
                return call()
            except AgentLLMError as exc:
                if not any(m in str(exc) for m in transient_markers) or attempt == 2:
                    raise
            except Exception:
                raise
        raise AgentLLMError(f"{step}: unreachable")

    from app.agents.analyst import (
        draft_claims_llm,
        draft_plan_llm,
        review_claims_llm,
        revise_claims_llm,
    )
    from app.schemas.brief import Weights  # noqa: F401  (typing aid only)

    def researcher_fn(names, category_hint):
        return pace("researcher", lambda: _researcher_once(names, category_hint))

    def _researcher_once(names, category_hint):
        plan = draft_plan_llm(
            researcher_key, nemotron, names, category_hint,
            timeout=timeout, base_url=researcher_base,
            max_tokens=researcher_gen["max_tokens"], reasoning=researcher_gen.get("reasoning"),
        )
        # Code-side owner attribution: a planned search whose query matches
        # exactly one concept name attaches to that concept; anything else is
        # shared market evidence. Allowlist/budget are enforced by the
        # coordinator on the returned list.
        lowered = {n: cid for cid, n in
                   ((c.concept_id, c.name.lower()) for c in brief.concepts)}
        out = []
        for call in plan.calls:
            owner = None
            if call.endpoint == "search":
                q = (call.params.get("query") or "").lower()
                hits = [cid for n, cid in lowered.items() if n in q]
                if len(hits) == 1:
                    owner = hits[0]
            out.append((owner, call.endpoint, dict(call.params)))
        print("[researcher] plan calls:", [(o, e, p) for o, e, p in out])
        return out

    def analyst_fn(score_summary, evidence_summary, limitations, weights):
        return pace("analyst", lambda: _analyst_once(score_summary, evidence_summary, limitations, weights))

    def _analyst_once(score_summary, evidence_summary, limitations, weights):
        draft = draft_claims_llm(
            main_key, gemma, score_summary, evidence_summary, limitations, weights,
            timeout=timeout, base_url=base_url,
            max_tokens=main_gen["max_tokens"], reasoning=main_gen.get("reasoning"),
        )
        print(f"[analyst] draft received: {len(draft.claims)} claims")
        return [c.model_dump() for c in draft.claims]

    def critic_fn(claims, score_summary, known_ids):
        return pace("critic", lambda: _critic_once(claims, score_summary, known_ids))

    def _critic_once(claims, score_summary, known_ids):
        out = review_claims_llm(
            main_key, gemma, claims, score_summary, sorted(known_ids),
            timeout=timeout, base_url=base_url,
            max_tokens=main_gen["max_tokens"], reasoning=main_gen.get("reasoning"),
        )
        print(f"[critic] findings received: {len(out.findings)}")
        return [f.model_dump() for f in out.findings]

    def revise_fn(claims, findings):
        return pace("revise", lambda: _revise_once(claims, findings))

    def _revise_once(claims, findings):
        draft = revise_claims_llm(
            main_key, gemma, claims, findings,
            timeout=timeout, base_url=base_url,
            max_tokens=main_gen["max_tokens"], reasoning=main_gen.get("reasoning"),
        )
        print(f"[revise] revised draft received: {len(draft.claims)} claims")
        return [c.model_dump() for c in draft.claims]

    engine = get_engine(database_url)
    init_db(engine)

    client = QlooClient(
        base_url=settings.qloo_base_url,
        api_key=qloo_key,
        timeout_seconds=settings.qloo_timeout_seconds,
    )
    source = LiveEvidenceSource(client)

    print("[run] starting decision run (live Qloo + OpenRouter hooks)...")
    try:
        report = run_decision(
            engine, brief, source,
            researcher_fn=researcher_fn,
            analyst_fn=analyst_fn,
            critic_fn=critic_fn,
            revise_fn=revise_fn,
        )
    finally:
        print("[llm] hook attempts used:", llm_attempts,
              f"(total {sum(llm_attempts.values())}/{hard_cap} worst-case cap)")

    from app.services.persistence import get_run_bundle
    bundle = get_run_bundle(engine, report["run_id"])

    body = report["report"]  # run_decision returns {"run_id", "state", "report", "persisted"}

    print("\n==== LIVE G3 PROBE SUMMARY ====")
    print("run_id:", report["run_id"])
    print("state:", report["state"], "| fixture_mode:", body["fixture_mode"])
    print("winner:", body["winner"], "| ranks:",
          {r["concept_id"]: {"rank": r["rank"], "status": r["status"], "total": r["weighted_total"]}
           for r in body["ranks"]})
    print("limitations:", body["limitations"])
    print("claims (analyst):", len(body["claims"]))
    for c in body["claims"][:6]:
        print(f"  - [{c['claim_id']}] {c['concept_id']} {c['claim_type']}/{c['strength']}/{c['confidence']}: {c['text'][:110]}")
    print("critic findings:", len(body["critic_findings"]))
    for f in body["critic_findings"]:
        print(f"  - {f['issue_code']}/{f['severity']} on {f['affected_claim_id']}: {f['explanation'][:110]}")
    print("revision_count:", body.get("analyst", {}).get("revision_count"))
    print("persisted evidence rows:", len(bundle["evidence"]),
          "| score rows:", len(bundle["scores"]),
          "| critic rows:", len(bundle["critic"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
