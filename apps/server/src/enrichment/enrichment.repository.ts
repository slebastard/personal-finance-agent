import { Injectable } from '@nestjs/common';
import type { CompanyRecord } from '@pfa/contracts';
import { SqliteProvider } from '../database/sqlite.provider';

/** Vendor documents as Python stored them (snake_case). */
export interface HoldingsDoc {
  fund_isin: string; proxy_isin: string | null; kind: string | null; index: string | null;
  as_of: string | null; fetched_at: string; n_total: number; top_n: number; coverage_top: number;
  constituents: { rank: number; isin: string; name: string; ticker: string | null; weight: number }[];
  crosscheck?: { sector_max_gap_pts: number | null; country_max_gap_pts: number | null;
                 warn: boolean; threshold_pts: number } | null;
  source?: unknown;
}

/** The only place SQL about the Eulerpool tables lives. Missing tables (no `pfa enrich` yet) read as empty. */
@Injectable()
export class EnrichmentRepository {
  constructor(private readonly sqlite: SqliteProvider) {}

  private one<T>(sql: string, ...args: string[]): T | null {
    try {
      const r = this.sqlite.get<{ data: string }>(sql, ...args);
      return r ? (JSON.parse(r.data) as T) : null;
    } catch (e) {
      if (String(e).includes('no such table')) return null;
      throw e;
    }
  }

  holdings(fundIsin: string): HoldingsDoc | null {
    return this.one<HoldingsDoc>('SELECT data FROM etf_holdings WHERE fund_isin=?', fundIsin);
  }

  company(isin: string): CompanyRecord | null {
    return this.one<CompanyRecord>('SELECT data FROM companies WHERE isin=?', isin);
  }
}
