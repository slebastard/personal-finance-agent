import { Injectable } from '@nestjs/common';
import type {
  CompanyDto, CompanyRecord, CompanySummaryDto, ConstituentDto, FundCompaniesDto, HealthMetric,
  LookthroughCompanyDto, LookthroughDto, WeightedStatsDto,
} from '@pfa/contracts';
import { HEALTH_METRICS } from '@pfa/contracts';
import { ReportService, type Pos } from '../report/report.service';
import { ReferenceService } from '../reference/reference.service';
import { EnrichmentRepository, type HoldingsDoc } from './enrichment.repository';
import { round2 } from '../common/money';
import { notFound } from '../common/http-error.filter';

/**
 * Mirrors `pfa/lookthrough.py`, formula for formula (definitions in its module docstring). Python
 * is the oracle: `parity.test.ts` compares every figure served here to `pfa lookthrough|fund-companies
 * |company --json`. Nothing is computed in the client.
 */

const METRIC_PATHS: Record<HealthMetric, string[]> = {
  roe: ['metrics', 'roe'], roic: ['metrics', 'roic'],
  operating_margin: ['metrics', 'operating_margin'], net_margin: ['metrics', 'net_margin'],
  net_debt_to_ebit: ['quality', 'aaqs', 'net_debt_to_ebit'],
  revenue_growth_3y_pa: ['growth', 'revenue', 'pa_3y'],
  aaqs_score: ['quality', 'aaqs', 'score'], esg_total: ['esg', 'total'],
};
const QUALITY_BUCKETS = ['0–2', '2–4', '4–6', '6–8', '8–10'];

const dig = (doc: unknown, path: string[]): number | null => {
  let cur: any = doc;
  for (const k of path) {
    if (cur === null || typeof cur !== 'object') return null;
    cur = cur[k];
  }
  return typeof cur === 'number' && Number.isFinite(cur) ? cur : null;
};

export const qualityBucket = (score: number): number => Math.min(Math.floor(score / 2), 4);

export function weightedStats(pairs: [number, number | null][], denominator?: number): WeightedStatsDto {
  const have = pairs.filter(([w, x]) => x !== null && w > 0)
    .map(([w, x]) => [x as number, w] as [number, number]).sort((a, b) => a[0] - b[0]);
  const totalAll = denominator !== undefined ? denominator : pairs.reduce((s, [w]) => s + w, 0);
  const wHave = have.reduce((s, [, w]) => s + w, 0);
  if (!have.length || wHave <= 0) return { mean: null, p25: null, p50: null, p75: null, coverage: 0, n: 0 };
  const q = (p: number): number => {
    const target = p * wHave;
    let cum = 0;
    for (const [x, w] of have) {
      cum += w;
      if (cum >= target - 1e-12) return x;
    }
    return have[have.length - 1]![0];
  };
  return {
    mean: have.reduce((s, [x, w]) => s + w * x, 0) / wHave,
    p25: q(0.25), p50: q(0.5), p75: q(0.75),
    coverage: totalAll ? wHave / totalAll : 0, n: have.length,
  };
}

const EMPTY_SUMMARY: CompanySummaryDto = {
  covered: false, sector: null, country: null, marketCapM: null, currency: null, flags: 0,
  roe: null, roic: null, operatingMargin: null, netMargin: null, netDebtToEbit: null,
  revenueGrowth3yPa: null, aaqsScore: null, esgTotal: null, piotroski: null,
};

/** Mirrors `lookthrough._not_covered_reason`. */
const notCoveredReason = (cfg: Record<string, any>): string =>
  (!cfg.kind || ['none', 'to_find'].includes(cfg.kind))
    ? (cfg.note ?? 'absent de profile/etf_proxies.json')
    : 'pas encore enrichi : lance `python3 -m pfa enrich`';

@Injectable()
export class EnrichmentService {
  constructor(
    private readonly report: ReportService,
    private readonly repo: EnrichmentRepository,
    private readonly ref: ReferenceService,
  ) {}

  /** The few fields a table row needs, plus the raw metric values keyed like HEALTH_METRICS. */
  private summary(rec: CompanyRecord | null): { dto: CompanySummaryDto; m: Record<HealthMetric, number | null> } {
    if (!rec) {
      return { dto: EMPTY_SUMMARY, m: Object.fromEntries(HEALTH_METRICS.map((k) => [k, null])) as Record<HealthMetric, number | null> };
    }
    const m = Object.fromEntries(
      HEALTH_METRICS.map((k) => [k, dig(rec, METRIC_PATHS[k])])) as Record<HealthMetric, number | null>;
    return {
      m,
      dto: {
        covered: rec.covered ?? true, sector: rec.sector ?? null, country: rec.country ?? null,
        marketCapM: rec.market_cap_m ?? null, currency: rec.currency ?? null,
        flags: (rec.flags ?? []).length,
        roe: m.roe, roic: m.roic, operatingMargin: m.operating_margin, netMargin: m.net_margin,
        netDebtToEbit: m.net_debt_to_ebit, revenueGrowth3yPa: m.revenue_growth_3y_pa,
        aaqsScore: m.aaqs_score, esgTotal: m.esg_total,
        piotroski: dig(rec, ['quality', 'piotroski', 'score']),
      },
    };
  }

