import { z } from 'zod';
import { badRequest } from './http-error.filter';

const iso = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'attendu AAAA-MM-JJ');
const month = z.string().regex(/^\d{4}-\d{2}$/, 'attendu AAAA-MM');

export const periodQuery = z.object({
  from: iso.optional(), to: iso.optional(), month: month.optional(),
});

/** Resolve a period from query params, falling back to the full available range. */
export function resolvePeriod(
  q: unknown, fallback: { from: string; to: string } | null,
): { from: string; to: string } {
  const parsed = periodQuery.safeParse(q);
  if (!parsed.success) {
    throw badRequest('paramètres de période invalides', parsed.error.flatten().fieldErrors);
  }
  const { from, to, month } = parsed.data;
  if (month) {
    const [y, m] = month.split('-').map(Number) as [number, number];
    const last = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
    return { from: `${month}-01`, to: last };
  }
  if (!fallback && !(from && to)) {
    throw badRequest('aucune donnée en base : précise from et to, ou lance un import');
  }
  const resolved = { from: from ?? fallback!.from, to: to ?? fallback!.to };
  if (resolved.from > resolved.to) throw badRequest('from est postérieur à to');
  return resolved;
}
