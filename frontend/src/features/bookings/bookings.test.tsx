import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HttpResponse, http } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { Link, MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import type { Booking, Room } from '@/shared/api/types';
import { BookingsPage } from './BookingsPage';
import { ReviewBookingPage } from './ReviewBookingPage';

const room: Room = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'The Studio',
  location: 'West building · Level 1',
  capacity: 4,
  active: true,
  available: true,
};
const booking: Booking = {
  id: '33333333-3333-4333-8333-333333333333',
  room_id: room.id,
  starts_at: '2026-10-19T13:00:00+11:00',
  ends_at: '2026-10-19T14:00:00+11:00',
  status: 'active',
  created_at: '2026-10-18T06:00:00Z',
  cancelled_at: null,
};
const reviewPath = `/review?room_id=${room.id}&date=2026-10-19&start=13%3A00&end=14%3A00&capacity=1`;
let records: Booking[] = [];
let postCount = 0;
let cancellationCount = 0;
let bookingReads: URL[] = [];
let receivedBody: unknown;

const server = setupServer(
  http.get('*/api/v1/rooms', () =>
    HttpResponse.json({ items: [room], total: 1, limit: 100, offset: 0 }),
  ),
  http.get('*/api/v1/bookings', ({ request }) => {
    const url = new URL(request.url);
    bookingReads.push(url);
    const limit = Number(url.searchParams.get('limit') ?? '20');
    const offset = Number(url.searchParams.get('offset') ?? '0');
    return HttpResponse.json({
      items: records.slice(offset, offset + limit),
      total: records.length,
      limit,
      offset,
    });
  }),
  http.post('*/api/v1/bookings', async ({ request }) => {
    postCount += 1;
    receivedBody = await request.json();
    records = [booking];
    return HttpResponse.json(booking, { status: 201 });
  }),
  http.post('*/api/v1/bookings/:id/cancel', () => {
    cancellationCount += 1;
    const cancelled: Booking = {
      ...booking,
      status: 'cancelled',
      cancelled_at: '2026-10-18T07:00:00Z',
    };
    records = [cancelled];
    return HttpResponse.json(cancelled);
  }),
);

const clients: QueryClient[] = [];

function LocationProbe() {
  const location = useLocation();
  return (
    <>
      <output data-testid="location">
        {location.pathname}
        {location.search}
      </output>
      <Link to="/bookings?date=2026-10-19">Bookings navigation</Link>
      <Link to={reviewPath}>Review navigation</Link>
    </>
  );
}

