/**
 * Rounding aligned on Python, deliberately and exactly.
 *
 * Python's `round()` applies round-half-to-even to the TRUE binary value of the double.
 * Neither JavaScript primitive reproduces that:
 *   - `Math.round` is half-away-from-zero: Math.round(2.5) === 3, Python gives 2.
 *   - `toFixed` agrees with Python on non-ties (verified on Node 24) but rounds exact ties
 *     away from zero: (2.5).toFixed(0) === '3' where Python gives 2.
 *   - multiplying by 10^d before rounding introduces a SECOND float error, which flips
 *     round(2.345, 2) from 2.35 to 2.34 — this was the actual bug in the first attempt.
 *
 * Deciding on the decimal expansion handles ties and non-ties uniformly, and does not depend on
 * the engine's toFixed being correctly rounded.
 *
 * So the decision is taken on the exact decimal expansion instead. Python is the parity oracle,
 * therefore TypeScript is the side that must conform — not the other way round.
 */
export function roundHalfEven(v: number, digits = 0): number {
  if (!Number.isFinite(v)) return v;
  const neg = v < 0;
  const a = Math.abs(v);
  const s = a.toPrecision(20);          // beyond a double's ~17 significant digits: exact enough
  if (s.includes('e')) return Number(a.toFixed(digits)) * (neg ? -1 : 1);

  const [int = '0', frac = ''] = s.split('.');
  const keep = frac.slice(0, digits).padEnd(digits, '0');
  const rest = frac.slice(digits);
  let n = BigInt(int + keep);

  const first = rest[0] ?? '0';
  const exactHalf = first === '5' && /^50*$/.test(rest);
  if (first > '5' || (first === '5' && !exactHalf)) n += 1n;        // strictly above the tie
  else if (exactHalf && n % 2n === 1n) n += 1n;                     // exact tie -> even neighbour

  const out = Number(n) / 10 ** digits;
  return neg ? -out : out;
}

export const round2 = (v: number): number => roundHalfEven(v, 2);

/** Share of a total, guarding the zero denominator the way analytics.py does. */
export const share = (part: number, total: number): number => (total ? part / total : 0);
