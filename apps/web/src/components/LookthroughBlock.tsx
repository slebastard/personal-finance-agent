import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import type { EChartsOption } from 'echarts';
import type { LookthroughDto } from '@pfa/contracts';
import { api } from '../api/client';
import { eur, num, pct } from '../api/format';
import { Chart } from '../charts/Chart';
import { palette } from '../charts/theme';
import { Card, TableTwin, Tile } from './ui';
import { Def } from './Def';
import { HealthRanges } from './HealthRanges';
import { LearnPrompts } from './LearnPrompts';
import { qualityBars } from './FundCompanies';

const TOP = 15;
const short = (s: string, n = 34) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

/** Top companies across ALL my funds, stacked by the fund they come through. Colour follows the FUND. */
function stacked(lt: LookthroughDto): EChartsOption {
  const rows = lt.companies.slice(0, TOP);
  const cats = [...rows].reverse();
  return {
    grid: { left: 150, right: 90, top: 34, bottom: 6, containLabel: false },
    legend: { top: 0, data: lt.funds.map((f) => short(f.name, 30)), textStyle: { color: palette.muted(), fontSize: 11 } },
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        const c = cats[p.dataIndex]!;
        return `<b>${c.name}</b><br/>${eur(c.exposureEur)} au total (${pct(c.pctOfEquity)} de ma poche actions)<br/>`
          + c.funds.map((f) => `${short(f.fundName, 30)} : ${eur(f.eur)}`).join('<br/>');
      },
    },
    xAxis: { type: 'value', axisLabel: { show: false }, splitLine: { show: false } },
    yAxis: { type: 'category', data: cats.map((c) => c.name),
             axisLabel: { color: palette.muted(), fontSize: 12, formatter: (v: string) => short(v, 22) } },
    series: [
      ...lt.funds.map((f) => ({
        name: short(f.name, 30), type: 'bar' as const, stack: 'total', barWidth: 16,
        // a 2px surface gap between stacked segments
        itemStyle: { color: palette.cat(f.colorSlot ?? 8), borderColor: palette.surface(), borderWidth: 2 },
        data: cats.map((c) => c.funds.find((x) => x.fundIsin === f.isin)?.eur ?? 0),
      })),
      // invisible marks carrying the total at the end of each stack
      { name: 'total', type: 'scatter' as const, symbolSize: 0, silent: true, z: 5,
        label: { show: true, position: 'right' as const, color: palette.text(), fontSize: 12,
                 formatter: (p: any) => eur(p.value[0]) },
        data: cats.map((c) => [c.exposureEur, c.name]) },
    ],
  };
}

