import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import type { EChartsOption } from 'echarts';
import type { ConstituentDto, QualityBucketDto } from '@pfa/contracts';
import { api } from '../api/client';
import { SECTOR_NAMES_FR, eur, num, pct, qBucket, ratioX } from '../api/format';
import { Chart } from '../charts/Chart';
import { palette } from '../charts/theme';
import { Card, Segmented } from './ui';
import { Def } from './Def';
import { HealthRanges } from './HealthRanges';

type Unit = 'pct' | 'eur';
const BUCKET_LABELS = ['0–2', '2–4', '4–6', '6–8', '8–10'];

export function QualityLegend() {
  return (
    <div className="legend-q" aria-label="Légende : note de qualité">
      <span><Def k="aaqs_score">Note de qualité</Def> :</span>
      {BUCKET_LABELS.map((l, i) => (
        <span key={l}><i style={{ background: palette.quality(i + 1) }} />{l}</span>))}
      <span><i style={{ background: palette.axis() }} />n.d.</span>
    </div>);
}

const swatch = (r: ConstituentDto) => {
  const b = qBucket(r.aaqsScore);
  return b === null ? { fill: palette.axis(), ink: palette.text() }
                    : { fill: palette.quality(b + 1), ink: palette.qualityInk(b + 1) };
};

function treemap(rows: ConstituentDto[], unit: Unit): EChartsOption {
  return {
    tooltip: {
      formatter: (p: any) => {
        const r: ConstituentDto = p.data.row;
        return `<b>${r.name}</b><br/>${pct(r.weight)} du fonds · ${eur(r.eur)} chez moi<br/>`
          + `qualité ${num(r.aaqsScore, 0)}/10 · ${SECTOR_NAMES_FR[r.sector ?? ''] ?? r.sector ?? 'secteur n.d.'}`;
      },
    },
    series: [{
      type: 'treemap', roam: false, nodeClick: false, breadcrumb: { show: false },
      left: 0, right: 0, top: 0, bottom: 0,
      // a 2px surface gap between cells, never a stroked border
      itemStyle: { borderColor: palette.surface(), borderWidth: 2, gapWidth: 2, borderRadius: 3 },
      label: { show: true, fontSize: 12, overflow: 'truncate', position: 'insideTopLeft',
               formatter: (p: any) => {
                 const r: ConstituentDto = p.data.row;
                 return `${r.name}\n${unit === 'pct' ? pct(r.weight) : eur(r.eur)}`;
               } },
      data: rows.map((r) => ({
        name: r.name, value: r.weight, row: r,
        itemStyle: { color: swatch(r).fill },
        label: { color: swatch(r).ink },
      })),
    }],
  };
}

function bubbles(rows: ConstituentDto[]): EChartsOption {
  const pts = rows.filter((r) => r.revenueGrowth3yPa !== null && r.netMargin !== null);
  return {
    grid: { left: 56, right: 24, top: 16, bottom: 44, containLabel: false },
    tooltip: {
      formatter: (p: any) => {
        const r: ConstituentDto = p.data.row;
        return `<b>${r.name}</b><br/>croissance du CA ${pct(r.revenueGrowth3yPa, 0, true)} par an<br/>`
          + `marge nette ${pct(r.netMargin, 0)} · poids ${pct(r.weight)}`;
      },
    },
    xAxis: { type: 'value', name: 'Croissance du CA, 3 ans (par an)', nameLocation: 'middle', nameGap: 28,
             axisLabel: { color: palette.muted(), formatter: (v: number) => pct(v, 0) },
             splitLine: { lineStyle: { color: palette.grid() } } },
    yAxis: { type: 'value', name: 'Marge nette', nameLocation: 'middle', nameGap: 40,
             axisLabel: { color: palette.muted(), formatter: (v: number) => pct(v, 0) },
             splitLine: { lineStyle: { color: palette.grid() } } },
    series: [{
      type: 'scatter',
      // ONE colour: a bubble chart is an all-pairs form, and the palette validates only three slots
      // for it. Identity (the name) is carried by direct labels on the biggest bubbles and by tooltip.
      itemStyle: { color: palette.series1(), opacity: 0.8, borderColor: palette.surface(), borderWidth: 2 },
      symbolSize: (d: any[]) => Math.max(12, Math.sqrt(d[2]) * 120),
      label: { show: true, color: palette.text(), fontSize: 11, position: 'right',
               formatter: (p: any) => (p.data.row.rank <= 6 ? p.data.row.name : '') },
      data: pts.map((r) => ({ value: [r.revenueGrowth3yPa, r.netMargin, r.weight], row: r })),
    }],
  };
}

