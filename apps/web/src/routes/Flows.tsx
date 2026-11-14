import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { EChartsOption } from 'echarts';
import { api } from '../api/client';
import { Figure } from '../components/Delta';
import { CATEGORY_LABELS, FLOW_LABELS, categoryLabel, eur, monthLabel, pct, signCls }
  from '../api/format';
import { Chart } from '../charts/Chart';
import { palette } from '../charts/theme';
import { Card, Segmented, TableTwin, Tile } from '../components/ui';
import { PeriodPicker, resolve, type PeriodState } from '../components/PeriodPicker';
import type { FlowsDto } from '@pfa/contracts';

/** Income vs spending is a POLARITY, so it takes the good/bad status tokens — always beside a
 *  signed value, never colour alone. Categories use the validated categorical slots. */
function trend(monthly: FlowsDto['monthly']): EChartsOption {
  // keep the year only when the window straddles two, so a 12-month view is not ambiguous
  const years = new Set(monthly.map((m) => m.month.slice(0, 4)));
  const months = monthly.map((m) => {
    const full = monthLabel(m.month);
    if (years.size === 1) return full.replace(/ \d{4}$/, '');
    return full.replace(/^(\S{3})\S*\s(\d{2})(\d{2})$/, '$1. $3');
  });
  return {
    grid: { left: 56, right: 56, top: 28, bottom: 24 },
    legend: { top: 0 },
    tooltip: {
      trigger: 'axis',
      formatter: (raw: unknown) => {
        const ps = raw as any[];
        const i = ps[0].dataIndex as number;
        const m = monthly[i]!;
        return `<b>${monthLabel(m.month)}</b><br/>`
          + `revenus <b>${eur(m.income)}</b><br/>`
          + `consommation <b>${eur(m.spending)}</b><br/>`
          + `remboursements <b>${eur(m.refund)}</b><br/>`
          + `net <b>${eur(m.net)}</b>`;
      },
    },
    xAxis: { type: 'category', data: months },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => eur(v) } },
    series: [
      { name: 'Revenus', type: 'bar', stack: 'flux', barWidth: '55%',
        itemStyle: { color: palette.cat(1), borderRadius: [4, 4, 0, 0] },
        data: monthly.map((m) => m.income) },
      { name: 'Consommation', type: 'bar', stack: 'flux',
        itemStyle: { color: palette.cat(2), borderRadius: [0, 0, 4, 4] },
        data: monthly.map((m) => m.spending) },
      { name: 'Épargne nette', type: 'line', symbolSize: 8, smooth: false,
        lineStyle: { width: 2, color: palette.text() },
        itemStyle: { color: palette.text(),
                     borderColor: palette.surface(), borderWidth: 2 },
        data: monthly.map((m) => m.net) },
    ],
  };
}

function categories(cats: FlowsDto['byCategory'], detailed: boolean): EChartsOption {
  const rows = detailed
    ? cats.flatMap((c) => c.subcategories.map((s) => ({
        name: `${categoryLabel(c.category)} · ${s.subcategory}`, value: Math.abs(s.amount) })))
      .sort((a, b) => b.value - a.value).slice(0, 18)
    : cats.map((c) => ({ name: categoryLabel(c.category), value: Math.abs(c.amount) }));
  const data = [...rows].reverse();
  return {
    grid: { left: 190, right: 76, top: 6, bottom: 6 },
    xAxis: { type: 'value', axisLabel: { show: false }, splitLine: { show: false } },
    yAxis: { type: 'category', data: data.map((r) => r.name),
             axisLabel: { color: palette.muted(), fontSize: 12, width: 180, overflow: 'truncate' } },
    tooltip: { trigger: 'item', formatter: (p: any) => `<b>${eur(p.value)}</b><br/>${p.name}` },
    series: [{
      type: 'bar', barWidth: 16,
      itemStyle: { borderRadius: [0, 4, 4, 0], color: palette.series1() },
      label: { show: true, position: 'right', color: palette.text(), fontSize: 12,
               formatter: (p: any) => eur(p.value) },
      data: data.map((r) => r.value),
    }],
  };
}

