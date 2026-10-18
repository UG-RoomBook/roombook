import { setupWorker } from 'msw/browser';
import { handlers } from './handlers';

export async function startMocking() {
  const worker = setupWorker(...handlers);
  await worker.start({
    quiet: true,
    onUnhandledRequest(request, print) {
      const path = new URL(request.url).pathname;
      if (path.startsWith('/api/') || path === '/version') print.error();
    },
  });
}
