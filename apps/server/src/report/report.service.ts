import { Injectable } from '@nestjs/common';
import type { AccountDto, BucketRow, Envelope, HoldingKind, InstrumentDto, PositionDto,
  ReportDto }
  from '@pfa/contracts';
import { ReportRepository, HoldingRow } from './report.repository';
import { ReferenceService } from '../reference/reference.service';
import { Taxonomy } from './taxonomy';
import { round2, share } from '../common/money';
import { notFound } from '../common/http-error.filter';

const UNCLASSIFIED = 'Unclassified';
/** etf/fund are assumed equity until a /lookup says otherwise — and the assumption is flagged. */
const DEFAULT_ASSET_CLASS: Record<string, string> = {
  stock: 'equity', cash: 'cash', fonds_euros: 'fonds_euros', bond: 'bond',
  scpi: 'real_estate', crypto: 'crypto', other: 'other', etf: 'equity', fund: 'equity',
};

export interface Pos extends PositionDto { breakdowns: Record<string, Record<string, number>> }

@Injectable()
export class ReportService {
  private readonly tax: Taxonomy;

  constructor(private readonly repo: ReportRepository, ref: ReferenceService) {
    this.tax = new Taxonomy(ref);
    this.ref = ref;
  }
  private readonly ref: ReferenceService;

  resolveAsOf(asOf?: string): string {
    const dates = this.repo.snapshotDates();
    if (!dates.length) {
      throw notFound('NO_SNAPSHOT', 'aucun snapshot chargé — lance `python3 -m pfa sync`');
    }
    if (!asOf) return dates.at(-1)!;
    if (!dates.includes(asOf)) {
      throw notFound('SNAPSHOT_NOT_FOUND', `aucun snapshot au ${asOf}`, { available: dates });
    }
    return asOf;
  }

  positions(asOf: string): Pos[] {
    const rows = this.repo.holdings(asOf);
    const instruments = this.repo.instruments();
    const total = rows.reduce((s, r) => s + r.value, 0) || 1;
    return rows.map((r) => {
      const meta = r.isin ? instruments.get(r.isin) : undefined;
      const pnl = r.cost_basis ? round2(r.value - r.cost_basis) : null;
      return {
        key: r.key, accountId: r.account_id, accountName: r.account_name,
        envelope: r.envelope as Envelope, institution: r.institution,
        isin: r.isin, name: r.name, kind: r.kind as HoldingKind,
        quantity: r.quantity, unitPrice: r.unit_price, value: r.value,
        costBasis: r.cost_basis, pnl,
        pnlPct: pnl !== null && r.cost_basis ? pnl / r.cost_basis : null,
        weight: r.value / total,
        ter: meta?.ter ?? null,
        hasInstrumentData: Boolean(meta && Object.keys(meta.breakdowns).length),
        breakdowns: meta?.breakdowns ?? {},
      };
    });
  }

  assetClasses(p: Pos): [Record<string, number>, boolean] {
    const b = p.breakdowns['asset_class'];
    if (b && Object.keys(b).length) return [b, false];
    const assumed = ['etf', 'fund', 'other'].includes(p.kind);
    return [{ [DEFAULT_ASSET_CLASS[p.kind] ?? 'other']: 1 }, assumed];
  }

  /** Look-through buckets for one dimension, or null when the instrument has no breakdown. */
  private geoSector(p: Pos, dim: 'country' | 'region' | 'sector'): Record<string, number> | null {
    const b = p.breakdowns;
    if (dim === 'country') {
      if (b['country']) {
        const agg: Record<string, number> = {};
        for (const [k, w] of Object.entries(b['country'])) {
          const c = this.tax.country(k);
          agg[c] = (agg[c] ?? 0) + w;
        }
        return agg;
      }
      return null;
    }
    if (dim === 'region') {
      const c = this.geoSector(p, 'country');
      if (!c) return null;
      const agg: Record<string, number> = {};
      for (const [k, w] of Object.entries(c)) {
        const r = this.tax.regionOfCountry(k);
        agg[r] = (agg[r] ?? 0) + w;
      }
      return agg;
    }
    if (b['sector']) {
      const agg: Record<string, number> = {};
      for (const [k, w] of Object.entries(b['sector'])) {
        const s = this.tax.sector(k);
        agg[s] = (agg[s] ?? 0) + w;
      }
      return agg;
    }
    return null;
  }

