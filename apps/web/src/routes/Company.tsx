import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import type { EChartsOption } from 'echarts';
import type { CompanyRecord } from '@pfa/contracts';
import { api } from '../api/client';
import { SECTOR_NAMES_FR, compact, eur, marketCap, num, pct, ratioX } from '../api/format';
import { Chart } from '../charts/Chart';
import { palette } from '../charts/theme';
import { Card, TableTwin, Tile } from '../components/ui';
import { Def } from '../components/Def';
import { LearnPrompts } from '../components/LearnPrompts';

const HORIZONS = ['1y', '3y', '5y', '10y'] as const;
const HLAB: Record<string, string> = { '1y': '1 an', '3y': '3 ans', '5y': '5 ans', '10y': '10 ans' };

function history(rec: CompanyRecord): EChartsOption {
  const h = rec.history;
  return {
    grid: { left: 8, right: 8, top: 34, bottom: 8, containLabel: true },
    legend: { top: 0, textStyle: { color: palette.muted() } },
    tooltip: { trigger: 'axis', formatter: (ps: any) => `<b>${ps[0].axisValue}</b><br/>`
      + ps.map((p: any) => `${p.seriesName} : ${compact(p.value)} ${rec.currency ?? ''}`).join('<br/>') },
    xAxis: { type: 'category', data: h.map((x) => String(x.year)), axisLabel: { color: palette.muted() } },
    yAxis: { type: 'value', axisLabel: { color: palette.muted(), formatter: (v: number) => compact(v) },
             splitLine: { lineStyle: { color: palette.grid() } } },
    series: [
      { name: "Chiffre d'affaires", type: 'bar', itemStyle: { color: palette.cat(1), borderRadius: [3, 3, 0, 0] },
        data: h.map((x) => x.revenue) },
      { name: 'Résultat net', type: 'bar', itemStyle: { color: palette.cat(2), borderRadius: [3, 3, 0, 0] },
        data: h.map((x) => x.net_income) },
    ],
  };
}

function profitability(rec: CompanyRecord): EChartsOption {
  const h = rec.history;
  return {
    grid: { left: 8, right: 16, top: 34, bottom: 8, containLabel: true },
    legend: { top: 0, textStyle: { color: palette.muted() } },
    tooltip: { trigger: 'axis', formatter: (ps: any) => `<b>${ps[0].axisValue}</b><br/>`
      + ps.map((p: any) => `${p.seriesName} : ${pct(p.value, 0)}`).join('<br/>') },
    xAxis: { type: 'category', data: h.map((x) => String(x.year)), axisLabel: { color: palette.muted() } },
    yAxis: { type: 'value', axisLabel: { color: palette.muted(), formatter: (v: number) => pct(v, 0) },
             splitLine: { lineStyle: { color: palette.grid() } } },
    series: [
      { name: 'ROE', type: 'line', symbolSize: 8, lineStyle: { width: 2, color: palette.cat(1) },
        itemStyle: { color: palette.cat(1) }, data: h.map((x) => x.roe) },
      { name: 'ROIC', type: 'line', symbolSize: 8, lineStyle: { width: 2, color: palette.cat(2) },
        itemStyle: { color: palette.cat(2) }, data: h.map((x) => x.roic) },
    ],
  };
}

function margins(rec: CompanyRecord): EChartsOption {
  const m = rec.margins;
  const mk = (name: string, k: 'gross' | 'ebit' | 'net', slot: number) => ({
    name, type: 'bar' as const, itemStyle: { color: palette.cat(slot), borderRadius: [3, 3, 0, 0] },
    data: HORIZONS.map((h) => m[k][h]) });
  return {
    grid: { left: 8, right: 8, top: 34, bottom: 8, containLabel: true },
    legend: { top: 0, textStyle: { color: palette.muted() } },
    tooltip: { trigger: 'axis', formatter: (ps: any) => `<b>moyenne sur ${ps[0].axisValue}</b><br/>`
      + ps.map((p: any) => `${p.seriesName} : ${pct(p.value, 0)}`).join('<br/>') },
    xAxis: { type: 'category', data: HORIZONS.map((h) => HLAB[h]!), axisLabel: { color: palette.muted() } },
    yAxis: { type: 'value', axisLabel: { color: palette.muted(), formatter: (v: number) => pct(v, 0) },
             splitLine: { lineStyle: { color: palette.grid() } } },
    series: [mk('Marge brute', 'gross', 1), mk("Marge d'exploitation", 'ebit', 2), mk('Marge nette', 'net', 3)],
  };
}

