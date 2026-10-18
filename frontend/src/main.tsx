import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './app/App';
import { Providers } from './app/Providers';
import './styles/index.css';

async function render() {
  if (import.meta.env.DEV && import.meta.env.VITE_ENABLE_MOCKS === 'true') {
    const { startMocking } = await import('./mocks/startMocking');
    await startMocking();
  }
  const root = document.getElementById('root');
  if (!root) throw new Error('Missing root element');
  createRoot(root).render(
    <StrictMode>
      <Providers>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </Providers>
    </StrictMode>,
  );
}

void render();
