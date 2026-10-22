"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { LogoBanner } from "@/components/LogoBanner";
import {
  ApiError,
  BriefPayload,
  HardConstraint,
  deleteRun,
  getRunBundle,
  newRunId,
  postRun,
  resumeRun,
} from "@/lib/api";
import {
  ATTRIBUTE_LABELS,
  ATTRIBUTE_NAMES,
  cleanAttributes,
} from "@/lib/attributes";
import { CRITERIA } from "@/lib/criteria";
import { squeezeWeights, Weights } from "@/lib/weights";

const ACCENTS = ["#a6c3d8", "#292b43", "#baa2c5"] as const;

interface ConceptDraft {
  name: string;
  description: string;
  attributes: Record<string, string>;
}

function Slider({
  c,
  value,
  onChange,
}: {
  c: (typeof CRITERIA)[number];
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="flex items-baseline gap-2">
        <span className="font-serif text-3xl text-ink">{c.label}</span>
        <span className="font-serif text-lg text-ink">{c.name}</span>
      </div>
      <p className="mt-0.5 font-serif text-base text-mistslate">{c.job}</p>
      <input
        type="range"
        min={0}
        max={100}
        step={1}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-3 w-full"
        style={
          {
            "--slider-fill": c.color,
            "--slider-pct": value,
          } as React.CSSProperties
        }
        aria-label={`${c.label} ${c.name} weight`}
      />
      <div className="mt-1 text-right font-serif text-sm text-mistslate">
        {value}%
      </div>
    </div>
  );
}