  private fundEquity(pos: Pos[], isin: string): { value: number; eq: number; name: string | null } {
    const lines = pos.filter((p) => p.isin === isin);
    if (!lines.length) return { value: 0, eq: 0, name: null };
    const [ac] = this.report.assetClasses(lines[0]!);
    const value = lines.reduce((s, p) => s + p.value, 0);
    return { value, eq: value * (ac['equity'] ?? 0), name: lines[0]!.name };
  }

  private heldFundsWithEquity(pos: Pos[]) {
    const seen = new Set<string>();
    const out: { isin: string; name: string; equity: number }[] = [];
    for (const p of pos) {
      if (p.isin && ['etf', 'fund'].includes(p.kind) && !seen.has(p.isin)) {
        seen.add(p.isin);
        const f = this.fundEquity(pos, p.isin);
        if (f.eq > 0) out.push({ isin: p.isin, name: f.name!, equity: f.eq });
      }
    }
    return out;
  }

  fundCompanies(isin: string, asOfParam?: string): FundCompaniesDto {
    const asOf = this.report.resolveAsOf(asOfParam);
    const pos = this.report.positions(asOf);
    const { value, eq, name } = this.fundEquity(pos, isin);
    if (name === null) throw notFound('NOT_HELD', `aucune ligne ${isin} détenue au ${asOf}`);
    const cfg = this.ref.etfProxies[isin] ?? {};
    const doc = this.repo.holdings(isin);
    if (!doc) {
      return { asOf, fundIsin: isin, fundName: name, covered: false,
               reason: notCoveredReason(cfg),
               proxy: { kind: cfg.kind ?? null, isin: cfg.holdings_from ?? null, index: cfg.index ?? null } };
    }
    const constituents: ConstituentDto[] = [];
    const pairs = Object.fromEntries(HEALTH_METRICS.map((k) => [k, [] as [number, number | null][]])) as
      Record<HealthMetric, [number, number | null][]>;
    const dist = [0, 0, 0, 0, 0];
    for (const c of doc.constituents) {
      const rec = this.repo.company(c.isin);
      const { dto, m } = this.summary(rec);
      constituents.push({ rank: c.rank, isin: c.isin, name: rec?.name ?? c.name, ticker: c.ticker ?? null,
                          weight: c.weight, eur: round2(eq * c.weight), ...dto });
      for (const k of HEALTH_METRICS) pairs[k].push([c.weight, m[k]]);
      if (m.aaqs_score !== null) dist[qualityBucket(m.aaqs_score)]! += c.weight;
    }
    const cov = doc.coverage_top;
    const health = Object.fromEntries(
      HEALTH_METRICS.map((k) => [k, weightedStats(pairs[k], cov)])) as Record<HealthMetric, WeightedStatsDto>;
    const cc = doc.crosscheck;
    return {
      asOf, fundIsin: isin, fundName: name, covered: true,
      proxy: { kind: doc.kind, isin: doc.proxy_isin, index: doc.index ?? null, note: cfg.note ?? null,
               crosscheck: cc ? { sectorMaxGapPts: cc.sector_max_gap_pts, countryMaxGapPts: cc.country_max_gap_pts,
                                  warn: cc.warn, thresholdPts: cc.threshold_pts } : null },
      holdingsAsOf: doc.as_of, fetchedAt: doc.fetched_at,
      nTotal: doc.n_total, topN: doc.top_n, coverageTop: cov,
      equityValue: round2(eq), positionValue: round2(value),
      constituents,
      companiesWithData: constituents.filter((r) => r.covered).length,
      weightWithData: constituents.filter((r) => r.covered).reduce((s, r) => s + r.weight, 0),
      health,
      qualityDistribution: QUALITY_BUCKETS.map((bucket, i) => ({ bucket, weight: dist[i]! })),
    };
  }

