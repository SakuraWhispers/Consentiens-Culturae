"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Logo } from "@/components/Logo";
import { getRunBundle, RunBundle } from "@/lib/api";

const CONCEPT_ACCENTS: Record<string, string> = {
  A: "#a6c3d8",
  B: "#7d8da2",
  C: "#baa2c5",
};

function pct(n: number | null): string {
  return n === null ? "—" : `${Math.round(n * 100)}%`;
}

function RunPage() {
  const params = useParams<{ runId: string }>();
  const runId = params?.runId ?? "";
  const [bundle, setBundle] = useState<RunBundle | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    getRunBundle(runId)
      .then(setBundle)
      .catch((e: Error) => setError(e.message));
  }, [runId]);

  if (error) {
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
  if (!report) {
    return (
      <main className="min-h-screen bg-white">
        <div className="mx-auto max-w-6xl px-6 py-20 text-center font-serif text-2xl text-mistslate">
          Run {bundle.run.state} — report pending.
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
          <div>
            <Logo markClass="h-10 w-8" />
            <p className="mt-2 font-serif text-lg text-ink">
              Cultura ducit, ratio iudicat.
            </p>
          </div>
          <nav className="flex gap-10 font-serif text-2xl">
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
      </div>

      <div className="mx-auto max-w-6xl space-y-10 px-6 py-10">
        {/* Winner banner */}
        {report.winner && winner && (
          <section className="rounded-2xl bg-cream p-8 shadow-sm">
            <p className="font-serif text-lg text-mistslate">Top-ranked concept</p>
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
            <p className="mt-3 font-serif text-lg text-mistslate">
              Infeasible under the hard constraints:{" "}
              {infeasible.map((r) => conceptName(r.concept_id)).join(", ")}.
            </p>
          )}
        </section>

        {/* Claims */}
        {report.claims.length > 0 && (
          <section>
            <h3 className="font-serif text-3xl text-ink">
              Reading of the result
              <span className="ml-3 align-middle font-sans text-xs font-medium text-mistslate">
                {report.explanation_template
                  ? "template fallback"
                  : "written by LLM within limits"}
              </span>
            </h3>
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
                    <span className="font-sans text-xs text-mistslate">{c.concept_id}</span>
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
          </section>
        )}

        {/* Critic findings */}
        {report.critic_findings.length > 0 && (
          <section>
            <h3 className="font-serif text-3xl text-ink">Critic findings</h3>
            <ul className="mt-4 space-y-2">
              {report.critic_findings.map((f, i) => (
                <li key={i} className="rounded-xl border border-mistline bg-white p-4">
                  <p className="font-sans text-sm font-medium text-ink">
                    {f.severity.toUpperCase()} · {f.issue_code}
                  </p>
                  <p className="mt-1 font-serif text-lg text-ink">{f.explanation}</p>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Sensitivity */}
        <section className="rounded-2xl bg-cream p-8 shadow-sm">
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
              </li>
            ))}
          </ul>
        </section>

        {/* Limitations */}
        {report.limitations.length > 0 && (
          <section>
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
