import { Controller, Get, Param, Query } from '@nestjs/common';
import { ReportService } from './report.service';

@Controller()
export class ReportController {
  constructor(private readonly report: ReportService) {}

  @Get('report')
  get(@Query('asOf') asOf?: string) { return this.report.report(asOf); }

  @Get('exposure')
  exposure(@Query('asOf') asOf?: string) {
    return this.report.exposure(this.report.resolveAsOf(asOf));
  }

  @Get('instruments/:isin')
  instrument(@Param('isin') isin: string, @Query('asOf') asOf?: string) {
    return this.report.instrument(isin.toUpperCase(), asOf);
  }

  @Get('positions')
  positions(@Query('asOf') asOf?: string) {
    return this.report.positions(this.report.resolveAsOf(asOf))
      .map(({ breakdowns, ...p }) => p);
  }
}
