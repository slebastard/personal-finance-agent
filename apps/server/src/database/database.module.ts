import { Global, Module } from '@nestjs/common';
import { SqliteProvider } from './sqlite.provider';

@Global()
@Module({ providers: [SqliteProvider], exports: [SqliteProvider] })
export class DatabaseModule {}
