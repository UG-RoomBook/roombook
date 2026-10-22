import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
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
  const navigate = useNavigate();
  return (
    <>
      <output data-testid="location">
        {location.pathname}
        {location.search}
      </output>
      <button onClick={() => void navigate(-1)}>Back in history</button>
    </>
  );
}

function renderSearch(url = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const view = render(
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
  return { ...view, client };
}

describe('room discovery', () => {
  it('disables end selection until a valid start and exposes both duration boundaries', async () => {
    server.use(
      http.get('*/api/v1/rooms', () =>
        HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 }),
      ),
    );
    renderSearch('/?date=2026-10-23');
    expect(screen.getByLabelText('Until')).toBeDisabled();
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '13:00' } });
    expect(screen.getByLabelText('Until')).toBeEnabled();
    expect(screen.getByRole('option', { name: '13:29' })).toBeDisabled();
    expect(screen.getByRole('option', { name: '13:30' })).toBeEnabled();
    expect(screen.getByRole('option', { name: '15:00' })).toBeEnabled();
    expect(screen.getByRole('option', { name: '15:01' })).toBeDisabled();
    expect(screen.getByLabelText('Until')).toHaveAccessibleDescription(
      /30 minutes–2 hours.*Latest end time: 15:00/,
    );
    await screen.findByText('No rooms on this page');
  });

  it('preserves a valid end and clears it with an explanation when the start changes', async () => {
    server.use(
      http.get('*/api/v1/rooms', () =>
        HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 }),
      ),
    );
    renderSearch(`/${selectedInterval}`);
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '13:30' } });
    expect(screen.getByLabelText('Until')).toHaveValue('14:00');
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '14:00' } });
    expect(screen.getByLabelText('Until')).toHaveValue('');
    expect(screen.getByRole('alert')).toHaveTextContent('End time cleared');
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '23:30' } });
    expect(screen.getByLabelText('Until')).toBeDisabled();
    expect(screen.getByRole('status', { name: 'Booking duration' })).toHaveTextContent(
      'Choose another start time',
    );
    await screen.findByText('No rooms on this page');
  });

  it('recalculates on a date change into a DST gap and preserves ordinary valid changes', async () => {
    server.use(
      http.get('*/api/v1/rooms', () =>
        HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 }),
      ),
    );
    renderSearch('/?date=2026-10-02&start=01:30&end=02:30');
    fireEvent.change(screen.getByLabelText('Date'), { target: { value: '2026-10-03' } });
    expect(screen.getByLabelText('Until')).toHaveValue('02:30');
    fireEvent.change(screen.getByLabelText('Date'), { target: { value: '2026-10-04' } });
    expect(screen.getByLabelText('Until')).toHaveValue('');
    expect(screen.getByRole('option', { name: '02:30' })).toBeDisabled();
    expect(screen.getByRole('option', { name: '03:00' })).toBeEnabled();
    expect(screen.getByRole('status', { name: 'Booking duration' })).toHaveTextContent(
      'Latest end time: 04:30',
    );
    await screen.findByText('No rooms on this page');
  });

  it.each([
    ['13:00', '13:29'],
    ['13:00', '15:01'],
    ['13:01', '14:00'],
  ])('does not query availability for invalid URL policy %s–%s', async (start, end) => {
    let requests = 0;
    server.use(
      http.get('*/api/v1/rooms', () => {
        requests++;
        return HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 });
      }),
    );
    renderSearch(`/?date=2026-10-23&start=${start}&end=${end}`);
    expect(screen.getByRole('alert')).toBeVisible();
    await act(async () => {
      await Promise.resolve();
    });
    expect(requests).toBe(0);
  });

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
    await user.selectOptions(screen.getByLabelText('Until'), '12:00');
    expect(screen.getByLabelText('Until')).toHaveValue('');
    await user.click(screen.getByRole('button', { name: 'Find rooms' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose an end time.');
    expect(requests).toHaveLength(1);
    await user.selectOptions(screen.getByLabelText('Until'), '14:00');
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
    expect(screen.getByText('0 of 0 available on this page')).toBeVisible();
    expect(screen.queryByText('No matching rooms')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Next room page' }));
    expect(await screen.findByRole('article', { name: 'The Forum' })).toBeVisible();
    expect(screen.getByTestId('location')).toHaveTextContent('offset=20');
    expect(screen.getByLabelText('People')).toHaveValue('8');
    expect(screen.getByRole('button', { name: 'Previous room page' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Next room page' })).toBeDisabled();
  });

  it('restores applied filters from browser history and resets pagination on a new search', async () => {
    server.use(
      http.get('*/api/v1/rooms', ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset'));
        return HttpResponse.json({
          items: [{ ...forum, available: true }],
          total: 41,
          limit: 20,
          offset,
        });
      }),
    );
    const user = userEvent.setup();
    renderSearch(`/${selectedInterval.replace('capacity=1', 'capacity=8')}&offset=20`);
    await screen.findByRole('article', { name: 'The Forum' });
    expect(screen.getByText('Page 2')).toBeVisible();
    await user.clear(screen.getByLabelText('From'));
    await user.type(screen.getByLabelText('From'), '15:00');
    await user.selectOptions(screen.getByLabelText('Until'), '16:00');
    await user.selectOptions(screen.getByLabelText('People'), '4');
    await user.click(screen.getByRole('button', { name: 'Find rooms' }));
    await waitFor(() => expect(screen.getByText('Page 1')).toBeVisible());
    expect(screen.getByTestId('location')).toHaveTextContent('offset=0');
    await user.click(screen.getByRole('button', { name: 'Next room page' }));
    await waitFor(() => expect(screen.getByText('Page 2')).toBeVisible());
    await user.click(screen.getByRole('button', { name: 'Back in history' }));
    await waitFor(() => expect(screen.getByText('Page 1')).toBeVisible());
    await user.click(screen.getByRole('button', { name: 'Back in history' }));
    await waitFor(() => expect(screen.getByLabelText('From')).toHaveValue('13:00'));
    expect(screen.getByLabelText('Until')).toHaveValue('14:00');
    expect(screen.getByLabelText('People')).toHaveValue('8');
    expect(screen.getByTestId('location')).toHaveTextContent('offset=20');
  });

  it.each(['-1', '1.5', '9007199254740992', 'not-a-page'])(
    'uses the first bounded page for invalid URL offset %s',
    async (offset) => {
      let requestedOffset: string | null = null;
      server.use(
        http.get('*/api/v1/rooms', ({ request }) => {
          requestedOffset = new URL(request.url).searchParams.get('offset');
          return HttpResponse.json({ items: [studio], total: 1, limit: 20, offset: 0 });
        }),
      );
      renderSearch(`/?offset=${offset}`);
      await screen.findByRole('article', { name: 'The Studio' });
      expect(requestedOffset).toBe('0');
    },
  );

  it.each([
    [21, 20],
    [0, 0],
  ])(
    'recovers an out-of-range page for %i catalog rooms with one previous action',
    async (total, expectedOffset) => {
      const requestedOffsets: number[] = [];
      server.use(
        http.get('*/api/v1/rooms', ({ request }) => {
          const offset = Number(new URL(request.url).searchParams.get('offset'));
          requestedOffsets.push(offset);
          return HttpResponse.json({
            items: offset < total ? [forum] : [],
            total,
            limit: 20,
            offset,
          });
        }),
      );
      const user = userEvent.setup();
      renderSearch('/?offset=200&capacity=8');
      await screen.findByText('No matching rooms on this page');
      await user.click(screen.getByRole('button', { name: 'Previous room page' }));
      await waitFor(() => expect(requestedOffsets).toEqual([200, expectedOffset]));
      expect(screen.getByTestId('location')).toHaveTextContent(`offset=${expectedOffset}`);
      expect(screen.getByLabelText('People')).toHaveValue('8');
      if (total) {
        expect(await screen.findByRole('article', { name: 'The Forum' })).toBeVisible();
      } else {
        await screen.findByText('No matching rooms on this page');
        expect(screen.queryByRole('navigation', { name: 'Room pages' })).not.toBeInTheDocument();
      }
    },
  );

  it('withholds cached availability while it is being checked again', async () => {
    let refresh = false;
    let finish: (() => void) | undefined;
    server.use(
      http.get('*/api/v1/rooms', async () => {
        if (refresh) {
          await new Promise<void>((resolve) => {
            finish = resolve;
          });
        }
        return HttpResponse.json({
          items: [{ ...studio, available: !refresh }],
          total: 1,
          limit: 20,
          offset: 0,
        });
      }),
    );
    const { client } = renderSearch(`/${selectedInterval}`);
    expect(await screen.findByRole('button', { name: 'Book The Studio' })).toBeEnabled();
    refresh = true;
    void client.invalidateQueries({ queryKey: ['rooms'] });
    await waitFor(() => expect(finish).toBeTypeOf('function'));
    expect(await screen.findByText('Loading rooms')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Book The Studio' })).not.toBeInTheDocument();
    expect(screen.queryByText('1 of 1 available')).not.toBeInTheDocument();
    await act(async () => finish?.());
    expect(await screen.findByRole('button', { name: 'The Studio: booked' })).toBeDisabled();
    expect(screen.getByText('0 of 1 available')).toBeVisible();
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
            {
              error: {
                code: 'INTERNAL_ERROR',
                message: 'Service unavailable.',
                request_id: '00000000-0000-4000-8000-000000000010',
              },
            },
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
    expect(screen.getByText('Service unavailable.')).toBeVisible();
    expect(screen.getByText('Request ID: 00000000-0000-4000-8000-000000000010')).toBeVisible();
    expect(screen.getByLabelText('From')).toHaveValue('13:00');
    expect(screen.getByLabelText('Until')).toHaveValue('14:00');
    fail = false;
    await user.click(screen.getByRole('button', { name: /try again|retry/i }));
    expect(await screen.findByText('No rooms on this page')).toBeVisible();
  });
});
