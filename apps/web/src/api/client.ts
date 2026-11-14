import type {
  CompanyDto, FlowsDto, FundCompaniesDto, GlossaryEntry, InstrumentDto, LearnPromptDto,
  LookthroughDto, MetaDto, ReportDto, SavingsCapacityDto, TransactionDto, ApiError,
} from '@pfa/contracts';

/**
 * THE isolation point: the only module that knows how data reaches the client.
 *
 * Today it fetches `/api/v1/*`. For dated archives the same codebase is built with
 * VITE_DATA_MODE=inline, which reads a payload embedded in the page instead — so an archived HTML
 * stays double-clickable and readable offline without a second rendering engine to maintain.
 */
const BASE = '/api/v1';
const INLINE = import.meta.env.VITE_DATA_MODE === 'inline';

declare global {
  interface Window { PFA_DATA?: Record<string, unknown> }
}

type Query = Record<string, string | undefined>;

async function get<T>(path: string, params?: Query): Promise<T> {
  if (INLINE) {
    const key = path.split('?')[0]!;
    const data = window.PFA_DATA?.[key];
    if (data === undefined) throw new Error(`archive: aucune donnée embarquée pour ${key}`);
    return data as T;
  }
  const qs = params
    ? '?' + new URLSearchParams(
        Object.entries(params).filter(([, v]) => v !== undefined) as [string, string][])
    : '';
  const res = await fetch(`${BASE}${path}${qs}`);
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as ApiError | null;
    throw new Error(body?.error?.message ?? `HTTP ${res.status} sur ${path}`);
  }
  return res.json() as Promise<T>;
}

export interface Period extends Query { from?: string; to?: string; month?: string }

export const api = {
  meta: () => get<MetaDto>('/meta'),
  report: (asOf?: string) => get<ReportDto>('/report', { asOf }),
  instrument: (isin: string, asOf?: string) =>
    get<InstrumentDto>(`/instruments/${isin}`, { asOf }),
  fundCompanies: (isin: string, asOf?: string) =>
    get<FundCompaniesDto>(`/instruments/${isin}/companies`, { asOf }),
  lookthrough: (asOf?: string) => get<LookthroughDto>('/portfolio/lookthrough', { asOf }),
  company: (isin: string, asOf?: string) => get<CompanyDto>(`/companies/${isin}`, { asOf }),
  learnPrompts: (isin?: string) => get<LearnPromptDto[]>('/learn/prompts', { isin }),
  glossary: () => get<Record<string, GlossaryEntry>>('/reference/glossary'),
  flows: (p: Period) => get<FlowsDto>('/flows', p),
  transactions: (p: Period & Query) =>
    get<{ from: string; to: string; total: number; rows: TransactionDto[] }>(
      '/flows/transactions', p),
  savingsCapacity: () => get<SavingsCapacityDto>('/flows/savings-capacity'),
};
