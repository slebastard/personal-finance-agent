import { resolve } from 'node:path';

/** PFA_ROOT mirrors the Python package, so tests can point at a throwaway tree. */
const root = process.env.PFA_ROOT ?? resolve(__dirname, '../../../..');

export const config = {
  root,
  dbPath: resolve(root, 'data/finance.db'),
  generatedDir: resolve(root, 'data/generated'),
  port: Number(process.env.PFA_PORT ?? 3001),
  webDir: resolve(root, 'dashboards/app'),
};
