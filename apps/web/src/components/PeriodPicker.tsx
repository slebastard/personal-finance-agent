import { monthLabel } from '../api/format';
import type { Period } from '../api/client';

export interface PeriodState { mode: 'preset' | 'month' | 'custom'; preset?: string;
                               month?: string; from?: string; to?: string }

const PRESETS = [
  { id: 'this-month', label: 'Ce mois-ci' },
  { id: 'last-month', label: 'Mois dernier' },
  { id: 'last-3', label: '3 derniers mois' },
  { id: 'last-12', label: '12 derniers mois' },
  { id: 'ytd', label: 'Année en cours' },
  { id: 'all', label: 'Tout' },
];

const iso = (d: Date) => d.toISOString().slice(0, 10);

/** Presets come before the calendar: nobody wants to fight a date grid for "last month". */
export function resolve(state: PeriodState, range: { from: string; to: string } | null): Period {
  if (state.mode === 'month' && state.month) return { month: state.month };
  if (state.mode === 'custom') return { from: state.from, to: state.to };
  const today = range ? new Date(`${range.to}T00:00:00Z`) : new Date();
  const y = today.getUTCFullYear(); const m = today.getUTCMonth();
  switch (state.preset) {
    case 'this-month':
      return { from: iso(new Date(Date.UTC(y, m, 1))), to: iso(today) };
    case 'last-month': {
      const d = new Date(Date.UTC(y, m - 1, 1));
      return { month: iso(d).slice(0, 7) };
    }
    case 'last-3':
      return { from: iso(new Date(Date.UTC(y, m - 2, 1))), to: iso(today) };
    case 'last-12':
      return { from: iso(new Date(Date.UTC(y, m - 11, 1))), to: iso(today) };
    case 'ytd':
      return { from: `${y}-01-01`, to: iso(today) };
    default:
      return {};
  }
}

export function monthsIn(range: { from: string; to: string } | null): string[] {
  if (!range) return [];
  const out: string[] = [];
  const [fy, fm] = range.from.split('-').map(Number) as [number, number];
  const [ty, tm] = range.to.split('-').map(Number) as [number, number];
  for (let y = fy, m = fm; y < ty || (y === ty && m <= tm);) {
    out.push(`${y}-${String(m).padStart(2, '0')}`);
    m += 1; if (m > 12) { m = 1; y += 1; }
  }
  return out.reverse();
}

export function PeriodPicker({ state, onChange, range }:
  { state: PeriodState; onChange: (s: PeriodState) => void;
    range: { from: string; to: string } | null }) {
  return (
    <section className="filters" role="group" aria-label="Période analysée">
      <div className="fgroup">
        <span>Période</span>
        <div className="seg">
          {PRESETS.map((p) => (
            <button key={p.id}
              aria-pressed={state.mode === 'preset' && state.preset === p.id}
              onClick={() => onChange({ mode: 'preset', preset: p.id })}>
              {p.label}
            </button>
          ))}
        </div>
      </div>
      <div className="fgroup">
        <span>Mois</span>
        <select value={state.mode === 'month' ? state.month ?? '' : ''}
          onChange={(e) => e.target.value
            ? onChange({ mode: 'month', month: e.target.value })
            : onChange({ mode: 'preset', preset: 'last-12' })}>
          <option value="">—</option>
          {monthsIn(range).map((m) => (
            <option key={m} value={m}>{monthLabel(m)}</option>))}
        </select>
      </div>
      <details className="fgroup" style={{ display: 'block' }}>
        <summary>Période personnalisée</summary>
        <div className="fgroup" style={{ marginTop: 8 }}>
          <input type="date" value={state.from ?? range?.from ?? ''}
            min={range?.from} max={range?.to}
            onChange={(e) => onChange({ ...state, mode: 'custom', from: e.target.value })} />
          <span>→</span>
          <input type="date" value={state.to ?? range?.to ?? ''}
            min={range?.from} max={range?.to}
            onChange={(e) => onChange({ ...state, mode: 'custom', to: e.target.value })} />
        </div>
      </details>
    </section>
  );
}
