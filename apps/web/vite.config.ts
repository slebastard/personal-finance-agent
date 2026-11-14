import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

const root = resolve(__dirname, '../..');

export default defineConfig({
  plugins: [react()],
  // relative asset paths: the same bundle works from any directory, and from file:// for archives
  base: './',
  build: {
    outDir: resolve(root, 'dashboards/app'),
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    // one data path in dev and in production: the client always talks to /api
    proxy: { '/api': { target: 'http://127.0.0.1:3001', changeOrigin: true } },
  },
});
