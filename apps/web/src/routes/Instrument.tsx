import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import type { EChartsOption } from 'echarts';
import type { FundRow } from '@pfa/contracts';
import { api } from '../api/client';
import {
  ASSET_LABELS, COUNTRY_LABELS, ENVELOPE_LABELS, REGION_LABELS, SECTOR_LABELS,
  eur, pct, signCls,
} from '../api/format';
import { Chart } from '../charts/Chart';
import { Figure } from '../components/Delta';
import { palette, withAlpha, echarts } from '../charts/theme';
import { tickSeries } from '../charts/ticks';
import { Card, Segmented, TableTwin, Tile } from '../components/ui';
import { FundCompanies } from '../components/FundCompanies';
import { LearnPrompts } from '../components/LearnPrompts';

type Unit = 'pct' | 'eur';
type Geo = 'country' | 'region';

const RESIDUAL = ['Unclassified', 'Other', 'Other (tail)'];
const countryName = (b: string) => COUNTRY_LABELS[b] ?? REGION_LABELS[b] ?? b;
const qty = (v: number | null) =>
  v === null ? '—' : new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 4 }).format(v);

/** Horizontal bars for one fund breakdown. `mark` draws the portfolio-wide equity average. */
function bars(rows: FundRow[], naming: (b: string) => string, unit: Unit,
              mark?: Record<string, number>): EChartsOption {
  const data = [...rows].reverse();
  const val = (r: FundRow) => (unit === 'pct' ? r.weight : r.eur);
  return {
    grid: { left: 150, right: 70, top: 6, bottom: 6, containLabel: false },
    xAxis: { type: 'value',
             // headroom for the labels, and for a reference mark sitting beyond the longest bar
             max: Math.max(...rows.map(val), ...(mark && unit === 'pct' ? Object.values(mark) : []), 0.01), axisLabel: { show: false },
             splitLine: { show: false } },
    yAxis: { type: 'category', data: data.map((r) => naming(r.bucket)),
             axisLabel: { color: palette.muted(), fontSize: 12 } },
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        const r = data[p.dataIndex]!;
        const m = mark?.[r.bucket];
        return `<b>${naming(r.bucket)}</b><br/>${pct(r.weight)} du fonds · ${eur(r.eur)} chez moi`
          + (m !== undefined ? `<br/>moyenne de ma poche actions : ${pct(m)}` : '');
      },
    },
    series: [{
      type: 'bar', barWidth: 16,
      itemStyle: {
        borderRadius: [0, 4, 4, 0],
        color: (p: any) => RESIDUAL.includes(data[p.dataIndex]!.bucket)
          ? palette.axis() : palette.series1(),
      },
      label: { show: true, position: 'right', color: palette.text(), fontSize: 12,
               formatter: (p: any) => (unit === 'pct' ? pct(data[p.dataIndex]!.weight)
                                                       : eur(data[p.dataIndex]!.eur)) },
      data: data.map(val),
    }, ...(mark && unit === 'pct'
      ? [tickSeries(data.flatMap((r) => mark[r.bucket] !== undefined
          ? [[mark[r.bucket]!, naming(r.bucket)] as [number, string]] : []))]
      : [])],
  };
}

function perfChart(perf: Record<string, number | undefined>): EChartsOption {
  const items = ([['1y', '1 an'], ['3y_annualized', '3 ans (annualisé)'],
                  ['5y_annualized', '5 ans (annualisé)']] as const)
    .filter(([k]) => perf[k] !== undefined);
  return {
    grid: { left: 8, right: 8, top: 24, bottom: 28, containLabel: true },
    xAxis: { type: 'category', data: items.map(([, l]) => l),
             axisLabel: { color: palette.muted() } },
    yAxis: { type: 'value', axisLabel: { show: false }, splitLine: { show: false } },
    tooltip: { trigger: 'item', formatter: (p: any) => `${p.name} : <b>${pct(p.value, 1, true)}</b>` },
    series: [{
      type: 'bar', barWidth: 36,
      itemStyle: { borderRadius: [4, 4, 0, 0], color: palette.series1() },
      label: { show: true, position: 'top', color: palette.text(),
               formatter: (p: any) => pct(p.value, 1, true) },
      data: items.map(([k]) => perf[k]!),
    }],
  };
}

