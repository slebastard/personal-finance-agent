import { Injectable } from '@nestjs/common';
import type { LearnPromptDto, LookthroughDto } from '@pfa/contracts';
import { ReferenceService } from '../reference/reference.service';
import { EnrichmentService } from './enrichment.service';

const eur = (v: number) => `${new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 }).format(v)} €`;
const pct = (v: number, d = 1) => `${(v * 100).toFixed(d).replace('.', ',')} %`;

/**
 * Reading suggestions. The CATALOGUE (reference/learning_prompts.json) is data; this evaluates its
 * triggers on figures the parity-tested services already produce. It selects, it never generates:
 * every suggestion is reproducible from the numbers shown beside it, and carries its evidence.
 */
@Injectable()
export class LearnService {
  constructor(private readonly ref: ReferenceService, private readonly svc: EnrichmentService) {}

  private portfolioEvidence(w: any, lt: LookthroughDto): string | null {
    const top = (n: number) => lt.companies.slice(0, n);
    switch (w.kind) {
      case 'company_in_many_funds': {
        const hit = lt.companies.find((c) => c.nFunds >= (w.min_funds ?? 2) && c.pctOfEquity >= (w.min_pct_of_equity ?? 0));
        return hit ? `${hit.name} est détenue via ${hit.nFunds} fonds : ${eur(hit.exposureEur)}, soit ${pct(hit.pctOfEquity)} de ta poche actions.` : null;
      }
      case 'top10_concentration':
        return lt.top10PctOfEquity >= (w.min_pct_of_equity ?? 0)
          ? `Les 10 premières sociétés représentent ${pct(lt.top10PctOfEquity)} de ta poche actions (${pct(lt.top10PctOfIdentified)} de la part identifiée).` : null;
      case 'high_leverage_in_top': {
        const hits = top(w.top_n ?? 10).filter((c) => c.netDebtToEbit !== null && c.netDebtToEbit >= (w.min_net_debt_to_ebit ?? 3));
        return hits.length ? `Dette nette / EBIT ≥ ${w.min_net_debt_to_ebit ?? 3} chez : ${hits.map((c) => `${c.name} (${(c.netDebtToEbit as number).toFixed(1).replace('.', ',')})`).join(', ')}.` : null;
      }
      case 'growth_vs_solidity': {
        const hits = top(w.top_n ?? 10).filter((c) => c.revenueGrowth3yPa !== null && c.revenueGrowth3yPa >= (w.min_growth_pa ?? 0.3)
          && c.piotroski !== null && c.piotroski <= (w.max_piotroski ?? 4));
        return hits.length ? `${hits.map((c) => `${c.name} (croissance ${pct(c.revenueGrowth3yPa as number, 0)} par an, Piotroski ${c.piotroski})`).join(' ; ')}.` : null;
      }
      case 'low_coverage':
        return lt.equityValue && lt.identifiedPct < (w.max_identified_pct ?? 0.5)
          ? `${pct(lt.identifiedPct, 0)} de ta poche actions est identifiée au niveau des sociétés (${eur(lt.identifiedEur)} sur ${eur(lt.equityValue)}).` : null;
      default:
        return null;
    }
  }

  prompts(isin?: string, asOf?: string): LearnPromptDto[] {
    const out: LearnPromptDto[] = [];
    const catalogue = this.ref.learningPrompts;
    const lt = this.svc.lookthrough(asOf, 50);
    const fund = isin ? this.svc.fundCompanies(isin, asOf) : null;
    for (const p of catalogue) {
      let evidence: string | null = null;
      if (p.scope === 'fund' && fund) {
        if (p.when.kind === 'fund_proxied' && fund.proxy.kind === 'physical_proxy') {
          evidence = `${fund.fundName} est un fonds à réplication synthétique ; ses sociétés affichées viennent de ${fund.proxy.isin}.`;
        } else if (p.when.kind === 'crosscheck_warn' && fund.proxy.crosscheck?.warn) {
          const c = fund.proxy.crosscheck;
          evidence = `Écart maximal au substitut : secteurs ${(c.sectorMaxGapPts ?? 0).toFixed(1).replace('.', ',')} pt, pays ${(c.countryMaxGapPts ?? 0).toFixed(1).replace('.', ',')} pt (seuil ${c.thresholdPts} pt).`;
        }
      } else if (p.scope === 'portfolio') {
        evidence = this.portfolioEvidence(p.when, lt);
      }
      if (evidence) {
        out.push({ id: p.id, title: p.title, question: p.question, why: p.why, evidence,
                   reading: p.reading ?? [], learn: p.learn });
      }
    }
    return out;
  }
}
