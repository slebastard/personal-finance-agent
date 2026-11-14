/**
 * Shared contract between the Nest server and the React client.
 *
 * Conventions carried over from `pfa report --json`, deliberately unchanged:
 *   - amounts are EUR, rounded to 2 decimals
 *   - percentages are FRACTIONS (0.442), never percentages (44.2)
 *   - dates are `YYYY-MM-DD`
 */

export type Envelope =
  | 'livret_a' | 'ldds' | 'lep' | 'livret_other' | 'pea' | 'pea_pme'
  | 'assurance_vie' | 'per' | 'cto' | 'current' | 'crypto' | 'real_estate' | 'other';

export type HoldingKind =
  | 'etf' | 'stock' | 'fund' | 'fonds_euros' | 'bond' | 'cash' | 'scpi' | 'crypto' | 'other';

export type Dimension = 'asset_class' | 'region' | 'country' | 'sector';

/** `pct` is a fraction of the relevant total. */
export interface BucketRow { bucket: string; value: number; pct: number }

export interface MetaDto {
  snapshots: string[];
  latestAsOf: string | null;
  rulesVerifiedOn: string;
  transactionRange: { from: string; to: string } | null;
  lastRun: { runId: string; kind: string; status: string; startedAt: string | null } | null;
  /** `display_name` from the private profile/manual_inputs.json; null when not set. */
  userName: string | null;
}

export interface PositionDto {
  key: string; accountId: string; accountName: string; envelope: Envelope;
  institution: string; isin: string | null; name: string; kind: HoldingKind;
  quantity: number | null; unitPrice: number | null; value: number;
  costBasis: number | null; pnl: number | null; pnlPct: number | null;
  weight: number; ter: number | null; hasInstrumentData: boolean;
}

export interface AccountDto {
  id: string; name: string; envelope: Envelope; institution: string; balance: number;
  unrealizedPnl: number | null; unrealizedPnlPct: number | null;
  ageYears: number | null; contractFee: number | null;
}

export interface PerimeterChangeDto {
  gone: { id: string; name: string | null; envelope: string | null; institution: string | null;
          lastBalance: number; lastSeen: string; closedOn: string | null;
          reason: string | null; transferredTo: string | null }[];
  new: { id: string; name: string | null; envelope: string | null; balance: number }[];
  note: string | null;
}

export interface ReportDto {
  asOf: string; previousAsOf: string | null;
  totalValue: number; changeVsPrevious: number | null;
  envelopes: BucketRow[];
  accounts: AccountDto[];
  positions: PositionDto[];
  exposure: {
    totalValue: number; equityValue: number;
    assetClass: BucketRow[]; region: BucketRow[]; country: BucketRow[]; sector: BucketRow[];
    coverage: { geoPct: number; sectorPct: number };
  };
  driftVsTargets: Partial<Record<Dimension, { bucket: string; target: number; actual: number;
                                              drift: number }[]>>;
  concentration: { nPositions: number; top1Pct: number; top5Pct: number; hhi: number };
  fees: { fundFeesEurPerYear: number; weightedTerOnCovered: number; terCoveragePct: number;
          wrapperFeesEurPerYear: number };
  envelopeChecks: { account: string; check: string; value: number | null; limit: number | null;
                    headroom?: number | null; ok?: boolean; rate?: number; note?: string }[];
  perimeterChanges: PerimeterChangeDto;
  receivables: ReceivablesDto;
  history: { asOf: string; total: number }[];
}

/** One row of a fund's own composition: weight in the fund, and euros that represents for me. */
export interface FundRow { bucket: string; weight: number; eur: number }

