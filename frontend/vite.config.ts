import { fileURLToPath, URL } from 'node:url';
import { readFile } from 'node:fs/promises';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { loadEnv, type Plugin } from 'vite';
import { defineConfig } from 'vitest/config';

function mockWorker(): Plugin {
  return {
    name: 'roombook-mock-worker',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/mockServiceWorker.js', (_request, response, next) => {
        void readFile(new URL('./node_modules/msw/lib/mockServiceWorker.js', import.meta.url))
          .then((worker) => {
            response.setHeader('Content-Type', 'application/javascript');
            response.setHeader('Service-Worker-Allowed', '/');
            response.end(worker);
          })
          .catch(next);
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const apiTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000';
  return {
    plugins: [react(), tailwindcss(), mockWorker()],
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    server: {
      proxy: {
        '/api': apiTarget,
        '/version': apiTarget,
        '/health': apiTarget,
        '/ready': apiTarget,
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      restoreMocks: true,
      coverage: {
        provider: 'v8',
        reporter: ['text', 'html', 'lcov'],
        include: ['src/**/*.{ts,tsx}'],
        exclude: [
          'src/**/*.test.{ts,tsx}',
          'src/shared/api/generated/**',
          'src/test/**',
          'src/mocks/**',
          'src/main.tsx',
        ],
        thresholds: { lines: 80 },
      },
    },
  };
});