export function LookthroughBlock() {
  const nav = useNavigate();
  const { data: lt } = useQuery({ queryKey: ['lookthrough'], queryFn: () => api.lookthrough() });
  if (!lt) return null;
  const names = Object.fromEntries(lt.funds.map((f) => [f.isin, f.name]));
  const noData = lt.funds.length === 0;
  const q = lt.quality;

  if (noData) {
    return (
      <Card title="Sociétés derrière mes fonds" caption="look-through au niveau des sociétés" wide>
        <p className="note">Aucun fonds n'est encore décomposé en sociétés. Lance <code>python3 -m pfa enrich</code>
          {' '}(voir <code>PLAN-enrichment.md</code>).</p>
        {lt.fundsNotCovered.length > 0 && (
          <p className="cap">{lt.fundsNotCovered.length} fonds actions sans liste de sociétés.</p>)}
      </Card>);
  }
  return (
    <>
      <h2 className="section">Sociétés derrière mes fonds</h2>
      <div className={`banner ${lt.identifiedPct < 0.5 ? 'warn' : ''}`} role="note">
        <span><b>{pct(lt.identifiedPct, 0)} de ma poche actions</b> est identifiée au niveau des sociétés
          {' '}({eur(lt.identifiedEur)} sur {eur(lt.equityValue)}).</span>
        <span className="cap">Reste : la longue traîne des indices (au-delà des premières lignes listées de
          chaque fonds) et {lt.fundsNotCovered.length} fonds sans liste de sociétés. Toute moyenne ci-dessous
          ne décrit que la part identifiée.</span>
      </div>

      <section className="tiles">
        <Tile label="Poche actions identifiée" value={pct(lt.identifiedPct, 0)}
              delta={`${eur(lt.identifiedEur)} sur ${eur(lt.equityValue)}`} />
        <Tile label="10 premières sociétés" value={pct(lt.top10PctOfEquity, 1)}
              delta={`de ma poche actions · ${pct(lt.top10PctOfIdentified, 0)} de la part identifiée`} />
        <Tile label="Sociétés distinctes" value={String(lt.nCompanies)}
              delta={`dont ${lt.nShared} détenues via au moins 2 fonds`} />
        <Tile label={<Def k="aaqs_score">Note de qualité moyenne</Def>}
              value={q.aaqs_score.mean === null ? 'n.d.' : `${num(q.aaqs_score.mean, 1)} / 10`}
              delta={`pondérée par mes euros · couverture ${pct(q.aaqs_score.coverage, 0)}`} />
      </section>

      <Card title="Mes plus grosses expositions" wide
            caption={`les ${TOP} premières sociétés, tous fonds confondus · empilées par fonds d'origine · clic = fiche société`}>
        <Chart option={stacked(lt)} height={Math.max(TOP * 30 + 50, 200)} ariaLabel="Principales sociétés détenues"
               onClick={(p) => {
                 const c = lt.companies.slice(0, TOP).reverse()[p.dataIndex];
                 if (c) nav(`/companies/${c.isin}`);
               }} />
        <TableTwin head={['Société', 'Total', '% poche actions', 'Fonds']}
          rows={lt.companies.slice(0, TOP).map((c) => [
            <Link key={c.isin} to={`/companies/${c.isin}`}>{c.name}</Link>, eur(c.exposureEur), pct(c.pctOfEquity, 2),
            c.funds.map((f) => `${short(f.fundName, 24)} ${eur(f.eur)}`).join(' · ')])} />
      </Card>

      <section className="grid2 start">
        <Card title="Santé moyenne de mon portefeuille"
              caption="moyennes pondérées par mes euros, sur la part identifiée — couverture indiquée">
          <HealthRanges health={q} />
        </Card>
        <Card title="Répartition des notes de qualité" caption="part de mes euros identifiés, par tranche de note">
          <Chart option={qualityBars(lt.qualityDistribution)} height={230} ariaLabel="Répartition des notes de qualité" />
        </Card>
      </section>

      <section className="grid2 start">
        <Card title="Recouvrement entre mes fonds"
              caption="sociétés communes aux listes de deux fonds · recouvrement = Σ min(poids A, poids B)">
          {lt.overlaps.length ? (
            <table className="tbl"><thead><tr><th>Fonds A</th><th>Fonds B</th><th className="n">Sociétés communes</th>
              <th className="n">Recouvrement</th></tr></thead>
              <tbody>{lt.overlaps.map((o) => (
                <tr key={o.a + o.b}><td>{short(names[o.a] ?? o.a, 30)}</td><td>{short(names[o.b] ?? o.b, 30)}</td>
                  <td className="n">{o.common}</td><td className="n">{pct(o.overlapWeight, 1)}</td></tr>))}</tbody></table>
          ) : <p className="note">Aucune société commune entre les listes.</p>}
        </Card>
        <Card title="Fonds sans liste de sociétés" caption="part de ta poche actions non décomposée">
          {lt.fundsNotCovered.length ? (
            <table className="tbl"><thead><tr><th>Fonds</th><th className="n">Actions</th></tr></thead>
              <tbody>{lt.fundsNotCovered.map((f) => (
                <tr key={f.isin}><td>{short(f.name, 40)}<br /><span className="cap">{short(f.reason, 90)}</span></td>
                  <td className="n">{eur(f.equityValue)}</td></tr>))}</tbody></table>
          ) : <p className="note">Tous tes fonds actions sont décomposés.</p>}
        </Card>
      </section>

      <LearnPrompts />
    </>);
}
