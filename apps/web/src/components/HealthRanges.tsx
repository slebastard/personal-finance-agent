import type { HealthMetric, WeightedStatsDto } from '@pfa/contracts';
import { num, pct, ratioX } from '../api/format';
import { Def } from './Def';

interface Cfg {
  key: HealthMetric; label: string; gloss: string;
  fmt: (v: number | null) => string;
}

const pc = (v: number | null) => pct(v, 0);
const CFG: Cfg[] = [
  { key: 'roe', label: 'ROE', gloss: 'roe', fmt: pc },
  { key: 'roic', label: 'ROIC', gloss: 'roic', fmt: pc },
  { key: 'operating_margin', label: "Marge d'exploitation", gloss: 'operating_margin', fmt: pc },
  { key: 'net_margin', label: 'Marge nette', gloss: 'net_margin', fmt: pc },
  { key: 'revenue_growth_3y_pa', label: 'Croissance du CA (3 ans, par an)', gloss: 'revenue_growth_pa',
    fmt: (v) => pct(v, 0, true) },
  { key: 'net_debt_to_ebit', label: 'Dette nette / EBIT', gloss: 'net_debt_to_ebit',
    fmt: ratioX },
  { key: 'aaqs_score', label: 'Note de qualité (0–10)', gloss: 'aaqs_score', fmt: (v) => num(v, 1) },
  { key: 'esg_total', label: 'Note ESG (0–100)', gloss: 'esg_total', fmt: (v) => num(v, 0) },
];

const W = 260; const H = 20; const PAD = 8;

/** One metric: a band for the interquartile range, a dot for the weighted mean, a tick for the median. */
function Range({ s, fmt }: { s: WeightedStatsDto; fmt: Cfg['fmt'] }) {
  if (s.mean === null || s.p25 === null || s.p75 === null || s.p50 === null) {
    return <span className="cap">n.d.</span>;
  }
  const vals = [s.mean, s.p25, s.p50, s.p75];
  let lo = Math.min(0, ...vals); let hi = Math.max(0, ...vals);
  if (hi === lo) hi = lo + 1;
  const span = hi - lo;
  lo -= span * 0.06; hi += span * 0.06;
  const x = (v: number) => PAD + ((v - lo) / (hi - lo)) * (W - 2 * PAD);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img"
         aria-label={`moyenne ${fmt(s.mean)}, médiane ${fmt(s.p50)}, de ${fmt(s.p25)} à ${fmt(s.p75)}`}>
      <line x1={PAD} x2={W - PAD} y1={H / 2} y2={H / 2} stroke="var(--grid)" strokeWidth={1} />
      {lo < 0 && <line x1={x(0)} x2={x(0)} y1={3} y2={H - 3} stroke="var(--axis)" strokeWidth={1} />}
      <rect x={x(s.p25)} y={H / 2 - 5} width={Math.max(x(s.p75) - x(s.p25), 2)} height={10} rx={3}
            fill="var(--series-1)" opacity={0.3} />
      <line x1={x(s.p50)} x2={x(s.p50)} y1={H / 2 - 6} y2={H / 2 + 6} stroke="var(--text-secondary)" strokeWidth={2} />
      <circle cx={x(s.mean)} cy={H / 2} r={5} fill="var(--series-1)" stroke="var(--surface-1)" strokeWidth={2} />
    </svg>
  );
}

/**
 * Weighted health of a set of companies. EVERY mean shows the share of the weight it rests on:
 * a mean over 37 % of a fund says nothing about the other 63 %.
 */
export function HealthRanges({ health }: { health: Record<HealthMetric, WeightedStatsDto> }) {
  return (
    <div className="ranges">
      <div className="rhead cap">
        <span>Indicateur</span><span>Interquartile (bande) · médiane (trait) · moyenne (point)</span>
        <span className="n">Moyenne pondérée</span><span className="n">Couverture</span>
      </div>
      {CFG.map((c) => {
        const s = health[c.key];
        return (
          <div className="rrow" key={c.key}>
            <span><Def k={c.gloss}>{c.label}</Def></span>
            <span><Range s={s} fmt={c.fmt} /></span>
            <span className="n">{c.fmt(s.mean)}
              <span className="cap"> · méd. {c.fmt(s.p50)}</span></span>
            <span className={`n ${s.coverage < 0.8 ? 'warn-t' : ''}`}>{pct(s.coverage, 0)}</span>
          </div>);
      })}
    </div>
  );
}
