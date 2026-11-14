import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import type { EChartsOption } from 'echarts';
import { api } from '../api/client';
import {
  ASSET_LABELS, COUNTRY_LABELS, ENVELOPE_LABELS, REGION_LABELS, SECTOR_LABELS,
  eur, pct, signCls,
} from '../api/format';
import { Chart } from '../charts/Chart';
import { palette } from '../charts/theme';
import { tickSeries } from '../charts/ticks';
import { Card, TableTwin, Tile } from '../components/ui';
import { LookthroughBlock } from '../components/LookthroughBlock';
import type { BucketRow } from '@pfa/contracts';

/** Colour follows the ENVELOPE, never its rank: adding or emptying one never repaints the others.
 *  The ring is drawn in slot order, which keeps neighbouring hues to the validated adjacent pairs. */
const ENVELOPE_SLOT: Record<string, number> = {
  pea: 1, assurance_vie: 2, livret_a: 3, current: 4, ldds: 5, per: 6, cto: 7, pea_pme: 8,
};

const label = (m: Record<string, string>) => (b: string) => m[b] ?? b;
/** Country buckets can also carry the synthetic 'Unclassified' and 'Other (tail)' rows. */
const countryName = (b: string) => COUNTRY_LABELS[b] ?? REGION_LABELS[b] ?? b;

function bars(rows: BucketRow[], naming: (b: string) => string, total: number,
              targets?: Record<string, number>): EChartsOption {
  const data = [...rows].reverse();
  return {
    grid: { left: 140, right: 64, top: 6, bottom: 6, containLabel: false },
    xAxis: { type: 'value',
             max: Math.max(...rows.map((r) => r.pct), ...Object.values(targets ?? {}), 0.01), axisLabel: { show: false },
             splitLine: { show: false } },
    yAxis: { type: 'category', data: data.map((r) => naming(r.bucket)),
             axisLabel: { color: palette.muted(), fontSize: 12 } },
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        const r = data[p.dataIndex]!;
        const t = targets?.[r.bucket];
        return `<b>${eur(r.value)}</b> · ${pct(r.pct)}${naming(r.bucket) ? ` — ${naming(r.bucket)}` : ''}`
          + (t !== undefined ? `<br/>cible ${pct(t)}` : '');
      },
    },
    series: [{
      type: 'bar', barWidth: 16,
      // 4px rounded data-end, square at the baseline
      itemStyle: {
        borderRadius: [0, 4, 4, 0],
        color: (p: any) => ['Unclassified', 'Other', 'Other (tail)'].includes(data[p.dataIndex]!.bucket)
          ? palette.axis() : palette.series1(),
      },
      label: { show: true, position: 'right', color: palette.text(), fontSize: 12,
               formatter: (p: any) => pct(data[p.dataIndex]!.pct) },
      data: data.map((r) => r.pct),
    }, ...(targets
      ? [tickSeries(data.flatMap((r) => targets[r.bucket] !== undefined
          ? [[targets[r.bucket]!, naming(r.bucket)] as [number, string]] : []))]
      : [])],
  };
}

function donut(rows: BucketRow[], total: number): EChartsOption {
  // Ordered by palette SLOT, not by value: the ring's neighbours are then exactly the palette's
  // documented adjacent pairs, which keeps the weak orange/yellow pair opposite instead of
  // touching. Sorting by value would make that adjacency a matter of luck.
  const live = rows.filter((r) => r.value > 0)
    .sort((a, b) => (ENVELOPE_SLOT[a.bucket] ?? 99) - (ENVELOPE_SLOT[b.bucket] ?? 99));
  return {
    tooltip: { trigger: 'item', formatter: (p: any) =>
      `<b>${eur(p.value)}</b> · ${pct(p.percent / 100)}<br/>${p.name}` },
    legend: { bottom: 0, textStyle: { color: palette.muted() } },
    series: [{
      type: 'pie', radius: ['58%', '82%'], center: ['50%', '42%'],
      // 2px surface gap between slices — a gap, never a stroked border
      itemStyle: { borderColor: palette.surface(), borderWidth: 2 },
      label: { show: true, position: 'inside', formatter: (p: any) =>
        p.percent >= 7 ? `${Math.round(p.percent)} %` : '',
        fontSize: 12, fontWeight: 600 },
      labelLine: { show: false },
      data: live.map((r) => ({
        name: ENVELOPE_LABELS[r.bucket] ?? r.bucket, value: r.value,
        itemStyle: { color: palette.cat(ENVELOPE_SLOT[r.bucket] ?? 8) },
        label: { color: palette.catInk(ENVELOPE_SLOT[r.bucket] ?? 8) },
      })),
    }],
  };
}