export default function Flows() {
  const [period, setPeriod] = useState<PeriodState>({ mode: 'preset', preset: 'last-12' });
  const [detailed, setDetailed] = useState<'off' | 'on'>('off');

  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta });
  const range = meta.data?.transactionRange ?? null;
  const p = useMemo(() => resolve(period, range), [period, range]);
  const flows = useQuery({ queryKey: ['flows', p], queryFn: () => api.flows(p), enabled: !!meta.data });
  const unclassified = useQuery({
    queryKey: ['tx', p, 'unclassified'],
    queryFn: () => api.transactions({ ...p, flow: 'unclassified', limit: '50' }),
    enabled: !!meta.data,
  });

  if (meta.error) return <Card title="Erreur"><p className="note">{String(meta.error)}</p></Card>;
  if (!range) {
    return <Card title="Aucune transaction">
      <p className="note">Lance <code>python3 -m pfa import-transactions &lt;export.csv&gt;</code>.</p>
    </Card>;
  }

  const d = flows.data;
  const q = d?.quality;

  return (
    <>
      <header className="app">
        <div>
          <h1>Flux · {d ? `${d.from} → ${d.to}` : '…'}</h1>
          <div className="hero"><Figure text={eur(d?.net ?? null)} /></div>
          <div className="sub">
            épargne nette sur la période
            {d && d.months >= 1 && ` · ${eur(d.net / d.months)} par mois`}
          </div>
        </div>
        <div className="sub">Source : export Bankin' · classification locale</div>
      </header>

      <PeriodPicker state={period} onChange={setPeriod} range={range} />

      <div className={`stack${flows.isFetching ? ' loading' : ''}`}>
        <section className="tiles">
          <Tile label="Revenus externes" value={eur(d?.byNature.income.amount ?? null)}
                delta={d ? `${d.byNature.income.count} mouvements` : undefined} />
          <Tile label="Consommation" value={eur(d?.byNature.spending.amount ?? null)}
                delta={d ? `${d.byNature.spending.count} mouvements` : undefined} />
          <Tile label="Épargne nette" value={eur(d?.net ?? null)} cls={signCls(d?.net)}
                delta={d?.savingsRate !== null && d?.savingsRate !== undefined
                  ? `taux d'épargne ${pct(d.savingsRate)}` : undefined} />
          <Tile label="Qualité des données"
                value={q ? pct(1 - q.unclassifiedAmountPct, 0) : '—'}
                delta={q ? `classé · réconciliation ${q.reconciliationGap === null
                  ? 'hors bornes' : eur(q.reconciliationGap, 2)}` : undefined} />
        </section>

        {q && (q.unclassifiedAmountPct > 0.02 || q.monthsWithSuspiciousIncome.length > 0) && (
          <Card title="À arbitrer" caption="Signalé plutôt que rangé par défaut">
            <p className="note">
              {q.unclassifiedAmountPct > 0.02 && (
                <>{pct(q.unclassifiedAmountPct)} du montant n'est pas classé
                  ({q.unclassifiedCount} transactions) : ces lignes dépassent le seuil de revue et
                  n'ont aucune règle explicite, elles sont donc exclues des totaux plutôt que
                  comptées en consommation. </>)}
              {q.monthsWithSuspiciousIncome.length > 0 && (
                <>Revenu quasi nul sur {q.monthsWithSuspiciousIncome.join(', ')} : deux mois
                  consécutifs sans salaire sont une erreur de classification, pas un fait.</>)}
            </p>
            {unclassified.data && unclassified.data.rows.length > 0 && (
              <table className="tbl" style={{ marginTop: 12 }}>
                <thead><tr><th>Date</th><th>Libellé</th><th>Catégorie Bankin'</th>
                  <th className="n">Montant</th></tr></thead>
                <tbody>{unclassified.data.rows.map((t) => (
                  <tr key={t.id}>
                    <td>{t.date}</td><td>{t.label}</td>
                    <td className="cap">{t.category} / {t.subcategory}</td>
                    <td className={`n ${signCls(t.amount)}`}>{eur(t.amount, 2)}</td>
                  </tr>))}</tbody>
              </table>)}
          </Card>)}

        <section className="grid2">
          <Card title="Tendance mensuelle"
                caption="Revenus et consommation autour de zéro · ligne = épargne nette" wide>
            {d && <Chart option={trend(d.monthly)} height={320} ariaLabel="Tendance mensuelle" />}
            {d && <TableTwin head={['Mois', 'Revenus', 'Consommation', 'Remb.', 'Net']}
              rows={d.monthly.map((m) => [monthLabel(m.month), eur(m.income), eur(m.spending),
                                          eur(m.refund), eur(m.net)])} />}
          </Card>
        </section>

        <section className="grid2">
          <Card title="Dépenses par catégorie" caption="Consommation seule — les virements internes sont exclus" wide>
            <div style={{ marginBottom: 10 }}>
              <Segmented label="Granularité" value={detailed}
                options={[{ value: 'off', label: 'Catégories' },
                          { value: 'on', label: 'Sous-catégories' }]}
                onChange={setDetailed} />
            </div>
            {d && <Chart option={categories(d.byCategory, detailed === 'on')}
                         height={Math.max((detailed === 'on' ? 18 : d.byCategory.length) * 30, 160)}
                         ariaLabel="Dépenses par catégorie" />}
            {d && <TableTwin head={['Catégorie', 'Montant', 'Mouvements']}
              rows={d.byCategory.flatMap((c) => [
                [categoryLabel(c.category), eur(c.amount), String(c.count)],
                ...(detailed === 'on'
                  ? c.subcategories.map((s) => [`· ${s.subcategory}`, eur(s.amount), String(s.count)])
                  : [])])} />}
          </Card>
        </section>

        <section className="grid2">
          <Card title="Flux internes"
                caption="Mouvements entre tes propres comptes — ni revenus, ni dépenses">
            {d && <>
              <p className="note">
                {eur(d.byNature.internal.amount)} sur {d.byNature.internal.count} mouvements.
                Versements au PEA, à l'assurance-vie, au Livret A, et rapatriements. Les compter
                comme des dépenses ferait apparaître de l'épargne comme de la consommation.
              </p>
              <FlowTable period={p} flow="internal" />
            </>}
          </Card>
          {d && d.byNature.provisional.count > 0 && (
            <Card title="Retenues provisoires"
                  caption="Argent remis qui reviendra — ni dépense, ni épargne">
              <p className="note">
                {eur(d.byNature.provisional.amount)} sur {d.byNature.provisional.count} mouvement.
                Exclu de la consommation et de la capacité d'épargne ; la créance correspondante
                est suivie dans l'onglet Portefeuille, hors du total Finary.
              </p>
              <FlowTable period={p} flow="provisional" />
            </Card>)}
          <Card title="Répartition par nature" caption="Contrôle de cohérence">
            {d && <TableTwin summary="Détail" head={['Nature', 'Montant', 'Mouvements']}
              rows={Object.entries(d.byNature).map(([k, v]) => [
                FLOW_LABELS[k] ?? k, eur(v.amount), String(v.count)])} />}
            {d && <table className="tbl">
              <tbody>{Object.entries(d.byNature).map(([k, v]) => (
                <tr key={k}><td>{FLOW_LABELS[k] ?? k}</td>
                  <td className={`n ${signCls(v.amount)}`}>{eur(v.amount)}</td>
                  <td className="n cap">{v.count}</td></tr>))}</tbody>
            </table>}
          </Card>
        </section>
      </div>
    </>
  );
}

function FlowTable({ period, flow }: { period: ReturnType<typeof resolve>; flow: string }) {
  const { data } = useQuery({
    queryKey: ['tx', period, flow],
    queryFn: () => api.transactions({ ...period, flow, limit: '50' }),
  });
  if (!data?.rows.length) return null;
  return (
    <table className="tbl" style={{ marginTop: 12 }}>
      <thead><tr><th>Date</th><th>Libellé</th><th className="n">Montant</th></tr></thead>
      <tbody>{data.rows.map((t) => (
        <tr key={t.id}>
          <td>{t.date}</td>
          <td>{t.label}<br /><span className="cap">règle : {t.ruleId ?? '—'}</span></td>
          <td className={`n ${signCls(t.amount)}`}>{eur(t.amount, 2)}</td>
        </tr>))}</tbody>
    </table>
  );
}
