/** Shared criteria palette: the engine's four WEIGHTED criteria (C4 is a
 *  weightless pass/fail gate and therefore never has a slider). Fixed names
 *  + one-line job descriptions (human decision 2026-10-20: ship truthful
 *  C1/C2/C3/C5 labeling). Slider colors and default weights from the designs
 *  and the documented UI contract. */
export interface CriterionMeta {
  id: "c1" | "c2" | "c3" | "c5";
  label: "C1" | "C2" | "C3" | "C5";
  name: string;
  job: string;
  color: string;
  defaultPct: number;
}

export const CRITERIA: CriterionMeta[] = [
  {
    id: "c1",
    label: "C1",
    name: "Cultural affinity alignment",
    job: "How well the concept fits the audience's cultural style and taste.",
    color: "#3554a1",
    defaultPct: 35,
  },
  {
    id: "c2",
    label: "C2",
    name: "Differentiation",
    job: "How distinct the concept is from the other two on the board.",
    color: "#7d8da2",
    defaultPct: 20,
  },
  {
    id: "c3",
    label: "C3",
    name: "Market-context relevance",
    job: "How much the market context pulled from Qloo supports the concept.",
    color: "#baa2c5",
    defaultPct: 25,
  },
  {
    id: "c5",
    label: "C5",
    name: "Evidence coverage",
    job: "How much valid evidence each concept actually got.",
    color: "#292b43",
    defaultPct: 20,
  },
];