/** The per-line page: sourced fiche + my position + look-through composition + value history. */
export interface InstrumentDto {
  asOf: string; isin: string; name: string; kind: HoldingKind;
  hasInstrumentData: boolean;
  issuer: string | null; index: string | null; replication: string | null;
  ter: number | null; sri: number | null; peaEligible: boolean | null;
  notes: string | null; fetchedAt: string | null;
  sources: { url: string; fetched_at?: string }[];
  /** Published by the source, net of fees — NOT my performance on the line. */
  performance: { '1y'?: number; '3y_annualized'?: number; '5y_annualized'?: number };
  position: {
    value: number; weight: number; costBasis: number | null;
    pnl: number | null; pnlPct: number | null; feeEurPerYear: number | null;
    lines: { accountName: string; envelope: Envelope; quantity: number | null;
             unitPrice: number | null; costBasis: number | null; value: number;
             pnl: number | null }[];
  };
  composition: {
    equityValue: number;
    assetClass: FundRow[]; country: FundRow[]; region: FundRow[]; sector: FundRow[];
    /** Portfolio-wide equity average: the reference mark drawn on the bars. */
    portfolioRegion: { bucket: string; pct: number }[];
    portfolioSector: { bucket: string; pct: number }[];
  };
  history: { asOf: string; value: number; quantity: number | null; unitPrice: number | null }[];
}

/** Money handed over that comes back (rental deposit). Shown BESIDE the Finary total, never in it. */
export interface ReceivablesDto {
  items: {
    id: string; label: string; kind: string | null;
    paidOn: string | null; paid: number | null;
    expectedRefund: number | null; expectedRetention: number | null;
    expectedRefundDate: string | null; note: string | null;
  }[];
  totalPaid: number;
  totalExpectedRefund: number;
  totalWithReceivables: number;
}

// --------------------------------------------------------------------------- companies (Eulerpool)

export const HEALTH_METRICS = [
  'roe', 'roic', 'operating_margin', 'net_margin', 'net_debt_to_ebit',
  'revenue_growth_3y_pa', 'aaqs_score', 'esg_total',
] as const;
export type HealthMetric = (typeof HEALTH_METRICS)[number];

/** Weighted statistics over the constituents that HAVE the metric (missing is never zero). */
export interface WeightedStatsDto {
  mean: number | null; p25: number | null; p50: number | null; p75: number | null;
  /** Share of the reference weight for which the metric is known. */
  coverage: number; n: number;
}

/** The few company fields a table row needs. Fractions throughout (0.25 = 25 %). */
export interface CompanySummaryDto {
  covered: boolean; sector: string | null; country: string | null;
  marketCapM: number | null; currency: string | null; flags: number;
  roe: number | null; roic: number | null; operatingMargin: number | null; netMargin: number | null;
  netDebtToEbit: number | null; revenueGrowth3yPa: number | null; aaqsScore: number | null;
  esgTotal: number | null; piotroski: number | null;
}

export interface ConstituentDto extends CompanySummaryDto {
  rank: number; isin: string; name: string; ticker: string | null;
  /** Weight in the fund (fraction). */
  weight: number;
  /** Euros of MY money this represents: my equity in the fund x weight. */
  eur: number;
}

export interface QualityBucketDto { bucket: string; weight: number }

export interface FundCompaniesDto {
  asOf: string; fundIsin: string; fundName: string;
  covered: boolean; reason?: string;
  proxy: {
    kind: string | null; isin: string | null; index: string | null; note?: string | null;
    crosscheck?: { sectorMaxGapPts: number | null; countryMaxGapPts: number | null;
                   warn: boolean; thresholdPts: number } | null;
  };
  holdingsAsOf?: string | null; fetchedAt?: string | null;
  nTotal?: number; topN?: number; coverageTop?: number;
  equityValue?: number; positionValue?: number;
  constituents?: ConstituentDto[];
  companiesWithData?: number; weightWithData?: number;
  health?: Record<HealthMetric, WeightedStatsDto>;
  qualityDistribution?: QualityBucketDto[];
}

export interface LookthroughCompanyDto extends CompanySummaryDto {
  isin: string; name: string; ticker: string | null;
  exposureEur: number; pctOfEquity: number; nFunds: number;
  funds: { fundIsin: string; fundName: string; weight: number; eur: number }[];
}

