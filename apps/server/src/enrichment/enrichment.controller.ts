import { Controller, Get, Param, Query } from '@nestjs/common';
import { EnrichmentService } from './enrichment.service';
import { LearnService } from './learn.service';
import { ReferenceService } from '../reference/reference.service';

/** HTTP only: validate, delegate, serialise. No arithmetic lives here. */
@Controller()
export class EnrichmentController {
  constructor(
    private readonly svc: EnrichmentService,
    private readonly learn: LearnService,
    private readonly ref: ReferenceService,
  ) {}

  @Get('instruments/:isin/companies')
  fund(@Param('isin') isin: string, @Query('asOf') asOf?: string) {
    return this.svc.fundCompanies(isin.toUpperCase(), asOf);
  }

  @Get('portfolio/lookthrough')
  lookthrough(@Query('asOf') asOf?: string) { return this.svc.lookthrough(asOf); }

  @Get('companies/:isin')
  company(@Param('isin') isin: string, @Query('asOf') asOf?: string) {
    return this.svc.company(isin.toUpperCase(), asOf);
  }

  @Get('learn/prompts')
  prompts(@Query('isin') isin?: string, @Query('asOf') asOf?: string) {
    return this.learn.prompts(isin?.toUpperCase(), asOf);
  }

  @Get('reference/glossary')
  glossary() { return this.ref.glossary; }
}
