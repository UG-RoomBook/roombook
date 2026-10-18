import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { FindRoomPage } from './FindRoomPage';

const studio = {
  id: '00000000-0000-4000-8000-000000000001',
  name: 'The Studio',
  location: 'West building · Level 1',
  capacity: 4,
  active: true,
};
const forum = {
  id: '00000000-0000-4000-8000-000000000002',
  name: 'The Forum',
  location: 'North building · Level 2',
  capacity: 8,
  active: true,
};
const selectedInterval = '?date=2026-10-19&start=13%3A00&end=14%3A00&capacity=1';
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function Location() {
  const location = useLocation();
  return (
    <output data-testid="location">
      {location.pathname}
      {location.search}
    </output>
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
          <Route path="/review" element={<h1>Review booking</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('room discovery', () => {
  it('shows metadata without inventing availability before a valid interval is selected', async () => {
    let sentUrl: URL | undefined;
    server.use(
      http.get('*/api/v1/rooms', ({ request }) => {
        sentUrl = new URL(request.url);
        return HttpResponse.json({ items: [studio, forum], total: 2, limit: 20, offset: 0 });
      }),
    );
    renderSearch();
    expect(await screen.findByRole('article', { name: 'The Studio' })).toBeVisible();
    expect(screen.getAllByText('Choose a time')).toHaveLength(2);
    expect(screen.queryByText('Available')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'The Studio: choose a time' })).toBeDisabled();
    expect(sentUrl?.searchParams.has('starts_at')).toBe(false);
    expect(sentUrl?.searchParams.has('ends_at')).toBe(false);
  });

  it('validates form input, sends explicit Melbourne offsets and carries filters to review', async () => {
    const requests: URL[] = [];
    server.use(
      http.get('*/api/v1/rooms', ({ request }) => {
        const url = new URL(request.url);
        requests.push(url);
        const selected = url.searchParams.has('starts_at');
        return HttpResponse.json({
          items: [{ ...studio, ...(selected ? { available: true } : {}) }],
          total: 1,
          limit: 20,
          offset: 0,
        });
      }),
    );
    const user = userEvent.setup();
    renderSearch('/?date=2026-10-19');
    await screen.findByRole('article', { name: 'The Studio' });
    await user.click(screen.getByRole('button', { name: 'Find rooms' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a start time.');
    await user.type(screen.getByLabelText('From'), '13:00');
    await user.type(screen.getByLabelText('Until'), '12:00');
    await user.click(screen.getByRole('button', { name: 'Find rooms' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Choose an end time after the start time.',
    );
    expect(requests).toHaveLength(1);
    await user.clear(screen.getByLabelText('Until'));
    await user.type(screen.getByLabelText('Until'), '14:00');
    await user.selectOptions(screen.getByLabelText('People'), '4');
    await user.click(screen.getByRole('button', { name: 'Find rooms' }));
    const book = await screen.findByRole('button', { name: 'Book The Studio' });
    expect(requests.at(-1)?.searchParams.get('starts_at')).toBe('2026-10-19T13:00:00+11:00');
    expect(requests.at(-1)?.searchParams.get('ends_at')).toBe('2026-10-19T14:00:00+11:00');
    await user.click(book);
    expect(screen.getByRole('heading', { name: 'Review booking' })).toBeVisible();
    const location = screen.getByTestId('location').textContent ?? '';
    const params = new URLSearchParams(location.split('?')[1]);
    expect(location).toMatch(/^\/review\?/);
    expect(params.get('room_id')).toBe(studio.id);
    expect(params.get('date')).toBe('2026-10-19');
    expect(params.get('start')).toBe('13:00');
    expect(params.get('end')).toBe('14:00');
    expect(params.get('capacity')).toBe('4');
  });

  it('does not query availability for invalid URL intervals', async () => {
    let requests = 0;
    server.use(
      http.get('*/api/v1/rooms', () => {
        requests += 1;
        return HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 });
      }),
    );
    renderSearch('/?date=2026-10-04&start=02%3A30&end=03%3A30');
    expect(screen.getByRole('alert')).toHaveTextContent('daylight saving');
    expect(screen.queryByText('Loading rooms')).not.toBeInTheDocument();
    await act(async () => {
      await Promise.resolve();
    });
    expect(requests).toBe(0);
  });

  it('distinguishes available, booked and inactive rooms', async () => {
    server.use(
      http.get('*/api/v1/rooms', () =>
        HttpResponse.json({
          items: [
            { ...studio, available: true },
            { ...forum, available: false },
            {
              ...studio,
              id: '00000000-0000-4000-8000-000000000004',
              name: 'Closed room',
              active: false,
              available: true,
            },
          ],
          total: 3,
          limit: 20,
          offset: 0,
        }),
      ),
    );
    renderSearch(`/${selectedInterval}`);
    expect(await screen.findByRole('button', { name: 'Book The Studio' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'The Forum: booked' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Closed room: inactive' })).toBeDisabled();
    expect(screen.getByText('1 of 3 available')).toBeVisible();
  });

  it('rejects incomplete interval availability without enabling booking', async () => {
    server.use(
      http.get('*/api/v1/rooms', () =>
        HttpResponse.json({
          items: [studio],
          total: 1,
          limit: 20,
          offset: 0,
        }),
      ),
    );
    renderSearch(`/${selectedInterval}`);
    expect(await screen.findByText('Rooms could not be loaded')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Book The Studio' })).not.toBeInTheDocument();
  });

  it('retains pagination when capacity filtering empties the current page', async () => {
    server.use(
      http.get('*/api/v1/rooms', ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset'));
        return HttpResponse.json({
          items: [{ ...(offset === 20 ? forum : studio), available: true }],
          total: 21,
          limit: 20,
          offset,
        });
      }),
    );
    const user = userEvent.setup();
    renderSearch(`/${selectedInterval.replace('capacity=1', 'capacity=8')}`);
    expect(await screen.findByText('No matching rooms on this page')).toBeVisible();
    expect(screen.queryByText('No matching rooms')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Next room page' }));
    expect(await screen.findByRole('article', { name: 'The Forum' })).toBeVisible();
    expect(screen.getByTestId('location')).toHaveTextContent('offset=20');
    expect(screen.getByLabelText('People')).toHaveValue('8');
    expect(screen.getByRole('button', { name: 'Previous room page' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Next room page' })).toBeDisabled();
  });

  it('shows loading, failure and retry as distinct states', async () => {
    let finish: (() => void) | undefined;
    let fail = true;
    server.use(
      http.get('*/api/v1/rooms', async () => {
        if (fail) {
          await new Promise<void>((resolve) => {
            finish = resolve;
          });
          return HttpResponse.json(
            { error: { code: 'INTERNAL_ERROR', message: 'Service unavailable.' } },
            { status: 500 },
          );
        }
        return HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 });
      }),
    );
    const user = userEvent.setup();
    renderSearch(`/${selectedInterval}`);
    expect(screen.getByText('Loading rooms')).toBeVisible();
    await waitFor(() => expect(finish).toBeTypeOf('function'));
    await act(async () => finish?.());
    expect(await screen.findByText('Rooms could not be loaded')).toBeVisible();
    fail = false;
    await user.click(screen.getByRole('button', { name: /try again|retry/i }));
    expect(await screen.findByText('No rooms on this page')).toBeVisible();
  });
});