export interface LookthroughDto {
  asOf: string; equityValue: number; identifiedEur: number; identifiedPct: number;
  funds: { isin: string; name: string; colorSlot: number | null; index: string | null;
           proxyIsin: string | null; equityValue: number; coverageTop: number;
           identifiedEur: number }[];
  fundsNotCovered: { isin: string; name: string; equityValue: number; reason: string }[];
  companies: LookthroughCompanyDto[]; nCompanies: number;
  /** Companies held through at least two of my funds. */
  nShared: number;
  top10PctOfEquity: number; top10PctOfIdentified: number;
  overlaps: { a: string; b: string; common: number; overlapWeight: number }[];
  quality: Record<HealthMetric, WeightedStatsDto>;
  qualityDistribution: QualityBucketDto[];
}

/** The vendor record exactly as stored (snake_case): data/companies/<ISIN>.json. */
export interface CompanyRecord {
  isin: string; name: string; ticker: string | null; covered: boolean;
  country: string | null; currency: string | null; sector: string | null; industry: string | null;
  employees: number | null; ipo: string | null; market_cap_m: number | null; description: string | null;
  metrics: Record<string, number | null>;
  margins: Record<'gross' | 'ebit' | 'net', Record<'1y' | '3y' | '5y' | '10y', number | null>>;
  growth: Record<'revenue' | 'ebit' | 'income', Record<string, number | null>>;
  history: { year: number; period: string | null; revenue: number | null; ebit: number | null;
             net_income: number | null; eps: number | null; roe: number | null; roic: number | null }[];
  quality: {
    aaqs: Record<string, number | null>;
    piotroski: { score: number | null; period_date: string | null };
    altman: { z: number | null; zone: string | null };
  };
  esg: { environment: number | null; social: number | null; governance: number | null;
         total: number | null; co2: Record<string, number | null>;
         exposures: Record<string, boolean> } | null;
  vendor_models: Record<string, number | null> | null;
  flags: { field: string; reason: string }[];
  sources: { endpoint: string; fetched_at: string; ok: boolean }[];
  fetched_at: string;
}

export interface CompanyDto {
  asOf: string | null; company: CompanyRecord;
  held: { exposureEur: number; pctOfEquity: number;
          funds: { fundIsin: string; fundName: string; weight: number; eur: number }[] } | null;
}

export interface GlossaryEntry {
  label: string; formula: string; high: string; low: string; caveat: string; source: string;
}

export interface LearnPromptDto {
  id: string; title: string; question: string; why: string;
  evidence: string;
  reading: { label: string; url: string | null }[];
  learn: { rung: number; command: string };
}

// --------------------------------------------------------------------------- flows

export type FlowNature =
  'income' | 'spending' | 'internal' | 'refund' | 'provisional' | 'unclassified';

export const FLOW_NATURES: FlowNature[] =
  ['income', 'spending', 'internal', 'refund', 'provisional', 'unclassified'];

export interface FlowsDto {
  from: string; to: string; months: number;
  byNature: Record<FlowNature, { amount: number; count: number }>;
  byCategory: {
    category: string; amount: number; count: number;
    subcategories: { subcategory: string; amount: number; count: number }[];
  }[];
  monthly: { month: string; income: number; spending: number; refund: number;
             internal: number; provisional: number; unclassified: number; net: number }[];
  net: number;
  savingsRate: number | null;
  quality: {
    /** Σ flows − Δ balance. Validates COMPLETENESS, not classification: reclassifying a row
     *  does not change the sum. `null` when the window is not bounded by two snapshots. */
    reconciliationGap: number | null;
    unclassifiedAmountPct: number;
    unclassifiedCount: number;
    /** Two consecutive near-zero income months. One alone is a month-end payroll slipping. */
    monthsWithSuspiciousIncome: string[];
  };
}

export interface TransactionDto {
  id: string; date: string; label: string; account: string; accountId: string | null;
  amount: number; category: string | null; subcategory: string | null;
  flow: FlowNature; ruleId: string | null; note: string | null;
}

export interface ReviewCandidateDto extends Omit<TransactionDto, 'accountId' | 'account' | 'note'> {
  why: string[];
}

export interface SavingsCapacityDto {
  from: string; to: string; months: number;
  monthlyIncome: number; monthlySpending: number; monthlyNet: number;
  savingsRate: number | null;
  caveats: string[];
}

export interface ApiError { error: { code: string; message: string; details?: unknown } }
