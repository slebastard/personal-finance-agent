import type { ReactNode } from 'react';
import { eur, pct, signCls } from '../api/format';

export const Card = ({ title, caption, children, wide }:
  { title?: string; caption?: ReactNode; children: ReactNode; wide?: boolean }) => (
  <div className="card" style={wide ? { gridColumn: '1 / -1' } : undefined}>
    {title && <h2>{title}</h2>}
    {caption && <p className="cap">{caption}</p>}
    {children}
  </div>
);

export const Tile = ({ label, value, delta, cls }:
  { label: ReactNode; value: ReactNode; delta?: ReactNode; cls?: string }) => (
  <div className="card tile">
    <div className="label">{label}</div>
    <div className={`value ${cls ?? ''}`}>{value}</div>
    <div className="delta">{delta ?? ' '}</div>
  </div>
);

/** Every chart has a table twin: a tooltip must enhance a value, never be the only way to read it. */
export const TableTwin = ({ rows, head, summary = 'Tableau' }:
  { head: string[]; rows: (ReactNode)[][]; summary?: string }) => (
  <details>
    <summary>{summary}</summary>
    <table className="tbl">
      <thead><tr>{head.map((h, i) => (
        <th key={h} className={i ? 'n' : undefined}>{h}</th>))}</tr></thead>
      <tbody>{rows.map((r, i) => (
        <tr key={i}>{r.map((c, j) => (
          <td key={j} className={j ? 'n' : undefined}>{c}</td>))}</tr>))}</tbody>
    </table>
  </details>
);

export const Segmented = <T extends string>({ label, value, options, onChange }:
  { label: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) => (
  <div className="fgroup">
    <span>{label}</span>
    <div className="seg">
      {options.map((o) => (
        <button key={o.value} aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  </div>
);

export const Money = ({ v, dec = 0, sign }: { v: number | null; dec?: number; sign?: boolean }) => (
  <span className={sign ? signCls(v) : undefined}>{eur(v, dec)}</span>
);

export const Pct = ({ v, dec = 1, signed }:
  { v: number | null; dec?: number; signed?: boolean }) => <>{pct(v, dec, signed)}</>;
