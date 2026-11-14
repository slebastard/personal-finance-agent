import { Module } from '@nestjs/common';
import { ReportModule } from '../report/report.module';
import { EnrichmentController } from './enrichment.controller';
import { EnrichmentRepository } from './enrichment.repository';
import { EnrichmentService } from './enrichment.service';
import { LearnService } from './learn.service';

@Module({
  imports: [ReportModule],
  controllers: [EnrichmentController],
  providers: [EnrichmentService, EnrichmentRepository, LearnService],
})
export class EnrichmentModule {}
