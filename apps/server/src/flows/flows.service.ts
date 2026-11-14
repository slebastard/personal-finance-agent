import { Injectable } from '@nestjs/common';
import type { FlowNature, FlowsDto, SavingsCapacityDto, TransactionDto } from '@pfa/contracts';
import { FLOW_NATURES } from '@pfa/contracts';
import { FlowsRepository, TxRow } from './flows.repository';
import { round2, roundHalfEven } from '../common/money';

const MS_PER_MONTH = 30.44;

/** Month a row is attributed to in monthly series: income follows its billing period
 *  (`period_month`, e.g. a salary paid 2026-03-03 is February's), every other nature its cash date.
 *  Window totals and reconciliation always use the cash date. Mirrors `flows._month_of`. */
const monthOf = (r: { flow: string; date: string; period_month: string | null }): string =>
  r.flow === 'income' ? (r.period_month ?? r.date.slice(0, 7)) : r.date.slice(0, 7);

@Injectable()
export class FlowsService {
  constructor(private readonly repo: FlowsRepository) {}

  range() { return this.repo.range(); }

  toDto(r: TxRow): TransactionDto {
    return {
      id: r.id, date: r.date, label: r.label, account: r.account, accountId: r.account_id,
      amount: r.amount, category: r.category, subcategory: r.subcategory,
      flow: r.flow as FlowNature, ruleId: r.rule_id, note: r.note,
    };
  }

  page(from: string, to: string, flow?: string, category?: string, limit?: number,
       offset?: number) {
    const { rows, total } = this.repo.page(from, to, flow, category, limit, offset);
    return { total, rows: rows.map((r) => this.toDto(r)) };
  }

  aggregate(from: string, to: string): FlowsDto {
    const rows = this.repo.between(from, to);

    const byNature = Object.fromEntries(
      FLOW_NATURES.map((n) => [n, { amount: 0, count: 0 }]),
    ) as FlowsDto['byNature'];

    const cats = new Map<string, { category: string; amount: number; count: number;
                                   subs: Map<string, { subcategory: string; amount: number;
                                                       count: number }> }>();
    const monthly = new Map<string, FlowsDto['monthly'][number]>();

    for (const r of rows) {
      const n = r.flow as FlowNature;
      byNature[n].amount = round2(byNature[n].amount + r.amount);
      byNature[n].count += 1;

      // only consumption is broken down by category: a transfer to the PEA has a Bankin' category
      // ("Home / Rent", verified) that would be nonsense in a spending breakdown
      if (n === 'spending') {
        const key = r.category ?? '(sans catégorie)';
        const c = cats.get(key) ?? { category: key, amount: 0, count: 0, subs: new Map() };
        c.amount = round2(c.amount + r.amount);
        c.count += 1;
        const sk = r.subcategory ?? '(sans sous-catégorie)';
        const s = c.subs.get(sk) ?? { subcategory: sk, amount: 0, count: 0 };
        s.amount = round2(s.amount + r.amount);
        s.count += 1;
        c.subs.set(sk, s);
        cats.set(key, c);
      }

      const mk = monthOf(r);
      const m = monthly.get(mk) ?? { month: mk, income: 0, spending: 0, refund: 0,
                                     internal: 0, provisional: 0, unclassified: 0, net: 0 };
      m[n] = round2(m[n] + r.amount);
      monthly.set(mk, m);
    }

    for (const m of monthly.values()) m.net = round2(m.income + m.spending + m.refund);

    const byCategory = [...cats.values()]
      .sort((a, b) => a.amount - b.amount)
      .map(({ subs, ...c }) => ({
        ...c,
        subcategories: [...subs.values()].sort((a, b) => a.amount - b.amount),
      }));

    const income = byNature.income.amount;
    const net = round2(income + byNature.spending.amount + byNature.refund.amount);

    return {
      from, to,
      months: round2(this.monthsBetween(from, to)),
      byNature, byCategory,
      monthly: [...monthly.values()].sort((a, b) => a.month.localeCompare(b.month)),
      net,
      savingsRate: income ? roundHalfEven(net / income, 4) : null,
      quality: this.quality(rows, from, to),
    };
  }

