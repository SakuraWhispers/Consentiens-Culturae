import Link from "next/link";
import { LogoBanner } from "@/components/LogoBanner";

const FEATURES: Array<{ title: string; body: string; icon: React.ReactNode }> = [
  {
    title: "Data-Driven Insights",
    body:
      "Leverage Qloo culture-affinity evidence to understand how your concepts resonate with specific audiences.",
    icon: (
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M5 19V12M12 19V5M19 19v-6" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    title: "Transparent Scoring",
    body:
      "Every score is backed by clear methodology, ensuring your stakeholders trust the results.",
    icon: (
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M12 4 3 9l9 5 9-5-9-5Zm-9 8 9 5 9-5-9-5Z" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    title: "Sensitivity Analysis",
    body:
      "Test how small changes in criteria impact your concept rankings to find the optimal path.",
    icon: (
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M3 12h4l2-6 4 12 2-6h6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
];

export default function Home() {
  return (
    <main className="min-h-screen">
      {/* Hero (cream) */}
      <section className="bg-cream">
        <div className="mx-auto max-w-6xl px-6 pt-10 pb-16 flex flex-col items-center text-center">
          <LogoBanner height={100} priority />

          <h1 className="mt-14 font-serif text-5xl md:text-7xl leading-[1.08] text-ink">
            Better cultural insights.
          </h1>
          <h1 className="font-serif text-5xl md:text-7xl leading-[1.08] text-royal">
            Smarter concept decisions.
          </h1>

          <p className="mt-8 max-w-2xl font-serif text-xl text-mistslate">
            Compare three product concepts with Qloo culture-affinity evidence,
            transparent scoring, and sensitivity analysis — all in one place.
          </p>

          <Link
            href="/analysis"
            className="mt-10 rounded-lg bg-royal px-8 py-3.5 font-serif text-lg text-white transition hover:bg-ink"
          >
            Start your analysis
          </Link>
        </div>
      </section>

      {/* Features (white) */}
      <section className="bg-white">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <h2 className="font-serif text-4xl md:text-5xl text-ink">
            Why Consentiens Culturae?
          </h2>
          <p className="mt-4 max-w-2xl font-serif text-xl text-mistslate">
            Our platform provides a structured framework for evaluating product
            concepts through the lens of cultural affinity and data-driven
            decision making.
          </p>

          <div className="mt-12 grid gap-8 md:grid-cols-3">
            {FEATURES.map((f) => (
              <div
                key={f.title}
                className="rounded-2xl bg-cream p-8 transition hover:bg-creamcard"
              >
                <span className="flex h-12 w-12 items-center justify-center rounded-full bg-white text-royal shadow-sm">
                  {f.icon}
                </span>
                <h3 className="mt-8 font-serif text-2xl font-medium text-ink">
                  {f.title}
                </h3>
                <p className="mt-3 font-serif text-lg leading-relaxed text-mistslate">
                  {f.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Closing band (cream) */}
      <footer className="bg-cream">
        <div className="mx-auto flex max-w-6xl flex-col items-center px-6 py-14 text-center">
          <LogoBanner height={90} />
        </div>
      </footer>
    </main>
  );
}
