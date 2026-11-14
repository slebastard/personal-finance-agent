import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import { Logger } from '@nestjs/common';
import { AppModule } from './app.module';
import { HttpErrorFilter } from './common/http-error.filter';
import { config } from './config/config';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import express from 'express';

async function bootstrap() {
  const app = await NestFactory.create(AppModule, { logger: ['log', 'warn', 'error'] });
  app.useGlobalFilters(new HttpErrorFilter());
  app.setGlobalPrefix('api/v1');
  // Serve the built client from the same origin, so production needs no proxy and no CORS.
  if (existsSync(join(config.webDir, 'index.html'))) {
    app.use(express.static(config.webDir));
    // hash routing means the client never asks the server for a deep path, so one fallback is
    // enough: anything that is not /api and not a built asset gets index.html
    app.use((req: express.Request, res: express.Response, next: express.NextFunction) => {
      if (req.path.startsWith('/api/')) return next();
      return res.sendFile(join(config.webDir, 'index.html'));
    });
  }
  // 127.0.0.1 only: this serves personal financial data and has no authentication (v1).
  await app.listen(config.port, '127.0.0.1');
  new Logger('bootstrap').log(`http://127.0.0.1:${config.port}/api/v1  ·  db=${config.dbPath}`);
}
bootstrap();