  private monthsBetween(from: string, to: string): number {
    const d = (Date.parse(to) - Date.parse(from)) / 86_400_000;
    return Math.max(d / MS_PER_MONTH, 1 / MS_PER_MONTH);
  }

  private quality(rows: TxRow[], from: string, to: string): FlowsDto['quality'] {
    const totalAbs = rows.reduce((s, r) => s + Math.abs(r.amount), 0) || 1;
    const unc = rows.filter((r) => r.flow === 'unclassified');

    // Σ flows must equal Δ balance. This validates COMPLETENESS (a truncated export, a missing
    // month) — not the classification, since reclassifying a row does not change the sum.
    let gap: number | null = null;
    const accounts = [...new Set(rows.map((r) => r.account_id).filter(Boolean))] as string[];
    const gaps: number[] = [];
    for (const acc of accounts) {
      const b = this.repo.balanceBounds(acc, from, to);
      if (!b) continue;
      const flux = rows
        .filter((r) => r.account_id === acc && r.date > b.from && r.date <= b.to)
        .reduce((s, r) => s + r.amount, 0);
      gaps.push(flux - (b.end - b.start));
    }
    if (gaps.length) gap = round2(gaps.reduce((a, b) => a + b, 0));

    // A month-end salary legitimately slips into the first days of the next month (observed:
    // 2025-12-01, 2026-03-03, 2026-05-04). Only TWO CONSECUTIVE low months are a real anomaly.
    const perMonth = new Map<string, number>();
    for (const r of rows) {
      if (r.flow !== 'income') continue;
      const k = monthOf(r);
      perMonth.set(k, (perMonth.get(k) ?? 0) + r.amount);
    }
    const months = [...perMonth.keys()].sort();
    const values = [...perMonth.values()].sort((a, b) => a - b);
    const median = values.length ? values[Math.floor(values.length / 2)]! : 0;
    const low = new Set(months.filter((m) => median && perMonth.get(m)! < 0.25 * median));
    const suspicious = months.filter(
      (m, i) => low.has(m) && i + 1 < months.length && i > 0 && low.has(months[i - 1]!));

    return {
      reconciliationGap: gap,
      unclassifiedAmountPct: roundHalfEven(
        unc.reduce((s, r) => s + Math.abs(r.amount), 0) / totalAbs, 4),
      unclassifiedCount: unc.length,
      monthsWithSuspiciousIncome: suspicious,
    };
  }

  savingsCapacity(): SavingsCapacityDto | null {
    const range = this.repo.range();
    if (!range) return null;
    // a 12-month trailing window, ending at the last COMPLETE month: a part-month would drag the
    // average down for no reason
    const end = new Date(`${range.to}T00:00:00Z`);
    const lastFull = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth(), 0));
    const start = new Date(Date.UTC(lastFull.getUTCFullYear() - 1, lastFull.getUTCMonth() + 1, 1));
    const from = start.toISOString().slice(0, 10) < range.from
      ? range.from : start.toISOString().slice(0, 10);
    const to = lastFull.toISOString().slice(0, 10);

    const a = this.aggregate(from, to);
    const caveats: string[] = [];
    if (a.quality.unclassifiedAmountPct > 0.02) {
      caveats.push(`${(a.quality.unclassifiedAmountPct * 100).toFixed(1)} % du montant n'est pas `
        + 'classé : la capacité est approximative tant que ces lignes ne sont pas arbitrées.');
    }
    if (a.quality.monthsWithSuspiciousIncome.length) {
      caveats.push('Mois à revenu suspect : '
        + a.quality.monthsWithSuspiciousIncome.join(', ') + ' — classification probablement fausse.');
    }
    if (a.quality.reconciliationGap === null) {
      caveats.push('Réconciliation impossible : la fenêtre n\'est pas bornée par deux snapshots.');
    }
    return {
      from, to, months: a.months,
      monthlyIncome: round2(a.byNature.income.amount / a.months),
      monthlySpending: round2(a.byNature.spending.amount / a.months),
      monthlyNet: round2(a.net / a.months),
      savingsRate: a.savingsRate,
      caveats,
    };
  }
}
