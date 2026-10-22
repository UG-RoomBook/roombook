import { QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { RoomDay } from '@/shared/api/client';
import { RoomBookingPage } from './RoomBookingPage';

const room = {
  id: '00000000-0000-4000-8000-000000000001',
  name: 'The Studio',
  location: 'West',
  capacity: 4,
  active: true,
};
function schedule(date = '2026-10-19'): RoomDay {
  const ends: Record<string, string[]> = {
    '10:00': ['10:30', '10:45'],
    '11:15': ['11:45', '12:00', '12:15', '12:30', '12:45', '13:00', '13:15'],
    '13:00': ['13:30', '13:45', '14:00', '14:15', '14:30', '14:45', '15:00'],
    '13:30': ['14:00', '14:15', '14:30', '14:45', '15:00', '15:15', '15:30'],
    '14:00': ['14:30', '14:45', '15:00'],
  };
  return {
    room,
    date,
    timezone: 'Australia/Melbourne',
    generated_at: '2026-10-18T00:00:00Z',
    booking_window_ends_at: '2026-11-01T00:00:00Z',
    slots: Array.from({ length: 96 }, (_, i) => {
      const time =
        `${Math.floor(i / 4)}`.padStart(2, '0') + ':' + `${(i % 4) * 15}`.padStart(2, '0');
      return {
        time,
        starts_at: `${date}T${time}:00+11:00`,
        available: Boolean(ends[time]),
        unavailable_reason: ends[time] ? null : 'unavailable',
        valid_ends: (ends[time] ?? []).map((end) => ({
          time: end,
          ends_at: `${date}T${end}:00+11:00`,
        })),
      };
    }),
  };
}
const server = setupServer(
  http.get('*/api/v1/rooms/:id/availability', ({ request }) =>
    HttpResponse.json(schedule(new URL(request.url).searchParams.get('date')!)),
  ),
);
const clients: QueryClient[] = [];
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  clients.splice(0).forEach((client) => client.clear());
  focusManager.setFocused(undefined);
  vi.useRealTimers();
});
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
function renderSchedule(query = 'date=2026-10-19') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  clients.push(client);
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/rooms/${room.id}?${query}`]}>
        <Location />
        <Routes>
          <Route path="/rooms/:roomId" element={<RoomBookingPage />} />
          <Route path="/review" element={<h1>Review destination</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...view, client };
}
function radio(name: 'start' | 'end', time: string) {
  // Query the labelled group once; avoid computing 96 accessible names on each assertion.
  const group = screen.getByRole('group', { name: name === 'start' ? 'Start time' : 'End time' });
  return group.querySelector<HTMLInputElement>(`input[value="${time}"]`)!;
}
async function ready() {
  await screen.findByText('Availability checked. Updates every 30 seconds.');
}

describe('room schedule', () => {
  it('starts empty, labels disabled times, and allows only continuous server-confirmed intervals', async () => {
    renderSchedule();
    await ready();
    expect(screen.getByRole('button', { name: 'Review booking' })).toBeDisabled();
    expect(radio('start', '10:00')).not.toBeChecked();
    expect(radio('start', '10:30')).toBeDisabled();
    expect(radio('start', '10:30')).toHaveAccessibleName('10:30 Unavailable');
    fireEvent.click(radio('start', '10:00'));
    expect(radio('end', '10:30')).toBeEnabled();
    expect(radio('end', '10:45')).toBeEnabled();
    expect(radio('end', '11:00')).toBeDisabled();
    expect(radio('end', '12:00')).toBeDisabled();
    fireEvent.click(radio('end', '10:45'));
    expect(screen.getByText('10:00–10:45 · 45 minutes')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Review booking' }));
    expect(screen.getByTestId('location')).toHaveTextContent(
      `/review?room_id=${room.id}&date=2026-10-19&start=10%3A00&end=10%3A45`,
    );
  });
  it('offers both 30 and 120 minutes, preserves a valid end, and clears an invalid end', async () => {
    renderSchedule('date=2026-10-19&start=13:00&end=14:00');
    await ready();
    expect(radio('end', '13:30')).toBeEnabled();
    expect(radio('end', '15:00')).toBeEnabled();
    expect(radio('end', '15:15')).toBeDisabled();
    fireEvent.click(radio('start', '13:30'));
    expect(radio('end', '14:00')).toBeChecked();
    fireEvent.click(radio('start', '14:00'));
    expect(screen.getByTestId('location')).not.toHaveTextContent('end=');
    expect(screen.getByText(/End time cleared because it no longer fits/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Review booking' })).toBeDisabled();
  });
  it('clears both times on a date change and restores them through navigation and refresh', async () => {
    const view = renderSchedule('date=2026-10-19&start=13:00&end=14:00');
    await ready();
    fireEvent.change(screen.getByLabelText('Date'), { target: { value: '2026-10-20' } });
    await ready();
    expect(screen.getByTestId('location')).not.toHaveTextContent('start=');
    fireEvent.click(screen.getByRole('button', { name: 'History back' }));
    await ready();
    expect(radio('end', '14:00')).toBeChecked();
    view.unmount();
    renderSchedule('date=2026-10-19&start=13:00&end=14:00');
    await ready();
    expect(radio('end', '14:00')).toBeChecked();
  });
  it('disables review during refresh and clears an end invalidated by a competing booking', async () => {
    const { client } = renderSchedule('date=2026-10-19&start=13:00&end=14:00');
    await ready();
    let finish: (() => void) | undefined;
    server.use(
      http.get('*/api/v1/rooms/:id/availability', async () => {
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
        const data = schedule();
        const start = data.slots.find((slot) => slot.time === '13:00')!;
        start.available = false;
        start.valid_ends = [];
        start.unavailable_reason = 'unavailable';
        return HttpResponse.json(data);
      }),
    );
    void client.invalidateQueries({ queryKey: ['rooms'] });
    await waitFor(() => expect(finish).toBeTypeOf('function'));
    expect(screen.getByRole('button', { name: 'Review booking' })).toBeDisabled();
    await act(async () => finish?.());
    await ready();
    await waitFor(() => expect(screen.getByTestId('location')).not.toHaveTextContent('end='));
    expect(radio('start', '13:00')).toBeDisabled();
    expect(screen.getByText(/End time cleared because it is no longer available/)).toBeVisible();
  });
  it('cannot overwrite a new date with an older delayed response', async () => {
    let finish: (() => void) | undefined;
    server.use(
      http.get('*/api/v1/rooms/:id/availability', async ({ request }) => {
        const date = new URL(request.url).searchParams.get('date')!;
        if (date === '2026-10-19')
          await new Promise<void>((resolve) => {
            finish = resolve;
          });
        return HttpResponse.json(schedule(date));
      }),
    );
    renderSchedule();
    await waitFor(() => expect(finish).toBeTypeOf('function'));
    fireEvent.change(screen.getByLabelText('Date'), { target: { value: '2026-10-20' } });
    await ready();
    await act(async () => finish?.());
    expect(screen.getByLabelText('Date')).toHaveValue('2026-10-20');
    fireEvent.click(radio('start', '10:00'));
    fireEvent.click(radio('end', '10:30'));
    fireEvent.click(screen.getByRole('button', { name: 'Review booking' }));
    expect(screen.getByTestId('location')).toHaveTextContent('date=2026-10-20');
  });
  it('shows read failures as errors, keeps selections and recovers on retry', async () => {
    const { client } = renderSchedule('date=2026-10-19&start=13:00&end=14:00');
    await ready();
    server.use(
      http.get('*/api/v1/rooms/:id/availability', () =>
        HttpResponse.json(
          { error: { code: 'BAD_REQUEST', message: 'Unavailable' } },
          { status: 400 },
        ),
      ),
    );
    await act(async () => {
      await client.invalidateQueries({ queryKey: ['rooms'] });
    });
    await screen.findByText('Availability could not be loaded');
    expect(screen.queryByRole('group', { name: 'Start time' })).not.toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('end=14:00');
    expect(screen.getByRole('button', { name: 'Review booking' })).toBeDisabled();
    server.resetHandlers();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await ready();
    expect(radio('end', '14:00')).toBeChecked();
  });
  it('supports native arrow-key selection with disabled starts skipped', async () => {
    renderSchedule();
    await ready();
    const user = userEvent.setup();
    radio('start', '10:00').focus();
    await user.keyboard(' ');
    expect(radio('start', '10:00')).toBeChecked();
    await user.keyboard('{ArrowRight}');
    expect(radio('start', '11:15')).toBeChecked();
    expect(radio('start', '11:15')).toHaveFocus();
    expect(
      within(screen.getByRole('group', { name: 'End time' })).getByText('11:45'),
    ).toBeVisible();
  });
  it('refreshes on focus and every 30 seconds while visible', async () => {
    let reads = 0;
    server.use(
      http.get('*/api/v1/rooms/:id/availability', () => {
        reads++;
        return HttpResponse.json(schedule());
      }),
    );
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    renderSchedule();
    await ready();
    expect(reads).toBe(1);
    act(() => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    await waitFor(() => expect(reads).toBe(2));
    await ready();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    await waitFor(() => expect(reads).toBe(3));
  });
});
