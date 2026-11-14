import { Controller, Get } from '@nestjs/common';
import { SqliteProvider } from './database/sqlite.provider';
import { ReferenceService } from './reference/reference.service';
import { FlowsService } from './flows/flows.service';
import { config } from './config/config';
import type { MetaDto } from '@pfa/contracts';

@Controller()
export class HealthController {
  constructor(private readonly sqlite: SqliteProvider,
              private readonly reference: ReferenceService,
              private readonly flows: FlowsService) {}

  @Get('health')
  health() {
    const db = this.sqlite.connection;
    const n = (t: string) =>
      (db.prepare(`SELECT COUNT(*) AS n FROM ${t}`).get() as { n: number }).n;
    return {
      ok: true, dbPath: config.dbPath,
      counts: { snapshots: n('snapshots'), holdings: n('holdings'),
                transactions: n('transactions'), runs: n('runs') },
      rulesVerifiedOn: this.reference.verifiedOn,
    };
  }

  @Get('meta')
  meta(): MetaDto {
    const db = this.sqlite.connection;
    const snapshots = (db.prepare('SELECT as_of FROM snapshots ORDER BY as_of')
      .all() as { as_of: string }[]).map((r) => r.as_of);
    const lastRun = db.prepare(
      'SELECT run_id, kind, status, started_at FROM runs '
      + 'ORDER BY COALESCE(started_at, as_of) DESC LIMIT 1').get() as
      { run_id: string; kind: string; status: string; started_at: string | null } | undefined;
    return {
      snapshots,
      latestAsOf: snapshots.at(-1) ?? null,
      rulesVerifiedOn: this.reference.verifiedOn,
      transactionRange: this.flows.range(),
      lastRun: lastRun
        ? { runId: lastRun.run_id, kind: lastRun.kind, status: lastRun.status,
            startedAt: lastRun.started_at }
        : null,
    };
  }
}