function renderPage(path = reviewPath) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <LocationProbe />
        <Routes>
          <Route path="/review" element={<ReviewBookingPage />} />
          <Route path="/bookings" element={<BookingsPage />} />
          <Route path="/" element={<h1>Find a room</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
beforeEach(() => {
  records = [];
  postCount = 0;
  cancellationCount = 0;
  bookingReads = [];
  receivedBody = undefined;
});
afterEach(() => {
  server.resetHandlers();
  for (const client of clients.splice(0)) client.clear();
});
afterAll(() => server.close());

describe('booking review', () => {
  it('rejects an invalid interval without submitting a booking', () => {
    renderPage(reviewPath.replace('end=14%3A00', 'end=12%3A00'));
    expect(screen.getByRole('alert')).toHaveTextContent('Choose an end time after the start time.');
    expect(screen.queryByRole('button', { name: 'Confirm booking' })).not.toBeInTheDocument();
    expect(postCount).toBe(0);
  });

  it('keeps one request pending and only confirms after the server accepts it', async () => {
    let release = () => {};
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post('*/api/v1/bookings', async ({ request }) => {
        postCount += 1;
        receivedBody = await request.json();
        await pending;
        records = [booking];
        return HttpResponse.json(booking, { status: 201 });
      }),
    );
    renderPage();
    await screen.findByRole('button', { name: 'Confirm booking' });
    const form = screen.getByRole('form', { name: 'Confirm room booking' });
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitFor(() => expect(postCount).toBe(1));
    expect(screen.getByRole('button', { name: 'Confirming booking' })).toBeDisabled();
    expect(screen.queryByText(/Booking confirmed:/)).not.toBeInTheDocument();
    expect(receivedBody).toEqual({
      room_id: room.id,
      starts_at: '2026-10-19T13:00:00+11:00',
      ends_at: '2026-10-19T14:00:00+11:00',
    });
    await act(async () => release());
    await screen.findByRole('heading', { name: 'Bookings', level: 1 });
    expect(await screen.findByText(/Booking confirmed: The Studio/)).toHaveAttribute(
      'role',
      'status',
    );
    expect(postCount).toBe(1);
  });

  it('retains the room and filter inputs after a concurrent conflict', async () => {
    const user = userEvent.setup();
    server.use(
      http.post('*/api/v1/bookings', () => {
        postCount += 1;
        return HttpResponse.json(
          {
            error: {
              code: 'BOOKING_CONFLICT',
              message: 'Room interval overlaps an active booking.',
              request_id: 'conflict-1',
            },
          },
          { status: 409 },
        );
      }),
    );
    renderPage(`${reviewPath}&offset=20`);
    await user.click(await screen.findByRole('button', { name: 'Confirm booking' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Room no longer available');
    expect(screen.getByRole('heading', { name: 'The Studio', level: 2 })).toBeInTheDocument();
    expect(screen.getByText('13:00–14:00')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(`room_id=${room.id}`);
    expect(postCount).toBe(1);
    await user.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/?date=2026-10-19&start=13%3A00&end=14%3A00&capacity=1&offset=20',
    );
  });

  it('does not retry an uncertain gateway timeout and sends the user to check bookings', async () => {
    const user = userEvent.setup();
    server.use(
      http.post('*/api/v1/bookings', () => {
        postCount += 1;
        return HttpResponse.json(
          {
            error: {
              code: 'UPSTREAM_TIMEOUT',
              message: 'The upstream request timed out.',
            },
          },
          { status: 504 },
        );
      }),
    );
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Confirm booking' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Booking outcome not confirmed');
    expect(screen.getByRole('alert')).toHaveTextContent('The request may have completed.');
    expect(screen.getByTestId('location')).toHaveTextContent('outcome=unknown');
    expect(screen.queryByRole('button', { name: 'Confirm booking' })).not.toBeInTheDocument();
    expect(postCount).toBe(1);
    await user.click(screen.getByRole('button', { name: 'Check bookings' }));
    await screen.findByRole('heading', { name: 'Bookings', level: 1 });
    await waitFor(() => expect(bookingReads.length).toBeGreaterThan(0));
    expect(screen.getByTestId('location')).toHaveTextContent('/bookings?date=2026-10-19');
    expect(postCount).toBe(1);
  });

  it('keeps the uncertain-outcome guard when the review URL is reopened', async () => {
    renderPage(`${reviewPath}&outcome=unknown`);
    await screen.findByRole('button', { name: 'Check bookings' });
    expect(screen.getByRole('alert')).toHaveTextContent('Booking outcome not confirmed');
    expect(screen.queryByRole('button', { name: 'Confirm booking' })).not.toBeInTheDocument();
    expect(postCount).toBe(0);
  });

  it('keeps pending and uncertain guards when navigating away and back', async () => {
    const user = userEvent.setup();
    let release = () => {};
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post('*/api/v1/bookings', async () => {
        postCount += 1;
        await pending;
        return HttpResponse.json(
          { error: { code: 'UPSTREAM_TIMEOUT', message: 'Timeout.' } },
          { status: 504 },
        );
      }),
    );
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Confirm booking' }));
    await waitFor(() => expect(postCount).toBe(1));
    await user.click(screen.getByRole('link', { name: 'Bookings navigation' }));
    await screen.findByRole('heading', { name: 'Bookings', level: 1 });
    await user.click(screen.getByRole('link', { name: 'Review navigation' }));
    expect(await screen.findByRole('button', { name: 'Confirming booking' })).toBeDisabled();
    await user.click(screen.getByRole('link', { name: 'Bookings navigation' }));
    await act(async () => release());
    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/bookings?date=2026-10-19'),
    );
    expect(screen.getByTestId('location')).not.toHaveTextContent('outcome=');
    await user.click(screen.getByRole('link', { name: 'Review navigation' }));
    expect(await screen.findByRole('button', { name: 'Check bookings' })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('outcome=unknown'),
    );
    expect(postCount).toBe(1);
  });

  it('does not submit when the selected group exceeds room capacity', async () => {
    renderPage(reviewPath.replace('capacity=1', 'capacity=8'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Group exceeds room capacity');
    expect(screen.getByRole('button', { name: 'Confirm booking' })).toBeDisabled();
    expect(postCount).toBe(0);
  });

  it.each([
    { status: 404, title: 'Room not found', message: 'Unknown room.' },
    {
      status: 422,
      title: 'Check the booking details',
      message: 'Choose a valid booking interval.',
    },
    { status: 400, title: 'Booking could not be confirmed', message: 'Request rejected.' },
  ])('keeps the selection after a $status response', async ({ status, title, message }) => {
    const user = userEvent.setup();
    server.use(
      http.post('*/api/v1/bookings', () =>
        HttpResponse.json(
          {
            error: {
              code: 'BOOKING_REJECTED',
              message,
            },
          },
          { status },
        ),
      ),
    );
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Confirm booking' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(title);
    expect(screen.getByText('13:00–14:00')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('date=2026-10-19');
    if (status === 422) expect(screen.getByRole('alert')).toHaveTextContent(message);
  });

  it('can recover room details without losing the selected interval', async () => {
    const user = userEvent.setup();
    server.use(
      http.get('*/api/v1/rooms', () =>
        HttpResponse.json(
          {
            error: {
              code: 'ROOM_NOT_FOUND',
              message: 'Room list unavailable.',
            },
          },
          { status: 404 },
        ),
      ),
    );
    renderPage();
    expect(await screen.findByRole('alert')).toHaveTextContent('Room details unavailable');
    server.use(
      http.get('*/api/v1/rooms', () =>
        HttpResponse.json({ items: [room], total: 1, limit: 100, offset: 0 }),
      ),
    );
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('button', { name: 'Confirm booking' })).toBeEnabled();
    expect(screen.getByText('13:00–14:00')).toBeInTheDocument();
  });
});

describe('shared bookings', () => {
  it('returns focus on Keep and Escape, then waits for cancellation and refreshes the list', async () => {
    records = [booking];
    const user = userEvent.setup();
    let release = () => {};
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post('*/api/v1/bookings/:id/cancel', async () => {
        cancellationCount += 1;
        await pending;
        const cancelled: Booking = {
          ...booking,
          status: 'cancelled',
          cancelled_at: '2026-10-18T07:00:00Z',
        };
        records = [cancelled];
        return HttpResponse.json(cancelled);
      }),
    );
    renderPage('/bookings?date=2026-10-19');
    const cancel = await screen.findByRole('button', { name: 'Cancel booking' });
    await user.click(cancel);
    expect(screen.getByRole('button', { name: 'Keep booking' })).toHaveFocus();
    await user.click(screen.getByRole('button', { name: 'Keep booking' }));
    expect(cancel).toHaveFocus();
    await user.click(cancel);
    await user.keyboard('{Escape}');
    expect(cancel).toHaveFocus();
    expect(screen.queryByRole('button', { name: 'Yes, cancel' })).not.toBeInTheDocument();
    await user.click(cancel);
    const confirm = screen.getByRole('button', { name: 'Yes, cancel' });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await waitFor(() => expect(cancellationCount).toBe(1));
    expect(screen.getByRole('button', { name: 'Cancelling booking' })).toBeDisabled();
    expect(screen.getByText('Confirmed')).toBeInTheDocument();
    const readsBefore = bookingReads.length;
    await act(async () => release());
    expect(await screen.findByText('Cancelled', { exact: true })).toBeInTheDocument();
    await waitFor(() => expect(bookingReads.length).toBeGreaterThan(readsBefore));
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'The Studio', level: 3 })).toHaveFocus(),
    );
    expect(screen.queryByRole('button', { name: 'Cancel booking' })).not.toBeInTheDocument();
    expect(screen.getByText(/Booking cancelled: The Studio/)).toHaveAttribute('role', 'status');
    expect(cancellationCount).toBe(1);
  });

  it('keeps an active reservation after a cancellation failure and offers a read-only refresh', async () => {
    records = [booking];
    const user = userEvent.setup();
    server.use(
      http.post('*/api/v1/bookings/:id/cancel', () => {
        cancellationCount += 1;
        return HttpResponse.json(
          { error: { code: 'UPSTREAM_TIMEOUT', message: 'Timeout.' } },
          { status: 504 },
        );
      }),
    );
    renderPage('/bookings?date=2026-10-19');
    await user.click(await screen.findByRole('button', { name: 'Cancel booking' }));
    await user.click(screen.getByRole('button', { name: 'Yes, cancel' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Cancellation outcome not confirmed',
    );
    expect(screen.getByText('Confirmed')).toBeInTheDocument();
    const readsBefore = bookingReads.length;
    await user.click(screen.getByRole('button', { name: 'Refresh bookings' }));
    await waitFor(() => expect(bookingReads.length).toBeGreaterThan(readsBefore));
    expect(cancellationCount).toBe(1);
  });

  it.each([
    { status: 404, message: 'This reservation was not found.' },
    { status: 400, message: 'The reservation has not been confirmed as cancelled.' },
  ])('retains cancellation controls after a $status rejection', async ({ status, message }) => {
    records = [booking];
    const user = userEvent.setup();
    server.use(
      http.post('*/api/v1/bookings/:id/cancel', () =>
        HttpResponse.json(
          {
            error: {
              code: 'CANCELLATION_REJECTED',
              message: 'Request rejected.',
            },
          },
          { status },
        ),
      ),
    );
    renderPage('/bookings?date=2026-10-19');
    const cancel = await screen.findByRole('button', { name: 'Cancel booking' });
    await user.click(cancel);
    await user.click(screen.getByRole('button', { name: 'Yes, cancel' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    await user.click(screen.getByRole('button', { name: 'Keep booking' }));
    expect(cancel).toHaveFocus();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('preserves URL pagination and resets it when the date filter changes', async () => {
    records = Array.from({ length: 21 }, (_, index) => ({
      ...booking,
      id: `33333333-3333-4333-8333-${String(index).padStart(12, '0')}`,
    }));
    const user = userEvent.setup();
    renderPage('/bookings?date=2026-10-19');
    await user.click(await screen.findByRole('button', { name: 'Next' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('offset=20'));
    expect(await screen.findByText('21–21 of 21')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Date'), { target: { value: '2026-10-20' } });
    await user.click(screen.getByRole('button', { name: 'Show bookings' }));
    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/bookings?date=2026-10-20'),
    );
    expect(screen.getByTestId('location')).not.toHaveTextContent('offset=');
    await waitFor(() =>
      expect(
        bookingReads.some((url) => url.searchParams.get('from') === '2026-10-20T00:00:00+11:00'),
      ).toBe(true),
    );
  });

  it('labels the empty shared list and validates an empty date field', async () => {
    const user = userEvent.setup();
    renderPage('/bookings?date=2026-10-19');
    expect(await screen.findByRole('heading', { name: 'No bookings' })).toBeInTheDocument();
    expect(screen.getByText('Shared room reservations.')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Date'), { target: { value: '' } });
    await user.click(screen.getByRole('button', { name: 'Show bookings' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a valid date.');
    expect(screen.getByLabelText('Date')).toHaveAttribute('aria-invalid', 'true');
  });

  it('retries a failed list read without creating or cancelling a reservation', async () => {
    const user = userEvent.setup();
    server.use(
      http.get('*/api/v1/bookings', () =>
        HttpResponse.json(
          {
            error: {
              code: 'BAD_QUERY',
              message: 'List unavailable.',
            },
          },
          { status: 400 },
        ),
      ),
    );
    renderPage('/bookings?date=2026-10-19');
    expect(await screen.findByRole('alert')).toHaveTextContent('Bookings unavailable');
    server.use(
      http.get('*/api/v1/bookings', () =>
        HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 }),
      ),
    );
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: 'No bookings' })).toBeInTheDocument();
    expect(postCount).toBe(0);
    expect(cancellationCount).toBe(0);
  });

  it('uses a room ID if names cannot load, while keeping cancellation available', async () => {
    records = [booking];
    server.use(
      http.get('*/api/v1/rooms', () =>
        HttpResponse.json({ error: { code: 'NOT_FOUND', message: 'Not found.' } }, { status: 404 }),
      ),
    );
    renderPage('/bookings?date=2026-10-19');
    expect(await screen.findByRole('alert')).toHaveTextContent('Room names unavailable');
    const row = screen.getByRole('article');
    expect(within(row).getByRole('heading', { name: `Room ${room.id}` })).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: 'Cancel booking' })).toBeEnabled();
  });
});