export function qualityBars(dist: QualityBucketDto[]): EChartsOption {
  return {
    grid: { left: 8, right: 8, top: 22, bottom: 26, containLabel: true },
    xAxis: { type: 'category', data: dist.map((d) => d.bucket), axisLabel: { color: palette.muted() },
             name: 'Note de qualité (0–10)', nameLocation: 'middle', nameGap: 26 },
    yAxis: { type: 'value', axisLabel: { show: false }, splitLine: { show: false } },
    tooltip: { trigger: 'item', formatter: (p: any) => `Notes ${p.name} : <b>${pct(p.value, 1)}</b> du poids` },
    series: [{
      type: 'bar', barWidth: 34,
      itemStyle: { borderRadius: [4, 4, 0, 0] },
      label: { show: true, position: 'top', color: palette.text(), formatter: (p: any) => pct(p.value, 0) },
      data: dist.map((d, i) => ({ value: d.weight, itemStyle: { color: palette.quality(i + 1) } })),
    }],
  };
}

type Key = 'rank' | 'name' | 'sector' | 'weight' | 'eur' | 'aaqsScore' | 'roe' | 'netMargin'
  | 'revenueGrowth3yPa' | 'netDebtToEbit' | 'esgTotal';
const COLS: { key: Key; label: string; gloss?: string; fmt: (r: ConstituentDto) => string; num?: boolean }[] = [
  { key: 'rank', label: '#', fmt: (r) => String(r.rank), num: true },
  { key: 'name', label: 'Société', fmt: (r) => r.name },
  { key: 'sector', label: 'Secteur', fmt: (r) => SECTOR_NAMES_FR[r.sector ?? ''] ?? r.sector ?? 'n.d.' },
  { key: 'weight', label: 'Poids', fmt: (r) => pct(r.weight, 2), num: true },
  { key: 'eur', label: '€ chez moi', fmt: (r) => eur(r.eur), num: true },
  { key: 'aaqsScore', label: 'Qualité', gloss: 'aaqs_score', fmt: (r) => num(r.aaqsScore, 0), num: true },
  { key: 'roe', label: 'ROE', gloss: 'roe', fmt: (r) => pct(r.roe, 0), num: true },
  { key: 'netMargin', label: 'Marge nette', gloss: 'net_margin', fmt: (r) => pct(r.netMargin, 0), num: true },
  { key: 'revenueGrowth3yPa', label: 'Croiss. CA/an', gloss: 'revenue_growth_pa',
    fmt: (r) => pct(r.revenueGrowth3yPa, 0, true), num: true },
  { key: 'netDebtToEbit', label: 'Dette/EBIT', gloss: 'net_debt_to_ebit',
    fmt: (r) => ratioX(r.netDebtToEbit), num: true },
  { key: 'esgTotal', label: 'ESG', gloss: 'esg_total', fmt: (r) => num(r.esgTotal, 0), num: true },
];

export function ConstituentsTable({ rows }: { rows: ConstituentDto[] }) {
  const [sort, setSort] = useState<{ key: Key; dir: 1 | -1 }>({ key: 'rank', dir: 1 });
  const sorted = useMemo(() => [...rows].sort((a, b) => {
    const va = a[sort.key] as number | string | null; const vb = b[sort.key] as number | string | null;
    if (va === null && vb === null) return 0;
    if (va === null) return 1;            // unknown values always sink, whatever the direction
    if (vb === null) return -1;
    return (va < vb ? -1 : va > vb ? 1 : 0) * sort.dir;
  }), [rows, sort]);
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="tbl sortable">
        <thead><tr>{COLS.map((c) => (
          <th key={c.key} className={c.num ? 'n' : undefined} aria-sort={
            sort.key === c.key ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}
              onClick={() => setSort((s) => ({ key: c.key, dir: s.key === c.key ? (s.dir === 1 ? -1 : 1) : 1 }))}>
            {c.gloss ? <Def k={c.gloss}>{c.label}</Def> : c.label}
            {sort.key === c.key ? (sort.dir === 1 ? ' ▲' : ' ▼') : ''}
          </th>))}</tr></thead>
        <tbody>{sorted.map((r) => (
          <tr key={r.isin}>{COLS.map((c) => (
            <td key={c.key} className={c.num ? 'n' : undefined}>
              {c.key === 'name'
                ? <><Link to={`/companies/${r.isin}`}>{r.name}</Link>
                    {!r.covered && <span className="pill warn"> hors couverture</span>}
                    {r.covered && r.flags > 0 && <span className="pill" title="Voir la fiche : données écartées ou anciennes"> ⚑ {r.flags}</span>}</>
                : c.fmt(r)}
            </td>))}</tr>))}</tbody>
      </table>
    </div>);
}

