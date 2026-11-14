/**
 * Parity between the TypeScript read path and the Python oracle.
 *
 * This is the counterpart to accepting a duplicated implementation: `pfa/analytics.py` and
 * `pfa/flows.py` remain the reference, and any divergence in the server fails here rather than
 * silently reaching the dashboard.
 */
import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

// Exercised over real HTTP rather than by importing the services: it tests the surface the client
// actually consumes, and sidesteps bundling a Node built-in (node:sqlite) into the test runner.
const ROOT = resolve(__dirname, '../../..');
const DB = resolve(ROOT, 'data/finance.db');
const PORT = 3999;
const BASE = `http://127.0.0.1:${PORT}/api/v1`;
let server: ChildProcess | undefined;

const EUR_TOLERANCE = 0.01;      // one cent
const FRACTION_TOLERANCE = 1e-6;

const py = (...args: string[]) =>
  JSON.parse(execFileSync('python3', ['-m', 'pfa', ...args],
    { cwd: ROOT, encoding: 'utf-8', maxBuffer: 64 * 1024 * 1024 }));

const ts = async <T>(path: string): Promise<T> => {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${path} -> HTTP ${r.status}`);
  return r.json() as Promise<T>;
};

const hasDb = existsSync(DB);

beforeAll(async () => {
  if (!hasDb) return;
  server = spawn('node', [resolve(__dirname, '../dist/main.js')],
    { env: { ...process.env, PFA_PORT: String(PORT) }, stdio: 'ignore' });
  for (let i = 0; i < 60; i += 1) {
    try {
      if ((await fetch(`${BASE}/health`)).ok) return;
    } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error('le serveur ne répond pas');
});

afterAll(() => { server?.kill(); });

describe.skipIf(!hasDb)('flows parity', () => {
  const expected = hasDb ? py('flows', '--json') : null;
  const get = () => ts<any>(`/flows?from=${expected.from}&to=${expected.to}`);

  it('agrees on every flow nature, to the cent', async () => {
    const got = await get();
    for (const [nature, v] of Object.entries<any>(expected.by_nature)) {
      expect(got.byNature[nature as keyof typeof got.byNature].amount)
        .toBeCloseTo(v.amount, 2);
      expect(got.byNature[nature as keyof typeof got.byNature].count).toBe(v.count);
    }
  });

  it('agrees on the net and the savings rate', async () => {
    const got = await get();
    expect(Math.abs(got.net - expected.net)).toBeLessThanOrEqual(EUR_TOLERANCE);
    if (expected.savings_rate !== null) {
      expect(Math.abs(got.savingsRate! - expected.savings_rate))
        .toBeLessThanOrEqual(FRACTION_TOLERANCE);
    }
  });

  it('agrees on the reconciliation gap — the completeness check', async () => {
    const got = await get();
    expect(got.quality.reconciliationGap).toBe(expected.quality.reconciliation_gap);
  });

  it('agrees on the category and monthly breakdowns', async () => {
    const got = await get();
    expect(got.byCategory.length).toBe(expected.by_category.length);
    expect(got.monthly.length).toBe(expected.monthly.length);
    const byName = new Map(got.byCategory.map((c) => [c.category, c.amount]));
    for (const c of expected.by_category) {
      expect(byName.get(c.category)).toBeCloseTo(c.amount, 2);
    }
  });

  it('agrees on suspicious-income months', async () => {
    const got = await get();
    expect(got.quality.monthsWithSuspiciousIncome)
      .toEqual(expected.quality.months_with_suspicious_income);
  });
});

describe.skipIf(!hasDb)('report parity', () => {
  const expected = hasDb ? py('report', '--json') : null;
  const get = () => ts<any>('/report');

  it('agrees on the total and the delta', async () => {
    const got = await get();
    expect(Math.abs(got.totalValue - expected.total_value)).toBeLessThanOrEqual(EUR_TOLERANCE);
    expect(got.asOf).toBe(expected.as_of);
    expect(got.previousAsOf).toBe(expected.previous_as_of);
    if (expected.change_vs_previous !== null) {
      expect(Math.abs(got.changeVsPrevious! - expected.change_vs_previous))
        .toBeLessThanOrEqual(EUR_TOLERANCE);
    }
  });

  it('agrees on the look-through exposure, dimension by dimension', async () => {
    const got = await get();
    const pairs: [any[], any[]][] = [
      [got.exposure.assetClass, expected.exposure.asset_class],
      [got.exposure.region, expected.exposure.region],
      [got.exposure.sector, expected.exposure.sector],
      [got.exposure.country, expected.exposure.country],
    ];
    for (const [ours, theirs] of pairs) {
      const mine = new Map(ours.map((r) => [r.bucket, r]));
      expect(ours.length).toBe(theirs.length);
      for (const r of theirs) {
        const m = mine.get(r.bucket);
        expect(m, `bucket ${r.bucket} manquant`).toBeDefined();
        expect(Math.abs(m!.value - r.value)).toBeLessThanOrEqual(EUR_TOLERANCE);
        expect(Math.abs(m!.pct - r.pct)).toBeLessThanOrEqual(FRACTION_TOLERANCE);
      }
    }
    expect(Math.abs(got.exposure.equityValue - expected.exposure.equity_value))
      .toBeLessThanOrEqual(EUR_TOLERANCE);
  });

  it('agrees on fees and concentration', async () => {
    const got = await get();
    expect(Math.abs(got.fees.fundFeesEurPerYear - expected.fees.fund_fees_eur_per_year))
      .toBeLessThanOrEqual(EUR_TOLERANCE);
    expect(Math.abs(got.fees.weightedTerOnCovered - expected.fees.weighted_ter_on_covered))
      .toBeLessThanOrEqual(FRACTION_TOLERANCE);
    expect(got.concentration.nPositions).toBe(expected.concentration.n_positions);
    expect(Math.abs(got.concentration.top5Pct - expected.concentration.top5_pct))
      .toBeLessThanOrEqual(FRACTION_TOLERANCE);
  });

  it('agrees that a closed account left the perimeter', async () => {
    const got = await get();
    expect(got.perimeterChanges.gone.map((g) => g.id).sort())
      .toEqual(expected.perimeter_changes.gone.map((g: any) => g.id).sort());
  });

  it('agrees on receivables, which sit beside the Finary total and never in it', async () => {
    const got = await get();
    const r = expected.receivables;
    expect(got.receivables.items.map((i) => [i.id, i.paid, i.expectedRefund, i.expectedRetention]))
      .toEqual(r.items.map((i: any) => [i.id, i.paid, i.expected_refund, i.expected_retention]));
    expect(got.receivables.totalExpectedRefund).toBe(r.total_expected_refund);
    expect(got.receivables.totalWithReceivables).toBe(r.total_with_receivables);
    expect(got.totalValue).toBe(expected.total_value);          // untouched by the receivable
  });
});

describe.skipIf(!hasDb)('instrument page parity', () => {
  const held: string[] = hasDb
    ? [...new Set<string>(py('report', '--json').positions
        .filter((p: any) => p.isin).map((p: any) => p.isin))]
    : [];

  const near = (a: number | null, b: number | null, tol: number) => {
    if (a === null || b === null) { expect(a).toBe(b); return; }
    expect(Math.abs(a - b)).toBeLessThanOrEqual(tol);
  };
  const rowsMatch = (got: any[], exp: any[]) => {
    expect(got.map((r) => r.bucket)).toEqual(exp.map((r) => r.bucket));
    got.forEach((r, i) => {
      near(r.eur, exp[i].eur, EUR_TOLERANCE);
      near(r.weight, exp[i].weight, FRACTION_TOLERANCE);
    });
  };

  it('has at least one held ISIN to compare', () => { expect(held.length).toBeGreaterThan(0); });

  it('agrees with Python on position, composition and history for every held ISIN', async () => {
    for (const isin of held) {
      const exp = py('instrument', isin, '--json');
      const got = await ts<any>(`/instruments/${isin}`);
      near(got.position.value, exp.position.value, EUR_TOLERANCE);
      near(got.position.pnl, exp.position.pnl, EUR_TOLERANCE);
      near(got.position.feeEurPerYear, exp.position.fee_eur_per_year, EUR_TOLERANCE);
      near(got.position.weight, exp.position.weight, FRACTION_TOLERANCE);
      near(got.composition.equityValue, exp.composition.equity_value, EUR_TOLERANCE);
      rowsMatch(got.composition.assetClass, exp.composition.asset_class);
      rowsMatch(got.composition.country, exp.composition.country);
      rowsMatch(got.composition.region, exp.composition.region);
      rowsMatch(got.composition.sector, exp.composition.sector);
      expect(got.history.map((h: any) => h.asOf)).toEqual(exp.history.map((h: any) => h.as_of));
      got.history.forEach((h: any, i: number) => near(h.value, exp.history[i].value, EUR_TOLERANCE));
      expect(got.performance).toEqual(exp.performance);
      expect(got.sources.map((x: any) => x.url)).toEqual(exp.sources.map((x: any) => x.url));
      expect(got.peaEligible).toBe(exp.pea_eligible);
    }
  });

  it('answers 404 for an ISIN I do not hold', async () => {
    const r = await fetch(`${BASE}/instruments/XX0000000000`);
    expect(r.status).toBe(404);
  });
});