  lookthrough(asOfParam?: string, limit = 200): LookthroughDto {
    const asOf = this.report.resolveAsOf(asOfParam);
    const pos = this.report.positions(asOf);
    const equityTotal = this.report.exposure(asOf).equityValue;
    const proxies = this.ref.etfProxies;
    const funds: LookthroughDto['funds'] = [];
    const notCovered: LookthroughDto['fundsNotCovered'] = [];
    const holdings = new Map<string, Map<string, number>>();
    const companies = new Map<string, { isin: string; name: string; ticker: string | null; raw: number;
                                         funds: LookthroughCompanyDto['funds'] }>();
    const held = this.heldFundsWithEquity(pos);
    const docs = new Map<string, HoldingsDoc>();
    for (const f of held) {
      const doc = this.repo.holdings(f.isin);
      const cfg = proxies[f.isin] ?? {};
      if (!doc) {
        notCovered.push({ isin: f.isin, name: f.name, equityValue: round2(f.equity),
                          reason: notCoveredReason(cfg) });
        continue;
      }
      docs.set(f.isin, doc);
      holdings.set(f.isin, new Map(doc.constituents.map((c) => [c.isin, c.weight])));
      funds.push({ isin: f.isin, name: f.name, colorSlot: cfg.color_slot ?? null, index: doc.index ?? null,
                   proxyIsin: doc.proxy_isin, equityValue: round2(f.equity), coverageTop: doc.coverage_top,
                   identifiedEur: round2(f.equity * doc.coverage_top) });
      for (const c of doc.constituents) {
        const eur = f.equity * c.weight;
        const e = companies.get(c.isin) ?? { isin: c.isin, name: c.name, ticker: c.ticker ?? null, raw: 0, funds: [] };
        e.raw += eur;
        e.funds.push({ fundIsin: f.isin, fundName: f.name, weight: c.weight, eur: round2(eur) });
        companies.set(c.isin, e);
      }
    }
    const identified = held.filter((f) => holdings.has(f.isin))
      .reduce((s, f) => s + f.equity * docs.get(f.isin)!.coverage_top, 0);
    const sorted = [...companies.values()].sort((a, b) => b.raw - a.raw);
    const rows: LookthroughCompanyDto[] = sorted.map((e) => {
      const rec = this.repo.company(e.isin);
      return { isin: e.isin, name: rec?.name ?? e.name, ticker: e.ticker,
               exposureEur: round2(e.raw), pctOfEquity: equityTotal ? e.raw / equityTotal : 0,
               funds: e.funds, nFunds: e.funds.length, ...this.summary(rec).dto };
    });
    const top10 = sorted.slice(0, 10).reduce((s, e) => s + e.raw, 0);

    const overlaps: LookthroughDto['overlaps'] = [];
    const ids = [...holdings.keys()].sort();
    for (let i = 0; i < ids.length; i += 1) {
      for (let j = i + 1; j < ids.length; j += 1) {
        const a = holdings.get(ids[i]!)!; const b = holdings.get(ids[j]!)!;
        const common = [...a.keys()].filter((k) => b.has(k));
        if (common.length) {
          overlaps.push({ a: ids[i]!, b: ids[j]!, common: common.length,
                          overlapWeight: common.reduce((s, k) => s + Math.min(a.get(k)!, b.get(k)!), 0) });
        }
      }
    }
    const pairs = Object.fromEntries(HEALTH_METRICS.map((k) => [k, [] as [number, number | null][]])) as
      Record<HealthMetric, [number, number | null][]>;
    const dist = [0, 0, 0, 0, 0];
    for (const e of companies.values()) {
      const { m } = this.summary(this.repo.company(e.isin));
      for (const k of HEALTH_METRICS) pairs[k].push([e.raw, m[k]]);
      if (m.aaqs_score !== null) dist[qualityBucket(m.aaqs_score)]! += e.raw;
    }
    return {
      asOf, equityValue: round2(equityTotal), identifiedEur: round2(identified),
      identifiedPct: equityTotal ? identified / equityTotal : 0,
      funds, fundsNotCovered: notCovered, companies: rows.slice(0, limit), nCompanies: rows.length,
      nShared: [...companies.values()].filter((e) => e.funds.length >= 2).length,
      top10PctOfEquity: equityTotal ? top10 / equityTotal : 0,
      top10PctOfIdentified: identified ? top10 / identified : 0,
      overlaps,
      quality: Object.fromEntries(
        HEALTH_METRICS.map((k) => [k, weightedStats(pairs[k], identified)])) as Record<HealthMetric, WeightedStatsDto>,
      qualityDistribution: QUALITY_BUCKETS.map((bucket, i) => ({ bucket, weight: identified ? dist[i]! / identified : 0 })),
    };
  }

  company(isin: string, asOfParam?: string): CompanyDto {
    const rec = this.repo.company(isin);
    if (!rec) throw notFound('NO_COMPANY', `aucune fiche pour ${isin} : lance \`pfa enrich\``);
    const lt = this.lookthrough(asOfParam, 10_000);
    const held = lt.companies.find((c) => c.isin === isin);
    return { asOf: lt.asOf, company: rec,
             held: held ? { exposureEur: held.exposureEur, pctOfEquity: held.pctOfEquity, funds: held.funds } : null };
  }
}