/** The company-level section of a fund's page. */
export function FundCompanies({ isin }: { isin: string }) {
  const nav = useNavigate();
  const { data: d, error } = useQuery({ queryKey: ['fund-companies', isin], queryFn: () => api.fundCompanies(isin) });
  const [unit, setUnit] = useState<Unit>('pct');
  if (error) return null;
  if (!d) return null;
  if (!d.covered) {
    return (
      <Card title="Sociétés du fonds" caption="composition détaillée" wide>
        <p className="note">
          Pas de liste de sociétés pour ce fonds : {d.reason ?? 'pas encore enrichi'}.
          {d.proxy.kind === null && ' Il est absent de profile/etf_proxies.json ou non couvert.'}
          {' '}Lance <code>python3 -m pfa enrich --isin {isin}</code> si un substitut est déclaré.
        </p>
      </Card>);
  }
  const rows = d.constituents ?? [];
  const cc = d.proxy.crosscheck;
  const proxied = d.proxy.kind === 'physical_proxy';
  return (
    <>
      <div className={`banner ${cc?.warn ? 'warn' : ''}`} role="note">
        <span><b>{d.topN} sociétés = {pct(d.coverageTop ?? 0, 1)} du fonds</b>
          {' '}({d.nTotal} lignes au total)</span>
        {proxied && (
          <span>Lignes issues de l'ETF physique <code>{d.proxy.isin}</code> ({d.proxy.index}), substitut de
            ce fonds <Def k="synthetic_replication">(pourquoi ?)</Def></span>)}
        {cc && cc.sectorMaxGapPts !== null && (
          <span>Écart au fonds détenu : secteurs {num(cc.sectorMaxGapPts, 1)} pt, pays {num(cc.countryMaxGapPts, 1)} pt
            {cc.warn ? ` — AU-DESSUS du seuil de ${cc.thresholdPts} pt : à lire avec prudence` : ' — dans le seuil'}</span>)}
        <span className="cap">Données Eulerpool du {d.holdingsAsOf ?? '—'} · récupérées le {d.fetchedAt?.slice(0, 10)}
          {' · '}{d.companiesWithData}/{d.topN} sociétés avec fiche</span>
      </div>

      <section className="filters" role="group" aria-label="Unité des sociétés">
        <Segmented label="Taille des cases" value={unit} onChange={setUnit}
          options={[{ value: 'pct', label: 'poids dans le fonds' }, { value: 'eur', label: '€ chez moi' }]} />
      </section>

      <Card title="Principales sociétés" caption={`surface = poids · couleur = note de qualité · clic = fiche société`} wide>
        <QualityLegend />
        <Chart option={treemap(rows, unit)} height={340} ariaLabel="Treemap des principales sociétés"
               onClick={(p) => p?.data?.row && nav(`/companies/${p.data.row.isin}`)} />
        <details open>
          <summary>Tableau (triable)</summary>
          <ConstituentsTable rows={rows} />
        </details>
      </Card>

      <section className="grid2 start">
        <Card title="Santé moyenne du fonds"
              caption={`moyennes pondérées par le poids, sur les sociétés qui ont la donnée — couverture indiquée`}>
          {d.health && <HealthRanges health={d.health} />}
        </Card>
        <Card title="Répartition des notes de qualité" caption="part du poids du fonds par tranche de note">
          {d.qualityDistribution && <Chart option={qualityBars(d.qualityDistribution)} height={230}
                                           ariaLabel="Répartition des notes de qualité" />}
          <p className="cap">Une note n'est pas un conseil : c'est le résumé d'un modèle du fournisseur
            (<Def k="aaqs_score">définition</Def>).</p>
        </Card>
      </section>

      <Card title="Croissance et rentabilité" wide
            caption="une bulle = une société · taille = poids dans le fonds · les 6 plus grosses sont nommées">
        <Chart option={bubbles(rows)} height={340} ariaLabel="Croissance du chiffre d'affaires et marge nette"
               onClick={(p) => p?.data?.row && nav(`/companies/${p.data.row.isin}`)} />
        <p className="cap">
          {rows.filter((r) => r.revenueGrowth3yPa !== null && r.netMargin !== null).length} sociétés sur {rows.length}
          {' '}ont les deux données. Une croissance passée très élevée peut venir d'une base de départ très basse.
        </p>
      </Card>
    </>);
}
