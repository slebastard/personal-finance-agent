import { Module } from '@nestjs/common';
import { FlowsController } from './flows.controller';
import { FlowsService } from './flows.service';
import { FlowsRepository } from './flows.repository';

@Module({
  controllers: [FlowsController],
  providers: [FlowsService, FlowsRepository],
  exports: [FlowsService],
})
export class FlowsModule {}