function historyChart(h: { asOf: string; value: number }[]): EChartsOption {
  const line = palette.series1();
  return {
    grid: { left: 8, right: 56, top: 28, bottom: 8, containLabel: true },
    xAxis: { type: 'category', data: h.map((p) => p.asOf), axisLabel: { color: palette.muted() },
             boundaryGap: false },
    yAxis: { type: 'value', scale: true, axisLabel: { color: palette.muted(),
             formatter: (v: number) => eur(v) }, splitLine: { lineStyle: { color: palette.grid() } } },
    tooltip: { trigger: 'axis', formatter: (p: any) => `${p[0].axisValue}<br/><b>${eur(p[0].value)}</b>` },
    series: [{
      type: 'line', data: h.map((p) => p.value),
      // a gentle curve only when there are enough points for it to mean something
      smooth: h.length > 3 ? 0.25 : false,
      lineStyle: { width: 2, color: line }, itemStyle: { color: line, borderColor: palette.surface(), borderWidth: 2 },
      symbolSize: 9,
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: withAlpha(line, 0.26) }, { offset: 1, color: withAlpha(line, 0) }]) },
      // the latest value is named at the end of the line instead of making the reader hunt for it
      endLabel: { show: true, formatter: (p: any) => eur(p.value as number), color: palette.text(),
                  fontSize: 12, distance: 8 },
    }],
  };
}

