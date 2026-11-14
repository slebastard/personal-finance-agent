import { Injectable, Logger, OnModuleDestroy } from '@nestjs/common';
import { DatabaseSync, type SQLInputValue } from 'node:sqlite';
import { statSync } from 'node:fs';
import { config } from '../config/config';
import { unavailable } from '../common/http-error.filter';

/**
 * Read-only access to the Python pipeline's SQLite file, via Node's built-in `node:sqlite`.
 *
 * Built-in rather than better-sqlite3 on purpose: no native module to compile, no pnpm build-script
 * approval, nothing to rebuild on a Node upgrade. It keeps the server as dependency-light as the
 * Python side.
 *
 * Read-only is deliberate twice over: the server structurally cannot corrupt the pipeline's data,
 * and it makes the project invariant visible — the JSON files under data/ are the source of truth,
 * the database is rebuildable with `pfa rebuild`.
 *
 * `pfa rebuild` DELETES and recreates the file, which would leave an open handle serving stale rows
 * forever. The inode/mtime check below detects that and reopens.
 */
@Injectable()
export class SqliteProvider implements OnModuleDestroy {
  private db?: DatabaseSync;
  private stamp = '';
  private readonly log = new Logger('sqlite');

  get connection(): DatabaseSync {
    let st: ReturnType<typeof statSync>;
    try {
      st = statSync(config.dbPath);
    } catch {
      this.close();
      throw unavailable(
        `${config.dbPath} absent — lance \`python3 -m pfa rebuild\` ou \`pfa sync\`.`);
    }
    const stamp = `${st.ino}:${st.mtimeMs}:${st.size}`;
    if (!this.db || stamp !== this.stamp) {
      this.close();
      this.db = new DatabaseSync(config.dbPath, { readOnly: true });
      this.stamp = stamp;
      this.log.log(`opened ${config.dbPath}`);
    }
    return this.db;
  }

  /** Typed query helpers: node:sqlite returns Record<string, SQLOutputValue>, which every call
   *  site would otherwise have to cast. Centralised here so the casting happens once. */
  all<T>(sql: string, ...params: SQLInputValue[]): T[] {
    return this.connection.prepare(sql).all(...params) as unknown as T[];
  }

  get<T>(sql: string, ...params: SQLInputValue[]): T | undefined {
    return this.connection.prepare(sql).get(...params) as unknown as T | undefined;
  }

  private close() {
    try { this.db?.close(); } catch { /* already gone */ }
    this.db = undefined;
    this.stamp = '';
  }

  onModuleDestroy() { this.close(); }
}
