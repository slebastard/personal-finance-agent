import { Module } from '@nestjs/common';
import { DatabaseModule } from './database/database.module';
import { ReferenceModule } from './reference/reference.module';
import { ReportModule } from './report/report.module';
import { FlowsModule } from './flows/flows.module';
import { EnrichmentModule } from './enrichment/enrichment.module';
import { HealthController } from './health.controller';

@Module({
  imports: [DatabaseModule, ReferenceModule, ReportModule, FlowsModule, EnrichmentModule],
  controllers: [HealthController],
})
export class AppModule {}