  private rows(m: Record<string, number>, total: number, order?: string[]): BucketRow[] {
    const entries = Object.entries(m).filter(([, v]) => Math.abs(v) >= 0.005);
    // Residual buckets go LAST whatever their size — matching analytics.py._rows, and matching the
    // chart convention where the muted tail sits at the bottom rather than wherever its value lands.
    const residual = (k: string) => (k === UNCLASSIFIED || k === 'Other' ? 1 : 0);
    const sorted = entries.sort((a, b) => {
      const r = residual(a[0]) - residual(b[0]);
      if (r) return r;
      if (order) {
        const ia = order.indexOf(a[0]); const ib = order.indexOf(b[0]);
        const d = (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
        if (d) return d;
      }
      return b[1] - a[1];
    });
    return sorted.map(([bucket, value]) => ({
      bucket, value: round2(value), pct: share(value, total),
    }));
  }

  exposure(asOf: string) {
    const pos = this.positions(asOf);
    const total = pos.reduce((s, p) => s + p.value, 0);
    const asset: Record<string, number> = {};
    const dims = { region: {}, country: {}, sector: {} } as
      Record<'region' | 'country' | 'sector', Record<string, number>>;
    let equity = 0;

    for (const p of pos) {
      const [ac] = this.assetClasses(p);
      for (const [k, w] of Object.entries(ac)) asset[k] = (asset[k] ?? 0) + p.value * w;
      const eq = p.value * (ac['equity'] ?? 0);
      if (eq <= 0) continue;
      equity += eq;
      for (const dim of ['region', 'country', 'sector'] as const) {
        const b = this.geoSector(p, dim);
        if (!b) { dims[dim][UNCLASSIFIED] = (dims[dim][UNCLASSIFIED] ?? 0) + eq; continue; }
        for (const [k, w] of Object.entries(b)) dims[dim][k] = (dims[dim][k] ?? 0) + eq * w;
      }
    }

    const countryRows = this.rows(dims.country, equity);
    const head = countryRows.slice(0, 12);
    const tail = countryRows.slice(12);
    if (tail.length) {
      const other = tail.reduce((s, r) => s + r.value, 0);
      head.push({ bucket: 'Other (tail)', value: round2(other), pct: share(other, equity) });
    }

    return {
      totalValue: round2(total),
      equityValue: round2(equity),
      assetClass: this.rows(asset, total),
      region: this.rows(dims.region, equity, this.tax.regions),
      country: head,
      sector: this.rows(dims.sector, equity, this.tax.gics),
      coverage: {
        geoPct: equity ? 1 - (dims.region[UNCLASSIFIED] ?? 0) / equity : 1,
        sectorPct: equity ? 1 - (dims.sector[UNCLASSIFIED] ?? 0) / equity : 1,
      },
    };
  }

  accounts(asOf: string): AccountDto[] {
    const fees = this.ref.accountFees;
    return this.repo.accounts(asOf).map((a) => {
      const years = a.opened_on
        ? (Date.parse(asOf) - Date.parse(a.opened_on)) / 86_400_000 / 365.25
        : null;
      return {
        id: a.id, name: a.name, envelope: a.envelope as Envelope, institution: a.institution,
        balance: round2(a.balance), unrealizedPnl: null, unrealizedPnlPct: null,
        ageYears: years === null ? null : round2(years),
        contractFee: fees[a.id] ?? null,
      };
    });
  }

  fees(asOf: string) {
    const pos = this.positions(asOf);
    let covered = 0; let feeTotal = 0; let investable = 0;
    for (const p of pos) {
      if (p.kind === 'cash') continue;
      investable += p.value;
      if (p.ter !== null) { covered += p.value; feeTotal += p.value * p.ter; }
    }
    return {
      fundFeesEurPerYear: round2(feeTotal),
      weightedTerOnCovered: covered ? feeTotal / covered : 0,
      terCoveragePct: investable ? covered / investable : 0,
      wrapperFeesEurPerYear: 0,
    };
  }

  concentration(asOf: string) {
    const pos = this.positions(asOf).filter((p) => !['cash', 'fonds_euros'].includes(p.kind));
    const total = pos.reduce((s, p) => s + p.value, 0) || 1;
    const w = pos.map((p) => p.value / total).sort((a, b) => b - a);
    return {
      nPositions: pos.length,
      top1Pct: w[0] ?? 0,
      top5Pct: w.slice(0, 5).reduce((a, b) => a + b, 0),
      hhi: w.reduce((s, x) => s + x * x, 0),
    };
  }

  /**
   * Accounts that entered or left between two snapshots. Without this a closed account reads as a
   * loss: when an account was closed the total fell by a small amount while a much larger balance of
   * perimeter left, and the two effects were indistinguishable.
   */
  perimeterChanges(asOf: string, previous: string | null): ReportDto['perimeterChanges'] {
    if (!previous) return { gone: [], new: [], note: null };
    const prev = this.repo.balancesAt(previous);
    const cur = this.repo.balancesAt(asOf);
    const names = this.repo.accountNames();
    const closed = this.ref.closedAccounts;

    const gone = [...prev.keys()].filter((id) => !cur.has(id)).map((id) => {
      const meta = closed[id] ?? {};
      return {
        id, name: names.get(id)?.name ?? null, envelope: names.get(id)?.envelope ?? null,
        institution: names.get(id)?.institution ?? null,
        lastBalance: round2(prev.get(id)!), lastSeen: previous,
        closedOn: meta.closed_on ?? null,
        reason: meta.note ?? (Object.keys(meta).length ? 'clôturé' : null),
        transferredTo: meta.transferred_to ?? null,
      };
    });
    const fresh = [...cur.keys()].filter((id) => !prev.has(id)).map((id) => ({
      id, name: names.get(id)?.name ?? null, envelope: names.get(id)?.envelope ?? null,
      balance: round2(cur.get(id)!),
    }));

    let note: string | null = null;
    if (gone.length || fresh.length) {
      const delta = round2(gone.reduce((s, g) => s + g.lastBalance, 0)
        - fresh.reduce((s, n) => s + n.balance, 0));
      note = `Le périmètre a changé entre ${previous} et ${asOf} : `
        + `${delta >= 0 ? '+' : ''}${delta.toFixed(2)} EUR de comptes sortis du périmètre, `
        + 'à ne pas lire comme une performance.';
      const undeclared = gone.filter((g) => !g.closedOn).map((g) => g.name ?? g.id);
      if (undeclared.length) {
        note += ` Comptes disparus sans clôture déclarée : ${undeclared.join(', ')}`
          + ' — synchronisation cassée ou clôture à enregistrer dans'
          + ' profile/manual_inputs.json -> closed_accounts.';
      }
    }
    return { gone, new: fresh, note };
  }

  /** The per-line page. Mirrors `analytics.instrument_view`, figure for figure. */
  instrument(isin: string, asOfParam?: string): InstrumentDto {
    const asOf = this.resolveAsOf(asOfParam);
    const all = this.positions(asOf);
    const lines = all.filter((p) => p.isin === isin);
    if (!lines.length) {
      throw notFound('NOT_HELD', `aucune ligne ${isin} détenue au ${asOf}`);
    }
    const meta = this.repo.instruments().get(isin);
    const total = all.reduce((s, p) => s + p.value, 0) || 1;
    const value = lines.reduce((s, p) => s + p.value, 0);
    const costs = lines.filter((p) => p.costBasis !== null).map((p) => p.costBasis as number);
    const cost = costs.length ? costs.reduce((a, b) => a + b, 0) : null;
    const pnl = cost ? round2(value - cost) : null;
    const ter = meta?.ter ?? null;

    const first = lines[0]!;
    const [ac] = this.assetClasses(first);
    const eq = value * (ac['equity'] ?? 0);
    const expo = this.exposure(asOf);

    const fundRows = (d: Record<string, number> | null, base: number, order?: string[]) =>
      d ? this.rows(Object.fromEntries(Object.entries(d).map(([k, w]) => [k, base * w])),
                    base, order).map((r) => ({ bucket: r.bucket, weight: r.pct, eur: r.value }))
        : [];

    return {
      asOf, isin, name: first.name, kind: first.kind,
      hasInstrumentData: Boolean(meta),
      issuer: meta?.issuer ?? null, index: meta?.index ?? null,
      replication: meta?.replication ?? null, ter, sri: meta?.sri ?? null,
      peaEligible: meta?.pea_eligible === null || meta?.pea_eligible === undefined
        ? null : Boolean(meta.pea_eligible),
      notes: meta?.notes ?? null, fetchedAt: meta?.fetched_at ?? null,
      sources: meta ? JSON.parse(meta.sources || '[]') : [],
      performance: meta ? JSON.parse(meta.performance || '{}') : {},
      position: {
        value: round2(value), weight: value / total,
        costBasis: cost === null ? null : round2(cost),
        pnl, pnlPct: pnl !== null && cost ? pnl / cost : null,
        feeEurPerYear: ter ? round2(value * ter) : null,
        lines: lines.map((p) => ({
          accountName: p.accountName, envelope: p.envelope, quantity: p.quantity,
          unitPrice: p.unitPrice, costBasis: p.costBasis, value: round2(p.value),
          pnl: p.pnl === null ? null : round2(p.pnl),
        })),
      },
      composition: {
        equityValue: round2(eq),
        assetClass: Object.entries(ac).sort((a, b) => b[1] - a[1])
          .map(([bucket, weight]) => ({ bucket, weight, eur: round2(value * weight) })),
        country: fundRows(this.geoSector(first, 'country'), eq),
        region: fundRows(this.geoSector(first, 'region'), eq, this.tax.regions),
        sector: fundRows(this.geoSector(first, 'sector'), eq, this.tax.gics),
        portfolioRegion: expo.region.map((r) => ({ bucket: r.bucket, pct: r.pct })),
        portfolioSector: expo.sector.map((r) => ({ bucket: r.bucket, pct: r.pct })),
      },
      history: this.repo.isinHistory(isin).map((h) => ({
        asOf: h.as_of, value: round2(h.value), quantity: h.quantity,
        unitPrice: h.quantity ? Math.round((round2(h.value) / h.quantity) * 1e4) / 1e4 : null,
      })),
    };
  }

  /**
   * Money handed over that comes back. Shown BESIDE the Finary total, never in it: the total
   * reconciles to the cent with Finary's overview. The amount paid is read from the transaction.
   */
  receivables(asOf: string, totalValue: number): ReportDto['receivables'] {
    const items: ReportDto['receivables']['items'] = [];
    for (const r of this.ref.receivables) {
      const tx = this.repo.transactionById(r.transaction_id);
      if (tx && tx.date > asOf) continue;
      const paid = tx ? round2(-tx.amount) : null;
      const exp: number | null = r.expected_refund ?? null;
      items.push({
        id: r.id, label: r.label, kind: r.kind ?? null,
        paidOn: tx?.date ?? null, paid, expectedRefund: exp,
        expectedRetention: paid !== null && exp !== null ? round2(paid - exp) : null,
        expectedRefundDate: r.expected_refund_date ?? null,
        note: tx ? (r.note ?? null) : 'transaction introuvable : relancer import-transactions',
      });
    }
    const expTotal = round2(items.reduce((a, i) => a + (i.expectedRefund ?? 0), 0));
    return {
      items,
      totalPaid: round2(items.reduce((a, i) => a + (i.paid ?? 0), 0)),
      totalExpectedRefund: expTotal,
      totalWithReceivables: round2(totalValue + expTotal),
    };
  }

  drift(exposure: ReturnType<ReportService['exposure']>) {
    const targets = this.ref.targets ?? {};
    const out: ReportDto['driftVsTargets'] = {};
    const pick = { asset_class: exposure.assetClass, region: exposure.region,
                   sector: exposure.sector } as const;
    for (const dim of ['asset_class', 'region', 'sector'] as const) {
      const t = targets[dim];
      if (!t) continue;
      const actual = new Map(pick[dim].map((r) => [r.bucket, r.pct]));
      out[dim] = Object.entries(t)
        .filter(([k]) => !k.startsWith('_'))
        .map(([bucket, target]) => ({
          bucket, target, actual: actual.get(bucket) ?? 0,
          drift: (actual.get(bucket) ?? 0) - target,
        }));
    }
    return out;
  }

  report(asOfParam?: string): ReportDto {
    const asOf = this.resolveAsOf(asOfParam);
    const dates = this.repo.snapshotDates();
    const previous = dates.filter((d) => d < asOf).at(-1) ?? null;
    const exposure = this.exposure(asOf);
    const prevTotal = previous ? this.repo.snapshotTotal(previous) : null;
    const positions = this.positions(asOf).map(({ breakdowns, ...p }) => p);

    return {
      asOf, previousAsOf: previous,
      totalValue: exposure.totalValue,
      changeVsPrevious: prevTotal === null ? null : round2(exposure.totalValue - prevTotal),
      envelopes: (() => {
        const rows = this.repo.envelopes(asOf);
        const total = rows.reduce((s, r) => s + r.value, 0) || 1;
        return rows.map((r) => ({ bucket: r.envelope, value: round2(r.value),
                                  pct: r.value / total }));
      })(),
      accounts: this.accounts(asOf),
      positions,
      exposure,
      driftVsTargets: this.drift(exposure),
      concentration: this.concentration(asOf),
      fees: this.fees(asOf),
      envelopeChecks: [],
      perimeterChanges: this.perimeterChanges(asOf, previous),
      receivables: this.receivables(asOf, exposure.totalValue),
      history: this.repo.history().map((h) => ({ asOf: h.as_of, total: h.total_value })),
    };
  }
}
