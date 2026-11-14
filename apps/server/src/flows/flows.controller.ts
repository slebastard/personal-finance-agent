import { Controller, Get, Query } from '@nestjs/common';
import { FlowsService } from './flows.service';
import { resolvePeriod } from '../common/period';
import { notFound } from '../common/http-error.filter';

/** HTTP only: validate, delegate, serialise. No arithmetic lives here. */
@Controller('flows')
export class FlowsController {
  constructor(private readonly flows: FlowsService) {}

  @Get()
  aggregate(@Query() q: Record<string, string>) {
    const { from, to } = resolvePeriod(q, this.flows.range());
    return this.flows.aggregate(from, to);
  }

  @Get('transactions')
  transactions(@Query() q: Record<string, string>) {
    const { from, to } = resolvePeriod(q, this.flows.range());
    const limit = Math.min(Number(q['limit'] ?? 200) || 200, 1000);
    const offset = Math.max(Number(q['offset'] ?? 0) || 0, 0);
    return { from, to, ...this.flows.page(from, to, q['flow'], q['category'], limit, offset) };
  }

  @Get('savings-capacity')
  savings() {
    const s = this.flows.savingsCapacity();
    if (!s) throw notFound('NO_TRANSACTIONS', 'aucune transaction importée');
    return s;
  }
}