function ConceptCard({
  index,
  draft,
  onChange,
  valueHints,
}: {
  index: number;
  draft: ConceptDraft;
  onChange: (d: ConceptDraft) => void;
  valueHints: string[];
}) {
  const prepared = draft.name.trim() !== "" && draft.description.trim() !== "";
  const listId = `concept-attr-values-${index}`;
  return (
    <div className="w-full">
      <p className="font-serif text-xl text-ink">Concept {index + 1}</p>
      <div
        className="mt-2 rounded-xl border border-ink/40 bg-creamcard overflow-hidden"
        style={{ borderTop: `3px solid ${ACCENTS[index]}` }}
      >
        <div className="p-3">
          <input
            value={draft.name}
            onChange={(e) => onChange({ ...draft, name: e.target.value })}
            placeholder="Name"
            maxLength={120}
            className="w-full rounded-md border border-mistline bg-white px-2 py-1.5 font-serif text-base text-ink placeholder:text-mistslate/60 focus:border-royal focus:outline-none"
          />
          <textarea
            value={draft.description}
            onChange={(e) =>
              onChange({ ...draft, description: e.target.value })
            }
            placeholder="Describe this concept…"
            maxLength={2000}
            rows={4}
            className="mt-2 w-full resize-none rounded-md border border-mistline bg-white px-2 py-1.5 font-serif text-sm text-ink placeholder:text-mistslate/60 focus:border-royal focus:outline-none"
          />
          {/* Attributes: a hard constraint can only be checked when the
              concept carries the same attribute and the same value string. */}
          <div className="mt-3 border-t border-mistline/70 pt-2">
            <p className="font-serif text-sm text-mistslate">
              Attributes (needed for the hard-constraint check)
            </p>
            <datalist id={listId}>
              {valueHints.map((hint) => (
                <option key={hint} value={hint} />
              ))}
            </datalist>
            <div className="mt-1.5 grid gap-1.5">
              {ATTRIBUTE_NAMES.map((name) => (
                <div key={name} className="flex items-center gap-2">
                  <label
                    htmlFor={`attr-${index}-${name}`}
                    className="w-28 shrink-0 font-serif text-sm text-ink/80"
                  >
                    {ATTRIBUTE_LABELS[name]}
                  </label>
                  <input
                    id={`attr-${index}-${name}`}
                    list={listId}
                    value={draft.attributes[name] ?? ""}
                    onChange={(e) =>
                      onChange({
                        ...draft,
                        attributes: { ...draft.attributes, [name]: e.target.value },
                      })
                    }
                    placeholder="—"
                    maxLength={100}
                    className="flex-1 rounded-md border border-mistline bg-white px-2 py-1 font-serif text-sm focus:border-royal focus:outline-none"
                  />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      <p
        className={`mt-2 font-serif text-base ${
          prepared ? "text-royal" : "text-mistslate"
        }`}
      >
        {prepared ? `${draft.name.trim()} — prepared` : "Awaiting a concept"}
      </p>
    </div>
  );
}

function ConstraintsEditor({
  constraints,
  onChange,
  valueHints,
}: {
  constraints: HardConstraint[];
  onChange: (c: HardConstraint[]) => void;
  valueHints: string[];
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-8">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 font-serif text-xl text-ink hover:text-royal"
      >
        <span className="text-mistslate">{open ? "▾" : "▸"}</span> Hard
        constraints (optional)
      </button>
      <p className="mt-1 font-serif text-base text-mistslate">
        Up to 3 attribute/value checks a concept must pass to rank at all
        (feasibility gate C4). A concept with no such attribute — or a
        different value — is not ranked, and the results page says why.
      </p>
      {open && (
        <div className="mt-3 space-y-2">
          <datalist id="constraint-attr-values">
            {valueHints.map((hint) => (
              <option key={hint} value={hint} />
            ))}
          </datalist>
          {constraints.map((c, i) => (
            <div key={i} className="flex items-center gap-2">
              <select
                value={c.attribute}
                onChange={(e) => {
                  const next = [...constraints];
                  next[i] = { ...c, attribute: e.target.value };
                  onChange(next);
                }}
                className="w-1/2 rounded-md border border-mistline bg-white px-2 py-1.5 font-serif text-sm focus:border-royal focus:outline-none"
              >
                <option value="">choose an attribute…</option>
                {ATTRIBUTE_NAMES.map((name) => (
                  <option key={name} value={name}>
                    {ATTRIBUTE_LABELS[name]} ({name})
                  </option>
                ))}
              </select>
              <input
                value={c.value}
                list="constraint-attr-values"
                placeholder='allowed value (e.g. "under 5k")'
                maxLength={100}
                onChange={(e) => {
                  const next = [...constraints];
                  next[i] = { ...c, value: e.target.value };
                  onChange(next);
                }}
                className="flex-1 rounded-md border border-mistline bg-white px-2 py-1.5 font-serif text-sm focus:border-royal focus:outline-none"
              />
              <button
                type="button"
                onClick={() =>
                  onChange(constraints.filter((_, j) => j !== i))
                }
                className="text-mistslate hover:text-ink"
                aria-label="Remove constraint"
              >
                ✕
              </button>
            </div>
          ))}
          {constraints.length < 3 && (
            <button
              type="button"
              onClick={() => onChange([...constraints, { attribute: "", value: "" }])}
              className="rounded-md border border-mistline px-3 py-1.5 font-serif text-base text-mistslate hover:border-royal hover:text-royal"
            >
              + add constraint
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function AnalysisPage() {
  const router = useRouter();
  const [market, setMarket] = useState("");
  const [audience, setAudience] = useState("");
  const [goal, setGoal] = useState("");
  const [concepts, setConcepts] = useState<ConceptDraft[]>([
    { name: "", description: "", attributes: {} },
    { name: "", description: "", attributes: {} },
    { name: "", description: "", attributes: {} },
  ]);
  const [weights, setWeights] = useState<Weights>(
    Object.fromEntries(CRITERIA.map((c) => [c.id, c.defaultPct])) as Weights
  );
  function changeWeight(id: (typeof CRITERIA)[number]["id"], requested: number) {
    setWeights((w) => squeezeWeights(w, id, requested));
  }
  const [constraints, setConstraints] = useState<HardConstraint[]>([]);
  const [phase, setPhase] = useState<"setup" | "running" | "error">("setup");
  const [error, setError] = useState<string | null>(null);
  const [retryable, setRetryable] = useState(false);
  // When the API says how long to wait (429), the Retry button stays locked
  // until then, so the user is not bounced straight back into a 429.
  const [retryAt, setRetryAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  // The run id of the attempt in flight (and of a failed one), so the user
  // can resume it or start fresh.
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [liveState, setLiveState] = useState<string | null>(null);
  // True when the failed attempt left a run behind that can be resumed.
  const [partialRun, setPartialRun] = useState(false);
  const [recovery, setRecovery] = useState<string | null>(null);

  useEffect(() => {
    if (retryAt === null) return;
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, [retryAt]);

  const waitSeconds = retryAt === null ? 0 : Math.max(0, Math.ceil((retryAt - now) / 1000));

  const preparedCount = concepts.filter(
    (c) => c.name.trim() !== "" && c.description.trim() !== ""
  ).length;

  const total = useMemo(
    () => CRITERIA.reduce((sum, c) => sum + weights[c.id], 0),
    [weights]
  );

  const briefValid =
    preparedCount === 3 &&
    market.trim() !== "" &&
    audience.trim().length >= 3 &&
    goal.trim().length >= 3 &&
    total === 100 &&
    constraints.every((c) => c.attribute.trim() && c.value.trim());

  // The values the concept cards already carry, offered to the constraints
  // (and vice versa) so both sides use the IDENTICAL string — the backend
  // compares them exactly.
  const constraintValues = Array.from(
    new Set(constraints.map((c) => c.value.trim()).filter((v) => v !== ""))
  );
  const conceptValues = Array.from(
    new Set(
      concepts.flatMap((c) =>
        Object.values(c.attributes).map((v) => v.trim())
      ).filter((v) => v !== "")
    )
  );

  async function run() {
    setPhase("running");
    setError(null);
    const ids = ["A", "B", "C"];
    const payload: BriefPayload = {
      market: market.trim(),
      audience_description: audience.trim(),
      business_goal: goal.trim(),
      constraints: constraints.filter((c) => c.attribute.trim() && c.value.trim()),
      weights: {
        c1: weights.c1 / 100,
        c2: weights.c2 / 100,
        c3: weights.c3 / 100,
        c5: weights.c5 / 100,
      },
      concepts: concepts.map((c, i) => ({
        concept_id: ids[i],
        name: c.name.trim(),
        description: c.description.trim(),
        attributes: cleanAttributes(c.attributes),
      })),
    };
    // The run id is chosen here, so the run can be followed (and found
    // again) even if this request dies half-way through.
    const runId = newRunId();
    setActiveRunId(runId);
    setLiveState(null);
    // Keep the brief so a "start fresh" on the results page can screen the
    // same thing again without re-typing it.
    try {
      window.sessionStorage.setItem("cc:lastBrief", JSON.stringify(payload));
    } catch {
      // storage unavailable (private mode) — not fatal
    }
    const poller = setInterval(() => {
      getRunBundle(runId)
        .then((bundle) => setLiveState(bundle.run.state))
        .catch(() => undefined);
    }, 2500);
    try {
      const res = await postRun(payload, runId);
      clearInterval(poller);
      router.push(`/analysis/${res.run_id}`);
    } catch (e) {
      clearInterval(poller);
      setPhase("error");
      setError(e instanceof Error ? e.message : String(e));
      if (e instanceof ApiError) {
        setRetryable(e.retryable);
        setRetryAt(
          e.retryAfterSeconds ? Date.now() + e.retryAfterSeconds * 1000 : null
        );
        setNow(Date.now());
        // A server-side failure (5xx) means the run may have been started
        // and then interrupted: the user can resume it or start fresh.
        if (e.status >= 500) {
          getRunBundle(runId)
            .then((bundle) => {
              setPartialRun(
                !bundle.run.final_report_json &&
                  bundle.run.state !== "COMPLETED" &&
                  bundle.run.state !== "COMPLETED_WITH_LIMITATIONS"
              );
            })
            .catch(() => setPartialRun(false));
        }
      } else {
        // A network failure (the API unreachable) is worth retrying too.
        setRetryable(true);
        setRetryAt(null);
      }
    }
  }

  /** Continue the interrupted run where it stopped (no Qloo call repeated). */
  async function resumePartial() {
    if (!activeRunId) return;
    setRecovery("Resuming…");
    try {
      const res = await resumeRun(activeRunId);
      setRecovery(null);
      router.push(`/analysis/${res.run_id}`);
    } catch (e) {
      setRecovery(e instanceof Error ? e.message : String(e));
    }
  }

  /** Delete the interrupted run's rows and screen the same brief again. */
  async function startFresh() {
    if (!activeRunId) return;
    setRecovery("Starting fresh…");
    try {
      await deleteRun(activeRunId);
      const stored = window.sessionStorage.getItem("cc:lastBrief");
      if (stored) {
        const brief = JSON.parse(stored) as BriefPayload;
        const fresh = await postRun(brief, newRunId());
        setRecovery(null);
        router.push(`/analysis/${fresh.run_id}`);
        return;
      }
      setRecovery(null);
      router.push("/analysis");
    } catch (e) {
      setRecovery(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <main className="min-h-screen bg-white">
      {/* Header */}
      <header className="bg-cream">
        <div className="mx-auto flex max-w-6xl items-start justify-between px-6 py-5">
          <LogoBanner height={72} />
          <nav className="flex gap-10 font-serif text-2xl pt-2">
            <Link href="/" className="text-ink/80 hover:text-ink">
              Home
            </Link>
            <Link
              href="/analysis"
              className="text-royal underline decoration-royal underline-offset-8"
            >
              Analysis
            </Link>
          </nav>
        </div>
      </header>

      {/* Title row */}
      <div className="mx-auto max-w-6xl px-6 pt-10 pb-6">
        <div className="flex items-start justify-between">
          <h1 className="font-serif text-6xl md:text-7xl text-ink">Analysis</h1>
          <span className="rounded-md bg-mistline/60 px-3 py-1.5 font-serif text-base text-ink/80">
            {phase === "running"
              ? "Running · live evidence + LLM"
              : "Concept setup · No results yet"}
          </span>
        </div>
        <p className="mt-3 font-serif text-2xl text-ink">
          Begin with your idea, prepare three concepts, and define the criteria
          that matter.
        </p>
        <hr className="mt-8 border-mistline" />
      </div>

      <div className="mx-auto grid max-w-6xl gap-14 px-6 pb-16 md:grid-cols-[1fr_40%]">
        {/* Left column */}
        <div>
          <h2 className="font-serif text-4xl text-ink">Begin with an idea</h2>
          <p className="mt-2 font-serif text-xl text-mistslate">
            Describe the product, its audience, and what makes it different.
          </p>

          <label className="mt-4 block font-serif text-lg text-ink">
            Market
            <input
              value={market}
              onChange={(e) => setMarket(e.target.value)}
              placeholder='e.g. "Lisbon, Portugal"'
              maxLength={120}
              className="mt-1.5 w-full rounded-md border border-ink/50 bg-white px-3 py-2 font-serif text-base text-ink placeholder:text-mistslate/60 focus:border-royal focus:outline-none"
            />
          </label>
          <label className="mt-3 block font-serif text-lg text-ink">
            Audience
            <textarea
              value={audience}
              onChange={(e) => setAudience(e.target.value)}
              placeholder="Who is deciding whether to buy — their tastes, style, and cultural moments."
              maxLength={2000}
              rows={3}
              className="mt-1.5 w-full resize-none rounded-md border border-ink/50 bg-white px-3 py-2 font-serif text-base text-ink placeholder:text-mistslate/60 focus:border-royal focus:outline-none"
            />
          </label>
          <label className="mt-3 block font-serif text-lg text-ink">
            Business goal
            <textarea
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="What decision this run must inform. Screening only — never a demand forecast."
              maxLength={2000}
              rows={2}
              className="mt-1.5 w-full resize-none rounded-md border border-ink/50 bg-white px-3 py-2 font-serif text-base text-ink placeholder:text-mistslate/60 focus:border-royal focus:outline-none"
            />
          </label>

          <hr className="my-8 border-mistline" />

          <div className="flex items-baseline justify-between">
            <h2 className="font-serif text-4xl text-ink">Your concepts</h2>
            <span className="font-serif text-lg text-mistslate">
              {preparedCount} of 3 prepared
            </span>
          </div>
          <p className="mt-2 font-serif text-xl text-mistslate">
            Three spaces for the concepts you&apos;ll compare.
          </p>

          <div className="mt-4 grid gap-6 sm:grid-cols-3">
            {concepts.map((draft, i) => (
              <ConceptCard
                key={i}
                index={i}
                draft={draft}
                valueHints={constraintValues}
                onChange={(d) => {
                  const next = [...concepts];
                  next[i] = d;
                  setConcepts(next);
                }}
              />
            ))}
          </div>

          <ConstraintsEditor
            constraints={constraints}
            onChange={setConstraints}
            valueHints={conceptValues}
          />
        </div>

        {/* Right column */}
        <div>
          <h2 className="font-serif text-4xl text-ink">Set your criteria</h2>
          <p className="mt-2 font-serif text-xl text-mistslate">
            Adjust the relative importance of the four weighted criteria. The
            four sliders always add to 100% — moving one automatically
            redistributes the others in proportion, so the total never leaves
            100.
          </p>

          <div className="mt-5 rounded-2xl border border-ink/25 bg-white p-6 shadow-sm">
            <div className="space-y-7">
              {CRITERIA.map((c) => (
                <Slider
                  key={c.id}
                  c={c}
                  value={weights[c.id]}
                  onChange={(v) => changeWeight(c.id, v)}
                />
              ))}
            </div>
            <div className="mt-6 flex items-baseline justify-between">
              <span className="font-serif text-base text-mistslate">Lower priority</span>
              <span
                className={`font-serif text-lg ${
                  total === 100 ? "text-royal" : "text-[#b5563a]"
                }`}
              >
                Total {total}% {total === 100 ? "✓" : "(must be 100%)"}
              </span>
              <span className="font-serif text-base text-mistslate">Higher priority</span>
            </div>
          </div>

          <button
            type="button"
            disabled={!briefValid || phase === "running"}
            onClick={run}
            className="mt-6 w-full rounded-lg bg-royal px-8 py-3.5 font-serif text-xl text-white transition
                       enabled:hover:bg-ink disabled:cursor-not-allowed disabled:opacity-40"
          >
            {phase === "running" ? "Running analysis…" : "Run analysis"}
          </button>

          {phase === "running" && liveState && (
            <p className="mt-3 rounded-md border border-mistline bg-cream px-3 py-2 font-serif text-base text-ink">
              In progress: {liveState.replace(/_/g, " ").toLowerCase()}…
            </p>
          )}

          {phase === "error" && (
            <div className="mt-3 rounded-md border border-[#b5563a]/40 bg-[#b5563a]/10 px-3 py-3 font-serif text-base text-ink">
              <p>{error}</p>
              {retryable && (
                <div className="mt-3 flex flex-wrap items-center gap-4">
                  <button
                    type="button"
                    onClick={run}
                    disabled={waitSeconds > 0}
                    className="rounded-md bg-royal px-4 py-1.5 font-serif text-lg text-white transition
                               enabled:hover:bg-ink disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {waitSeconds > 0 ? `Retry in ${waitSeconds}s` : "Retry analysis"}
                  </button>
                  <span className="font-serif text-sm text-mistslate">
                    Your brief is kept — retrying runs the same screening again.
                  </span>
                </div>
              )}
              {partialRun && (
                <div className="mt-4 border-t border-[#b5563a]/30 pt-3">
                  <p className="font-serif text-base text-ink">
                    This attempt was interrupted after it had already collected
                    evidence. You can continue it where it stopped (the Qloo
                    calls are not repeated) or delete the partial run and
                    screen again.
                  </p>
                  <div className="mt-3 flex flex-wrap gap-3">
                    <button
                      type="button"
                      onClick={resumePartial}
                      className="rounded-md bg-royal px-4 py-1.5 font-serif text-lg text-white hover:bg-ink"
                    >
                      Resume this run
                    </button>
                    <button
                      type="button"
                      onClick={startFresh}
                      className="rounded-md border border-ink/40 px-4 py-1.5 font-serif text-lg text-ink hover:bg-cream"
                    >
                      Start fresh
                    </button>
                    {recovery && (
                      <span className="self-center font-serif text-sm text-mistslate">
                        {recovery}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          <p className="mt-5 font-serif text-base leading-relaxed text-mistslate">
            These are configuration controls, not concept scores. Results will
            follow once your concepts and criteria are ready. A live run with
            LLM explanations typically takes 5–15 minutes — please keep this
            tab open until the results page loads.
          </p>
        </div>
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
