import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { FindRoomPage } from './FindRoomPage';
const studio = {
  id: '00000000-0000-4000-8000-000000000001',
  name: 'The Studio',
  location: 'West',
  capacity: 4,
  active: true,
};
const forum = {
  ...studio,
  id: '00000000-0000-4000-8000-000000000002',
  name: 'The Forum',
  capacity: 8,
};
const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
function Location() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output data-testid="location">
        {location.pathname}
        {location.search}
      </output>
      <button onClick={() => void navigate(-1)}>History back</button>
    </>
  );
}
function renderSearch(url = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Location />
        <Routes>
          <Route path="/" element={<FindRoomPage />} />
          <Route path="/rooms/:roomId" element={<h1>Choose time</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
describe('room-first discovery', () => {
  it('offers active rooms without an interval and drops legacy search times from navigation', async () => {
    let sent: URL | undefined;
    server.use(
      http.get('*/api/v1/rooms', ({ request }) => {
        sent = new URL(request.url);
        return HttpResponse.json({
          items: [studio, { ...forum, active: false }],
          total: 2,
          limit: 20,
          offset: 0,
        });
      }),
    );
    renderSearch('/?date=2026-10-19&start=13:00&end=14:00&capacity=4');
    const choose = await screen.findByRole('button', { name: 'Choose time for The Studio' });
    expect(choose).toBeEnabled();
    expect(screen.getByRole('button', { name: 'The Forum: inactive' })).toBeDisabled();
    expect(screen.queryByLabelText('Date')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('From')).not.toBeInTheDocument();
    expect(sent?.searchParams.has('starts_at')).toBe(false);
    await userEvent.click(choose);
    expect(screen.getByTestId('location')).toHaveTextContent(
      `/rooms/${studio.id}?capacity=4&offset=0`,
    );
    expect(screen.getByTestId('location')).not.toHaveTextContent('start=');
  });
  it('keeps pagination when group size empties a page and restores it from history', async () => {
    server.use(
      http.get('*/api/v1/rooms', ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset'));
        return HttpResponse.json({
          items: [offset ? forum : studio],
          total: 21,
          limit: 20,
          offset,
        });
      }),
    );
    renderSearch('/?capacity=8');
    await screen.findByText('No matching rooms on this page');
    await userEvent.click(screen.getByRole('button', { name: 'Next room page' }));
    await screen.findByRole('article', { name: 'The Forum' });
    expect(screen.getByTestId('location')).toHaveTextContent('offset=20');
    await userEvent.selectOptions(screen.getByLabelText('People'), '4');
    await screen.findByRole('article', { name: 'The Studio' });
    expect(screen.getByTestId('location')).toHaveTextContent('offset=0');
    await userEvent.click(screen.getByRole('button', { name: 'History back' }));
    await screen.findByRole('article', { name: 'The Forum' });
    expect(screen.getByLabelText('People')).toHaveValue('8');
  });
  it.each(['-1', '1.5', '9007199254740992', 'not-a-page'])(
    'bounds invalid offset %s',
    async (offset) => {
      let actual: string | null = null;
      server.use(
        http.get('*/api/v1/rooms', ({ request }) => {
          actual = new URL(request.url).searchParams.get('offset');
          return HttpResponse.json({ items: [studio], total: 1, limit: 20, offset: 0 });
        }),
      );
      renderSearch(`/?offset=${offset}`);
      await screen.findByRole('article', { name: 'The Studio' });
      expect(actual).toBe('0');
    },
  );
  it('recovers an out-of-range page with one previous action', async () => {
    server.use(
      http.get('*/api/v1/rooms', ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset'));
        return HttpResponse.json({
          items: offset < 21 ? [forum] : [],
          total: 21,
          limit: 20,
          offset,
        });
      }),
    );
    renderSearch('/?offset=200&capacity=8');
    await screen.findByText('No matching rooms on this page');
    await userEvent.click(screen.getByRole('button', { name: 'Previous room page' }));
    await screen.findByRole('article', { name: 'The Forum' });
    expect(screen.getByTestId('location')).toHaveTextContent('offset=20');
  });
  it('shows failure and a retry without losing the group size', async () => {
    let fail = true;
    server.use(
      http.get('*/api/v1/rooms', () =>
        fail
          ? HttpResponse.json(
              { error: { code: 'BAD_QUERY', message: 'Service unavailable.' } },
              { status: 400 },
            )
          : HttpResponse.json({ items: [forum], total: 1, limit: 20, offset: 0 }),
      ),
    );
    renderSearch('/?capacity=8');
    await screen.findByText('Rooms could not be loaded');
    expect(screen.getByLabelText('People')).toHaveValue('8');
    fail = false;
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(screen.getByRole('article', { name: 'The Forum' })).toBeVisible());
  });
});
