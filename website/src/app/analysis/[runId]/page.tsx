"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { LogoBanner } from "@/components/LogoBanner";
import {
  BriefPayload,
  deleteRun,
  getRunBundle,
  newRunId,
  postRun,
  resumeRun,
  RunBundle,
} from "@/lib/api";

const CONCEPT_ACCENTS: Record<string, string> = {
  A: "#a6c3d8",
  B: "#7d8da2",
  C: "#baa2c5",
};

/** The workflow states, in the words a reader can follow. */
const STATE_LABELS: Record<string, string> = {
  CREATED: "starting up",
  VALIDATING_INPUT: "checking the brief",
  RETRIEVING_EVIDENCE: "retrieving Qloo evidence",
  NORMALIZING_EVIDENCE: "normalizing the evidence",
  SCORING: "scoring the concepts",
  DRAFTING_EXPLANATION: "the analyst is writing the reading",
  CRITIC_REVIEW: "the critic is challenging the claims",
  REVISING: "revising the flagged claims",
  FINAL_VALIDATION: "validating the report",
  ROBUSTNESS_ANALYSIS: "running the sensitivity analysis",
  COMPLETED: "done",
  COMPLETED_WITH_LIMITATIONS: "done",
  FAILED_TERMINAL: "failed",
  FAILED_RETRYABLE: "interrupted",
};

function pct(n: number | null): string {
  return n === null ? "—" : `${Math.round(n * 100)}%`;
}

