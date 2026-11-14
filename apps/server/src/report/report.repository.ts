import { Injectable } from '@nestjs/common';
import { SqliteProvider } from '../database/sqlite.provider';

export interface HoldingRow {
  as_of: string; account_id: string; key: string; isin: string | null; name: string; kind: string;
  quantity: number | null; unit_price: number | null; value: number; cost_basis: number | null;
  account_name: string; envelope: string; institution: string; opened_on: string | null;
}
export interface InstrumentRow {
  isin: string; name: string; kind: string; ter: number | null; pea_eligible: number | null;
  replication: string | null; index: string | null; issuer: string | null; sri: number | null;
  performance: string; sources: string; fetched_at: string; notes: string | null;
}

/** The only place SQL about the portfolio lives. */
@Injectable()
export class ReportRepository {
  constructor(private readonly sqlite: SqliteProvider) {}

  snapshotDates(): string[] {
    return this.sqlite.all<{ as_of: string }>('SELECT as_of FROM snapshots ORDER BY as_of')
      .map((r) => r.as_of);
  }

  /** My value in one ISIN at every snapshot, summed over the accounts that hold it. */
  isinHistory(isin: string): { as_of: string; value: number; quantity: number | null }[] {
    return this.sqlite.all<{ as_of: string; value: number; quantity: number | null }>(
      'SELECT as_of, SUM(value) AS value, SUM(quantity) AS quantity FROM holdings '
      + 'WHERE isin=? GROUP BY as_of ORDER BY as_of', isin);
  }

  transactionById(id: string): { date: string; amount: number } | null {
    return this.sqlite.get<{ date: string; amount: number }>(
      'SELECT date, amount FROM transactions WHERE id=?', id) ?? null;
  }

  snapshotTotal(asOf: string): number | null {
    const r = this.sqlite.get<{ total_value: number }>(
      'SELECT total_value FROM snapshots WHERE as_of=?', asOf);
    return r?.total_value ?? null;
  }

  holdings(asOf: string): HoldingRow[] {
    return this.sqlite.all<HoldingRow>(
      'SELECT h.*, a.name AS account_name, a.envelope, a.institution, a.opened_on '
      + 'FROM holdings h JOIN accounts a ON a.id=h.account_id '
      + 'WHERE h.as_of=? ORDER BY h.value DESC', asOf);
  }

  instruments(): Map<string, InstrumentRow & { breakdowns: Record<string, Record<string, number>> }> {
    const out = new Map<string, any>();
    for (const r of this.sqlite.all<InstrumentRow>('SELECT * FROM instruments')) {
      out.set(r.isin, { ...r, breakdowns: {} });
    }
    for (const b of this.sqlite.all<
         { isin: string; dimension: string; bucket: string; weight: number }>(
         'SELECT * FROM instrument_breakdowns')) {
      const inst = out.get(b.isin) ?? { breakdowns: {} };
      (inst.breakdowns[b.dimension] ??= {})[b.bucket] = b.weight;
      out.set(b.isin, inst);
    }
    return out;
  }

  envelopes(asOf: string) {
    return this.sqlite.all<{ envelope: string; value: number }>(
      'SELECT a.envelope, SUM(v.balance) AS value FROM account_values v '
      + 'JOIN accounts a ON a.id=v.account_id WHERE v.as_of=? '
      + 'GROUP BY a.envelope ORDER BY value DESC', asOf);
  }

  accounts(asOf: string) {
    return this.sqlite.all<{ id: string; name: string; envelope: string; institution: string;
                             opened_on: string | null; balance: number }>(
      'SELECT a.*, v.balance FROM accounts a JOIN account_values v ON v.account_id=a.id '
      + 'WHERE v.as_of=? ORDER BY v.balance DESC', asOf);
  }

  balancesAt(asOf: string): Map<string, number> {
    return new Map(this.sqlite.all<{ account_id: string; balance: number }>(
      'SELECT account_id, balance FROM account_values WHERE as_of=?', asOf)
      .map((r) => [r.account_id, r.balance]));
  }

  accountNames(): Map<string, { name: string; envelope: string; institution: string }> {
    return new Map(this.sqlite.all<{ id: string; name: string; envelope: string;
                                     institution: string }>(
      'SELECT id, name, envelope, institution FROM accounts').map((r) => [r.id, r]));
  }

  history() {
    return this.sqlite.all<{ as_of: string; total_value: number }>(
      'SELECT as_of, total_value FROM snapshots ORDER BY as_of');
  }
}