export default function Portfolio() {
  const { data, isLoading, error } = useQuery({ queryKey: ['report'], queryFn: () => api.report() });

  if (error) return <Card title="Erreur"><p className="note">{String(error)}</p></Card>;
  if (!data) return <p className="cap">{isLoading ? 'Chargement…' : null}</p>;

  const ex = data.exposure;
  const invested = data.positions.filter((p) => p.kind !== 'cash')
    .reduce((s, p) => s + p.value, 0);
  const withPnl = data.positions.filter((p) => p.pnl !== null);
  const pnl = withPnl.reduce((s, p) => s + (p.pnl ?? 0), 0);
  const cost = withPnl.reduce((s, p) => s + (p.costBasis ?? 0), 0);
  const targets = Object.fromEntries(
    Object.entries(data.driftVsTargets).map(([dim, rows]) =>
      [dim, Object.fromEntries((rows ?? []).map((r) => [r.bucket, r.target]))]));

  return (
    <>
      <header className="app">
        <div>
          <h1>Patrimoine financier · au {data.asOf}</h1>
          <div className="hero">{eur(data.totalValue)}</div>
          <div className="sub">
            {data.changeVsPrevious !== null && (
              <span className={signCls(data.changeVsPrevious)}>
                {data.changeVsPrevious > 0 ? '▲' : '▼'} {eur(data.changeVsPrevious)}
              </span>)}
            {data.previousAsOf && ` depuis le ${data.previousAsOf}`}
          </div>
        </div>
        <div className="sub">Source : Finary (lecture seule) · décompositions : Boursorama / justETF</div>
      </header>

      {data.perimeterChanges.note && (
        <Card title="Changement de périmètre"
              caption="À retrancher du Δ avant d'y lire une performance">
          <p className="note">{data.perimeterChanges.note}</p>
          <TableTwin head={['Compte', 'Dernier solde', 'Vu le', 'Statut']}
            rows={data.perimeterChanges.gone.map((g) => [
              g.name ?? g.id, eur(g.lastBalance), g.lastSeen,
              g.closedOn ? `clôturé le ${g.closedOn}` : 'clôture NON déclarée'])}
            summary="Comptes sortis" />
        </Card>)}

      {data.receivables.items.length > 0 && (
        <Card title="Créances — hors total Finary"
              caption="Argent remis qui te reviendra · estimation saisie à la main, hors exposition et performance">
          <div className="ghost">
            <table className="tbl">
              <thead><tr><th>Créance</th><th className="n">Versé</th>
                <th className="n">Restitution attendue</th><th className="n">Retenue attendue</th>
                <th>Date</th></tr></thead>
              <tbody>{data.receivables.items.map((i) => (
                <tr key={i.id}>
                  <td>{i.label}<br /><span className="cap">payé le {i.paidOn ?? '—'}</span></td>
                  <td className="n">{eur(i.paid)}</td>
                  <td className="n">{eur(i.expectedRefund)}</td>
                  <td className="n">{eur(i.expectedRetention)}</td>
                  <td>{i.expectedRefundDate ?? 'inconnue'}</td>
                </tr>))}</tbody>
            </table>
            <p className="note">
              Total Finary {eur(data.totalValue)} · avec créances{' '}
              <b>{eur(data.receivables.totalWithReceivables)}</b>
            </p>
          </div>
        </Card>)}

      <section className="tiles">
        <Tile label="Investi (hors liquidités)" value={eur(invested)}
              delta={`${pct(invested / data.totalValue)} du total`} />
        <Tile label="Plus-value latente" value={eur(pnl)} cls={signCls(pnl)}
              delta={`${pct(cost ? pnl / cost : null, 1, true)} sur prix de revient connu`} />
        <Tile label="Frais des fonds / an" value={eur(data.fees.fundFeesEurPerYear)}
              delta={`TER moyen ${pct(data.fees.weightedTerOnCovered, 2)} · couverture ${pct(data.fees.terCoveragePct, 0)}`} />
        <Tile label="Concentration" value={pct(data.concentration.top1Pct)}
              delta={`top 5 ${pct(data.concentration.top5Pct)} · ${data.concentration.nPositions} lignes`} />
      </section>

      <section className="grid2">
        <Card title="Par enveloppe" caption="Part du total">
          <Chart option={donut(data.envelopes, data.totalValue)} height={300}
                 ariaLabel="Répartition par enveloppe" />
          <TableTwin head={['Enveloppe', 'Montant', 'Part']}
            rows={data.envelopes.map((e) => [
              ENVELOPE_LABELS[e.bucket] ?? e.bucket, eur(e.value), pct(e.pct)])} />
        </Card>
        <Card title="Classes d'actifs" caption="Transparisation des fonds · trait = cible">
          <Chart option={bars(ex.assetClass, label(ASSET_LABELS), ex.totalValue, targets['asset_class'])}
                 height={Math.max(ex.assetClass.length * 34, 120)} ariaLabel="Classes d'actifs" />
          <TableTwin head={['Classe', 'Montant', 'Part']}
            rows={ex.assetClass.map((r) => [
              ASSET_LABELS[r.bucket] ?? r.bucket, eur(r.value), pct(r.pct)])} />
        </Card>
        <Card title="Géographie (poche actions)"
              caption={`Couverture ${pct(ex.coverage.geoPct, 0)} · trait = cible`}>
          <Chart option={bars(ex.region, label(REGION_LABELS), ex.equityValue, targets['region'])}
                 height={Math.max(ex.region.length * 34, 120)} ariaLabel="Géographie" />
          <TableTwin head={['Région', 'Montant', 'Part']}
            rows={ex.region.map((r) => [
              REGION_LABELS[r.bucket] ?? r.bucket, eur(r.value), pct(r.pct)])} />
        </Card>
        <Card title="Secteurs (poche actions)"
              caption={`GICS · couverture ${pct(ex.coverage.sectorPct, 0)}`}>
          <Chart option={bars(ex.sector, label(SECTOR_LABELS), ex.equityValue)}
                 height={Math.max(ex.sector.length * 34, 120)} ariaLabel="Secteurs" />
          <TableTwin head={['Secteur', 'Montant', 'Part']}
            rows={ex.sector.map((r) => [
              SECTOR_LABELS[r.bucket] ?? r.bucket, eur(r.value), pct(r.pct)])} />
        </Card>
        <Card title="Principaux pays" caption="Poche actions, transparisée">
          <Chart option={bars(ex.country, countryName, ex.equityValue)}
                 height={Math.max(ex.country.length * 34, 120)} ariaLabel="Pays" />
          <TableTwin head={['Pays', 'Montant', 'Part']}
            rows={ex.country.map((r) => [
              COUNTRY_LABELS[r.bucket] ?? REGION_LABELS[r.bucket] ?? r.bucket,
              eur(r.value), pct(r.pct)])} />
        </Card>
      </section>

      <LookthroughBlock />

      <Card title="Lignes" caption={`${data.positions.length} lignes`} wide>
        <div style={{ overflowX: 'auto' }}>
          <table className="tbl">
            <thead><tr>
              <th>Ligne</th><th>Enveloppe</th><th className="n">Valeur</th><th className="n">Poids</th>
              <th className="n">+/− latente</th><th className="n">%</th><th className="n">TER</th>
            </tr></thead>
            <tbody>{data.positions.map((p) => (
              <tr key={p.key}>
                <td>{p.isin ? <Link to={`/instruments/${p.isin}`}>{p.name}</Link> : p.name}<br />
                  <span className="cap">{p.isin ?? p.kind}</span>
                  {!p.hasInstrumentData && !['cash', 'fonds_euros'].includes(p.kind) && (
                    <span className="pill"> à documenter</span>)}</td>
                <td>{ENVELOPE_LABELS[p.envelope] ?? p.envelope}</td>
                <td className="n">{eur(p.value)}</td>
                <td className="n">{pct(p.weight)}</td>
                <td className={`n ${signCls(p.pnl)}`}>{eur(p.pnl)}</td>
                <td className={`n ${signCls(p.pnlPct)}`}>{pct(p.pnlPct, 1, true)}</td>
                <td className="n">{pct(p.ter, 2)}</td>
              </tr>))}</tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
