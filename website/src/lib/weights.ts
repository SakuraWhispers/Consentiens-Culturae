import { CRITERIA } from "./criteria";

export type CriteriaId = (typeof CRITERIA)[number]["id"];
export type Weights = Record<CriteriaId, number>; // integer percentages

export const ALL_IDS = CRITERIA.map((c) => c.id) as CriteriaId[];

/**
 * Proportional squeeze (human choice, 2026-10-20): the four sliders always
 * total exactly 100. Raising one slider lowers the other three in proportion
 * to their current sizes; lowering one raises the others the same way.
 *
 * Integer, largest-remainder allocation so displayed percentages stay clean
 * whole numbers at every step (slider step = 1).
 *
 * A request that cannot be satisfied (e.g. raising with nothing to squeeze)
 * leaves the weights untouched.
 */
export function squeezeWeights(
  current: Weights,
  id: CriteriaId,
  requested: number
): Weights {
  const clamped = Math.max(0, Math.min(100, Math.round(requested)));
  const delta = clamped - current[id];
  if (delta === 0) return current;

  const otherIds = ALL_IDS.filter((k) => k !== id);
  const others = otherIds.map((k) => current[k]);
  const othersTotal = others.reduce((a, b) => a + b, 0);

  // Raising: the freed budget must come out of the others.
  if (delta > 0) {
    if (othersTotal === 0) return current; // slider already at its ceiling
    const take = Math.min(delta, othersTotal); // clamp at the honest ceiling
    const target = othersTotal - take;
    const next = allocateProportionally(others, target, othersTotal);
    if (!next) return current;
    const out = { ...current, [id]: current[id] + take };
    otherIds.forEach((k, i) => {
      out[k] = next[i];
    });
    return out;
  }

  // Lowering: the freed budget is distributed to the others proportionally.
  const freed = current[id] - clamped;
  if (freed === 0) return current;
  if (othersTotal === 0) {
    // Escape hatch for the locked 100/0/0/0 state: proportionality is
    // undefined with an empty pool, so split the freed budget evenly.
    const even = allocateEven(otherIds.length, freed);
    const out = { ...current, [id]: clamped };
    otherIds.forEach((k, i) => {
      out[k] = even[i];
    });
    return out;
  }
  const target = othersTotal + freed; // cannot exceed 100 by construction
  const next = allocateProportionally(others, target, othersTotal);
  if (!next) return current;
  const out = { ...current, [id]: clamped };
  otherIds.forEach((k, i) => {
    out[k] = next[i];
  });
  return out;
}

/**
 * Even integer split of `target` across `count` slots (largest remainder).
 */
function allocateEven(count: number, target: number): number[] {
  const slots = Array<number>(count).fill(Math.floor(target / count));
  let assigned = slots.reduce((a, b) => a + b, 0);
  let i = 0;
  while (assigned < target) {
    slots[i % count] += 1;
    assigned += 1;
    i += 1;
  }
  return slots;
}

/**
 * Scale `parts` so they sum to `target`, keeping each part's share of the
 * original total `sourceTotal` (largest-remainder, integers only).
 * Returns null only when the scaling is mathematically impossible.
 */
function allocateProportionally(
  parts: number[],
  target: number,
  sourceTotal: number
): number[] | null {
  if (sourceTotal <= 0) return null;
  if (target < 0) return null;
  if (target === 0) return parts.map(() => 0);
  const exact = parts.map((p) => (p * target) / sourceTotal);
  const base = exact.map((e) => Math.floor(e));
  let assigned = base.reduce((a, b) => a + b, 0);
  // Hand leftover units to the largest fractional remainders.
  const remainders = exact
    .map((e, i) => ({ i, frac: e - Math.floor(e) }))
    .sort((a, b) => b.frac - a.frac);
  let r = 0;
  while (assigned < target) {
    base[remainders[r % base.length].i] += 1;
    assigned += 1;
    r += 1;
  }
  // Floating-point safety: shave any overflow from the largest parts.
  let gi = 0;
  while (assigned > target) {
    if (base[gi % base.length] > 0) {
      base[gi % base.length] -= 1;
      assigned -= 1;
    }
    gi += 1;
    if (gi > base.length * 2) break; // paranoia stop
  }
  return base;
}

/** Total display helper (always 100 after a squeeze; never negative). */
export function weightsTotal(w: Weights): number {
  return ALL_IDS.reduce((sum, k) => sum + w[k], 0);
}