function RunPage() {
  const params = useParams<{ runId: string }>();
  const router = useRouter();
  const runId = params?.runId ?? "";
  const [bundle, setBundle] = useState<RunBundle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<string | null>(null);
  // A run that has not moved for a while is probably interrupted (the
  // process died, the network dropped) rather than slow.
  const [stale, setStale] = useState(false);

  const refresh = useCallback(async () => {
    if (!runId) return;
    try {
      const next = await getRunBundle(runId);
      setBundle(next);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    let active = true;
    let lastState: string | null = null;
    let lastChange = Date.now();
    const tick = async () => {
      try {
        const next = await getRunBundle(runId);
        if (!active) return;
        setBundle(next);
        setError(null);
        if (next.run.state !== lastState) {
          lastState = next.run.state;
          lastChange = Date.now();
          setStale(false);
        } else if (Date.now() - lastChange > 120000) {
          setStale(true);
        }
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : String(e));
      }
    };
    tick();
    const timer = setInterval(tick, 2500);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [runId]);

  async function resume() {
    setAction("Resuming…");
    try {
      await resumeRun(runId);
      setAction(null);
      setStale(false);
      await refresh();
    } catch (e) {
      setAction(e instanceof Error ? e.message : String(e));
    }
  }

  async function startFresh() {
    setAction("Starting fresh…");
    try {
      await deleteRun(runId);
      const stored = window.sessionStorage.getItem("cc:lastBrief");
      if (stored) {
        const brief = JSON.parse(stored) as BriefPayload;
        const fresh = await postRun(brief, newRunId());
        setAction(null);
        router.push(`/analysis/${fresh.run_id}`);
        return;
      }
      setAction(null);
      router.push("/analysis");
    } catch (e) {
      setAction(e instanceof Error ? e.message : String(e));
    }
  }

  if (error && !bundle) {
    return (
      <main className="min-h-screen bg-white">
        <div className="mx-auto max-w-6xl px-6 py-20 text-center">
          <h1 className="font-serif text-5xl text-ink">{error}</h1>
          <Link href="/analysis" className="mt-6 inline-block font-serif text-lg text-royal underline">
            ← back to Analysis
          </Link>
        </div>
      </main>
    );
  }

  if (!bundle) {
    return (
      <main className="min-h-screen bg-white">
        <div className="mx-auto max-w-6xl px-6 py-20 text-center font-serif text-2xl text-mistslate">
          Loading run…
        </div>
      </main>
    );
  }

  const report = bundle.run.final_report_json;
  const state = bundle.run.state;
  const isTerminal = [
    "COMPLETED",
    "COMPLETED_WITH_LIMITATIONS",
    "FAILED_TERMINAL",
  ].includes(state);

  if (!report) {
    return (
      <main className="min-h-screen bg-white">
        <header className="bg-cream">
          <div className="mx-auto flex max-w-6xl items-start justify-between px-6 py-5">
            <LogoBanner height={72} />
            <nav className="flex gap-10 font-serif text-2xl pt-2">
              <Link href="/" className="font-serif text-ink/80 hover:text-ink">Home</Link>
              <Link href="/analysis" className="font-serif text-ink/80 hover:text-ink">Analysis</Link>
            </nav>
          </div>
        </header>
        <div className="mx-auto max-w-6xl px-6 py-20">
          <p className="font-serif text-3xl text-ink">
            {STATE_LABELS[state] ?? state}
            {isTerminal ? " — but this run produced no report." : "…"}
          </p>
          <p className="mt-2 font-serif text-lg text-mistslate">
            Run {state} · the report is written at the end of the pipeline.
          </p>
          {stale && (
            <div className="mt-6 rounded-2xl border border-mauve/50 bg-mauve/15 p-6">
              <p className="font-serif text-xl text-ink">
                This run has not moved for two minutes. It may have been
                interrupted (a dropped connection, a closed laptop).
              </p>
              <p className="mt-2 font-serif text-lg text-ink/85">
                Resume re-uses the Qloo evidence it already stored — no Qloo
                call is repeated. Start fresh deletes this run’s rows and
                screens again from the beginning.
              </p>
              <div className="mt-4 flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={resume}
                  className="rounded-md bg-royal px-5 py-2 font-serif text-lg text-white hover:bg-ink"
                >
                  Resume this run
                </button>
                <button
                  type="button"
                  onClick={startFresh}
                  className="rounded-md border border-ink/40 px-5 py-2 font-serif text-lg text-ink hover:bg-cream"
                >
                  Start fresh
                </button>
                {action && (
                  <span className="self-center font-serif text-base text-mistslate">
                    {action}
                  </span>
                )}
              </div>
            </div>
          )}
          {!stale && !isTerminal && (
            <p className="mt-6 font-serif text-lg text-mistslate">
              This page follows the run while it works — keep it open.
            </p>
          )}
        </div>
      </main>
    );
  }

  const winner = report.ranks.find((r) => r.concept_id === report.winner);
  const ranked = report.ranks.filter((r) => r.status !== "INFEASIBLE");
  const infeasible = report.ranks.filter((r) => r.status === "INFEASIBLE");
  const conceptName = (id: string | null) =>
    (id && bundle.run.input_json.concepts.find((c) => c.concept_id === id)?.name) ||
    id ||
    "—";

  return (
    <main className="min-h-screen bg-white">
      {/* Header (shared with Analysis) */}
      <header className="bg-cream">
        <div className="mx-auto flex max-w-6xl items-start justify-between px-6 py-5">
          <LogoBanner height={72} />
          <nav className="flex gap-10 font-serif text-2xl pt-2">
            <Link href="/" className="text-ink/80 hover:text-ink">Home</Link>
            <Link href="/analysis" className="text-ink/80 hover:text-ink">Analysis</Link>
          </nav>
        </div>
      </header>

      {/* Title */}
      <div className="mx-auto max-w-6xl px-6 pt-10">
        <div className="flex items-start justify-between">
          <h1 className="font-serif text-6xl md:text-7xl text-ink">Results</h1>
          <span className="rounded-md bg-mistline/60 px-3 py-1.5 font-serif text-base text-ink/80">
            Run {report.run_id.slice(0, 8)} · {bundle.run.state}
          </span>
        </div>
        {report.fixture_mode && report.fixture_banner && (
          <p className="mt-4 rounded-md border border-mauve/50 bg-mauve/15 px-4 py-2 font-serif text-lg text-ink">
            {report.fixture_banner}
          </p>
        )}
        <p className="mt-3 font-serif text-xl text-mistslate">
          Deterministic scoring on Qloo culture-affinity evidence. Weights as
          configured:{" "}
          {[
            ["C1", bundle.run.input_json.weights.c1],
            ["C2", bundle.run.input_json.weights.c2],
            ["C3", bundle.run.input_json.weights.c3],
            ["C5", bundle.run.input_json.weights.c5],
          ]
            .map(([l, w]) => `${l} ${Math.round((w as number) * 100)}%`)
            .join(" · ")}
        </p>

        {/* Table of contents: what the page shows and where */}
        <nav className="mt-6 rounded-2xl border border-mistline bg-cream p-5">
          <p className="font-serif text-lg text-ink">On this page</p>
          <ul className="mt-2 grid gap-x-8 gap-y-1 text-base sm:grid-cols-2">
            {[
              ["result", "The ranked result"],
              ...(report.tiebreak?.detected
                ? [["tiebreak", "The tie-break attempt"]]
                : []),
              ...(report.verbose
                ? [["verbose", "The full report in words"]]
                : []),
              ["researcher", "1 · What the researcher did and found"],
              ["analyst", "2 · What the analyst analysed and found"],
              ["critique", "3 · What the critique criticised"],
              ["explainer", "How the seeding and the weights work"],
              ["evidence", `The evidence, in full (${bundle.evidence.length} records)`],
              ["sensitivity", "Sensitivity analysis"],
              ["limitations", "Limitations and notes"],
            ].map(([id, label]) => (
              <li key={id}>
                <a
                  href={`#${id}`}
                  className="font-serif text-royal underline decoration-royal/40 underline-offset-4 hover:decoration-royal"
                >
                  {label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </div>

      <div className="mx-auto max-w-6xl space-y-10 px-6 py-10">
        {/* Winner banner */}
        {report.winner && winner && (
          <section id="result" className="rounded-2xl bg-cream p-8 shadow-sm">
            <p className="font-serif text-lg text-mistslate">
              {report.tie?.detected ? "Leading concepts (tied)" : "Top-ranked concept"}
            </p>
            <h2 className="mt-1 font-serif text-5xl text-ink">
              {conceptName(report.winner)}
              <span
                className="ml-3 align-middle font-sans text-sm font-medium text-royal"
              >
                {report.winner}
              </span>
            </h2>
            <p className="mt-3 font-serif text-xl text-ink">
              Weighted total {winner.weighted_total?.toFixed(1)} of 100 ·
              coverage {pct(winner.coverage)}
            </p>
            {report.tie?.detected && (
              <div className="mt-3 rounded-lg border border-mauve/60 bg-mauve/15 px-4 py-3">
                <p className="font-serif text-lg text-ink">
                  <span className="font-sans text-sm font-medium uppercase tracking-wide text-ink/70">
                    Tied
                  </span>{" "}
                  — {report.tie.concepts.map((c) => conceptName(c)).join(" and ")} are
                  level on the total (a gap of{" "}
                  {report.tie.spread?.toFixed(2)} points, which is within the{" "}
                  {report.tie.threshold}-point tie window). The order above is the
                  engine&apos;s tie-break, not a measured difference.
                </p>
                {report.sensitivity.tie_statements && (
                  <ul className="mt-2 space-y-1">
                    {report.tie.concepts.map((c) =>
                      report.sensitivity.tie_statements?.[c] ? (
                        <li key={c} className="font-serif text-base text-ink/85">
                          {conceptName(c)}: {report.sensitivity.tie_statements[c]}
                        </li>
                      ) : null
                    )}
                  </ul>
                )}
              </div>
            )}
            <div className="mt-6 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {winner.criterion_scores.map((cs) => (
                <div key={cs.criterion} className="rounded-lg border border-mistline bg-white p-4">
                  <p className="font-serif text-lg text-ink">{cs.criterion}</p>
                  <p className="mt-1 font-serif text-2xl text-royal">
                    {cs.value === null ? "—" : cs.value.toFixed(2)}
                  </p>
                  <p className="font-serif text-sm text-mistslate">
                    weight {pct(cs.weight_applied)}
                  </p>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Tie-break: what the engine did when the leaders ended level. */}
        {report.tiebreak?.detected && (
          <section
            id="tiebreak"
            className="rounded-2xl border border-mauve/50 bg-mauve/10 p-7 shadow-sm"
          >
            <h3 className="font-serif text-3xl text-ink">
              The tie-break attempt
            </h3>
            <p className="mt-2 font-serif text-lg text-ink/90">
              {report.tiebreak.concepts.map((c) => conceptName(c)).join(" and ")}{" "}
              ended level on the weighted total, so the engine looked harder before
              presenting anything: {report.tiebreak.extra_calls} extra Qloo{" "}
              {report.tiebreak.extra_calls === 1 ? "call" : "calls"} for the tied
              concepts only ({report.tiebreak.new_entities} new evidence{" "}
              {report.tiebreak.new_entities === 1 ? "record" : "records"},{" "}
              {report.tiebreak.known_entities_skipped} already known and not
              counted twice).
            </p>
            <dl className="mt-4 grid gap-3 sm:grid-cols-2">
              {report.tiebreak.concepts.map((c) => (
                <div key={c} className="rounded-lg border border-mauve/40 bg-white p-4">
                  <dt className="font-serif text-lg text-ink">{conceptName(c)}</dt>
                  <dd className="mt-1 font-serif text-xl text-royal">
                    {report.tiebreak?.before[c]?.toFixed(1)} →{" "}
                    {report.tiebreak?.after[c]?.toFixed(1)}
                  </dd>
                  <dd className="font-serif text-sm text-mistslate">
                    weighted total before → after the extra evidence
                  </dd>
                </div>
              ))}
            </dl>
            <p className="mt-4 rounded-lg bg-white px-4 py-3 font-serif text-base text-ink/90">
              {report.tiebreak.resolved
                ? "After the extra evidence, the totals separated and the tie was resolved."
                : "Even with the extra evidence, the totals stayed level. The engine does not invent a difference it cannot measure."}
            </p>
            {report.tiebreak.comparison.length > 0 && (
              <div className="mt-5">
                <p className="font-sans text-sm font-medium uppercase tracking-wide text-ink/70">
                  The focused comparison
                </p>
                <ul className="mt-2 space-y-3">
                  {report.tiebreak.comparison.map((claim) => (
                    <li
                      key={claim.claim_id}
                      className="rounded-lg border border-mistline bg-white p-4"
                    >
                      <p className="font-sans text-sm font-medium text-royal">
                        {conceptName(claim.concept_id)} · {claim.claim_type} ·{" "}
                        {claim.strength} ⇒ confidence {claim.confidence}
                      </p>
                      <p className="mt-1 font-serif text-base text-ink">
                        {claim.text}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <p className="mt-4 font-serif text-sm text-mistslate">
              {report.tiebreak.note}
            </p>
          </section>
        )}

        {/* The verbose report: the whole run told in words. Provenance is
            shown honestly: who wrote it and why. */}
        {report.verbose && (
          <section
            id="verbose"
            className="rounded-2xl border border-mistline bg-creamcard p-7 shadow-sm"
          >
            <h3 className="font-serif text-3xl text-ink">
              The full report in words
            </h3>
            <p className="mt-2 font-sans text-sm text-mistslate">
              {report.verbose.llm_written ? (
                <>
                  Written by the reporter model and cleared by the deterministic
                  number guard
                  {report.verbose.attempts > 1
                    ? ` (${report.verbose.attempts} attempts — an invented number was caught and the draft rewritten)`
                    : ""}
                  .
                </>
              ) : (
                <>
                  Written by the deterministic template
                  {report.verbose.template_reason
                    ? ` — ${report.verbose.template_reason}`
                    : ""}
                  .
                </>
              )}
            </p>
            <div className="mt-4 space-y-4">
              {report.verbose.prose.split("\n\n").map((paragraph, i) => (
                <p key={i} className="font-serif text-lg leading-relaxed text-ink">
                  {paragraph}
                </p>
              ))}
            </div>
          </section>
        )}

        {/* Ranked cards */}
        <section>
          <h3 className="font-serif text-3xl text-ink">Ranked concepts</h3>
          <div className="mt-4 grid gap-5 md:grid-cols-3">
            {ranked.map((r) => (
              <div
                key={r.concept_id}
                className="rounded-xl border border-ink/30 bg-creamcard p-5 shadow-sm"
                style={{ borderTop: `3px solid ${CONCEPT_ACCENTS[r.concept_id] ?? "#292b43"}` }}
              >
                <p className="font-serif text-lg text-mistslate">rank {r.rank} of {ranked.length}</p>
                <p className="mt-1 font-serif text-2xl text-ink">{conceptName(r.concept_id)}</p>
                <p className="mt-1 font-serif text-xl text-royal">
                  {r.weighted_total?.toFixed(1)} · coverage {pct(r.coverage)}
                </p>
              </div>
            ))}
          </div>
          {infeasible.length > 0 && (
            <div className="mt-3 rounded-xl border border-mauve/50 bg-mauve/15 p-4">
              <p className="font-serif text-lg text-ink">
                Not ranked under the hard constraints:{" "}
                {infeasible.map((r) => conceptName(r.concept_id)).join(", ")}.
              </p>
              <ul className="mt-2 list-disc pl-6">
                {infeasible.map((r) => (
                  <li key={r.concept_id} className="font-serif text-base text-ink/85">
                    <span className="font-sans text-sm text-ink">
                      {conceptName(r.concept_id)}
                    </span>
                    {r.reason ? ` — ${r.reason}` : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        {/* 1 · What the researcher did and found */}
        <section
          id="researcher"
          className="rounded-2xl border border-mistline bg-white p-7 shadow-sm"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="font-serif text-3xl text-ink">
              1 · What the researcher did and found
            </h3>
            <span className="rounded bg-mistline/70 px-2 py-0.5 font-sans text-xs font-medium text-ink/80">
              {report.research.mode === "agent"
                ? "plan written by the LLM researcher"
                : report.research.mode === "resumed"
                  ? "resumed — the stored evidence was reused"
                  : "deterministic plan (the agent plan was not usable)"}
            </span>
          </div>
          <p className="mt-3 font-serif text-lg text-ink/85">
            {report.research.qloo_calls} Qloo call
            {report.research.qloo_calls === 1 ? "" : "s"} ·{" "}
            {report.research.evidence.available} of {report.research.evidence.total}{" "}
            evidence records usable
            {report.research.evidence.total !== report.research.evidence.available
              ? " — the rest are partial or unmatched, and are listed with their reasons below."
              : "."}
          </p>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-mistline font-sans text-xs uppercase tracking-wide text-mistslate">
                  <th className="py-1 pr-3">Call</th>
                  <th className="py-1 pr-3">Params (redacted)</th>
                  <th className="py-1">For concept</th>
                </tr>
              </thead>
              <tbody>
                {report.research.calls.map((call, i) => (
                  <tr key={i} className="border-b border-mistline/60">
                    <td className="py-1.5 pr-3 font-sans text-ink">{call.endpoint}</td>
                    <td className="py-1.5 pr-3 font-sans text-ink/80">
                      {Object.entries(call.params)
                        .map(([k, v]) => `${k}=${v}`)
                        .join("  ") || "—"}
                    </td>
                    <td className="py-1.5 font-sans text-ink/80">
                      {call.owner ? conceptName(call.owner) : "all concepts (market-level)"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 font-serif text-sm text-mistslate">
            Only two Qloo endpoints are ever used — <code>search</code> (find
            entities) and <code>insights</code> (measure them) — and the
            parameters above are checked against a fixed allowlist before any
            call is made.
          </p>
        </section>

        {/* 2 · What the analyst analysed and found */}
        <section
          id="analyst"
          className="rounded-2xl border border-mistline bg-white p-7 shadow-sm"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="font-serif text-3xl text-ink">
              2 · What the analyst analysed and found
            </h3>
            <span className="rounded bg-royal/10 px-2 py-0.5 font-sans text-xs font-medium text-royal">
              {report.explanation_template
                ? "template fallback (the LLM stage did not deliver)"
                : "written by the LLM analyst, within its limits"}
            </span>
          </div>
          <p className="mt-3 font-serif text-lg text-ink/85">
            The analyst received the computed ranks and totals (it may not
            change them), the evidence counts per concept, the weights you
            set, and the real evidence IDs it may cite. It wrote{" "}
            {report.claims.length} claim{report.claims.length === 1 ? "" : "s"}.
          </p>
          {report.claims.length === 0 ? (
            <p className="mt-3 font-serif text-lg text-mistslate">
              No claims were produced for this run.
            </p>
          ) : (
            <ul className="mt-4 space-y-3">
              {report.claims.map((c) => (
                <li key={c.claim_id} className="rounded-xl border border-mistline bg-cream p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-royal/10 px-2 py-0.5 font-sans text-xs font-medium text-royal">
                      {c.claim_type}
                    </span>
                    <span className="rounded bg-mistline/70 px-2 py-0.5 font-sans text-xs text-ink/80">
                      {c.strength} · {c.confidence}
                    </span>
                    <span className="font-sans text-xs text-mistslate">
                      concept {c.concept_id}
                    </span>
                    {c.evidence_ids && c.evidence_ids.length > 0 && (
                      <span className="rounded bg-mauve/25 px-2 py-0.5 font-sans text-xs text-ink">
                        cites {c.evidence_ids.length} evidence record
                        {c.evidence_ids.length === 1 ? "" : "s"}
                      </span>
                    )}
                    {c.qualified && (
                      <span className="rounded bg-mauve/30 px-2 py-0.5 font-sans text-xs text-ink">
                        qualified
                      </span>
                    )}
                  </div>
                  <p className="mt-2 font-serif text-lg text-ink">{c.text}</p>
                  {c.audience_context && (
                    <p className="mt-1 font-serif text-sm text-mistslate">
                      Audience note (not scored): {c.audience_context}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* 3 · What the critique criticised */}
        <section
          id="critique"
          className="rounded-2xl border border-mistline bg-white p-7 shadow-sm"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="font-serif text-3xl text-ink">
              3 · What the critique criticised
            </h3>
            <span className="rounded bg-mistline/70 px-2 py-0.5 font-sans text-xs font-medium text-ink/80">
              {report.critic
                ? `${report.critic.llm_findings} from the LLM critic · ${report.critic.rule_findings} from the rule checks`
                : `${report.critic_findings.length} finding(s)`}
            </span>
          </div>
          <p className="mt-3 font-serif text-lg text-ink/85">
            The critique ran. It checked {report.critic.claims_reviewed} claim
            {report.critic.claims_reviewed === 1 ? "" : "s"} against{" "}
            {report.critic.evidence_records_available} usable evidence record
            {report.critic.evidence_records_available === 1 ? "" : "s"}, looking
            for these {report.critic.issue_codes.length} issue codes:{" "}
            <span className="font-sans text-sm text-ink/70">
              {report.critic.issue_codes.join(", ")}
            </span>
            .
          </p>
          {report.critic_findings.length === 0 ? (
            <p className="mt-2 font-serif text-lg text-mistslate">
              It found nothing to challenge: no claim contradicted the computed
              results, cited an unknown evidence ID, or overreached into a
              causal claim. A clean critique is a result, not a missing step.
            </p>
          ) : (
            <ul className="mt-4 space-y-2">
              {report.critic_findings.map((f, i) => (
                <li key={i} className="rounded-xl border border-mistline bg-cream p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-[#b5563a]/12 px-2 py-0.5 font-sans text-xs font-medium text-[#b5563a]">
                      {f.severity.toUpperCase()}
                    </span>
                    <span className="rounded bg-mistline/70 px-2 py-0.5 font-sans text-xs font-medium text-ink">
                      {f.issue_code}
                    </span>
                    <span className="font-sans text-xs text-mistslate">
                      {f.source === "rules" ? "rule checks" : "LLM critic"}
                    </span>
                    <span className="font-sans text-xs text-mistslate">
                      · suggests {f.suggested_action}
                    </span>
                  </div>
                  <p className="mt-1 font-serif text-lg text-ink">{f.explanation}</p>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* How the seeding and the weights work (plain language) */}
        <section
          id="explainer"
          className="rounded-2xl border border-ink/20 bg-cream p-7 shadow-sm"
        >
          <h3 className="font-serif text-3xl text-ink">
            How the seeding and the weights work
          </h3>
          <p className="mt-3 font-serif text-lg leading-relaxed text-ink/85">
            <strong>Your sliders become weights.</strong> Each percentage is
            divided by 100 (35% becomes 0.35) and the engine needs the four to
            add up to exactly 1.00 — the analysis form will not submit
            otherwise. A criterion with no evidence drops out and its share is
            spread over the others, and the hard-constraint check is a
            pass/fail gate: it never carries a share at all. Each criterion is
            then normalised across the three concepts, multiplied by its
            weight, and added up. Nothing in that arithmetic is written by a
            language model.
          </p>
          <p className="mt-3 font-serif text-lg leading-relaxed text-ink/85">
            <strong>The seeding is what makes the percentages reproducible.</strong>{" "}
            We do not guess. We generate {report.sensitivity.scenarios_tested}{" "}
            alternative weightings around yours (each criterion moved by up to
            20 points, then re-balanced to 100%) using a fixed seed
            {report.sensitivity.seed ? ` (${report.sensitivity.seed})` : ""}, so
            the same brief always produces the same scenarios and the same
            percentages. The sentence below is therefore a measurement, not a
            lucky draw:{" "}
            {report.sensitivity.tie_scenarios
              ? `${report.sensitivity.tie_scenarios} of the ${report.sensitivity.scenarios_tested} scenarios ended in a tie, and a tie is reported as a tie.`
              : "no scenario ended in a tie."}
          </p>
          {report.stages && report.stages.length > 0 && (
            <p className="mt-3 font-serif text-base text-ink/75">
              <strong>How long each stage took:</strong>{" "}
              {report.stages
                .map((s) => `${s.stage.replace(/_/g, " ").toLowerCase()} ${s.seconds}s`)
                .join(" · ")}
            </p>
          )}
        </section>

        {/* The evidence, in full */}
        <section id="evidence" className="rounded-2xl border border-mistline bg-white p-7 shadow-sm">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="font-serif text-3xl text-ink">The evidence, in full</h3>
            <span className="rounded bg-mistline/70 px-2 py-0.5 font-sans text-xs font-medium text-ink/80">
              {bundle.evidence.length} record
              {bundle.evidence.length === 1 ? "" : "s"} from{" "}
              {report.research.qloo_calls} Qloo call
              {report.research.qloo_calls === 1 ? "" : "s"}
            </span>
          </div>
          <p className="mt-2 font-serif text-base text-mistslate">
            Every record the run used, with the entity it came from, how well
            it matched, and the query that found it. The parameters are
            redacted; no key is ever stored here.
          </p>
          <details className="mt-3">
            <summary className="cursor-pointer font-serif text-lg text-royal">
              Show the {bundle.evidence.length} evidence records
            </summary>
            <div className="mt-3 max-h-[32rem] overflow-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-mistline font-sans text-xs uppercase tracking-wide text-mistslate">
                    <th className="py-1 pr-3">Entity</th>
                    <th className="py-1 pr-3">Popularity</th>
                    <th className="py-1 pr-3">Match</th>
                    <th className="py-1 pr-3">Coverage</th>
                    <th className="py-1">Found by</th>
                  </tr>
                </thead>
                <tbody>
                  {bundle.evidence.map((e) => (
                    <tr key={e.evidence_id} className="border-b border-mistline/60 align-top">
                      <td className="py-1.5 pr-3">
                        <span className="font-serif text-ink">
                          {e.entity_name ?? e.qloo_entity_id ?? "—"}
                        </span>
                        {e.entity_subtype && (
                          <span className="ml-2 font-sans text-xs text-mistslate">
                            {e.entity_subtype}
                          </span>
                        )}
                        {e.limitations && e.limitations.length > 0 && (
                          <span className="ml-2 font-sans text-xs text-[#b5563a]">
                            {e.limitations.join("; ")}
                          </span>
                        )}
                      </td>
                      <td className="py-1.5 pr-3 font-sans text-ink/80">
                        {e.popularity === null || e.popularity === undefined
                          ? "—"
                          : e.popularity.toFixed(3)}
                      </td>
                      <td className="py-1.5 pr-3 font-sans text-ink/80">
                        {e.match_quality}
                      </td>
                      <td className="py-1.5 pr-3 font-sans text-ink/80">
                        {e.coverage_status}
                      </td>
                      <td className="py-1.5 font-sans text-xs text-mistslate">
                        {e.endpoint_or_operation}
                        {Object.entries(e.query_params_redacted ?? {})
                          .map(([k, v]) => ` ${k}=${v}`)
                          .join("")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </section>

        {/* Sensitivity */}
        <section id="sensitivity" className="rounded-2xl bg-cream p-8 shadow-sm">
          <h3 className="font-serif text-3xl text-ink">Sensitivity analysis</h3>
          <p className="mt-2 font-serif text-lg text-mistslate">
            {report.sensitivity.scenarios_tested} preference scenarios tested
            (method: {report.sensitivity.method}; scoring version{" "}
            {report.sensitivity.scoring_version}).
            {report.sensitivity.pivotal_criterion &&
              ` Pivotal criterion: ${report.sensitivity.pivotal_criterion}.`}
          </p>
          <ul className="mt-4 space-y-2">
            {Object.entries(report.sensitivity.statements).map(([cid, statement]) => (
              <li key={cid} className="font-serif text-lg text-ink">
                <span className="font-sans text-sm font-medium text-royal">{cid}</span>
                {" — "}
                {statement}
                {report.sensitivity.tie_statements?.[cid] && (
                  <span className="block text-ink/80">
                    {report.sensitivity.tie_statements[cid]}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>

        {/* Limitations */}
        {report.limitations.length > 0 && (
          <section id="limitations">
            <h3 className="font-serif text-3xl text-ink">Limitations</h3>
            <ul className="mt-2 list-disc pl-6">
              {report.limitations.map((l, i) => (
                <li key={i} className="font-serif text-lg text-mistslate">{l}</li>
              ))}
            </ul>
          </section>
        )}

        <p className="font-serif text-lg text-mistslate">
          Cultural affinity is not purchase intent. {report.disclaimer}
        </p>
      </div>

      {/* Footer */}
      <footer className="border-t border-mistline bg-white">
        <div className="mx-auto flex max-w-6xl items-baseline justify-between px-6 py-5">
          <span className="font-serif text-xl text-ink">Consentiens Culturae</span>
          <span className="font-serif text-lg text-mistslate">
            Cultural insight. Considered decisions.
          </span>
        </div>
      </footer>
    </main>
  );
}

export default function Page() {
  return (
    <Suspense
      fallback={
        <main className="min-h-screen bg-white">
          <div className="mx-auto max-w-6xl px-6 py-20 text-center font-serif text-2xl text-mistslate">
            Loading run…
          </div>
        </main>
      }
    >
      <RunPage />
    </Suspense>
  );
}