export default function Instrument() {
  const { isin = '' } = useParams();
  const { data: d, error, isLoading } = useQuery({
    queryKey: ['instrument', isin], queryFn: () => api.instrument(isin) });
  const [unit, setUnit] = useState<Unit>('pct');
  const [geo, setGeo] = useState<Geo>('country');

  if (error) {
    return (<><p className="crumb"><Link to="/portfolio">← Portefeuille</Link></p>
      <Card title="Ligne introuvable"><p className="note">{String(error)}</p></Card></>);
  }
  if (!d) return <p className="cap">{isLoading ? 'Chargement…' : null}</p>;

  const c = d.composition;
  const hasGeoSector = c.country.length > 0 || c.sector.length > 0;
  const geoRows = geo === 'country' ? c.country : c.region;
  const regionMark = Object.fromEntries(c.portfolioRegion.map((r) => [r.bucket, r.pct]));
  const sectorMark = Object.fromEntries(c.portfolioSector.map((r) => [r.bucket, r.pct]));
  const p = d.position;
  const envelopes = [...new Set(p.lines.map((l) => ENVELOPE_LABELS[l.envelope] ?? l.envelope))];
  const perf = d.performance;
  const perfLabels = [['1y', '1 an'], ['3y_annualized', '3 ans (annualisé)'],
                      ['5y_annualized', '5 ans (annualisé)']] as const;
  const unitCap = unit === 'pct' ? 'part de la poche actions du fonds'
                                 : 'euros que cela représente dans ma ligne';

  const bucketTable = (rows: FundRow[], naming: (b: string) => string, head: string) => (
    <TableTwin head={[head, '% du fonds', '€ chez moi']}
      rows={rows.map((r) => [naming(r.bucket), pct(r.weight), eur(r.eur)])} />);

  return (
    <>
      <p className="crumb"><Link to="/portfolio">← Portefeuille</Link></p>
      <header className="app">
        <div>
          <h1>{d.name}</h1>
          <div className="hero"><Figure text={eur(p.value)} /></div>
          <div className="sub">{d.isin} · {envelopes.join(', ')}</div>
        </div>
        <div className="sub">Au {d.asOf}</div>
      </header>

      <section className="tiles">
        <Tile label="Valeur" value={eur(p.value)} delta={`${pct(p.weight)} de mon patrimoine`} />
        <Tile label="Plus-value latente" value={eur(p.pnl)} cls={signCls(p.pnl)}
              delta={`${pct(p.pnlPct, 1, true)} · investi ${eur(p.costBasis)}`} />
        <Tile label="Frais courants (TER)" value={pct(d.ter, 2)}
              delta={p.feeEurPerYear !== null ? `${eur(p.feeEurPerYear)} par an à cet encours` : '—'} />
        <Tile label="Éligible PEA"
              value={d.peaEligible === null ? '—' : d.peaEligible ? 'Oui' : 'Non'}
              delta={`SRI ${d.sri ?? '—'}/7`} />
      </section>

      {hasGeoSector && (
        <section className="filters" role="group" aria-label="Affichage des décompositions">
          <Segmented label="Unité" value={unit} onChange={setUnit}
            options={[{ value: 'pct', label: '% du fonds' }, { value: 'eur', label: '€ chez moi' }]} />
          {c.country.length > 0 && (
            <Segmented label="Géographie" value={geo} onChange={setGeo}
              options={[{ value: 'country', label: 'Pays' }, { value: 'region', label: 'Régions' }]} />)}
        </section>)}

      <section className="grid2 start">
        {c.assetClass.length === 1 ? (
          // one asset class is a fact, not a chart: a single bar would be an empty gesture
          <Card title="Classe d'actifs" caption="intégralité du fonds">
            <div className="hero" style={{ fontSize: 34 }}>
              {ASSET_LABELS[c.assetClass[0]!.bucket] ?? c.assetClass[0]!.bucket}
            </div>
            <p className="cap">soit {eur(p.value)}</p>
          </Card>
        ) : c.assetClass.length > 1 && (
          <Card title="Classes d'actifs" caption="part du fonds">
            <Chart option={bars(c.assetClass, (b) => ASSET_LABELS[b] ?? b, 'pct')}
                   height={Math.max(c.assetClass.length * 34, 90)} ariaLabel="Classes d'actifs" />
            {bucketTable(c.assetClass, (b) => ASSET_LABELS[b] ?? b, 'Classe')}
          </Card>)}

        {geoRows.length > 0 && (
          <Card title="Géographie" caption={unitCap}>
            <Chart option={bars(geoRows, geo === 'country' ? countryName : (b) => REGION_LABELS[b] ?? b,
                                unit, geo === 'region' ? regionMark : undefined)}
                   height={Math.max(geoRows.length * 30, 120)} ariaLabel="Géographie du fonds" />
            {geo === 'region' && unit === 'pct' && (
              <p className="cap">Le trait vertical marque la moyenne de toute ma poche actions.</p>)}
            {bucketTable(geoRows, geo === 'country' ? countryName : (b) => REGION_LABELS[b] ?? b,
                         geo === 'country' ? 'Pays' : 'Région')}
          </Card>)}

        {c.sector.length > 0 && (
          <Card title="Secteurs (GICS)" caption={unitCap}>
            <Chart option={bars(c.sector, (b) => SECTOR_LABELS[b] ?? b, unit, sectorMark)}
                   height={Math.max(c.sector.length * 30, 120)} ariaLabel="Secteurs du fonds" />
            {unit === 'pct' && (
              <p className="cap">Le trait vertical marque la moyenne de toute ma poche actions.</p>)}
            {bucketTable(c.sector, (b) => SECTOR_LABELS[b] ?? b, 'Secteur')}
          </Card>)}

        {!hasGeoSector && (
          <Card title="Décomposition">
            <p className="note">
              {c.assetClass.some((a) => a.bucket === 'bond')
                ? 'Fonds obligataire : la géographie et les secteurs ne sont calculés que sur la poche '
                  + 'actions, que ce fonds n’a pas.'
                : 'Aucune décomposition chiffrée publiée par l’émetteur — rien n’a été deviné. '
                  + 'Cette ligne compte en « Non documenté » dans la vue d’ensemble.'}
            </p>
          </Card>)}

      </section>

      <FundCompanies isin={d.isin} />

      <section className="grid2 start">
        <Card title="Performance de l'instrument"
              caption="Publiée par la source, nette de frais — ce n'est pas ma performance sur la ligne">
          {Object.keys(perf).length ? (<>
            <Chart option={perfChart(perf)} height={220} ariaLabel="Performance publiée" />
            <TableTwin head={['Horizon', 'Performance']}
              rows={perfLabels.filter(([k]) => perf[k] !== undefined)
                .map(([k, l]) => [l, pct(perf[k]!, 1, true)])} />
          </>) : <p className="note">Aucune performance publiée dans la fiche.</p>}
        </Card>

        <Card title="Évolution de ma valeur"
              caption="Un point par snapshot Finary — la courbe se remplit à chaque pfa sync">
          {d.history.length >= 2 ? (
            <Chart option={historyChart(d.history)} height={220} ariaLabel="Évolution de ma valeur" />
          ) : (
            <p className="note">Un seul snapshot : pas encore de courbe.</p>)}
          <TableTwin head={['Date', 'Valeur', 'Quantité', 'Cours']}
            rows={d.history.map((h) => [h.asOf, eur(h.value), qty(h.quantity),
                                        h.unitPrice === null ? '—' : eur(h.unitPrice, 2)])} />
          {d.history.length < 5 && (
            <p className="cap">
              Finary n'a pas d'API d'historique : ce qui n'a pas été archivé par un sync est perdu.
            </p>)}
        </Card>
      </section>

      <LearnPrompts isin={d.isin} />

      <section className="grid2 start">
        <Card title="Ma position" caption="Prix de revient et quantités issus de Finary">
          <div style={{ overflowX: 'auto' }}>
            <table className="tbl">
              <thead><tr><th>Compte</th><th className="n">Qté</th><th className="n">Cours</th>
                <th className="n">Investi</th><th className="n">Valeur</th><th className="n">+/−</th></tr></thead>
              <tbody>{p.lines.map((l) => (
                <tr key={l.accountName}>
                  <td>{l.accountName}<br />
                    <span className="cap">{ENVELOPE_LABELS[l.envelope] ?? l.envelope}</span></td>
                  <td className="n">{qty(l.quantity)}</td>
                  <td className="n">{eur(l.unitPrice, 2)}</td>
                  <td className="n">{eur(l.costBasis)}</td>
                  <td className="n">{eur(l.value)}</td>
                  <td className={`n ${signCls(l.pnl)}`}>{eur(l.pnl)}</td>
                </tr>))}</tbody>
            </table>
          </div>
          <p className="cap">Le cours est le dernier prix vu par Finary, pas la valeur liquidative officielle.</p>
        </Card>

        <Card title="Caractéristiques" caption="Fiche instrument, sources citées">
          {d.hasInstrumentData ? (<>
            <table className="tbl"><tbody>
              {([['ISIN', d.isin], ['Émetteur', d.issuer], ['Indice suivi', d.index],
                 ['Réplication', d.replication], ['Fiche mise à jour le', d.fetchedAt]] as const)
                .filter(([, v]) => v).map(([k, v]) => (
                  <tr key={k}><th>{k}</th><td>{v}</td></tr>))}
            </tbody></table>
            {d.notes && <p className="note">{d.notes}</p>}
            <ul>{d.sources.map((s) => (
              <li key={s.url}><a href={s.url} target="_blank" rel="noopener noreferrer">{s.url}</a>
                {s.fetched_at && <span className="cap"> ({s.fetched_at})</span>}</li>))}</ul>
          </>) : (
            <p className="note">
              Aucune fiche pour cet ISIN : lance <code>/lookup {d.isin}</code>.
            </p>)}
        </Card>
      </section>
    </>
  );
}