function esgBars(e: NonNullable<CompanyRecord['esg']>): EChartsOption {
  const rows = [['Environnement', e.environment], ['Social', e.social], ['Gouvernance', e.governance],
                ['Total', e.total]] as [string, number | null][];
  const data = [...rows].reverse();
  return {
    grid: { left: 110, right: 50, top: 6, bottom: 6, containLabel: false },
    xAxis: { type: 'value', max: 100, axisLabel: { show: false }, splitLine: { show: false } },
    yAxis: { type: 'category', data: data.map((r) => r[0]), axisLabel: { color: palette.muted() } },
    tooltip: { trigger: 'item', formatter: (p: any) => `${p.name} : <b>${num(p.value, 0)}</b> / 100` },
    series: [{ type: 'bar', barWidth: 16, itemStyle: { color: palette.series1(), borderRadius: [0, 4, 4, 0] },
               label: { show: true, position: 'right', color: palette.text(), formatter: (p: any) => num(p.value, 0) },
               data: data.map((r) => r[1]) }],
  };
}

const AAQS_LABELS: [string, string, (v: number | null) => string][] = [
  ['revenue_growth_3y_pa', 'Croissance du CA, 3 ans (par an)', (v) => pct(v, 0, true)],
  ['revenue_growth_10y_pa', 'Croissance du CA, 10 ans (par an)', (v) => pct(v, 0, true)],
  ['ebit_growth_3y_pa', "Croissance de l'EBIT, 3 ans (par an)", (v) => pct(v, 0, true)],
  ['ebit_growth_10y_pa', "Croissance de l'EBIT, 10 ans (par an)", (v) => pct(v, 0, true)],
  ['net_debt_to_ebit', 'Dette nette / EBIT', ratioX],
  ['ebit_max_drawdown_10y', "Plus forte baisse de l'EBIT sur 10 ans", (v) => pct(v, 0)],
  ['profit_continuity_10y', 'Années bénéficiaires sur 10', (v) => (v === null ? 'n.d.' : `${num(v, 0)} / 10`)],
  ['return_on_equity', 'ROE', (v) => pct(v, 0)],
  ['roce', 'ROCE', (v) => pct(v, 0)],
];

const EXPOSURE_LABELS: Record<string, string> = {
  adultContent: 'Contenu adulte', alcoholic: 'Alcool', animalTesting: 'Tests sur animaux', coalEnergy: 'Charbon',
  firearms: 'Armes à feu', furLeather: 'Fourrure / cuir', gambling: 'Jeux d\'argent', gmo: 'OGM',
  hazardousSubstances: 'Substances dangereuses', militaryContract: 'Contrats militaires', nuclear: 'Nucléaire',
  palmOil: 'Huile de palme', pesticides: 'Pesticides', tobacco: 'Tabac',
  catholic: 'Valeurs catholiques (sens non documenté)',
};

