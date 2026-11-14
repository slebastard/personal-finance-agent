import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react';

/**
 * A change, as a pill: arrow + sign + text. Colour alone never carries the meaning (the arrow and the
 * sign do), and the gain/loss colours are deliberately not the emerald used for data lines.
 * `value` only decides the direction; the text comes already formatted from the figures served.
 */
export function Delta({ value, children }: { value: number | null | undefined; children: React.ReactNode }) {
  const dir = value === null || value === undefined || value === 0 ? 'neutral' : value > 0 ? 'pos' : 'neg';
  const Icon = dir === 'pos' ? ArrowUpRight : dir === 'neg' ? ArrowDownRight : Minus;
  return <span className={`delta-chip ${dir}`}><Icon aria-hidden />{children}</span>;
}

/** Big figure with its unit set smaller beside it ("126 927" + "€"). */
export function Figure({ text }: { text: string }) {
  const m = /^(.*?)(\s*[€%$][^\d]*)$/.exec(text);
  if (!m) return <>{text}</>;
  return <>{m[1]}<span className="unit">{m[2]!.trim()}</span></>;
}
