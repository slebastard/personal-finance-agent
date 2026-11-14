import { Injectable } from '@nestjs/common';
import { SqliteProvider } from '../database/sqlite.provider';

export interface TxRow {
  id: string; date: string; label: string; account: string; account_id: string | null;
  amount: number; category: string | null; subcategory: string | null;
  flow: string; rule_id: string | null; period_month: string | null; note: string | null;
}

/** The only place SQL about transactions lives. */
@Injectable()
export class FlowsRepository {
  constructor(private readonly sqlite: SqliteProvider) {}

  range(): { from: string; to: string } | null {
    const r = this.sqlite.get<{ a: string | null; b: string | null }>(
      'SELECT MIN(date) AS a, MAX(date) AS b FROM transactions');
    return r?.a && r?.b ? { from: r.a, to: r.b } : null;
  }

  between(from: string, to: string): TxRow[] {
    return this.sqlite.all<TxRow>(
      'SELECT * FROM transactions WHERE date>=? AND date<=? ORDER BY date, id', from, to);
  }

  page(from: string, to: string, flow?: string, category?: string,
       limit = 200, offset = 0): { rows: TxRow[]; total: number } {
    const where = ['date>=?', 'date<=?'];
    const args: (string | number)[] = [from, to];
    if (flow) { where.push('flow=?'); args.push(flow); }
    if (category) { where.push('category=?'); args.push(category); }
    const w = where.join(' AND ');
    const total = this.sqlite.get<{ n: number }>(
      `SELECT COUNT(*) AS n FROM transactions WHERE ${w}`, ...args)!.n;
    const rows = this.sqlite.all<TxRow>(
      `SELECT * FROM transactions WHERE ${w} ORDER BY date DESC, ABS(amount) DESC LIMIT ? OFFSET ?`,
      ...args, limit, offset);
    return { rows, total };
  }

  /** Snapshot balances bounding the window, per account — the reconciliation input. */
  balanceBounds(accountId: string, from: string, to: string) {
    const b = this.sqlite.get<{ a: string | null; b: string | null }>(
      'SELECT MIN(as_of) AS a, MAX(as_of) AS b FROM account_values '
      + 'WHERE account_id=? AND as_of>=? AND as_of<=?', accountId, from, to);
    if (!b?.a || !b?.b || b.a === b.b) return null;
    const at = (d: string) => this.sqlite.get<{ balance: number }>(
      'SELECT balance FROM account_values WHERE account_id=? AND as_of=?', accountId, d)!.balance;
    return { from: b.a, to: b.b, start: at(b.a), end: at(b.b) };
  }
}