export default function Company() {
  const { isin = '' } = useParams();
  const { data, error, isLoading } = useQuery({ queryKey: ['company', isin], queryFn: () => api.company(isin) });
  if (error) {
    return (<><p className="crumb"><Link to="/portfolio">← Portefeuille</Link></p>
      <Card title="Société introuvable"><p className="note">{String(error)}</p></Card></>);
  }
  if (!data) return <p className="cap">{isLoading ? 'Chargement…' : null}</p>;
  const { company: c, held } = data;
  const m = c.metrics;
  const aq = c.quality.aaqs;
  const hasHistory = c.history.length > 1;

  return (
    <>
      <p className="crumb"><Link to="/portfolio">← Portefeuille</Link></p>
      <header className="app">
        <div>
          <h1>{c.name}</h1>
          <div className="sub">
            {[c.ticker, SECTOR_NAMES_FR[c.sector ?? ''] ?? c.sector, c.industry, c.country].filter(Boolean).join(' · ')}
            {' · '}capitalisation {marketCap(c.market_cap_m, c.currency)}
            {c.employees ? ` · ${new Intl.NumberFormat('fr-FR').format(c.employees)} salariés` : ''}
          </div>
        </div>
        <div className="sub">{c.isin}</div>
      </header>

      {!c.covered && (
        <div className="banner warn" role="note">Société hors couverture du fournisseur : aucune donnée de santé.</div>)}

      <section className="tiles">
        <Tile label="Mon exposition indirecte" value={held ? eur(held.exposureEur) : '—'}
              delta={held ? `${pct(held.pctOfEquity)} de ma poche actions · via ${held.funds.length} fonds`
                          : 'pas dans mes fonds enrichis'} />
        <Tile label={<Def k="roic">ROIC</Def>} value={pct(m['roic'] ?? null, 0)}
              delta={<>ROE <Def k="roe">{pct(m['roe'] ?? null, 0)}</Def></>} />
        <Tile label={<Def k="operating_margin">Marge d'exploitation</Def>} value={pct(m['operating_margin'] ?? null, 0)}
              delta={<>marge nette {pct(m['net_margin'] ?? null, 0)}</>} />
        <Tile label={<Def k="net_debt_to_ebit">Dette nette / EBIT</Def>}
              value={ratioX(aq['net_debt_to_ebit'] ?? null)}
              delta={aq['net_debt_to_ebit'] !== null && (aq['net_debt_to_ebit'] ?? 0) < 0 ? 'trésorerie nette' : ' '} />
      </section>

      {held && (
        <Card title="Où je la détiens" caption="euros de ma poche actions, par fonds" wide>
          <table className="tbl"><thead><tr><th>Fonds</th><th className="n">Poids dans le fonds</th>
            <th className="n">€ chez moi</th></tr></thead>
            <tbody>{held.funds.map((f) => (
              <tr key={f.fundIsin}><td><Link to={`/instruments/${f.fundIsin}`}>{f.fundName}</Link></td>
                <td className="n">{pct(f.weight, 2)}</td><td className="n">{eur(f.eur)}</td></tr>))}</tbody></table>
          <p className="cap">Une même société dans plusieurs fonds fait monter ton exposition réelle au-delà de ce que chaque ligne laisse penser.</p>
        </Card>)}

      {c.covered && (
        <>
          <section className="grid2 start">
            {hasHistory && (
              <Card title="Activité par exercice" caption={`${c.history[0]!.year}–${c.history.at(-1)!.year} · en ${c.currency ?? 'devise locale'}`}>
                <Chart option={history(c)} height={260} ariaLabel="Chiffre d'affaires et résultat net" />
                <TableTwin head={['Exercice', "Chiffre d'affaires", 'Résultat net', 'ROE', 'ROIC']}
                  rows={c.history.map((h) => [String(h.year), compact(h.revenue), compact(h.net_income),
                                              pct(h.roe, 0), pct(h.roic, 0)])} />
              </Card>)}
            {hasHistory && (
              <Card title="Rentabilité dans le temps" caption="ROE et ROIC par exercice">
                <Chart option={profitability(c)} height={260} ariaLabel="ROE et ROIC par exercice" />
              </Card>)}
          </section>

          <section className="grid2 start">
            <Card title="Marges moyennes" caption="moyenne sur 1, 3, 5 et 10 ans">
              <Chart option={margins(c)} height={240} ariaLabel="Marges par horizon" />
              <TableTwin head={['Horizon', 'Brute', "Exploitation", 'Nette']}
                rows={HORIZONS.map((h) => [HLAB[h]!, pct(c.margins.gross[h], 0), pct(c.margins.ebit[h], 0),
                                           pct(c.margins.net[h], 0)])} />
            </Card>
            <Card title="Croissance annualisée"
                  caption={<>sur 3, 5 et 10 ans · <Def k="revenue_growth_pa">définition</Def></>}>
              <table className="tbl"><thead><tr><th /><th className="n">3 ans</th><th className="n">5 ans</th>
                <th className="n">10 ans</th></tr></thead>
                <tbody>{([['revenue', "Chiffre d'affaires"], ['ebit', "Résultat d'exploitation"],
                          ['income', 'Résultat net']] as const).map(([k, l]) => (
                  <tr key={k}><td>{l}</td>
                    <td className="n">{pct(c.growth[k]['pa_3y'] ?? null, 0, true)}</td>
                    <td className="n">{pct(c.growth[k]['pa_5y'] ?? null, 0, true)}</td>
                    <td className="n">{pct(c.growth[k]['pa_10y'] ?? null, 0, true)}</td></tr>))}</tbody></table>
              <p className="cap">Une croissance très élevée peut venir d'une base de départ très basse.</p>
            </Card>
          </section>

          <section className="grid2 start">
            <Card title="Qualité" caption="scores du fournisseur et composantes">
              <div className="hero" style={{ fontSize: 34 }}>
                <Def k="aaqs_score">{aq['score'] === null || aq['score'] === undefined ? 'n.d.' : `${num(aq['score'], 0)} / 10`}</Def>
              </div>
              <table className="tbl"><tbody>{AAQS_LABELS.map(([k, l, f]) => (
                <tr key={k}><td>{l}</td><td className="n">{f(aq[k] ?? null)}</td></tr>))}</tbody></table>
              <table className="tbl" style={{ marginTop: 10 }}><tbody>
                <tr><td><Def k="piotroski">Score de Piotroski</Def></td>
                  <td className="n">{c.quality.piotroski.score === null ? 'n.d.' : `${num(c.quality.piotroski.score, 0)} / 9`}
                    <span className="cap"> · période {c.quality.piotroski.period_date ?? 'n.d.'}</span></td></tr>
                <tr><td><Def k="altman">Z-score d'Altman</Def></td>
                  <td className="n">{c.quality.altman.z === null ? 'n.d.' : num(c.quality.altman.z, 1)}
                    {c.quality.altman.zone && <span className="cap"> · zone {c.quality.altman.zone}</span>}</td></tr>
              </tbody></table>
            </Card>

            <Card title="ESG" caption="catégories et notes du fournisseur, méthode non publiée">
              {c.esg ? (<>
                <Chart option={esgBars(c.esg)} height={150} ariaLabel="Notes ESG" />
                <p className="cap"><Def k="co2">Émissions de CO₂</Def> (sans unité documentée) : scope 1 {compact(c.esg.co2['scope1'] ?? null)} ·
                  scope 2 {compact(c.esg.co2['scope2'] ?? null)} · scope 3 {compact(c.esg.co2['scope3'] ?? null)}</p>
                <p className="cap">Catégories d'activité signalées par le fournisseur (définitions non documentées) :</p>
                <div className="chips">{Object.entries(c.esg.exposures).filter(([, v]) => v).length
                  ? Object.entries(c.esg.exposures).filter(([, v]) => v).map(([k]) => (
                    <span className="chip" key={k}>{EXPOSURE_LABELS[k] ?? k}</span>))
                  : <span className="cap">aucune signalée</span>}</div>
              </>) : <p className="note">Pas de donnée ESG pour cette société.</p>}
            </Card>
          </section>

          {c.vendor_models && (
            <Card title="Modèles du fournisseur" caption="à titre éducatif — ni estimation d'analyste, ni conseil" wide>
              <div className="vendor card" style={{ padding: 12 }}>
                <p className="note"><b>Attention.</b> Ces valeurs sont le résultat de modèles dont les hypothèses ne sont pas publiées.
                  Elles ne sont ni agrégées ni utilisées ailleurs dans l'application.</p>
                <table className="tbl"><tbody>
                  <tr><td><Def k="fair_value">Valeur juste (modèle)</Def></td>
                    <td className="n">{num(c.vendor_models['fair_value'] ?? null, 2)} {c.currency}</td></tr>
                  <tr><td>Dernier cours vu par le fournisseur</td>
                    <td className="n">{num(c.vendor_models['last_price'] ?? null, 2)} {c.currency}</td></tr>
                  <tr><td>Écart du modèle au cours</td><td className="n">{pct(c.vendor_models['upside'] ?? null, 0, true)}</td></tr>
                  <tr><td>« Rendement attendu » (modèle)</td>
                    <td className="n">{pct(c.vendor_models['expected_return'] ?? null, 0)}</td></tr>
                </tbody></table>
              </div>
            </Card>)}
        </>)}

      {c.flags.length > 0 && (
        <Card title="Qualité des données" caption="ce que l'application a écarté ou signalé à l'ingestion" wide>
          <ul>{c.flags.map((f) => (<li key={f.field}><code>{f.field}</code> — {f.reason}</li>))}</ul>
        </Card>)}

      {c.description && (
        <Card title="Description" caption="fournisseur" wide><p className="note">{c.description}</p></Card>)}

      <LearnPrompts />

      <Card title="Sources" caption={`Eulerpool · récupéré le ${c.fetched_at.slice(0, 10)} · réponses brutes archivées dans data/raw/`} wide>
        <p className="cap">{c.sources.map((s) => `${s.endpoint}${s.ok ? '' : ' (indisponible)'}`).join(' · ')}</p>
        <p className="cap">Valeurs de valorisation (P/E…) volontairement absentes : le fournisseur les renvoie à zéro, ce qui est faux.</p>
      </Card>
    </>
  );
}
